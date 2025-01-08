# Trev's super dooper Tank/Pump monitoring system
# region IMPORTS

# from PiicoDev_RV3028 import PiicoDev_RV3028
import RGB1602
import time
import utime
import network
import ntptime
import os
import random               # just for PP detect sim...
import uasyncio
import gc
from utime import sleep, ticks_us, ticks_diff
from PiicoDev_Unified import sleep_ms
from PiicoDev_VL53L1X import PiicoDev_VL53L1X
from PiicoDev_Transceiver import PiicoDev_Transceiver
from machine import Timer, Pin, ADC, soft_reset # Import Pin
from Pump import Pump               # get our Pump class
from Tank import Tank
from secrets import MyWiFi
from MenuNavigator import MenuNavigator

# OK... major leap... intro to FSM...
from SM_SimpleFSM import SimpleDevice
# endregion
# region initial declarations etc

# constant/enums
OP_MODE_AUTO        = 0
OP_MODE_IRRIGATE    = 1
OP_MODE_MAINT       = 2

UI_MODE_NORM        = 0
UI_MODE_MENU        = 1

TIMERSCALE          = 10            # permits fast speed debugging... normally, set to 60 for "minutes" in timed ops
DEFAULT_CYCLE       = 5             # for timed stuff... might eliminate the default thing...

RADIO_PAUSE         = 1000
MIN_FREE_SPACE      = 100           # in KB...

FLUSH_PERIOD        = 2
ROTARY_PERIOD_MS    = 100           # needs to be short... check rotary ISR variables

EVENTRINGSIZE       = 20            # max log ringbuffer length
SWITCHRINGSIZE      = 20

MAX_OUTAGE          = 20            # seconds of no power

#All menu-CONFIGURABLE parameters
mydelay             = 5            # seconds, main loop period
LCD_ON_TIME         = 600            # seconds
Min_Dist            = 500           # full
Max_Dist            = 1400          # empty
MAX_LINE_PRESSURE   = 700           # TBC... but this seems about right
MIN_LINE_PRESSURE   = 300           # tweak after running... and this ONLY applies in OP_MODE_IRRIG
NO_LINE_PRESSURE    = 15            # tweak this too... applies in ANY pump-on mode
MAX_CONTIN_RUNMINS  = 60            # 3 hours max runtime.  More than this looks like trouble

SIMULATE_PUMP       = True          # debugging aid...replace pump switches with a PRINT
DEBUGLVL            = 0
ROC_AVERAGE         = 5             # make 1 for NO averaging... otherwise do an SMA of this period.  Need a ring buffer?

# Physical Constants
Tank_Height         = 1700
OverFull	        = 250
Delta               = 50            # change indicating pump state change has occurred
TEMP_CONV_FACTOR 	= 3.3 / 65535   # looks like 3.3V / max res of 16-bit ADC ??

# Tank variables/attributes
depth               = 0
last_depth          = 0
depth_ROC           = 0
max_ROC             = 0.2			# change in metres/minute... soon to be measured on SMA/ring buffer
min_ROC             = 0.15          # experimental.. might need to tweak.  To avoid noise in anomaly tests

op_mode             = OP_MODE_AUTO
ui_mode             = UI_MODE_NORM

# logging stuff...
LOG_FREQ            = 80
last_logged_depth   = 0
last_logged_kpa     = 0
min_log_change_m    = 0.001	        # to save space... only write to file if significant change in level
max_kpa_change      = 10            # update after pressure sensor active
level_init          = False 		# to get started

ringbufferindex     = 0             # for SMA calculation... keep last n measures in a ring buffer
eventindex          = 0             # for scrolling through error logs on screen
switchindex         = 0

lcdbtnflag          = True          # this should immediately trigger my asyncio timer on startup...

# Misc stuff
steady_state        = False         # if not, then don't check for anomalies
clock_adjust_ms     = 0             # will be set later... this just to ensure it is ALWAYS something
report_outage       = True          # do I report next power outage?

# Gather all tank-related stuff with a view to making a class...
housetank           = Tank("Empty")                     # make my tank object

# New state...
fill_states         = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]

# Pins
vsys                = ADC(3)                            # one day I'll monitor this for over/under...
temp_sensor         = ADC(4)			                # Internal temperature sensor is connected to ADC channel 4
lcdbtn 	            = Pin(6, Pin.IN, Pin.PULL_UP)		# check if IN is correct!
buzzer 		        = Pin(16, Pin.OUT)
presspmp            = Pin(15, Pin.IN, Pin.PULL_UP)      # prep for pressure pump monitor.  Needs output from opamp circuit
prsspmp_led         = Pin(14, Pin.OUT)
solenoid            = Pin(2, Pin.OUT, value=0)          # MUST ensure we don't close solenoid on startup... pump may already be running !!!  Note: Low == Open
vbus_sense          = Pin('WL_GPIO2', Pin.IN)           # external power monitoring of VBUS
led                 = Pin('LED', Pin.OUT)
bp_pressure         = ADC(0)                            # Is this right?  or should it be Pin 26

# Create pins for encoder lines and the onboard button

enc_btn             = Pin(18, Pin.IN, Pin.PULL_UP)
enc_a               = Pin(19, Pin.IN)
enc_b               = Pin(20, Pin.IN)
last_time           = 0
count               = 0


system              = SimpleDevice()                    #initialise my FSM.
wf                  = MyWiFi()
# Create PiicoDev sensor objects
#First... I2C devices
distSensor 	        = PiicoDev_VL53L1X()
lcd 		        = RGB1602.RGB1602(16,2)
radio               = PiicoDev_Transceiver()
#rtc 		        = PiicoDev_RV3028()                 # Initialise the RTC module, enable charging

# Configure your WiFi SSID and password
ssid                = wf.ssid
password            = wf.password
# endregion
# region DICTIONARIES
config_dict         = {
    'Delay'         : mydelay,
    'LCD'           : LCD_ON_TIME,
    'MinDist'       : Min_Dist,
    'MaxDist'       : Max_Dist,
    'Max Pressure'  : MAX_LINE_PRESSURE,
    'Min Pressure'  : MIN_LINE_PRESSURE,
    'No Pressure'   : NO_LINE_PRESSURE,
    'Max RunMins'   : MAX_CONTIN_RUNMINS
            }

timer_dict          = {
    'Cycle1'        : DEFAULT_CYCLE,
    'Cycle2'        : DEFAULT_CYCLE,
    'Cycle3'        : DEFAULT_CYCLE
              }
    
water_list = [("cycle1", {"init" : 2, "run" : 2, "off" : 3}),
              ("cycle2", {"init" : 4, "run" : 5, "off" : 3}),
              ("cycle3", {"init" : 1, "run" : 2, "off" : 3}),
            #   ("cycle4", {"init" : 1, "run" : 5, "off" : 1}),
            #   ("cycle5", {"init" : 1, "run" : 1, "off" : 1}),
            #   ("cycle6", {"init" : 1, "run" : 1, "off" : 1}),
              ("zzzEND", {"init" : 1, "run" : 8, "off" : 9})]

def update_config():
    
    for param_index in range(len(config_dict)):
        param: str             = new_menu['items'][3]['items'][0]['items'][param_index]['title']
        new_working_value: int = new_menu['items'][3]['items'][0]['items'][param_index]['value']['Working_val']
        if param in config_dict.keys():
            # print(f"in update_config {param}: dict is {config_dict[param]} nwv is {new_working_value}")
            if new_working_value > 0 and config_dict[param] != new_working_value:
                config_dict[param] = new_working_value
                print(f'Updated {param} to {new_working_value}')
                lcd.clear()
                lcd.setCursor(0,0)
                lcd.printout(f'Updated {param}')
                lcd.setCursor(0,1)
                lcd.printout(f'to {new_working_value:<13}')
        else:
            print(f"GAK! Config parameter {param} not found in config dictionary!")
            lcd.setCursor(0,0)
            lcd.printout("No dict entry:  ")
            lcd.setCursor(0,1)
            lcd.printout(param)

def update_timers():
    
    for param_index in range(len(timer_dict)):
        param: str             = new_menu['items'][3]['items'][1]['items'][param_index]['title']
        new_working_value: int = new_menu['items'][3]['items'][1]['items'][param_index]['value']['Working_val']
        # print(f">> {param=}, {new_working_value}")
        if param in timer_dict.keys():
            # print(f"in update_timers {param}: dict is {timer_dict[param]} nwv is {new_working_value}")
            if new_working_value > 0 and timer_dict[param] != new_working_value:
                timer_dict[param] = new_working_value
                print(f'Updated {param} to {new_working_value}')
                lcd.setCursor(0,0)
                lcd.printout(f'Updated {param}')
                lcd.setCursor(0,1)
                lcd.printout(f'to {new_working_value}')
        else:
            print(f"GAK! Config parameter {param} not found in timer dictionary!")
            lcd.setCursor(0,0)
            lcd.printout("No dict entry:  ")
            lcd.setCursor(0,1)
            lcd.printout(param)
# endregion
# region TIMED IRRIGATION
def toggle_borepump(x:Timer):
    global timer_state, op_mode, sl_index, my_timer, cyclename, cycle_end_time, nextcycle_ON_time

    x_str = f'{x}'
    period: int = int(int(x_str.split(',')[2].split('=')[1][0:-1]) / 1000)
    milisecs = period
    secs = int(milisecs / 1000)
    mins = int(secs / 60)
    mem = gc.mem_free()
    # need to use tuples to get this... cant index dictionary, as unordered.  D'oh...
    cyclename = str(sl_index)
    # print(f'{current_time()} in toggle, {sl_index=}, {cyclename=}, {timer_state=}, {period=},  {secs} seconds... {mins} minutes... {mem} free')
    if op_mode == OP_MODE_IRRIGATE:
        if sl_index < len(slist) - 1:
            timer_state = (timer_state + 1) % 3
            now = time.time()
            if  timer_state == 1:
                # print(f"{current_time()}: TOGGLE - turning pump ON")
                diff = slist[sl_index + 1] - slist[sl_index]        # look forward to next timer event
                cycle_end_time = now + diff * TIMERSCALE
                diff = slist[sl_index + 3] - slist[sl_index]
                nextcycle_ON_time = now + diff * TIMERSCALE
                # nextcycle_ON_time = now + (slist[sl_index + 1] + slist[sl_index + 2] + slist[sl_index + 3]) * TIMERSCALE
                borepump_ON()        #turn_on()
            elif timer_state == 2:
                # diff = slist[sl_index + 2] - slist[sl_index]
                # nextcycle_ON_time = now + diff * TIMERSCALE
                # print(f"{current_time()}: TOGGLE - turning pump OFF")
                borepump_OFF()       #turn_off()
            elif timer_state == 0:
                pass
                # diff = slist[sl_index + 1] - slist[sl_index]
                # nextcycle_ON_time = now + diff * TIMERSCALE
                # print(f"{current_time()}: TOGGLE - Doing nothing")
            if sl_index == len(slist) - 2:              # we must be in penultimate cycle, or last cycle
                nextcycle_ON_time = now 

            # print(f" end cycle {display_time(secs_to_localtime(cycle_end_time))}\nnext cycle {display_time(secs_to_localtime(nextcycle_ON_time))}")
        # now, set up next timer
            sl_index += 1
            diff = slist[sl_index] - slist[sl_index - 1]
            # print(f"Creating timer for index {sl_index}, {slist[sl_index]}, {diff=}")
            # if my_timer is not None:
            #     my_timer.deinit()
            my_timer = Timer(period=diff*TIMERSCALE*1000, mode=Timer.ONE_SHOT, callback=toggle_borepump)
        # print(f"{timer_state=}")
        else:
            op_mode = OP_MODE_AUTO
            print(f"{current_time()}: in TOGGLE... END IRRIGATION mode !  Now in {op_mode}")
            if borepump.state:
                borepump_OFF()       # to be sure, to be sure...
                print(f"{current_time()}:in toggle, at END turning pump OFF.  Should already be OFF...")
        if mem < 60000:
            print("Collecting garbage...")              # moved to AFTER timer created... might avoid the couple seconds discrepancy.  TBC
            gc.collect()
    else:
        print(f'{current_time()} in toggle {op_mode=}.  Why are we here??')

def start_irrigation_schedule():
    global timer_state, op_mode, slist, sl_index, my_timer, cycle_end_time, num_cycles          # cycle mod 3

    try:
        if op_mode == OP_MODE_IRRIGATE:
            print(f"Can't start irrigation program... already in {op_mode}")
        else:
            swl=sorted(water_list, key = lambda x: x[0])
            print(f"{current_time()}: Starting timed watering...")
            ev_log.write(f"{current_time()}: Starting timed watering\n")
            op_mode          = OP_MODE_IRRIGATE          # the trick is, how to reset this when we are done...

            timer_state      = 0
            sl_index         = 0
            next_switch_time = 0
            cycle_end_time   = 0
            num_cycles       = 0
            
            slist.clear()

            for s in swl:
                cyclename = s[0]
                # print(f"Adding timer nodes to slist for cycle {cyclename}")
                if "end" in cyclename.lower():
                    t=s[1]["init"]
                    next_switch_time += t
                    # print(f'{next_switch_time=}')
                    # print(f"Irrigation end time: {next_switch_time}")
                    slist.append(next_switch_time)
                    break
                else:
                    for k in ["init", "run", "off"]:
                        t=s[1][k]
                        if k == "init" and t == 0:
                            # print(f"Skipping {cyclename}")
                            break
                        else:
                            next_switch_time += t
                            # print(f'{next_switch_time=}')
                            slist.append(next_switch_time)
                            num_cycles += 1

            slist.sort()
            # print(f"Initiating timers: first target is {slist[0]}.  Total {len(slist)} targets")
            sl_index = 0
            my_timer = Timer(period=slist[sl_index]*TIMERSCALE*1000, mode=Timer.ONE_SHOT, callback=toggle_borepump)
            # print(slist)
            lcd.setCursor(0,1)
            lcd.printout(f"Schedule created")
            # print("Watering Schedule created")
            return
        
    except MemoryError:
        print("MemoryError caught")
        print(f"before gc free mem: {gc.mem_free()}")
        gc.collect()
        print(f" after gc free mem: {gc.mem_free()}")

    except Exception as e:
        print(f"Exception caught in start_irrigation_schedule: {e}")
        print(f"before gc free mem: {gc.mem_free()}")
        gc.collect()
        print(f" after gc free mem: {gc.mem_free()}")
# endregion
# region MENU METHODS
# methods invoked from menu

def exit_menu():                      # exit from MENU mode
    global ui_mode
    # process_menu = False
    lcd.setCursor(0,1)
    lcd.printout(f'{"Exit & Update":<16}')
    update_config()
    update_timers()
    ui_mode = UI_MODE_NORM
    tim=Timer(period=config_dict["LCD"] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)

def display_depth():
    global display_mode

    display_mode = "depth"
    print(f'{display_mode=}')

def display_pressure():
    global display_mode

    display_mode = "pressure"
    print(f'{display_mode=}')

def my_go_back():
    navigator.go_back()
               
def show_events():
    navigator.mode = "view_events"

def show_switch():
    navigator.mode = "view_switch"

def show_depth():
    print("Show Depth Not implemented")

def show_pressure():
    print("Show Pressure Not implemented")

def show_space():
    lcd.setCursor(0,1)
    lcd.printout(f'Free KB: {free_space():<6}')

def my_reset():
    ev_log.write(f"{event_time} SOFT RESET")
    housekeeping(True)
    soft_reset()

def hardreset():
    # ev_log.write(f"{event_time} HARD RESET")
    # housekeeping(True)
    pass

def flush_data():
    housekeeping(False)

def housekeeping(close_files: bool):
    print("Flushing data to flash...")
    start_time = time.ticks_us()
    f.flush()
    ev_log.write(f"{event_time} STOP")
    ev_log.write(f"\nMonitor shutdown at {display_time(secs_to_localtime(time.time()))}\n")
    dump_pump_arg(borepump)
    dump_event_ring()
    dump_pump_arg(presspump)
    ev_log.flush()
    end_time = time.ticks_us()
    if close_files:
        f.close()
        ev_log.close()

    print(f"Cleanup completed in {time.ticks_diff(end_time, start_time)} microseconds")

def showdir():
    for f in os.ilistdir():
        fn = f[0]
        if "tank" in fn:
            fstat = os.stat(fn)
            fdate = fstat[7]
            print(f'{fn}: time {display_time(secs_to_localtime(fdate))}')

new_menu = {
    "title": "L0 Main Menu",
    "items": [
      {
        "title": "1 Display->",
        "items": [
          { "title": "1.1 Depth", "action": display_depth},
          { "title": "1.2 Pressure", "action": display_pressure},
          { "title": "1.2 Space", "action": show_space},
          { "title": "1.4 Go Back", "action": my_go_back
          }
        ]
      },
      {
        "title": "2 History->",
        "items": [
          { "title": "2.1 Events",   "action": show_events},
          { "title": "2.2 Switch",   "action": show_switch},
          { "title": "2.3 Depth",    "action": show_depth},
          { "title": "2.4 Pressure", "action": show_pressure},
          { "title": "2.5 Timer",    "action": "Timer"},
          { "title": "2.6 Stats",    "action": "Stats"},
          { "title": "2.7 Go back",  "action": my_go_back}
        ]
      },
      {
        "title": "3 Actions->",
        "items": [
          { "title": "3.1 Timed Water",   "action": start_irrigation_schedule},
          { "title": "3.2 Flush",   "action": flush_data},
          { "title": "3.3 Reset",   "action": my_reset},
          { "title": "3.4 Files",   "action": showdir},
          { "title": "3.5 Go back", "action": my_go_back}
        ]
      },
      {
        "title": "4 Config->",
        "items": [
          { "title": "4.1 Set Config->",
            "items": [
                { "title": "Delay",        "value": {"Default_val": 15,   "Working_val" : mydelay,                  "Step" : 5}},
                { "title": "LCD",          "value": {"Default_val": 5,    "Working_val" : LCD_ON_TIME,              "Step" : 2}},
                { "title": "MinDist",      "value": {"Default_val": 500,  "Working_val" : Min_Dist,                 "Step" : 100}},
                { "title": "MaxDist",      "value": {"Default_val": 1400, "Working_val" : Max_Dist,                 "Step" : 100}},
                { "title": "Max Pressure", "value": {"Default_val": 700,  "Working_val" : MAX_LINE_PRESSURE,        "Step" : 25}},                
                { "title": "Min Pressure", "value": {"Default_val": 300,  "Working_val" : MIN_LINE_PRESSURE,        "Step" : 25}},
                { "title": "No Pressure",  "value": {"Default_val": 15,   "Working_val" : NO_LINE_PRESSURE,         "Step" : 1}},
                { "title": "Max RunMins",  "value": {"Default_val": 180,  "Working_val" : MAX_CONTIN_RUNMINS,   "Step" : 10}},
                { "title": "Go back",  "action": my_go_back}
            ]
          },
           { "title": "4.2 Set Timers->",
            "items": [
                { "title": "Cycle1",  "value": {"Default_val": 5,  "Working_val" : DEFAULT_CYCLE, "Step" : 5}},
                { "title": "Cycle2",  "value": {"Default_val": 5,  "Working_val" : DEFAULT_CYCLE, "Step" : 5}},
                { "title": "Cycle3",  "value": {"Default_val": 5,  "Working_val" : DEFAULT_CYCLE, "Step" : 5}},
                { "title": "Go back", "action": my_go_back}
            ]
          },
          { "title": "4.3 Save Config", "action": "Save Config"},
          { "title": "4.4 Load Config", "action": "Load Config"},
          { "title": "4.5 Go back", "action": my_go_back}
        ]
      },
    {
        "title": "5 Exit", "action": exit_menu
    }
    ]
}

navigator   = MenuNavigator(new_menu, lcd)

def encoder_a_IRQ(pin):
    global enc_a_last_time, encoder_count

    new_time = utime.ticks_ms()
    if (new_time - enc_a_last_time) > 200:
        if enc_a.value() == enc_b.value():
            encoder_count += 1
            # navigator.next()
        else:
            encoder_count -= 1
            # navigator.previous()
    enc_a_last_time = new_time

def encoder_btn_IRQ(pin):
    global enc_btn_last_time, encoder_btn_state

    new_time = utime.ticks_ms()
    if (new_time - enc_btn_last_time) > 200:
        encoder_btn_state = True
    enc_btn_last_time = new_time

def enable_controls():
    
   # Enable the interupt handlers
    enc_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_a_IRQ)
    enc_btn.irq(trigger=Pin.IRQ_FALLING, handler=encoder_btn_IRQ)

    lcdbtn.irq(handler=lcdbtn_pressed, trigger=Pin.IRQ_RISING)
# endregion
# region PRESS PUMP
# # how I will monitor pressure pump state...
def pp_callback(pin):
    presspmp.irq(handler=None)
    v = pin.value()
    presspump.switch_pump(v)
    print("Pressure Pump Pin triggered:", v)
    sleep_ms(100)

presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)

# Attach the ISR for both rising and falling edges
#
#presspmp.irq(trigger=Pin.IRQ_FALLING, handler=pp_LO_callback)
#
# def mypp_handler(pin):
#     global l, mypp
#
#     mypp.irq(handler=None)
#     v = pin.value()
#     if v:
#         print(str_HI)
#         l.write(str_HI)
#     else:
#         print(str_LO)
#         l.write(str_LO)
#     l.flush()
#     sleep(1)
#     mypp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=mypp_handler)

# endregion
# region LCD
def lcdbtn_pressed(x):          # my lcd button ISR
    global lcdbtnflag
    lcdbtnflag = True
    sleep_ms(300)

def lcd_off(x):
    lcd.setRGB(0,0,0)

def lcd_on():
    lcd.setRGB(170,170,138)

async def check_lcd_btn():
    global lcdbtnflag
    while True:
        if lcdbtnflag:
            lcd_on()    # turn on, and...
            if ui_mode != UI_MODE_MENU:                 # don't set timer for OFF in MENU
                # print(f'Setting LCD timer for {config_dict["LCD"]} seconds')
                tim=Timer(period=config_dict["LCD"] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)
            lcdbtnflag = False
        await uasyncio.sleep(0.5)
# endregion
# region UNUSED methods
# def Pico_RTC():
#     tod   = rtc.timestamp()
#     year  = tod.split()[0].split("-")[0]
#     month = tod.split()[0].split("-")[1]
#     day   = tod.split()[0].split("-")[2]
#     shortyear = year[2:]
#endregion
# region MAIN METHODS
def init_logging():
    global year, month, day, shortyear
    global f, ev_log, pp_log

    now             = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
    year            = now[0]
    month           = now[1]
    day             = now[2]
    shortyear       = str(year)[2:]
    datestr         = f"{shortyear}{month:02}{day:02}"
    daylogname      = f'tank {datestr}.txt'
    pplogname       = f'pressure {datestr}.txt'
    eventlogname    = 'borepump_events.txt'
    f               = open(daylogname, "a")
    ev_log          = open(eventlogname, "a")
    pp_log          = open(pplogname, "a")

def get_fill_state(d):
    if d > config_dict["MaxDist"]:
        tmp = fill_states[len(fill_states) - 1]
    elif config_dict["MaxDist"] - Delta < d and d <= config_dict["MaxDist"]:
        tmp = fill_states[4]
    elif config_dict["MinDist"] + Delta < d and d <= config_dict["MaxDist"] - Delta:
        tmp = fill_states[3]
    elif config_dict["MinDist"] < d and d <= config_dict["MinDist"] + Delta:
        tmp = fill_states[2]
    elif OverFull < d and d <= config_dict["MinDist"]:
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
    global pressure_str
    global depth
    global last_depth
    global depth_ROC
    global ringbuf, ringbufferindex, sma_depth
    global bp_kpa
    global temp
  
    get_tank_depth()
    ringbuf[ringbufferindex] = depth ; ringbufferindex = (ringbufferindex + 1) % ROC_AVERAGE
    sma_depth = calc_ROC_SMA()
    if DEBUGLVL > 0:
#        print("Ringbuf: ", ringbuf)
        print("sma_depth: ", sma_depth)
    depth_ROC = (sma_depth - last_depth) / (config_dict["Delay"] / 60)	# ROC in m/minute.  Save neagtives also... for anomaly testing
    if DEBUGLVL > 0: print(f"depth_ROC: {depth_ROC:.3f}")
    last_depth = sma_depth				# track change since last reading
    depth_str = f"{depth:.2f}m " + tank_is
    bp_kpa = 300 + ringbufferindex * 100            # hack for testing... replace with ADC read when calibrated
    pressure_str = f'{bp_kpa:3} kPa'    # might change this to be updated more frequently in a dedicated asyncio loop...
    temp = 27 - (temp_sensor.read_u16() * TEMP_CONV_FACTOR - 0.706)/0.001721

def current_time()-> str:
    now   = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
    # year  = now[0]
    month = now[1]
    day   = now[2]
    hour  = now[3]
    min   = now[4]
    sec   = now[5]
    short_time = f"{hour:02}:{min:02}:{sec:02}"
    str_time = str(month) + "/" + str(day) + " " + short_time 
    return str_time

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
    add_to_event_ring(f"ERR swtch {new_state}")
    
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

def confirm_solenoid():
    solenoid_state = sim_solenoid_detect()

    if op_mode == OP_MODE_AUTO:
        return solenoid_state
    elif op_mode == OP_MODE_IRRIGATE:
        return not solenoid_state

def radio_time(local_time):
    global clock_adjust_ms
    return(local_time + clock_adjust_ms)

def borepump_ON():
    if SIMULATE_PUMP:
        print("SIM Pump ON")
    else:
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
                add_to_switch_ring("PUMP ON")
                ev_log.write(f"{event_time} ON\n")
                system.on_event("ON ACK")
            else:
                log_switch_error(new_state)

def borepump_OFF():
    if SIMULATE_PUMP:
        print("SIM Pump OFF")
    else:
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
                add_to_switch_ring("PUMP OFF")
                ev_log.write(f"{event_time} OFF\n")
                system.on_event("OFF ACK")
                if DEBUGLVL > 1: print("cBP: Closing valve")
                solenoid.value(1)               # wait until pump OFF confirmed before closing valve !!!
            else:
                log_switch_error(new_state)

def controlBorePump():
    global tank_is, radio, event_time, system
    if tank_is == fill_states[0]:		# Overfull
        buzzer.value(1)			        # raise alarm
    else:
        buzzer.value(0)
    if tank_is == fill_states[len(fill_states) - 1]:		# Empty
        if not borepump.state:		# pump is off, we need to switch on
            if op_mode == OP_MODE_AUTO:
                if DEBUGLVL > 1: print("cBP: Opening valve")
                solenoid.value(0)
            if confirm_solenoid():
                borepump_ON()
            else:               # dang... want to turn pump on, but solenoid looks OFF
                raiseAlarm("NOT turning pump on... valve is CLOSED!", event_time)
    elif tank_is == fill_states[0] or tank_is == fill_states[1]:	# Full or Overfull
#        bore_ctl.value(0)			# switch borepump OFF
        if borepump.state:			# pump is ON... need to turn OFF
            if DEBUGLVL > 0: print("in controlBorePump, switching pump OFF")
            borepump_OFF()

def add_to_event_ring(msg:str):
    global eventring, eventindex
    
    if len(eventring) == 1 and len(eventring[0]) == 0:
        eventring[eventindex] = (str_time, msg)
    else:
        if len(eventring) < EVENTRINGSIZE:
#            print("Appending...")
            eventring.append((str_time, msg))
            eventindex = (eventindex + 1) % EVENTRINGSIZE
        else:
            eventindex = (eventindex + 1) % EVENTRINGSIZE
#            print(f"Overwriting index {eventindex}")
            eventring[eventindex] = (str_time, msg)

def add_to_switch_ring(msg:str):
    global switchring, switchindex

    if len(switchring) == 1 and len(switchring[0]) == 0:
        switchring[switchindex] = (str_time, msg)
    else:
        if len(switchring) < SWITCHRINGSIZE:
#            print("Appending...")
            switchring.append((str_time, msg))
            switchindex = (switchindex + 1) % SWITCHRINGSIZE
        else:
            switchindex = (switchindex + 1) % SWITCHRINGSIZE
#            print(f"Overwriting index {switchindex}")
            switchring[switchindex] = (str_time, msg)

def dump_event_ring():                          # both rings are now tuples... (datestamp, msg)

    ev_len = len(eventring)
    # print(f"Eventring has {ev_len} records")
    if ev_len > 0:
        if ev_len < EVENTRINGSIZE:
            for i in range(eventindex - 1, -1, -1):
                s = eventring[i]
                if len(s) > 0: print(f"Errorlog {i}: {s[0]} {s[1]}")
        else:
            i = (eventindex - 1) % EVENTRINGSIZE            # start with last log entered
            for k in range(EVENTRINGSIZE):
                s = eventring[i]
                if len(s) > 0: print(f"Errorlog {i}: {s[0]} {s[1]}")
                i = (i - 1) % EVENTRINGSIZE
    else:
        print("Eventring is empty")
    
def raiseAlarm(param, val):

    logstr = f"{event_time} ALARM {param}, value {val:.3g}"
    ev_str = f"ALARM {param}, value {val:.3g}"
    print(logstr)
    ev_log.write(f"{logstr}\n")
    add_to_event_ring(ev_str)
    
def checkForAnomalies():
    global borepump, max_ROC, depth_ROC, tank_is, bp_kpa

    if borepump.state:                  # pump is ON
        if op_mode == OP_MODE_IRRIGATE and  bp_kpa < config_dict["Min Pressure"]:
            raiseAlarm("Min Pressure", bp_kpa)
        if op_mode == OP_MODE_AUTO:
            if abs(depth_ROC) > max_ROC:
                raiseAlarm("Max ROC Exceeded", depth_ROC)
            if tank_is == "Overflow":        # ideally, refer to a Tank object... but this will work for now
                raiseAlarm("OVERFLOW and still ON", 999)        # probably should do more than this.. REALLY BAD scenario!
            if depth_ROC > min_ROC and not borepump.state:      # pump is OFF but level is rising!
                raiseAlarm("FILLING while OFF", depth_ROC)
            if depth_ROC < -min_ROC and borepump.state:         # pump is ON but level is falling!
                raiseAlarm("DRAINING while ON", depth_ROC)                              

def abort_pumping()-> None:
    global op_mode
# if bad stuff happens, kill off any active timers, switch off, send notification, and enter maintenance state

    if my_timer is not None:
        print("Killing my_timer...")
        my_timer.deinit()

    borepump_OFF()
    logstr = f"{current_time()} ABORT invoked!"
    print(logstr)
    ev_log.write(logstr + "\n")
    lcd.clear()
    lcd.setCursor(0,0)
    lcd.printout(str_time)
    lcd.setCursor(0,1)
    lcd.printout("MAINTENANCE MODE")
    op_mode = OP_MODE_MAINT
# do a SM thing here... TBD            

def check_for_critical_states() -> None:

    if borepump.state:              # pump is ON
        run_minutes = (time.time() - borepump.last_time_switched) / 60
        if bp_kpa > config_dict["Max Pressure"]:
            raiseAlarm("Excess kPa", bp_kpa)
            abort_pumping()
        if run_minutes > config_dict["Max RunMins"]:            # if pump is on, and has been on for more than max... do stuff!
            raiseAlarm("RUNTIME EXCEEDED", run_minutes)
            borepump_OFF()
        if bp_kpa < config_dict["No Pressure"]:
            raiseAlarm("NO Pressure", bp_kpa)
            abort_pumping()

def DisplayData()->None:
    if ui_mode != UI_MODE_MENU:             # suspend overwriting LCD whist in MENU
        lcd.clear()
        lcd.setCursor(0, 0)
        lcd.printout(str_time)
        if op_mode == OP_MODE_AUTO:
            if display_mode == "depth":
                display_str = depth_str
            elif display_mode == "pressure":
                display_str = pressure_str
            else:
                display_str = "?? no display mode"
        elif op_mode == OP_MODE_IRRIGATE:
            if cycle_end_time > 0:
                now = time.time()
                secs_remaining = cycle_end_time - now
                # print(f"In Display, {secs_remaining=}")
                if sl_index == num_cycles:
                    display_str = f"End TWM {pressure_str}"
                else:
                    if secs_remaining < 0:                              # explain... it works, but is cryptic!
                        secs_to_next_ON = nextcycle_ON_time - now       # what if this is negative ???  
                        if secs_to_next_ON < 60:
                            display_str = f"Wait {secs_to_next_ON}s {pressure_str}"
                        else:
                            display_str = f"Wait {int(secs_to_next_ON / 60)}m {pressure_str}"
                    else:
                        if secs_remaining > 60:
                            disp_time = f"{int(secs_remaining / 60)}m"
                        else:
                            disp_time = f"{secs_remaining}s"
                        display_str = f"C{sl_index + 1}/{num_cycles} {disp_time} {pressure_str}"
            else:
                display_str = "Cycle Pending..."
        lcd.setCursor(0, 1)
        lcd.printout(f"{display_str:<16}")

def LogData()->None:
    global LOG_FREQ
    global level_init
    global last_logged_depth
    global last_logged_kpa

# Now, do the print and logging
    tempstr = f"{temp:.2f} C"  
    logstr  = str_time + f" {depth:.3f} {bp_kpa:4}\n"
    dbgstr  = str_time + f" {depth:.3f}m {bp_kpa:4}kPa"    
#    if rec_num % log_freq == 0:
#    if rec_num == log_freq:			# avoid using mod... in case of overflow
#        rec_num = 0					# just reset to zero
#        print('Recnum mod zero...')
#        f.write(logstr)
    enter_log = False
    if not level_init:                  # only start logging after we allow level readings to stabilise
        level_init = True
        last_logged_depth = depth
    else:
        level_change = abs(depth - last_logged_depth)
        pressure_change = abs(last_logged_kpa - bp_kpa)
        if level_change > min_log_change_m:
            last_logged_depth = depth
            enter_log = True
        if pressure_change > max_kpa_change:
            last_logged_kpa = bp_kpa
            enter_log = True
        if enter_log: f.write(logstr)
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
    return initial_state

def dump_pump_arg(p:Pump):
    global ev_log

# write pump object stats to log file, typically when system is closed/interupted
    ev_log.flush()
    ev_log.write(f"Stats for pump {p.ID}\n")

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
    global  ringbuf, ringbufferindex, eventring, eventindex, switchring, switchindex

    ringbuf = [0.0]                 # start with a list containing zero...
    if ROC_AVERAGE > 1:             # expand it as needed...
        for x in range(ROC_AVERAGE - 1):
            ringbuf.append(0.0)
    if DEBUGLVL > 0: print("Ringbuf is ", ringbuf)
    ringbufferindex = 0

    eventring   = [tuple()]         # initialise to an empty tuple
    eventindex  = 0
    switchring  = [tuple()]
    switchindex = 0

def init_everything_else():
    global borepump, steady_state, free_space_KB, presspump, vbus_on_time, display_mode, navigator, encoder_count, encoder_btn_state, enc_a_last_time, enc_btn_last_time
    global slist, cycle_end_time

    encoder_count       = 0       # to track rotary next/prevs
    enc_a_last_time     = utime.ticks_ms()
    encoder_btn_state   = False
    enc_btn_last_time   = enc_a_last_time

    slist=[]

    lcd_on()  
# Get the current pump state and init my object    
    borepump = Pump("BorePump", get_initial_pump_state())

# On start, valve should now be open... but just to be sure... and to verify during testing...
    if borepump.state:
        if DEBUGLVL > 0:
            print("At startup, BorePump is ON  ... opening valve")
        solenoid.value(0)           # be very careful... inverse logic!
    else:
        if DEBUGLVL > 0:
            print("At startup, BorePump is OFF ... closing valve")
        solenoid.value(1)           # be very careful... inverse logic!

    presspump = Pump("PressurePump", False)
    free_space_KB = free_space()
    if free_space_KB < MIN_FREE_SPACE:
        raiseAlarm("Free space", free_space_KB)

    init_ringbuffers()
    navigator.set_event_list(eventring)
    navigator.set_switch_list(switchring)

# ensure we start out right...
    steady_state = False
    vbus_on_time = time.time()      # init this... so we can test external
    display_mode = "depth"
    enable_controls()              # enable rotary encoder, LCD B/L button etc

def heartbeat() -> bool:
    global borepump
# heartbeat... if pump is on, send a regular heartbeat to the RX end
# On RX, if a max time has passed... turn off.
# Need a mechanism to alert T... and reset

# Doing this inline as it were to avoid issues with async, buffering yada yada.
# The return value indicates if we need to sleep before continuing the main loop

# only do heartbeat if the pump is running
    if borepump.state:
        # print("sending HEARTBEAT")
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

def free_space()->int:
    # Get the filesystem stats
    stats = os.statvfs('/')
    
    # Calculate free space
    block_size = stats[0]
    total_blocks = stats[2]
    free_blocks = stats[3]

    # Free space in bytes
    free_space_kb = free_blocks * block_size / 1024
    return free_space_kb

def sim_pressure_pump_detect(x)->bool:            # to be hacked when I connect the CT circuit
    p = random.random()

    return True if p > x else False

def sim_solenoid_detect()->bool:
    return True

def monitor_vbus():
    global vbus_on_time, report_outage

    now = time.time()
    if vbus_sense.value():
        vbus_on_time = now
        report_outage = True
    else:
        if (now - vbus_on_time >= MAX_OUTAGE) and report_outage:
            s = f"{display_time(secs_to_localtime(time.time()))}  Power off for more than {MAX_OUTAGE} seconds\n"
            ev_log.write(s)  # seconds since last saw power 
            report_outage = False
            housekeeping(False)

# endregion
# region ASYNCIO defs
async def regular_flush(m)->None:
    while True:
        f.flush()
        ev_log.flush()
        await uasyncio.sleep(m)

async def check_rotary_state(menu_sleep:int)->None:
    global ui_mode, encoder_count, encoder_btn_state
    while True:
        if encoder_btn_state:               # button pressed
            lcd_on()                        # but set no OFF timer...stay on until I exit menu
            mode = navigator.mode

            if ui_mode == UI_MODE_MENU:
                mode = navigator.mode
                if mode == "menu":
                    navigator.enter()
                elif mode == "value_change":
                    navigator.set()
                elif "view" in mode:        # careful... if more modes are added, ensure they contain "view"
                    navigator.go_back()
            else:
                ui_mode = UI_MODE_MENU
                navigator.go_to_first()
                navigator.display_current_item()

            encoder_btn_state = False

        if encoder_count != 0:
            if encoder_count > 0:
                # print(f"CRS: {encoder_count=}")
                # for rc in range(encoder_count):
                while encoder_count > 0:
                    navigator.next()
                    encoder_count -= 1
            elif encoder_count < 0:
                # print(f"CRS: {encoder_count=}")
                # for rc in range(encoder_count):
                while encoder_count < 0:
                    navigator.previous()
                    encoder_count += 1

        await uasyncio.sleep_ms(menu_sleep)

async def blinkx2():
    while True:
        led.value(1)
        sleep_ms(50)
        led.value(0)
        sleep_ms(50)
        led.value(1)
        sleep_ms(50)
        led.value(0)
        await uasyncio.sleep_ms(1000)

async def do_main_loop():
    global event_time, ev_log, steady_state, housetank, system, op_mode

    print("RUNNING do_main_loop()")
    # start doing stuff
    buzzer.value(0)			    # turn buzzer off
    lcd.clear()
    lcd_on()
    #radio.rfm69_reset

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
    uasyncio.create_task(blinkx2())                             # visual indicator we are running
    uasyncio.create_task(check_lcd_btn())                       # start up lcd_button widget
    uasyncio.create_task(regular_flush(FLUSH_PERIOD))           # flush data every FLUSH_PERIOD minutes
    uasyncio.create_task(check_rotary_state(ROTARY_PERIOD_MS))  # check rotary every ROTARY_PERIOD_MS milliseconds

    start_irrigation_schedule()     # so I don't have to mess with rotary to test timer stuff

    rec_num=0
    while True:
        updateClock()			                    # get datetime stuff
        updateData()			                    # monitor water depth
        check_for_critical_states()
        if op_mode != OP_MODE_MAINT:
            if op_mode != OP_MODE_IRRIGATE: 
                if DEBUGLVL > 0: print(f"in do_main_loop, op_mode is {op_mode} and controlBorePump() starting now")
                controlBorePump()		            # do nothing if in IRRIGATE mode
    #        listen_to_radio()		                # check for badness
            DisplayData()
# experimental...
            if rec_num % LOG_FREQ == 0:           
                LogData()			                # record it
            if steady_state: checkForAnomalies()	# test for weirdness
            rec_num += 1
            if rec_num > ROC_AVERAGE and not steady_state: steady_state = True    # just ignore data until ringbuf is fully populated
            delay_ms = config_dict["Delay"] * 1000
            if heartbeat():                         # send heartbeat if ON... not if OFF.  For now, anyway
                delay_ms -= RADIO_PAUSE
            monitor_vbus()                          # escape clause... to trigger dump...
        # print(f"{event_time} main loop: {rec_num=}, {op_mode=}, {steady_state=}")
        await uasyncio.sleep_ms(delay_ms)

# endregion

def main() -> None:
    try:
        uasyncio.run(do_main_loop())

    except uasyncio.CancelledError:
        print("I see a cancelled uasyncio thing")

    except KeyboardInterrupt:
        lcd_off('')	                # turn off backlight
        print('\n### Program Interrupted by the user')
    # turn everything OFF
        if borepump is not None:                # in case i bail before this is defined...
            if borepump.state:
                borepump_OFF()

    #    confirm_and_switch_solenoid(False)     #  *** DO NOT DO THIS ***  If live, this will close valve while pump.
    #           to be real sure, don't even test if pump is off... just leave it... for now.

    # tidy up...
        housekeeping(True)

if __name__ == '__main__':
     main()