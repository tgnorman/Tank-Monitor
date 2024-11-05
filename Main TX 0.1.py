# Trev's super dooper Tank/Pump monitoring system

from PiicoDev_VL53L1X import PiicoDev_VL53L1X
from PiicoDev_RV3028 import PiicoDev_RV3028
from PiicoDev_Transceiver import PiicoDev_Transceiver
import RGB1602
import time
import network
import ntptime
import os
import random               # just for PP detect sim...
from time import sleep
from PiicoDev_Unified import sleep_ms
from machine import I2C, Pin, ADC, Timer # Import Pin
from Pump import Pump               # get our Pump class
from Tank import Tank
from secrets import MyWiFi


# OK... major leap... intro to FSM...
from SM_SimpleFSM import SimpleDevice

system      = SimpleDevice()            #initialise my FSM.
wf          = MyWiFi()

DEBUGLVL    = 2

# region initial declarations etc
# Configure your WiFi SSID and password
ssid        = wf.ssid
password    = wf.password

# Create PiicoDev sensor objects

#First... I2C devices
distSensor 	= PiicoDev_VL53L1X()
rtc 		= PiicoDev_RV3028()     # Initialise the RTC module, enable charging
lcd 		= RGB1602.RGB1602(16,2)

radio = PiicoDev_Transceiver()
RADIO_PAUSE = 1000
MIN_FREE_SPACE = 100                # in KB...
MAX_CONTINUOUS_RUNTIME = 6 * 60 * 60        # 6 hours max runtime.  More than this looks like trouble


# Pins
temp_sensor = ADC(4)			    # Internal temperature sensor is connected to ADC channel 4
backlight 	= Pin(6, Pin.IN)		# check if IN is correct!
buzzer 		= Pin(16, Pin.OUT)
presspmp 	= Pin(15,Pin.IN)		# or should this be ADC()?
prsspmp_led = Pin(14, Pin.OUT)
solenoid    = Pin(2, Pin.OUT, value=0)      # MUST ensure we don't close solenoid on startup... pump may already be running !!!  Note: Low == Open

# Misc stuff
conv_fac 	= 3.3 / 65535
steady_state = False                # if not, then don't check for anomalies
clock_adjust_ms = 0                 # will be set later... this just to ensure it is ALWAYS something

# Gather all tank-related stuff with a view to making a class...
housetank   = Tank("Empty")           # make my tank object

# New state...
fill_states = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]
# Physical Constants
Tank_Height = 1650
OverFull	= 150
Min_Dist    = 200           # full
Max_Dist    = 1000          # empty
Delta       = 50            # change indicating pump state change has occurred

# Tank variables/attributes
depth = 0
last_depth = 0
depth_ROC = 0
max_ROC = 0.4			# change in metres/minute
min_ROC = 0.15           # experimental.. might need to tweak.  To avoid noise in anomaly tests

# Various constants
mydelay = 5				# Sleep time... seconds, not ms...

# logging stuff...
log_freq = 5
last_logged_depth = 0
min_log_change_m = 0.1	# to save space... only write to file if significant change in level
level_init = False 		# to get started

counter = 0

# endregion

# start doing stuff
buzzer.value(0)			# turn buzzer off
lcd.clear()
rtc.getDateTime()

# CHANGE THIS... do after initialising internal clock
tod   = rtc.timestamp()
year  = tod.split()[0].split("-")[0]
month = tod.split()[0].split("-")[1]
day   = tod.split()[0].split("-")[2]
shortyear = year[2:]

def init_logging():
    global year, month, day, shortyear
    global f, ev_log
    daylogname  = f'tank {shortyear}{month}{day}.txt'
    pplogname   = f'pressure {month}{day}.txt'
    eventlogname = 'borepump_events.txt'
    f      = open(daylogname, "a")
    ev_log = open(eventlogname, "a")
    pp_log = open(pplogname, "a")

def get_fill_state(d):
    if d > Max_Dist:
        tmp = fill_states[len(fill_states) - 1]
    elif Max_Dist - Delta < d and d <= Max_Dist:
        tmp = fill_states[4]
    elif Min_Dist + Delta < d and d <= Max_Dist - Delta:
        tmp = fill_states[3]
    elif Min_Dist < d and d <= Min_Dist + Delta:
        tmp = fill_states[2]
    elif OverFull < d and d <= Min_Dist:
        tmp = fill_states[1]
    elif d <= OverFull:
        tmp = fill_states[0]
    return tmp

def updateData():
    global tank_is
    global depth_str
    global depth
    global last_depth
    global depth_ROC
    d = distSensor.read()
    depth_ROC = (depth - last_depth) / (mydelay / 60)	# ROC in m/minute.  Save neagtives also... for anomaly testing
    if DEBUGLVL > 1: print(f"depth_ROC: {depth_ROC:.3f}")
    last_depth = depth				# track change since last reading
    depth = (Tank_Height - d) / 1000
    tank_is = get_fill_state(d)
    depth_str = f"{depth:.2f}m " + tank_is

def updateClock():
    global str_time, event_time

    now   = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
#    tod   = rtc.timestamp()
    year  = now[0]
    
    month = now[1]
    day   = now[2]
    hour  = now[3]
    min   = now[4]
    sec   = now[5]
    short_time = f"{hour:02}:{min:02}:{sec:02}"
    str_time = str(month) + "/" + str(day) + " " + short_time 
    event_time = str(year) + "/" + str_time

def log_switch_error(new_state):
    global ev_log, event_time
    print(f"!!! log_switch_error  !! {new_state}")
    ev_log.write(f"{event_time}: ERROR on switching to state {new_state}\n")
    
def parse_reply(rply):
    if DEBUGLVL > 0: print(f"in parse arg is {rply}")
    if isinstance(rply, tuple):			# good...
        key = rply[0]
        val = rply[1]
#        print(f"in parse: key={key}, val={val}")
        if key.upper() == "STATUS":
            return True, val
        else:
            print(f"Unknown tuple from receiver: key {key}, val {val}")
            return False, -1
    else:
        print(f"Parse expected tuple... didn't get one.  Got {rply}")
        return False, False

def transmit_and_pause(msg, delay):
    global radio

    if DEBUGLVL > 1: print(f"TX Sending {msg}, sleeping for {delay} ms")
    radio.send(msg)
    sleep_ms(delay)

def confirm_solenoid()-> bool:
    sleep_ms(500)
    return True                     #... remember to fix this when I have another detect circuit...

def radio_time(local_time):
    global clock_adjust_ms
    return(local_time + clock_adjust_ms)

def controlBorePump():
    global tank_is, counter, radio, event_time
    if tank_is == fill_states[0]:		# Overfull
        buzzer.value(1)			# raise alarm
    else:
        buzzer.value(0)
    if tank_is == fill_states[len(fill_states) - 1]:		# Empty
        if not borepump.state:		# pump is off, we need to switch on
            if DEBUGLVL > 0: print("cBP: Opening valve")
            solenoid.value(0)
            if confirm_solenoid():
                counter += 1
                tup = ("ON", radio_time(time.time()))   # was previosuly counter... now, time
    #            print(tup)
                transmit_and_pause(tup, 2 * RADIO_PAUSE)    # that's two sleeps... as expecting immediate reply
    # try implicit CHECK... which should happen in my RX module as state_changed
    #            radio.send("CHECK")
    #            sleep_ms(RADIO_PAUSE)
                if radio.receive():
                    rply = radio.message
    #                print(f"radio.message (rm): {rm}")
    #                print(f"received response: rply is {rply}")
                    valid_response, new_state = parse_reply(rply)
    #                print(f"in ctlBP: rply is {valid_response} and {new_state}")
                    if valid_response and new_state > 0:
                        borepump.switch_pump(True)
                        ev_log.write(f"{event_time} ON\n")
                        if DEBUGLVL > 0: print(f"FSM: Set borepump to state {borepump.state}")
                    else:
                        log_switch_error(new_state)
            else:               # dang... want to turn pump on, but solenoid looks OFF
                raiseAlarm("NOT turning pump on... valve is CLOSED!", event_time)
    elif tank_is == fill_states[0] or tank_is == fill_states[1]:	# Full or Overfull
#        bore_ctl.value(0)			# switch borepump OFF
        if borepump.state:			# pump is ON... need to turn OFF
 
            counter -= 1
            tup = ("OFF", radio_time(time.time()))
#            print(tup)
            transmit_and_pause(tup, 2 * RADIO_PAUSE)    # that's two sleeps... as expecting immediate reply
# try implicit CHECK... which should happen in my RX module as state_changed
#            radio.send("CHECK")
#            sleep_ms(RADIO_PAUSE)
            if radio.receive():
                rply = radio.message
                valid_response, new_state = parse_reply(rply)
#                print(f"in ctlBP: rply is {valid_response} and {new_state}")
                if valid_response and not new_state:        # this means I received confirmation that pump is OFF...
                    borepump.switch_pump(False)
                    ev_log.write(f"{event_time} OFF\n")
                    if DEBUGLVL > 0: print("cBP: Closing valve")
                    solenoid.value(1)               # wait until pump OFF confirmed before closing valve !!!
                    if DEBUGLVL > 0: print(f"FSM: Set borepump to state {borepump.state}")
                else:
                    log_switch_error(new_state)
                    
def raiseAlarm(param, val):
    global ev_log, event_time
    str = f"{event_time} ALARM {param}, value {val:.3g}"
    print(str)
    ev_log.write(f"{str}\n")
    
def checkForAnomalies():
    global borepump, max_ROC, depth_ROC, tank_is, MAX_CONTINUOUS_RUNTIME

    if borepump.state and tank_is == "Overflow":        # ideally, refer to a Tank object... but this will work for now
        raiseAlarm("OVERFLOW and still ON", 999)        # probably should do more than this.. REALLY BAD scenario!
    if abs(depth_ROC) > max_ROC:
        raiseAlarm("Max ROC Exceeded", depth_ROC)
    if depth_ROC > min_ROC and not borepump.state:      # pump is OFF but level is rising!
        raiseAlarm("FILLING while OFF", depth_ROC)
    if depth_ROC < -min_ROC and borepump.state:         # pump is ON but level is falling!
        raiseAlarm("DRAINING while ON", depth_ROC)
    if borepump.state:                                  # if pump is on, and has been on for more than max... do stuff!
        runtime = time.time() - borepump.last_time_switched
        if runtime > MAX_CONTINUOUS_RUNTIME:
            raiseAlarm("RUNTIME EXCEEDED", runtime)
    
def displayAndLog():
    global log_freq
    global depth
    global last_depth
    global level_init
    global last_logged_depth
    global min_log_change_m   
    lcd.clear()
    lcd.setCursor(0, 0)
    lcd.printout(str_time)
    lcd.setCursor(0, 1)
    lcd.printout(depth_str)
#    temp = 27 - (temp_sensor.read_u16() * conv_fac - 0.706)/0.001721
#    tempstr=f"{temp:.2f} C"  
    logstr = str_time + f" {depth:.2f}m\n"
    dbgstr = str_time + f" {depth:.3f}m"    
#    if rec_num % log_freq == 0:
#    if rec_num == log_freq:			# avoid using mod... in case of overflow
#        rec_num = 0					# just reset to zero
#        print('Recnum mod zero...')
#        f.write(logstr)
    if not level_init:
        level_init = True
        last_logged_depth = depth
    else:
        level_change = abs(depth - last_logged_depth)
        if level_change > min_log_change_m:
            last_logged_depth = depth
            f.write(logstr)      
    print(dbgstr)

def listen_to_radio():
#This needs to be in a separate event task... next job is that
    global radio
    if radio.receive():
        msg = radio.message
        if isinstance(msg, str):
            print(msg)
            if "FAIL" in msg:
                print(f"Dang... something went wrong...{msg}")
        elif isinstance(msg, tuple):
            print("Received tuple: ", msg[0], msg[1])

def init_radio():
    global radio, system
    
    print("Initialising radio...")
    if radio.receive():
        msg = radio.message
        print(f"Read {msg}")
    else:
        print("nothing received in init_radio")
    print("Pinging RX Pico...")
    while not ping_RX():
        print("Waiting for RX to respond...")
        sleep(1)

# if we get here, my RX is responding.
    print("RX responded to ping... comms ready")
    system.on_event("ACK COMMS")

def ping_RX() -> bool:           # at startup, test if RX is listening
    global radio

    ping_acknowleged = False
    transmit_and_pause("PING", RADIO_PAUSE)
    if radio.receive():                     # depending on time relative to RX Pico, may need to pause more here before testing???
        msg = radio.message
        if isinstance(msg, str):
            if msg == "PING REPLY":
                ping_acknowleged = True

    return ping_acknowleged

def get_initial_pump_state() -> bool:

    initial_state = False
    transmit_and_pause("CHECK",  RADIO_PAUSE)
    if radio.receive():
        rply = radio.message
        valid_response, new_state = parse_reply(rply)
        if valid_response and new_state > 0:
            initial_state = True
    print(f"Pump Initial state is {initial_state}")
    return initial_state

def dump_pump():
    global borepump, ev_log
# write pump object stats to log file, typically when system is closed/interupted

    dc_secs = borepump.cum_seconds_on
    days  = int(dc_secs/(60*60*24))
    hours = int(dc_secs % (60*60*24) / (60*60))
    mins  = int(dc_secs % (60*60) / 60)
    secs  = int(dc_secs % 60)
    ev_log.write(f"\nMonitor shutdown at {display_time(secs_to_localtime(time.time()))}\n")
    ev_log.write(f"Last switch time:   {display_time(secs_to_localtime(borepump.last_time_switched))}\n")
    ev_log.write(f"Total switches this period: {borepump.num_switch_events}\n")
    ev_log.write(f"Cumulative runtime: {days} days {hours} hours {mins} minutes {secs} seconds\n")

def connect_wifi():
    global system

# Connect to Wi-Fi
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print("connect_wifi..")
    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.connect(ssid, password)
        while not wlan.isconnected():
            print(">", end="")
            time.sleep(1)
    system.on_event("ACK WIFI")
    print('Connected to:', wlan.ifconfig())

def secs_to_localtime(s):
    tupltime = time.localtime(s)
    year = tupltime[0]
    DST_end   = time.mktime((year, 4,(31-(int(5*year/4+4))%7),2,0,0,0,0,0)) #Time of April change to end DST
    DST_start = time.mktime((year,10,(7-(int(year*5/4+4)) % 7),2,0,0,0,0,0)) #Time of October change to start DST
    
    if DST_end < s and s < DST_start:		# then adjust
#        print("Winter ... adding 9.5 hours")
        adj_time = time.localtime(s + int(9.5 * 3600))
    else:
#        print("DST... adding 10.5 hours")
        adj_time = time.localtime(s + int(10.5 * 3600))
    return(adj_time)

def display_time(t):
    year  = t[0]
    month = t[1]
    day   = t[2]
    hour  = t[3]
    min   = t[4]
    sec   = t[5]
    time_str = f"{year}/{month:02}/{day:02} {hour:02}:{min:02}:{sec:02}"
    return time_str
    
def set_time():
 # Set time using NTP server
    print("Syncing time with NTP...")
    ntptime.settime()  # This will set the system time to UTC
    
def init_clock():
    global system

    print("Initialising local clock")
    if time.localtime()[0] < 2024:  # if we reset, localtime will return 2021...
#        connect_wifi()
        set_time()
    system.on_event("ACK NTP")

def sync_clock():                   # initiate exchange of time info with RX, purpose is to determine clock adjustment
    global radio, clock_adjust_ms

    if system.state == "CLOCK_SET":
        print("Starting clock sync process")
        count = 10
        delay = 500                     # millisecs
        for n in range(count):
            local_time = time.time()
            tup = ("CLK", local_time)
            radio.send(tup)
            sleep_ms(delay)
        max_loops = 100
        loop_count = 0
        while not radio.receive() and loop_count < max_loops:
            sleep_ms(50)
            loop_count += 1
        if loop_count < max_loops:      # then we got a reply
            if DEBUGLVL > 0: print(f"Got CLK SYNC reply after {loop_count} loops")
            rcv_msg = radio.message
            if type(rcv_msg) is tuple:
                if rcv_msg[0] == "CLK":
                    clock_adjust_ms = rcv_msg[1]
        else:                           # we did NOT get a reply... don't block... set adj to default 500
            clock_adjust_ms = 500
       
        system.on_event("CLK SYNC")
    else:
        print(f"What am I doing here in state {system.state}")

    if DEBUGLVL > 0: print(f"Setting clock_adjust to {clock_adjust_ms}") 

def init_everything_else():
    global borepump, steady_state, free_space_KB, presspump
       
# Get the current pump state and init my object    
    borepump = Pump(0, get_initial_pump_state())

# On start, valve should now be open... but just to be sure... and to verify during testing...
    if borepump.state:
        if DEBUGLVL > 0:
            print("At startup, BorePump is ON  ... opening valve")
        solenoid.value(0)           # be very careful... inverse logic!
    else:
        if DEBUGLVL > 0:
            print("At startup, BorePump is OFF ... closing valve")
        solenoid.value(1)           # be very careful... inverse logic!

    presspump = Pump(1, False)
    free_space_KB = free_space()
# ensure we start out right...
    steady_state_= False

def heartbeat() -> bool:
    global borepump
# heartbeat... if pump is on, send a regular heartbeat to the RX end
# On RX, if a max time has passed... turn off.
# Need a mechanism to alert T... and reset

# Doing this inline as it were to avoid issues with async, buffering yada yada.
# The return value indicates if we need to sleep before continuing the main loop
    if not borepump.state:      # only do stuff if we believe the pump is running
        return (True)             # nothing... so sleep
    else:
        transmit_and_pause("BABOOM", RADIO_PAUSE)       # this might be a candidate for a shorter delay... if no reply expected
        return (False)            # implied sleep... so, negative

def switch_valve(state):
    global solenoid

    if state:
        solenoid.value(0)       # NOTE:  ZERO to turn ON/OPEN
    else:
        sleep_ms(400)           # what is appropriate sleep time???
        solenoid.value(1)       # High to close

def confirm_and_switch_solenoid(state):
#  NOTE: solenoid relay is reverse logic... LOW is ON
    global borepump

    if state:
        if DEBUGLVL > 0: print("Turning valve ON")
        switch_valve(borepump.state)
    else:
        if borepump.state:          # not good to turn valve off while pump is ON !!!
            raiseAlarm("Solenoid OFF Invalid - Pump is!", borepump.state )
        else:
            if DEBUGLVL > 0: print("Turning valve OFF")
            switch_valve(False)

def free_space():
    # Get the filesystem stats
    stats = os.statvfs('/')

    # Calculate free space
    block_size = stats[0]
    total_blocks = stats[2]
    free_blocks = stats[3]

    # Free space in bytes
    free_space_kb = free_blocks * block_size / 1024
    return free_space_kb

def sim_pressure_pump_detect(x):
    p = random.random()

    return True if p > x else False

def sim_solenoid_detect():
    pass

def main():
    global event_time, ev_log, steady_state, housetank, system

    rec_num=0
    #radio.rfm69_reset

# first cut at how to progress SM on start-up.  Not clear if this is optimal.  Maybe better to drive this inside SM methods

    if not system:              # yikes... don't have a SM ??
        if DEBUGLVL > 0:
            print("GAK... no state machine exists at start-up")
    else:
        while  system.state != "READY":
            print(system.state)
            if system.state == "PicoReset":     connect_wifi()  # ACK WIFI
            if system.state == "WIFI_READY":    init_clock()    # ACK NTP
            if system.state == "CLOCK_SET":     init_radio()    # ACK COMMS
            if system.state == "COMMS_READY":   sync_clock()    # ACK SYNC
            if system.state == "CLOCK_SYNCED": system.on_event("START_MONITORING")
            sleep(1)

    start_time = time.time()
    print(f"Main TX starting at {display_time(secs_to_localtime(start_time))}")
    init_logging()
    updateClock()				    # get DST-adjusted local time
    
    print(f"Housetank state is {housetank.state}")
    ev_log.write(f"Pump Monitor starting: {event_time}\n")
    init_everything_else()

    try:
        while True:
            updateClock()			# get datetime stuff
            updateData()			# monitor water depth
            controlBorePump()		# do whatever
    #        listen_to_radio()		# check for badness
            displayAndLog()			# record it
            if steady_state: checkForAnomalies()	    # test for weirdness
            rec_num += 1
            if rec_num > 2 and not steady_state: steady_state = True
            if heartbeat():             # send heartbeat if ON... not if OFF.  For now, anyway
                if DEBUGLVL > 1: print("Need to sleep...")
                sleep(mydelay)
            else:
                if DEBUGLVL > 1: print("Need a shorter sleep")
                sleep_ms(mydelay * 1000 - RADIO_PAUSE)
            
    except KeyboardInterrupt:
    # turn everything OFF
        borepump.switch_pump(False)             # turn pump OFF
    #    confirm_and_switch_solenoid(False)     #  *** DO NOT DO THIS ***  If live, this will close valve while pump.
    #           to be real sure, don't even test if pump is off... just leave it... for now.

        lcd.setRGB(0,0,0)		                # turn off backlight
    
    # tidy up...
        f.flush()
        f.close()
        ev_log.write(f"{event_time} STOP")
        dump_pump()
        ev_log.flush()
        ev_log.close()

        print('\n### Program Interrupted by the user')

if __name__ == '__main__':
    main()