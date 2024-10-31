# Trev's super dooper Tank/Pump monitoring system

from PiicoDev_VL53L1X import PiicoDev_VL53L1X
from PiicoDev_RV3028 import PiicoDev_RV3028
from PiicoDev_Transceiver import PiicoDev_Transceiver
import RGB1602
import time
import network
import ntptime
from time import sleep
from PiicoDev_Unified import sleep_ms
from machine import I2C, Pin, ADC # Import Pin
import secrets

# Configure your WiFi SSID and password
ssid        = secrets.ssid_s
password    = secrets.password_s

from Pump import Pump               # get our Pump class

DEBUGLVL       = 1

# Create PiicoDev sensor objects

#First... I2C devices
distSensor 	= PiicoDev_VL53L1X()
rtc 		= PiicoDev_RV3028()     # Initialise the RTC module, enable charging
lcd 		= RGB1602.RGB1602(16,2)

radio = PiicoDev_Transceiver()
RADIO_PAUSE = 1000

# Pins
temp_sensor = ADC(4)			    # Internal temperature sensor is connected to ADC channel 4
backlight 	= Pin(6, Pin.IN)		# check if IN is correct!
buzzer 		= Pin(16, Pin.OUT)
presspmp 	= Pin(15,Pin.IN)		# or should this be ADC()?
prsspmp_led = Pin(14, Pin.OUT)
solenoid    = Pin(2, Pin.OUT, value=1)

# Misc stuff
conv_fac 	= 3.3 / 65535

# Gather all tank-related stuff with a view to making a class...
# New state... .
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

MAX_CONTINUOUS_RUNTIME = 6 * 60 * 60        # 6 hours max runtime.  More than this looks like trouble
counter = 0

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
    daylogname = f'tank {shortyear}{month}{day}.txt'
    eventlogname = 'borepump_events.txt'
    f      = open(daylogname, "a")
    ev_log = open(eventlogname, "a")

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
    ev_log.write(f"{event_time}: ERROR on switching to state {new_state}")
    
def parse_reply(rply):
    if DEBUGLVL > 1: print(f"in parse arg is {rply}")
    if isinstance(rply, tuple):			# good...
        key = rply[0]
        val = rply[1]
#        print(f"in parse: key={key}, val={val}")
        if key.upper() == "STATUS":
            return True, val
        else:
            print("Unknown reply from receiver")
            return False, -1
    else:
        print("Parse expected tuple... didn't get one")
        return False, False

def transmit_and_pause(msg, delay):
    global radio

    if DEBUGLVL > 1: print(f"Sending {msg}")
    radio.send(msg)
    sleep_ms(delay)

def confirm_solenoid()-> bool:
    return True                     #... remember to fix this when I have another detect circuit...

def controlBorePump():
    global tank_is, counter, radio, event_time
    if tank_is == fill_states[0]:		# Overfull
        buzzer.value(1)			# raise alarm
    else:
        buzzer.value(0)
    if tank_is == fill_states[len(fill_states) - 1]:		# Empty
        if not borepump.state:		# pump is off, we need to switch on
            print("Opening valve")
            solenoid.value(0)
            if confirm_solenoid():
                counter += 1
                tup = ("ON", time.time())   # was previosuly counter... now, time
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
            tup = ("OFF", time.time())
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
                    print("Closing valve")
                    solenoid.value(1)               # wait until pump OFF confirmed before closing valve !!!
                    if DEBUGLVL > 0: print(f"FSM: Set borepump to state {borepump.state}")
                else:
                    log_switch_error(new_state)
                    
def raiseAlarm(param, val):
    global ev_log, event_time
    str = f"{event_time} ALARM {param}, value {val:.3g}\n"
    ev_log.write(str)
    print(str)
    
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
    dbgstr = str_time + f" {depth:.2f}m"    
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

#This needs to be in a separate event task... next job is that
def listen_to_radio():
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
    global radio
    
    print("Initialising radio...")
    if radio.receive():
        msg = radio.message
        print(f"Read {msg}")
    else:
        print("nothing received in init_radio")

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

# Connect to Wi-Fi
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.connect(ssid, password)
        while not wlan.isconnected():
            time.sleep(1)
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
    
# Set time using NTP server
def set_time():
    print("Syncing time with NTP...")
    ntptime.settime()  # This will set the system time to UTC

def init_clock():
    if time.localtime()[0] < 2024:  # if we reset, localtime will return 2021...
        connect_wifi()
        set_time()
        
def init_everything_else():
    global borepump
    
#    updateClock()                   # get DST-adjusted local time
    init_radio()
    print("Pinging RX Pico...")
    while not ping_RX():
        print("Waiting for RX to respond...")
        sleep(1)

# if we get here, my RX is responding.
    print("RX responded to ping... comms ready")

# Get the current pump state and init my object    
    borepump = Pump(get_initial_pump_state())

# heartbeat... if pump is on, send a regular heartbeat to the RX end
# On RX, if a max time has passed... turn off.
# Need a mechanism to alert T... and reset

def heartbeat() -> bool:
    global borepump
# Doing this inline as it were to avoid issues with async, buffering yada yada.
# The return value indicates if we need to sleep before continuing the main loop
    if not borepump.state:      # only do stuff if we believe the pump is running
        return True             # nothing... so sleep
    else:
        transmit_and_pause("BABOOM", RADIO_PAUSE)       # this might be a candidate for a shorter delay... if no reply expected
        return False            # implied sleep... so, negative

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
    
def main():
    global event_time, ev_log
#    rec_num=0
    #radio.rfm69_reset

    print("Initialising clock") 
    init_clock()
    start_time = time.time()
    print(f"Main TX starting at {display_time(secs_to_localtime(start_time))}")
    init_logging()
    updateClock()				    # get DST-adjusted local time
    
    ev_log.write(f"Pump Monitor starting: {event_time}\n")
    init_everything_else()

    try:
        while True:
            updateClock()			# get datetime stuff
            updateData()			# monitor water depth
            controlBorePump()		# do whatever
    #        listen_to_radio()		# check for badness
            displayAndLog()			# record it
            checkForAnomalies()	    # test for weirdness
    #        rec_num += 1

            if heartbeat():             # send heartbeat if ON... not if OFF.  For now, anyway
                sleep(mydelay)
            
    except KeyboardInterrupt:
    # turn everything OFF
        borepump.switch_pump(False)             # turn pump OFF
        confirm_and_switch_solenoid(False)      # close valve
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