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
from time import sleep, ticks_us, ticks_diff
from PiicoDev_Unified import sleep_ms
from machine import Timer, Pin, ADC, Timer # Import Pin
from Pump import Pump               # get our Pump class
from Tank import Tank
from secrets import MyWiFi
import uasyncio

# OK... major leap... intro to FSM...
from SM_SimpleFSM import SimpleDevice

system      = SimpleDevice()            #initialise my FSM.
wf          = MyWiFi()

DEBUGLVL    = 0
ROC_AVERAGE = 5         # make 1 for NO averaging... otherwise do an SMA of this period.  Need a ring buffer?

# region initial declarations etc
# Configure your WiFi SSID and password
ssid        = wf.ssid
password    = wf.password

# Create PiicoDev sensor objects

#First... I2C devices
distSensor 	= PiicoDev_VL53L1X()
#rtc 		= PiicoDev_RV3028()     # Initialise the RTC module, enable charging
lcd 		= RGB1602.RGB1602(16,2)

radio       = PiicoDev_Transceiver()
RADIO_PAUSE = 1000
MIN_FREE_SPACE = 100                # in KB...
MAX_CONTINUOUS_RUNTIME = 4 * 60 * 60        # 6 hours max runtime.  More than this looks like trouble

LCD_ON_TIME = 5000      # millisecs
btnflag     = False

# Pins
vsys        = ADC(3)                            # one day I'll monitor this for over/under...
temp_sensor = ADC(4)			                # Internal temperature sensor is connected to ADC channel 4
lcdbtn 	    = Pin(6, Pin.IN, Pin.PULL_UP)		# check if IN is correct!
buzzer 		= Pin(16, Pin.OUT)
presspmp    = Pin(15, Pin.IN, Pin.PULL_UP)      # prep for pressure pump monitor.  Needs output from opamp circuit
prsspmp_led = Pin(14, Pin.OUT)
solenoid    = Pin(2, Pin.OUT, value=0)          # MUST ensure we don't close solenoid on startup... pump may already be running !!!  Note: Low == Open
vbus_sense  = Pin('WL_GPIO2', Pin.IN)           # external power monitoring of VBUS

# Misc stuff
conv_fac 	= 3.3 / 65535
steady_state = False                    # if not, then don't check for anomalies
clock_adjust_ms = 0                     # will be set later... this just to ensure it is ALWAYS something
MAX_OUTAGE  = 20                        # seconds of no power
report_outage    = True

# Gather all tank-related stuff with a view to making a class...
housetank   = Tank("Empty")             # make my tank object

# New state...
fill_states = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]
# Physical Constants
Tank_Height = 1700
OverFull	= 250
Min_Dist    = 400               # full
Max_Dist    = 1400              # empty
Delta       = 50                # change indicating pump state change has occurred

# Tank variables/attributes
depth       = 0
last_depth  = 0
depth_ROC   = 0
max_ROC     = 0.2			    # change in metres/minute... soon to be measured on SMA/ring buffer
min_ROC     = 0.15              # experimental.. might need to tweak.  To avoid noise in anomaly tests

# Various constants
if DEBUGLVL > 0:
    mydelay = 5
    FLUSH_PERIOD = 5
else:
    mydelay = 15             # Sleep time... seconds, not ms...  Up from 5, using calculated data
    FLUSH_PERIOD = 15

# logging stuff...
log_freq    = 5
last_logged_depth = 0
min_log_change_m = 0.001	# to save space... only write to file if significant change in level
level_init  = False 		# to get started

counter         = 0
ringbufferindex = 0         # for SMA calculation... keep last n measures in a ring buffer

LOGRINGSIZE     = 10        # max log ringbuffer length
logindex        = 0         # for scrolling through error logs on screen
# endregion

# start doing stuff
buzzer.value(0)			    # turn buzzer off
lcd.clear()
#rtc.getDateTime()

# how I will monitor pressure pump state...
def pp_callback(pin):
    presspmp.irq(handler=None)
    v = pin.value()
    presspump.switch_pump(v)
    print("Pressure Pump Pin triggered:", v)
    sleep_ms(100)
    presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)

# Configure the pin

# Attach the ISR for both rising and falling edges
presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)
#presspmp.irq(trigger=Pin.IRQ_FALLING, handler=pp_LO_callback)

# CHANGE THIS... do after initialising internal clock

def lcdbtn_pressed(x):          # my lcd button ISR
    global btnflag
    btnflag = not btnflag
    sleep_ms(300)

lcdbtn.irq(handler=lcdbtn_pressed, trigger=Pin.IRQ_RISING)

def lcd_off(x):
    lcd.setRGB(0,0,0)

async def check_lcd_btn():
    global btnflag
    while True:
        if btnflag:
#            lcdbl_toggle()
            lcd.setRGB(170,170,138)     # turn on, and...
            tim=Timer(period=LCD_ON_TIME, mode=Timer.ONE_SHOT, callback=lcd_off)
            btnflag = False
        await uasyncio.sleep(0.5)

# def Pico_RTC():
#     tod   = rtc.timestamp()
#     year  = tod.split()[0].split("-")[0]
#     month = tod.split()[0].split("-")[1]
#     day   = tod.split()[0].split("-")[2]
#     shortyear = year[2:]

# def internal_RTC():
#     global year
#     now   = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
#     year  = now[0]
#     month = now[1]
#     day   = now[2]

def init_logging():
    global year, month, day, shortyear
    global f, ev_log, pp_log

    now   = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
    year  = now[0]
    month = now[1]
    day   = now[2]
    shortyear = str(year)[2:]
    datestr = f"{shortyear}{month:02}{day:02}"
    daylogname  = f'tank {datestr}.txt'
    pplogname   = f'pressure {datestr}.txt'
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

def calc_ROC_SMA()-> float:
    sum = 0
    n = 0
    for dval in ringbuf:
        if dval > 0:
            sum += dval
            n += 1
    if n > 0:
        return sum / n
    else:
        return 0.0

def get_tank_depth():
    global depth, tank_is

    d = distSensor.read()
    depth = (Tank_Height - d) / 1000
    tank_is = get_fill_state(d)

def updateData():
    global tank_is
    global depth_str
    global depth
    global last_depth
    global depth_ROC
    global ringbuf, ringbufferindex, sma_depth
  
    get_tank_depth()
    ringbuf[ringbufferindex] = depth ; ringbufferindex = (ringbufferindex + 1) % ROC_AVERAGE
    sma_depth = calc_ROC_SMA()
    if DEBUGLVL > 0:
#        print("Ringbuf: ", ringbuf)
        print("sma_depth: ", sma_depth)
    depth_ROC = (sma_depth - last_depth) / (mydelay / 60)	# ROC in m/minute.  Save neagtives also... for anomaly testing
    if DEBUGLVL > 0: print(f"depth_ROC: {depth_ROC:.3f}")
    last_depth = sma_depth				# track change since last reading
    depth_str = f"{depth:.2f}m " + tank_is

def updateClock():
    global str_time, event_time

    now   = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
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
    add_to_log_ring(f"{event_time}: ERROR switching to {new_state}")
    
def parse_reply(rply):
    if DEBUGLVL > 1: print(f"in parse arg is {rply}")
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
    global tank_is, counter, radio, event_time, system
    if tank_is == fill_states[0]:		# Overfull
        buzzer.value(1)			# raise alarm
    else:
        buzzer.value(0)
    if tank_is == fill_states[len(fill_states) - 1]:		# Empty
        if not borepump.state:		# pump is off, we need to switch on
            if DEBUGLVL > 1: print("cBP: Opening valve")
            solenoid.value(0)
            if confirm_solenoid():
                counter += 1
                tup = ("ON", radio_time(time.time()))   # was previosuly counter... now, time
    #            print(tup)
                system.on_event("ON REQ")
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
                        system.on_event("ON ACK")
                        if DEBUGLVL > 0: print(f"Class: Set borepump to state {borepump.state}")
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
            system.on_event("OFF REQ")
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
                    system.on_event("OFF ACK")
                    if DEBUGLVL > 1: print("cBP: Closing valve")
                    solenoid.value(1)               # wait until pump OFF confirmed before closing valve !!!
                    if DEBUGLVL > 1: print(f"Class: Set borepump to state {borepump.state}")
                else:
                    log_switch_error(new_state)

def add_to_log_ring(s):
    global logindex
    
    logring[logindex] = s
    if len(logring) < LOGRINGSIZE:
        logring.append("")
#        logindex = len(logring)

    logindex = (logindex + 1) % LOGRINGSIZE
         
def dump_log_ring():
    if len(logring) < LOGRINGSIZE:
        for i in range(logindex - 1, -1, -1):
            s = logring[i]
            if s != "": print(f"Errorlog {i}: {logring[i]}")
    else:
        i = logindex - 1            # start with last log entered
        for k in range(LOGRINGSIZE):
            s = logring[i]
            if s != "": print(f"Errorlog {i}: {logring[i]}")
            i = (i - 1) % LOGRINGSIZE
    
def raiseAlarm(param, val):
    global logring, logindex
    global ev_log, event_time
    str = f"{event_time} ALARM {param}, value {val:.3g}"
    print(str)
    ev_log.write(f"{str}\n")
    add_to_log_ring(str)
    
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
    logstr = str_time + f" {depth:.3f}\n"
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
    # else:
        # print("nothing received in init_radio")
    # print("Pinging RX Pico...")
    while not ping_RX():            # NOTE: This potentially an infinte block...
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
#    print(f"Pump Initial state is {initial_state}")
    return initial_state

def dump_pump_arg(p:Pump):
    global ev_log

    pid = p.ID
# write pump object stats to log file, typically when system is closed/interupted
    ev_log.flush()
    ev_log.write(f"Stats for pump ID {pid}\n")

    dc_secs = p.cum_seconds_on
    days  = int(dc_secs / (60*60*24))
    hours = int(dc_secs % (60*60*24) / (60*60))
    mins  = int(dc_secs % (60*60) / 60)
    secs  = int(dc_secs % 60)
    
    ev_log.write(f"Last switch time:   {display_time(secs_to_localtime(p.last_time_switched))}\n")
    ev_log.write(f"Total switches this period: {p.num_switch_events}\n")
    ev_log.write(f"Cumulative runtime: {days} days {hours} hours {mins} minutes {secs} seconds\n")
    ev_log.flush()

def connect_wifi():
    global system

# Connect to Wi-Fi
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print("connect_wifi..")
    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.connect(ssid, password)
        while not wlan.isconnected():       # another potential infinite block...
            print(">", end="")
            time.sleep(1)
    system.on_event("ACK WIFI")
    print('Connected to:', wlan.ifconfig())

def secs_to_localtime(s):
    tupltime = time.localtime(s)
    year = tupltime[0]
    DST_end   = time.mktime((year, 4,(31-(int(5*year/4+4))%7),2,0,0,0,0,0))     # Time of April change to end DST
    DST_start = time.mktime((year,10,(7-(int(year*5/4+4)) % 7),2,0,0,0,0,0))    # Time of October change to start DST
    
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
#   if time.localtime()[0] < 2024:  # if we reset, localtime will return 2021...
#        connect_wifi()
    set_time()
    system.on_event("ACK NTP")

def calibrate_clock():
    global radio

    delay=500
#   for i in range(1):
    p = time.ticks_ms()
    s = "CLK"
    t=(s, p)
    transmit_and_pause(t, delay)

def sync_clock():                   # initiate exchange of time info with RX, purpose is to determine clock adjustment
    global radio, clock_adjust_ms, system

    if str(system.state) == "COMMS_READY":
        print("Starting clock sync process")
        calibrate_clock()
        count = 2
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
            rcv_msg = radio.message
            if type(rcv_msg) is tuple:
                if rcv_msg[0] == "CLK":
                    if DEBUGLVL > 0: print(f"Got CLK SYNC reply after {loop_count} loops")
                    clock_adjust_ms = int(rcv_msg[1])
                    if abs(clock_adjust_ms) > 100000:       # this looks dodgy...
                        print(f"*****Bad clock adjust: {clock_adjust_ms}... setting to 800")
                        clock_adjust_ms = 800
        else:                           # we did NOT get a reply... don't block... set adj to default 500
            clock_adjust_ms = 0
        system.on_event("CLK SYNC")
    else:
        print(f"What am I doing here in state {str(system.state)}")

    if DEBUGLVL > 0: print(f"Setting clock_adjust to {clock_adjust_ms}") 

def init_ringbuffers():
    global  ringbuf, ringbufferindex, logring, logindex

    ringbuf = [0.0]                 # start with a list containing zero...
    if ROC_AVERAGE > 1:             # expand it as needed...
        for x in range(ROC_AVERAGE - 1):
            ringbuf.append(0.0)
    if DEBUGLVL > 0: print("Ringbuf is ", ringbuf)
    ringbufferindex = 0

    logring = [""]
    logindex = 0

def init_everything_else():
    global borepump, steady_state, free_space_KB, presspump, vbus_on_time
    
    lcd.setRGB(170,170,138)   
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

    init_ringbuffers()

# ensure we start out right...
    steady_state = False

    vbus_on_time = time.time()      # init this... so we can test external

def heartbeat() -> bool:
    global borepump
# heartbeat... if pump is on, send a regular heartbeat to the RX end
# On RX, if a max time has passed... turn off.
# Need a mechanism to alert T... and reset

# Doing this inline as it were to avoid issues with async, buffering yada yada.
# The return value indicates if we need to sleep before continuing the main loop

# only do heartbeat if the pump is running
    if borepump.state:
        transmit_and_pause("BABOOM", RADIO_PAUSE)       # this might be a candidate for a shorter delay... if no reply expected
    return borepump.state

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
            raiseAlarm("Solenoid OFF Invalid - Pump is ", borepump.state )
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

async def regular_flush(m):
    while True:
        f.flush()
        ev_log.flush()
        await uasyncio.sleep(m)

# def mypp_handler(pin):
#     global l, mypp

#     mypp.irq(handler=None)
#     v = pin.value()
#     if v:
#         print(str_HI)
#         l.write(str_HI)
#     else:
#         print(str_LO)
#         l.write(str_LO)
# #    l.flush()
#     sleep(1)
#     mypp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=mypp_handler)

def housekeeping(close_files: bool):
    print("Flushing data to flash...")
    start_time = time.ticks_us()
    f.flush()
    ev_log.write(f"{event_time} STOP")
    ev_log.write(f"\nMonitor shutdown at {display_time(secs_to_localtime(time.time()))}\n")
    dump_pump_arg(borepump)
    dump_log_ring()
    ev_log.write("Next Pump dump...\n")
    dump_pump_arg(presspump)
    ev_log.flush()
    end_time = time.ticks_us()
    if close_files:
        f.close()
        ev_log.close()

    print(f"Cleanup completed in {time.ticks_diff(end_time, start_time)} microseconds")

def monitor_vbus():
    global vbus_on_time, report_outage

    now = time.time()
    if vbus_sense.value():
        vbus_on_time = now
        report_outage = True
    else:
        if (now - vbus_on_time >= MAX_OUTAGE) and report_outage:
            s = f">>: {display_time(secs_to_localtime(time.time()))}  Power off for more than {MAX_OUTAGE} seconds\n"
            ev_log.write(s)             # seconds since last saw power 
            report_outage = False
            housekeeping(False)

async def main():
    global event_time, ev_log, steady_state, housetank, system

    print("RUNNING START")
    rec_num=0
    #radio.rfm69_reset
    lcd.setRGB(170,170,138)
# first cut at how to progress SM on start-up.  Not clear if this is optimal.  Maybe better to drive this inside SM methods

    if not system:              # yikes... don't have a SM ??
        if DEBUGLVL > 0:
            print("GAK... no state machine exists at start-up")
    else:
 #       print(f"Before while...{type(system.state)} ")
        while  str(system.state) != "READY":
            print(str(system.state))
            if str(system.state) == "PicoReset":
                connect_wifi()  # ACK WIFI
                lcd.clear()
                lcd.printout("WIFI")
            if str(system.state) == "WIFI_READY":
                init_clock()    # ACK NTP
                lcd.clear()
                lcd.printout("CLOCK")
            if str(system.state) == "CLOCK_SET":
                init_radio()    # ACK COMMS
                lcd.clear()
                lcd.printout("COMMS")
            if str(system.state) == "COMMS_READY":
#                sync_clock()    # ACK SYNC
#            if str(system.state) == "CLOCK_SYNCED":
                lcd.clear()
                lcd.printout("READY")
                system.on_event("START_MONITORING")
            sleep(1)

    start_time = time.time()
    init_logging()          # needs corect time first!
    print(f"Main TX starting at {display_time(secs_to_localtime(start_time))}")
    updateClock()				    # get DST-adjusted local time
    
    get_tank_depth()
    init_everything_else()

    housetank.state = tank_is
    print(f"Initial Housetank state is {housetank.state}")
    if (housetank.state == "Empty" and not borepump.state):           # then we need to start doing somethin... else, we do NOTHING
        print("Immediate switch pump ON required")
    elif (borepump.state and (housetank.state == "Full" or housetank.state == "Overflow")):     # pump is ON... but...
        print("Immediate switch pump OFF required")
    else:
        print("No immediate action required")

    ev_log.write(f"\nPump Monitor starting: {event_time}\n")

# start coroutines..
    uasyncio.create_task(check_lcd_btn())                   # start up lcd_button widget
    uasyncio.create_task(regular_flush(FLUSH_PERIOD))       # flush data every 15 minutes
    

    while True:
        updateClock()			# get datetime stuff
        updateData()			# monitor water depth
        controlBorePump()		# do whatever
#        listen_to_radio()		# check for badness
        displayAndLog()			# record it
        if steady_state: checkForAnomalies()	    # test for weirdness
        rec_num += 1
        if rec_num > ROC_AVERAGE and not steady_state: steady_state = True    # just ignore data until ringbuf is fully populated
        delay_ms = mydelay * 1000
        if heartbeat():             # send heartbeat if ON... not if OFF.  For now, anyway
#           if DEBUGLVL > 1: print("Need to sleep...")
            delay_ms -= RADIO_PAUSE
#        print(f"Doing uasyncio.sleep_ms({delay_ms})")
        monitor_vbus()          # escape clause... to trigger dump...

        await uasyncio.sleep_ms(delay_ms)


try:
    uasyncio.run(main())

except uasyncio.CancelledError:
    print("I see a cancelled uasyncio thing")

except KeyboardInterrupt:
    lcd.setRGB(0,0,0)		                # turn off backlight
    print('\n### Program Interrupted by the user')
# turn everything OFF
    borepump.switch_pump(False)             # turn pump OFF
#    confirm_and_switch_solenoid(False)     #  *** DO NOT DO THIS ***  If live, this will close valve while pump.
#           to be real sure, don't even test if pump is off... just leave it... for now.

#    lcd_btn_task.              would like to cancel this task, but seems I can't

# tidy up...
    housekeeping(True)

# if __name__ == '__main__':
    # main()