# Trev's super dooper Tank/Pump monitoring system

# region IMPORTS

import RGB1602
import umail # type: ignore
import time
import uos
import utime
import uasyncio as asyncio
import ntptime
import gc
import micropython
import network
import sys
import random
from utime import sleep, ticks_us, ticks_diff
from PiicoDev_Unified import sleep_ms
from PiicoDev_VL53L1X import PiicoDev_VL53L1X
from PiicoDev_Transceiver import PiicoDev_Transceiver
from umachine import Timer, Pin, ADC, soft_reset, I2C
from secrets import MyWiFi
from MenuNavigator import MenuNavigator
from encoder import Encoder
from ubinascii import b2a_base64 as b64
from SM_SimpleFSM import SimpleDevice
from lcd_api import LcdApi
from i2c_lcd import I2cLcd
from Pump import Pump
from Tank import Tank
from TMErrors import TankError
# from utils import secs_to_localtime         # old methods... , display_time, short_time, long_time, format_secs_long, format_secs_short
from utils import now_time_short, now_time_long, format_secs_short, format_secs_long, now_time_tuple
from ringbuffer import RingBuffer, DuplicateDetectingBuffer
from TimerManager import TimerManager

# endregion
# region INITIALISE
SW_VERSION          = "21/5/25"      # for display

# micropython.mem_info()
# gc.collect()

# constant/enums
DEBUGLVL            = 0

OP_MODE_AUTO        = 0
OP_MODE_IRRIGATE    = 1
OP_MODE_MAINT       = 2
OP_MODE_DISABLED    = 9             # experimental ... pumping disabled due to low water level.  Must be > other modes

UI_MODE_NORM        = 0
UI_MODE_MENU        = 1

TIMERSCALE          = 60            # permits fast speed debugging... normally, set to 60 for "minutes" in timed ops
DEFAULT_CYCLE       = 38            # for timed stuff... might eliminate the default thing...
DEFAULT_DUTY_CYCLE  = 24            # % ON time for irrigation program

RADIO_PAUSE         = 1000
FREE_SPACE_LOWATER  = 150           # in KB...
FREE_SPACE_HIWATER  = 400

FLUSH_PERIOD        = 7             # seconds ... should avoid clashes with most other processes
DEBOUNCE_ROTARY     = 10            # determined from trial... see test_rotary_irq.py
DEBOUNCE_BUTTON     = 400           # 50 was still registering spurious presses... go real slow.
ROTARY_PERIOD_MS    = 200           # needs to be short... check rotary ISR variables
PRESSURE_PERIOD_MS  = 1000

EVENTRINGSIZE       = 20            # max log ringbuffer length
SWITCHRINGSIZE      = 20
KPARINGSIZE         = 20            # size of ring buffer for pressure logging... NOT for calculation of average
ERRORRINGSIZE       = 20            # max error log ringbuffer length
HI_FREQ_RINGSIZE    = 120           # for high frequency pressure logging.  At 1 Hz that's 2 minutes of data

HI_FREQ_AVG_COUNT   = 5             # for high frequency pressure alarm
LO_FREQ_AVG_COUNT   = 30            # for high frequency pressure alarm
BASELINE_AVG_COUNT  = 5             # for baseline pressure calculation
LOOKBACKCOUNT       = 60            # for looking back at pressure history... to see if kPa drop is normal or not

MAX_OUTAGE          = 30            # seconds of no power
ALARMTIME           = 10            # seconds of alarm on/off time

BP_SENSOR_MIN       = 3000          # raw ADC read... this will trigger sensor detect logic
VDIV_R1             = 12000         # ohms
VDIV_R2             = 33000
VDIV_Ratio          = VDIV_R2/(VDIV_R1 + VDIV_R2)

SLOW_BLINK          = 850
FAST_BLINK          = 300

# All menu-CONFIGURABLE parameters
mydelay             = 5             # seconds, main loop period
LCD_ON_TIME         = 90            # LCD time seconds
Min_Dist            = 500           # full
Max_Dist            = 1400          # empty
MAX_LINE_PRESSURE   = 700           # sort of redundant... now zone-specific. Might keep this as absolute critical value
# MIN_LINE_PRESSURE   = 280           # tweak after running... and this ONLY applies in OP_MODE_IRRIG.  Keep - may indicate a blown pipe
NO_LINE_PRESSURE    = 8             # tweak this too... applies in ANY pump-on mode
# MAX_KPA_DROP        = 20             # replaced by per-zone number
MAX_CONTIN_RUNMINS  = 360           # 3 hours max runtime.  More than this looks like trouble
LOG_HF_PRESSURE     = 2             # log high frequency pressure data.  Need to use int, not bool, for menu
SIMULATE_PUMP       = False         # debugging aid...replace pump switches with a PRINT
SIMULATE_KPA        = False         # debugging aid...replace pressure sensor with a PRINT
DEPTHRINGSIZE       = 12            # since adding fast_average in critical_states, this no longer is a concern
                                    # make 1 for NO averaging... otherwise do an SMA of this period.  Need a ring buffer?

# Physical Constants
Tank_Height         = 1700
OverFull	        = 250
Delta               = 50            # change indicating pump state change has occurred
TEMP_CONV_FACTOR 	= 3.3 / 65535   # looks like 3.3V / max res of 16-bit ADC ??

# Tank variables/attributes
depth               = 0
last_depth          = 0
depth_ROC           = 0
MAX_ROC             = 0.2			# change in metres/minute... soon to be measured on SMA/ring buffer
MIN_ROC             = 0.15          # experimental.. might need to tweak.  To avoid noise in anomaly tests

op_mode             = OP_MODE_AUTO
ui_mode             = UI_MODE_NORM

# logging stuff...
LOG_FREQ            = 1
last_logged_depth   = 0
last_logged_kpa     = 0
MIN_DEPTH_CHANGE_M  = 0.01          # to save space... only write to file if significant change in level
MAX_KPA_CHANGE      = 10            # update after pressure sensor active
level_init          = False 		# to get started

ringbufferindex     = 0             # for SMA calculation... keep last n measures in a ring buffer
eventindex          = 0             # for scrolling through error logs on screen
switchindex         = 0
kpaindex            = 0             # for scrolling through pressure logs on screen

# modified eventring stuff...
REPEAT_TIME_LIMIT   = 10            # threshold for repeat detection
MAX_REPEATS         = 30            # when to flag a problem...

event_repeat_count = 1
event_last_message = ""
event_last_message_time = 0

# lcdbtnflag          = True          # this should immediately trigger my asyncio timer on startup...

# Misc stuff
steady_state        = False         # if not, then don't check for anomalies
stable_pressure     = False         # if not, then don't check for anomalies or critical states
clock_adjust_ms     = 0             # will be set later... this just to ensure it is ALWAYS something
report_outage       = True          # do I report next power outage?
sys_start_time      = 0             # for uptime report
kpa_sensor_found    = True          # set to True if pressure sensor is detected  
baseline_set        = False         # set to True if baseline pressure is set
AVG_KPA_DELAY       = 15            # seconds to wait before taking average pressure
BASELINE_DELAY      = 45            # seconds to wait before taking baseline pressure.  Needs to be large enough to ensure calc_average doesn't crap out
avg_kpa_set         = False         # set to True if kpa average is set
FAST_AVG_COUNT      = 3             # for checking critical pressure states
BlinkDelay          = SLOW_BLINK    # for blinking LED... 1 second, given LED is on for 150ms, off for 850ms
kpa_peak            = 0             # track peak pressure for each zone
kpa_low             = 1000
program_cancelled   = False         # to provide better reporting

NUM_DISPLAY_MODES   = 3             # for more flexible display of info data
INFO_AUTO           = 0             # used to be AUTO mode
INFO_IRRIG          = 1
INFO_DIAG           = 2
INFO_MAINT          = -1            # special case... cannot cycle to here, only set explicitly as required

info_display_mode   = INFO_AUTO             # start somewhere

# Gather all tank-related stuff with a view to making a class...
housetank           = Tank("Empty")                     # make my tank object

# New state...
fill_states         = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]

# Pins
#vsys                = ADC(3)                            # one day I'll monitor this for over/under...
temp_sensor         = ADC(4)			                # Internal temperature sensor is connected to ADC channel 4
lcdbtn 	            = Pin(6, Pin.IN, Pin.PULL_UP)		# check if IN is correct!
buzzer 		        = Pin(16, Pin.OUT)
presspmp            = Pin(15, Pin.IN, Pin.PULL_UP)      # prep for pressure pump monitor.  Needs output from opamp circuit
prsspmp_led         = Pin(14, Pin.OUT)
solenoid            = Pin(2, Pin.OUT, value=0)          # MUST ensure we don't close solenoid on startup... pump may already be running !!!  Note: Low == Open
vbus_sense          = Pin('WL_GPIO2', Pin.IN)           # external power monitoring of VBUS
led                 = Pin('LED', Pin.OUT)
bp_pressure         = ADC(0)                            # read line pressure

# add buttons for 5-way nav control
nav_up 	            = Pin(10, Pin.IN, Pin.PULL_UP)		# UP button
nav_dn 	            = Pin(11, Pin.IN, Pin.PULL_UP)		# DOWN button  
nav_OK              = Pin(7,  Pin.IN, Pin.PULL_UP)		# SELECT button
nav_L               = Pin(12, Pin.IN, Pin.PULL_UP)		# LEFT button
nav_R               = Pin(13, Pin.IN, Pin.PULL_UP)		# RIGHT button  

# Create pins for encoder lines and the onboard button

enc_btn             = Pin(18, Pin.IN, Pin.PULL_UP)
# enc_a               = Pin(19, Pin.IN)
# enc_b               = Pin(20, Pin.IN)
px                  = Pin(20, Pin.IN)
py                  = Pin(19, Pin.IN)
last_time           = 0
# count               = 0
DO_NEXT_IN_CB       = True      # this could be a config param... but probably not worth it

alarm               = Pin(21, Pin.OUT)                  # for testing alarm buzzer
infomode            = Pin(27, Pin.IN, Pin.PULL_UP)      #@ for changing display mode

# new 2004 LCD...
I2C_ADDR            = 0x27
I2C_NUM_ROWS        = 4
I2C_NUM_COLS        = 20
i2c                 = I2C(0, sda=Pin(8), scl=Pin(9), freq=400000)
lcd4x20             = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)

system              = SimpleDevice()                    # initialise my FSM.
wf                  = MyWiFi()

# Create PiicoDev sensor objects
distSensor 	        = PiicoDev_VL53L1X()
lcd 		        = RGB1602.RGB1602(16,2)
radio               = PiicoDev_Transceiver()

errors              = TankError()
timer_mgr           = TimerManager()


#rtc 		        = PiicoDev_RV3028()                 # Initialise the RTC module, enable charging

# Configure WiFi SSID and password
ssid                = wf.ssid
password            = wf.password

SMTP_SERVER         = "smtp.gmail.com"
SMTP_PORT           = 465

# Email account credentials
FROM_EMAIL          = wf.fromaddr
FROM_PASSWORD       = wf.gmailAppPassword
TO_EMAIL            = wf.toaddr

# things for async SMTP file processing
sleepms = 100
linegrp = 100

EMAIL_QUEUE_SIZE    = 20  # Adjust size as needed
email_queue         = ["" for _ in range(EMAIL_QUEUE_SIZE)]
email_queue_head    = 0
email_queue_tail    = 0
email_queue_full    = False
email_task_running  = False

# Code Review suggestions to avoid race conditions
depth_lock          = asyncio.Lock()
# lcd_flag_lock       = asyncio.Lock()
pressure_lock       = asyncio.Lock()
email_queue_lock    = asyncio.Lock()
enc_btn_lock        = asyncio.Lock()


# endregion
# region EMAIL
def send_email_msg(to:str, subj:str, body:str):
    smtp = umail.SMTP(SMTP_SERVER, SMTP_PORT, ssl=True)
    smtp.login(FROM_EMAIL, FROM_PASSWORD)

    # Send the email
    smtp.to(TO_EMAIL)
    smtp.write(f"From: {FROM_EMAIL}\n")
    smtp.write(f"To: {to}\n")
    smtp.write(f"Subject: {subj}\n")
    smtp.write("\n")  # Separate headers from the body with a newline
    smtp.write(f"{body}\n")

    # Close the SMTP connection
    code = smtp.send()
    smtp.quit()
    print(f"Msg sent!... RC {code}")

# def send_file_blocking(to:str, subj:str, filename:str)->int:

#     try:
#         f = open(filename, "r")

#         smtp = umail.SMTP(SMTP_SERVER, SMTP_PORT, ssl=True)
#         smtp.login(FROM_EMAIL, FROM_PASSWORD)

#         # Send the email
#         smtp.to(TO_EMAIL)
#         smtp.write(f"From: {FROM_EMAIL}\n")
#         smtp.write(f"To: {to}\n")
#         smtp.write(f"Subject: {subj}: {filename}\n")
#         smtp.write("\n")  # Separate headers from the body with a newline

#         for l in f:
#             smtp.write(f"{l}")

#         f.close()
#         code = smtp.send()
#         print(f"File sent!... RC {code[0]}")
#         smtp.quit()
#         return int(code[0])

#     except:
#         print(f"GAK! Can't open file {filename}")
#         return -1

# endregion
# region DICTIONARIES
# Constants for other things... to ensure consistency!
DELAY               = "Delay"
LCD                 = "LCD"
MINDIST             = "MinDist"
MAXDIST             = "MaxDist"
# MINPRESSURE         = "Min Pressure"
MAXPRESSURE         = "Max Pressure"
# MAXDROP             = "Max Drop"
NOPRESSURE          = "No Pressure"
MAXRUNMINS          = "Max RunMins"
LOGHFDATA           = "Log HF Data"

config_dict         = {
    DELAY           : mydelay,
    LCD             : LCD_ON_TIME,
    MINDIST         : Min_Dist,
    MAXDIST         : Max_Dist,
    MAXPRESSURE     : MAX_LINE_PRESSURE,
    # MINPRESSURE     : MIN_LINE_PRESSURE,
    # MAXDROP         : MAX_KPA_DROP,
    NOPRESSURE      : NO_LINE_PRESSURE,
    MAXRUNMINS      : MAX_CONTIN_RUNMINS,
    LOGHFDATA       : LOG_HF_PRESSURE
            }

timer_dict          = {
    'Start Delay'   : 0,
    'Duty Cycle'    : DEFAULT_DUTY_CYCLE
              }

opmode_dict         = {
    OP_MODE_AUTO:       "AUTO",
    OP_MODE_IRRIGATE:   "IRRI",
    OP_MODE_MAINT:      "MTCE",
    OP_MODE_DISABLED:   "SUSP"
}

# program_list = [
#               ("Cycle1", {"init" : 0, "run" : 20, "off" : 60}),
#               ("Cycle2", {"init" : 0, "run" : 20, "off" : 60}),
#               ("Cycle3", {"init" : 1, "run" : 20, "off" : 1})]
#
#   TODO UST FOR DEBUGGING...  REMOVE LATER
program_list = [
              ("Cycle1", {"init" : 0, "run" : 3, "off" : 6}),
              ("Cycle2", {"init" : 0, "run" : 3, "off" : 4}),
              ("Cycle3", {"init" : 0, "run" : 3, "off" : 2}),
              ("Cycle4", {"init" : 0, "run" : 5, "off" : 10}),
              ("Cycle5", {"init" : 0, "run" : 5, "off" : 8}),
              ("Cycle6", {"init" : 0, "run" : 5, "off" : 6}),
              ("Cycle7", {"init" : 0, "run" : 5, "off" : 4}),
              ("Cycle8", {"init" : 0, "run" : 5, "off" : 2}),
              ("Cycle9", {"init" : 0, "run" : 5, "off" : 1})]

def update_config():
    
    for param_index in range(len(config_dict)):
        param: str             = new_menu['items'][3]['items'][0]['items'][param_index]['title']
        new_working_value: int = new_menu['items'][3]['items'][0]['items'][param_index]['value']['W_V']
        if param in config_dict.keys():
            if new_working_value > 0 and config_dict[param] != new_working_value:
  #              print(f'Updated config_dict {param} to {new_working_value}')
                old_value = config_dict[param]
                config_dict[param] = new_working_value
                lcd.clear()
                lcd.setCursor(0,0)
                lcd.printout(f'Updated {param}')
                lcd.setCursor(0,1)
                lcd.printout(f'to {new_working_value}')
                ev_log.write(f"{now_time_long()} Updated {param} to {new_working_value}\n")
                print(f"in update_config {param}: dict was {old_value} is now {new_working_value}")
        else:
            print(f"GAK! Config param {param} not found in dict!")
            lcd.clear()
            lcd.setCursor(0,0)
            lcd.printout("No dict entry:  ")
            lcd.setCursor(0,1)
            lcd.printout(param)

def update_timer_params():
    
    for param_index in range(len(timer_dict)):
        param: str             = new_menu['items'][3]['items'][1]['items'][param_index]['title']    # GAK... more bad dependencies
        new_working_value: int = new_menu['items'][3]['items'][1]['items'][param_index]['value']['W_V']
        # print(f">> {param=}, {new_working_value}")
        if param in timer_dict.keys():
            # print(f"in update_timers {param}: dict is {timer_dict[param]} nwv is {new_working_value}")
            if new_working_value > 0 and timer_dict[param] != new_working_value:
                timer_dict[param] = new_working_value
                # print(f'Updated timer_dict {param} to {new_working_value}')
                lcd.clear()
                lcd.setCursor(0,0)
                lcd.printout('Updated param')
                lcd.setCursor(0,1)
                lcd.printout(f'{param}: {new_working_value}')
        # else:
        #     print(f"GAK! Config parameter {param} not found in timer dictionary!")
        #     lcd.clear()
        #     lcd.setCursor(0,0)
        #     lcd.printout("No dict entry:  ")
        #     lcd.setCursor(0,1)
        #     lcd.printout(param)
    # print(f"{timer_dict=}")

def update_program_data()->None:
# This transfers run times from timer_dict to my programed water schedule, and also applies duty cycle to OFF

# First, update timer_dict
    update_timer_params()

    dc = timer_dict["Duty Cycle"]           # this is still getting data indirectly...
    adjusted_dc = max(min(dc, 95), 5)          # NORMALISE TO RANGE 5 - 95
    i = 1                                 # this feels wrong...
    for s in program_list:
        i += 1
        cyclename = s[0]
        # if cyclename in timer_dict.keys():
        #     on_time = timer_dict[cyclename]
        # else:
        #     on_time = s[1]["run"]
        menu_title = new_menu['items'][3]['items'][1]['items'][i]['title']
        if cyclename == menu_title:         # found correct menu item
            on_time = new_menu['items'][3]['items'][1]['items'][i]['value']['W_V']
            off_time = int(on_time * (100/adjusted_dc - 1) )
            # print(f"{cyclename=} {on_time=}  {off_time=}")
            s[1]["run"] = on_time
            s[1]["off"] = off_time
        else:                       # Oops... this doesn't look right...
            print(f"Found {menu_title}, expecting {cyclename}")

# now... fix start delay directly from menu
    program_list[0][1]["init"] = timer_dict["Start Delay"]      # another indirect data val...
    program_list[-1][1]["off"] = 1              # reset last cycle OFF time to 1

    lcd.setCursor(0,1)
    lcd.printout("program updated")
    # print(f"{program_list=}")

# Pressure to Zone mapping... names of zones
P0 = "00"
P1 = "Air"
P2 = "HT"
P3 = "Z45"
P4 = "Z3"
P5 = "Z2"
P6 = "Z1"
P7 = "Z4"
P8 = "XP"

# zone_list... zone ID, min, start-up, max pressures, quadratic eq  a,b,c coefficients, and zone_max_drop
# TODO ... need to test each zone's starting pressure...from full bore state, and adjust the min/max values accordingly.
# Then... when we have no water shortage, run for extended period to get quadratic profile of each zone.
zone_list:list[tuple[str, int, int, int, float, float, int, int]] = [
    (P0, 0,   0,   5,    2E-5, -0.1021, 0,   0),     # ZERO 
    (P1, 6,   15,  20,   2E-5, -0.1021, 2,   0),     # AIR
    (P2, 10,  20,  40,   8E-7, -0.004,  30,  5),     # HT: don't make this min higher... I want to resume from a cancelled cycle, not abort in HT mode
    (P3, 200, 35,  350,  1E-5, -0.1021, 340, 20),    # Z45
    (P4, 300, 350, 450,  2E-5, -0.1021, 445, 20),    # Z3
    (P5, 350, 420, 580,  2E-5, -0.1021, 575, 20),    # Z2
    (P6, 390, 550, 580,  2E-5, -0.1021, 585, 20),    # Z1
    (P7, 450, 650, 680,  2E-5, -0.1021, 620, 20),    # Z4
    (P8, 600, 700, 800,  2E-5, -0.1021, 650, 20)     # XP
]
# list needs to be reverse order for get_zone_from_list to work correctly
rev_sorted_zone_list = sorted(zone_list, key=lambda x: x[2], reverse=True)  # Sort by startup pressure in descending order

# this dict needed to store individual zone peak pressure on setting baseline.  Can't do it in immutable zone_list tuple...
peak_pressure_dict = {
    P0: (0, 0, 0),
    P1: (0, 0, 0),
    P2: (0, 0, 0),
    P3: (0, 0, 0),
    P4: (0, 0, 0),
    P5: (0, 0, 0),
    P6: (0, 0, 0),
    P7: (0, 0, 0),
    P8: (0, 0, 0),
    '???': (0, 0, 0)
}

def get_zone_from_list(pressure: int):
    """ Get zone, min and max by searching through the zone list for the first zone that exceeds the pressure """  
    i = len(zone_list)
    szl = sorted(zone_list, key=lambda x: x[2], reverse=True)  # Sort by average pressure in descending order
    # print(szl)
    for _, _, avg_pressure, _, _, _, _, _ in szl:
        # print(avg_pressure)
        if pressure >= avg_pressure:
            # print(f'{pressure=} is >= {avg_pressure}')
            return zone_list[i-1][0], zone_list[i-1][1], zone_list[i-1][2], zone_list[i-1][3], zone_list[i-1][4], zone_list[i-1][5], zone_list[i-1][6], zone_list[i-1][7]
        else:
            # print(f'{pressure=} is <= {avg_pressure}')
            i -= 1
            # print(f'Index {i}')
    return "???", 0, 0, 0, 0, 0, 0, 0  # Return None if no zone found

# endregion
# region TIMED IRRIGATION
def toggle_borepump(x:Timer):
    global toggle_timer, timer_state, op_mode, sl_index, cyclename, ON_cycle_end_time, next_ON_cycle_time, program_pending

    program_pending = False
    x_str = f'{x}'
    period: int = int(int(x_str.split(',')[2].split('=')[1][0:-1]) / 1000)
    milisecs = period
    secs = int(milisecs / 1000)
    # mins = int(secs / 60)
    mem = gc.mem_free()
    # need to use tuples to get this... cant index dictionary, as unordered.  D'oh...
    cyclename = str(sl_index)
    # print(f'{now_time_long()} in toggle, {sl_index=}, {cyclename=}, {timer_state=}, {period=},  {secs} seconds... {mins} minutes... {mem} free')
    if op_mode == OP_MODE_IRRIGATE:
        if sl_index < len(slist) - 1:
            timer_state = (timer_state + 1) % 3
            now = time.time()
            if  timer_state == 1:
                # print(f"{now_time_long()}: TOGGLE - turning pump ON")
                diff = slist[sl_index + 1] - slist[sl_index]        # look forward to next timer event
                ON_cycle_end_time = now + diff * TIMERSCALE
                if sl_index < len(slist) - 3:
                    diff = slist[sl_index + 3] - slist[sl_index]
                else:
                    diff = -2           # there is no next on time...
                next_ON_cycle_time = now + diff * TIMERSCALE
                # nextcycle_ON_time = now + (slist[sl_index + 1] + slist[sl_index + 2] + slist[sl_index + 3]) * TIMERSCALE
                borepump_ON()        #turn_on()
            elif timer_state == 2:
                # diff = slist[sl_index + 2] - slist[sl_index]
                # nextcycle_ON_time = now + diff * TIMERSCALE
                # print(f"{now_time_long()}: TOGGLE - turning pump OFF")
                if not borepump.state:      # then it looks like a kpa test paused this cycle
                    print(f"{now_time_long()}: TOGGLE - cycle paused - did we detect pressure drop?")

                borepump_OFF()       #turn_off()
            elif timer_state == 0:
                pass
                # diff = slist[sl_index + 1] - slist[sl_index]
                # nextcycle_ON_time = now + diff * TIMERSCALE
                # print(f"{now_time_long()}: TOGGLE - Doing nothing")
            if sl_index == len(slist) - 2:              # we must be in penultimate cycle, or last cycle
                next_ON_cycle_time = now - 2 * TIMERSCALE

            # print(f" end cycle {format_time_short(secs_to_localtime(ON_cycle_end_time))}\nnext cycle {format_time_short(secs_to_localtime(next_ON_cycle_time))}")
            # now, set up next timer
            sl_index += 1
            diff = slist[sl_index] - slist[sl_index - 1]
            print(f"Creating timer for index {sl_index}, {slist[sl_index]}, {diff=}")

            toggle_timer = Timer(period=diff*TIMERSCALE*1000, mode=Timer.ONE_SHOT, callback=toggle_borepump)
            # print(f"{timer_state=}")
        else:
            prog_str = f"{now_time_long()} Ending timed watering..."
            print(prog_str)
            event_ring.add("End PROG")
            ev_log.write(prog_str + "\n")

            op_mode = OP_MODE_AUTO
            DisplayData()       # show status immediately, don't wait for next loop ??

            # print(f"{now_time_long()} in TOGGLE... END IRRIGATION mode !  Now in {op_mode}")
            if borepump.state:
                borepump_OFF()       # to be sure, to be sure...
                print(f"{now_time_long()} in toggle, at END turning bp OFF.  Should already be OFF...")
        if mem < 60000:
            print("Collecting garbage...")              # moved to AFTER timer created... might avoid the couple seconds discrepancy.  TBC
            gc.collect()
    else:
        if not program_cancelled:       # TODO this can happen on entering DISABLE mode... then toggle timer triggers.  What to do ???
            print(f'{now_time_long()} in toggle {op_mode=}.  Why are we here?? Program has NOT been cancelled')

def apply_duty_cycle()-> None:

    dc = timer_dict["Duty Cycle"]
    adjusted_dc = max(min(dc, 95), 5)          # NORMALISE TO RANGE 5 - 95a=[]
    for s in program_list:
        on_time = s[1]["run"]
        off_time = int(on_time * (100/adjusted_dc - 1) )
        # print(f"{on_time=}  {off_time=}")
        s[1]["off"] = off_time

    # print(f"Duty cycle: {dc} ...{adjusted_dc=}\nadjusted water_list: {water_list}")
    
def start_irrigation_schedule():
    global twm_timer, timer_state, op_mode, slist, sl_index, ON_cycle_end_time, num_cycles, program_pending, program_start_time, program_end_time, program_cancelled        # cycle mod 3

    try:
        if op_mode == OP_MODE_IRRIGATE:
            print(f"Can't start program... already in mode {op_mode}")
            lcd.setCursor(0,1)
            lcd.printout("Already running!")
        else:
            # apply_duty_cycle()                  # what it says
            swl=sorted(program_list, key = lambda x: x[0])      # so, the source of things is program_list... need to ensure that is updated
            prog_str = f"{now_time_long()} Starting timed watering..."
            print(prog_str)
            event_ring.add("Start PROG")
            ev_log.write(prog_str + "\n")
            op_mode          = OP_MODE_IRRIGATE          # the trick is, how to reset this when we are done...

            program_cancelled = False
            timer_state      = 0
            sl_index         = 0
            # next_switch_time = timer_dict["Start Delay"] ... no, we add this in in the loop below.  
            next_switch_time = 0
            ON_cycle_end_time= 0
            num_cycles       = 0
            total_time       = 0
            
            slist.clear()

            for s in swl:
                # cyclename = s[0]
                # print(f"Adding timer nodes to slist for cycle {cyclename}")
                for k in ["init", "run", "off"]:
                    t=s[1][k]
                    # if k == "init" and t == 0:
                    #     print(f"Skipping {cyclename}")
                    #     break
                    # else:
                    next_switch_time += t
                    total_time += t
                    # print(f'{next_switch_time=}')
                    slist.append(next_switch_time)
                    num_cycles += 1
            slist.sort()
            # print(f"Initiating timers: first target is {slist[0]}.  Total {len(slist)} targets")
            sched_start_mins = int(slist[0] * TIMERSCALE / 60)
            start_hrs = int(sched_start_mins/60)
            start_mins = sched_start_mins % 60
            program_pending = True
            program_start_time = time.time() + sched_start_mins * 60
            program_end_time   = time.time() + total_time
            twm_timer = Timer(period=slist[0]*TIMERSCALE*1000, mode=Timer.ONE_SHOT, callback=toggle_borepump)
            print(slist)
            # print(f"{sched_start=}")
            lcd.setCursor(0,1)
            lcd.printout(f"Schd strt {start_hrs:>2}:{start_mins:02}m")
            # print("Watering Schedule created")
            return
        
    except MemoryError:
        print("MemoryError caught")
        # print(f"before gc free mem: {gc.mem_free()}")
        gc.collect()
        # print(f" after gc free mem: {gc.mem_free()}")

    except Exception as e:
        print(f"Exception caught in S_I_S: {e}")
        # print(f"before gc free mem: {gc.mem_free()}")
        gc.collect()
        # print(f" after gc free mem: {gc.mem_free()}")
# endregion
# region MENU METHODS
# methods invoked from menu
def Change_Mode(newmode)-> None:
    global ui_mode

    # print("Change_Mode Stack trace:")
    # try:
    #     raise Exception("StackTrace")
    # except Exception as e:
    #     sys.print_exception(e)      # type: ignore
    
    if newmode == UI_MODE_MENU:
        ui_mode = UI_MODE_MENU
        # print(f"Change_Mode: going to MENU mode {ui_mode=}")
        lcd.setRGB(240, 30, 240)
    elif newmode == UI_MODE_NORM:
        ui_mode = UI_MODE_NORM
        # print(f"Change_Mode: Exiting MENU mode {ui_mode=}")
        lcd.setRGB(170,170,138)
    else:
        print(f"Change_Mode: Unknown mode {newmode}")

def exit_menu():                      # exit from MENU mode
    global lcd_timer
    # process_menu = False
    # print("exit_menu(): Exiting menu mode")
    lcd.setCursor(0,1)
    lcd.printout(f'{"Exit & Update":<16}')
    update_config()
    update_timer_params()
    Change_Mode(UI_MODE_NORM)       # This cancels DEAD_MODE!... need to save state if I DONT want this... as-is, it does provide an escape
    DisplayInfo()
    # ui_mode = UI_MODE_NORM
    # print(f"Exiting menu...lcd_off in {config_dict['LCD']} seconds")
    if not lcd_timer is None:
        lcd_timer.deinit
    lcd_timer = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)

def cancel_program()->None:
    global program_pending, op_mode, program_cancelled

    program_pending = False
    program_cancelled = True
    op_mode = OP_MODE_AUTO

    try:
        if twm_timer is not None:        # this is not enough... need to catch the case where my_timer is not defined, so need try/except
            twm_timer.deinit()
            print("Timer CANCELLED")

        if borepump.state:
            borepump_OFF()

        lcd.setCursor(0,1)
        lcd.printout("Prog CANCELLED")

        event_ring.add("Prog cancelled")
        ev_log.write(f"{now_time_long()} Prog cancelled\n")

    except:
        print("No prog to cancel")
        lcd.setCursor(0,1)
        lcd.printout("No prog to cancel")
    
def display_depth():
    global display_mode

    display_mode = "depth"
    print(f'{display_mode=}')
    lcd.setCursor(0,1)
    lcd.printout(f'{"Display depth":<16}')

def display_pressure():
    global display_mode

    display_mode = "pressure"
    print(f'{display_mode=}')
    lcd.setCursor(0,1)
    lcd.printout(f'{"Display kPa":<16}')

def my_go_back():
    # print(f'in my_go_bacK, len(nav.c_l): {len(navigator.current_level)}')
    navigator.go_back()
    # navmode = navigator.mode
    # if navmode == "menu":
    #     exit_menu()
    # else:
    #     navigator.go_back()
               
def show_program():
    navigator.mode = "view_program"
               
def show_events():
    navigator.set_display_list("events")
    navigator.mode              = "view_ring"
    # navigator.displaylistname   = "events"
    # navigator.displaylist       = navigator.eventlist
    # navigator.display_navindex  = navigator.event_navindex

def show_switch():
    navigator.set_display_list("switch")
    navigator.mode              = "view_ring"
    # navigator.displaylistname   = "switch"
    # navigator.displaylist       = navigator.switchlist
    # navigator.display_navindex  = navigator.switch_navindex

def show_errors():
    navigator.set_display_list("errors")
    navigator.mode              = "view_ring"
    # navigator.displaylistname   = "errors"                  # this will need special handling to decode in MenuNavigator
    # navigator.displaylist       = navigator.errorlist
    # navigator.display_navindex  = navigator.error_navindex

def show_pressure():
    navigator.set_display_list("kpa")
    navigator.mode              = "view_ring"
    # navigator.displaylistname   = "kpa"
    # navigator.displaylist       = navigator.kpalist
    # navigator.display_navindex  = navigator.kpa_navindex

def show_depth():
    print("Not implemented")

def show_space():
    lcd.setCursor(0,1)
    lcd.printout(f'Free KB: {free_space():<6}')

def my_reset():
    ev_log.write(f"{now_time_long()} SOFT RESET\n")
    shutdown()
    sleep(FLUSH_PERIOD + 1)
    beepx3()
    lcd.setCursor(0,1)
    lcd.printout("OK to power OFF")
    lcd.setRGB(0,0,0)
    lcd4x20.display_off()
    lcd4x20.backlight_off()
    soft_reset()

def beepx3()->None:
    alarm.value(1)
    sleep_ms(100)
    alarm.value(0)
    sleep_ms(100)
    alarm.value(1)
    sleep_ms(100)
    alarm.value(0)
    sleep_ms(100)
    alarm.value(1)
    sleep_ms(100)
    alarm.value(0)

def hardreset():
    pass

def flush_data():
    tank_log.flush()
    ev_log.flush()
    pp_log.flush()
    hf_log.flush()
    lcd.setCursor(0,1)
    lcd.printout(f'{"Logs flushed":<16}')

def housekeeping(close_files: bool)->None:
    print("Flushing data...")
    start_time = time.ticks_us()
    tank_log.flush()
    ev_log.flush()
    pp_log.flush()
    hf_log.flush()
    end_time = time.ticks_us()
    if close_files:
        tank_log.close()
        ev_log.close()
        pp_log.close()
        hf_log.close()
    print(f"Cleanup completed in {int(time.ticks_diff(end_time, start_time) / 1000)} ms")

def shutdown()->None:
    if op_mode == OP_MODE_IRRIGATE:
        cancel_program()
    if borepump is not None:                # in case i bail before this is defined...
        if borepump.state:                  # to be sure...
            borepump_OFF()
    ev_log.write(f"{now_time_long()} STOP Monitor\n")
    if borepump is not None: dump_pump_arg(borepump)
    if presspump is not None:
        if presspump.num_switch_events > 0:
            dump_pump_arg(presspump)
    dump_zone_peak()
    ev_log.write("\nevent_ring dump:\n")
    event_ring.dump()
    ev_log.write("\nerror_ring dump:\n")
    error_ring.dump()
    if switch_ring.index > -1:
        ev_log.write("\nSwitch activity:\n")
        switch_ring.dump()
    tank_log.flush()
    tank_log.close()
    ev_log.flush()
    ev_log.close()
    pp_log.flush()
    pp_log.close()
    hf_log.flush()
    hf_log.close()

    timer_mgr.cancel_all()

def send_last_HF_data():
    filenames = [x for x in uos.listdir() if x.startswith("HF ") and x.endswith(".txt") ]
    if len(filenames) > 0:
        sorted_filenames = sorted(filenames, key=lambda x: uos.stat(x)[7], reverse=True)  # Sort by date (newest first)
        latest_file = sorted_filenames[0]
        add_to_email_queue(latest_file)
        # print(f"Email queue has {email_queue_head - email_queue_tail} items")
        lcd.setCursor(0,1)
        lcd.printout(f'{"Log queued":<16}')
    else:
        print("No HF data files found")
        lcd.setCursor(0,1)
        lcd.printout(f'{"No HF data":<16}')         

def send_tank_logs():
    # filelist: list[tuple] = []
# this also allocs memory... needs to change to static buffer
    filenames = [x for x in uos.listdir() if x.startswith("tank") and x.endswith(".txt") ]

    for f in filenames:
        # fstat = uos.stat(f)
        # fsize = fstat[6]
        # fdate = fstat[7]
        add_to_email_queue(f)
        # print(f'{f} {fsize:>7} bytes, time {display_time(secs_to_localtime(fdate))}')
    print(f'Email queue has {email_queue_head - email_queue_tail} items')
    lcd.setCursor(0,1)
    lcd.printout(f'{"Data queued":<16}')

def show_dir():

# This code works fine... but breaks ISR no-mem allocation rules.
# Needs to be rewritten using a static buffer

    filelist: list[tuple] = []  
    filenames = [x for x in uos.listdir() if x.endswith(".txt") and (x.startswith("tank") or x.startswith("pres") or x.startswith("HF")) ]

    for f in filenames:
        fstat = uos.stat(f)
        # print(f'file {f}  stat returns: {fstat}')
        fsize = fstat[6]
        fdate = fstat[7]
        print(f'{f} {fsize:>7} bytes, time {format_secs_long(int(fdate))}')

        filelist.append((f, f'Size: {fsize}'))        # this is NOT kosher... allocating mem in ISR context

    # navigator.set_file_list(filelist)
    navigator.mode = "view_files"
    navigator.set_file_list(filelist)

    navigator.goto_first()

def show_duty_cycle():
    boredc: float = borepump.calc_duty_cycle()
    presdc: float = presspump.calc_duty_cycle()
    lcd.setCursor(0,0)
    lcd.printout(f"PP d/c {presdc:>7,.2f}%")
    lcd.setCursor(0,1)
    lcd.printout(f"BP d/c {boredc:>7,.2f}%")

def find_last_cycle()-> int:
# find the last entry with "Cycle" in name/title
    pos=0
    while pos < len(program_list) - 1 and "Cycle" in program_list[pos][0]:
        # print(f'{pos=} {program_list[pos][0]}')
        pos += 1
    if not "Cycle" in program_list[pos][0]:
        # print(f'exit at {pos=} {program_list[pos][0]}, return {pos - 1}')
        pos -= 1
    # print(f"find_last_cycle: {pos=}")
    return pos

def add_cycle()-> None:
# This inserts a new row into program_list... and also updates the menu.  Can I do better??
# Need to check creation of the list of time intervals in start_timed_watering thing...

    last_cycle_pos = find_last_cycle()
    # print(f'In add_cycle, {last_cycle_pos=}')
    last_cycle_id = int(program_list[last_cycle_pos][0][-1])
    new_cycle_id = last_cycle_id + 1
    new_cycle_name: str = "Cycle" + str(new_cycle_id)
    prev_dict: dict[str, int] = program_list[last_cycle_pos][1]         # copy init, run, off from previous last entry
    new_dict = prev_dict.copy()
    new_tuple: tuple[str, dict[str, int]] = (new_cycle_name, new_dict)
    # print(f"new cycle is: {new_tuple}")
    # program_list.append(new_tuple)
    program_list.insert(last_cycle_pos + 1, new_tuple)
    lcd.setCursor(0,1)
    lcd.printout(f'{new_cycle_name} added')
    # print("Now... try to update the menu itself!!")
    sub_menu_list: list = navigator.current_level[-1]['submenu']["items"]          # this is a stack... get last entry
    # print(f'{navigator.current_index=}')
    # print(f'{sub_menu_list}')
    # print(f'sub_menu_list is type {type(sub_menu_list)}')
    old_menu_item:dict = sub_menu_list[navigator.current_menuindex - 1]     # YUK WARNING: bad dependency here !!!
    new_menu_item = old_menu_item.copy()
    new_menu_value: dict = old_menu_item["value"].copy()
    new_menu_item["title"] = new_cycle_name
    new_menu_item["value"] = new_menu_value                             # be very careful to NOT use ref to old dict
    # print(f'{new_menu_item=}')
    sub_menu_list.insert(navigator.current_menuindex, new_menu_item)        # only go back 1 slot
    navigator.current_menuindex += 1        # is this needed ?
    # print(f'{sub_menu_list=}')

#   finally.... update this, or view code breaks.  Yet another symptom of having data in two places... grrr...
    navigator.set_program_list(program_list)

def remove_cycle()-> None:
    last_cycle_pos = find_last_cycle()
    cycle_name = program_list[last_cycle_pos][0]
    # print(f'In remove_cycle, {last_cycle_pos=}')
    if last_cycle_pos > 0:
        del program_list[last_cycle_pos]
        lcd.setCursor(0,1)
        lcd.printout(f'{cycle_name} deleted')
        # print("Now... try to update the menu itself!!")
        sub_menu_list: list = navigator.current_level[-1]['submenu']["items"]         # this is a stack... get last entry
        # print(f'{navigator.current_index=}')
        # print(f'{sub_menu_list}')
        # print(f'sub_menu_list is type {type(sub_menu_list)}')
        # new_menu_item = sub_menu_list[navigator.current_index - 2]
        # new_menu_item["title"] = new_cycle_name
        # print(f'{new_menu_item=}')
        if "Cycle" in sub_menu_list[navigator.current_menuindex - 2]["title"]:
            del sub_menu_list[navigator.current_menuindex - 2]      # check the 2...
            navigator.current_menuindex -= 1        # is this needed ?
        # print(f'{sub_menu_list=}')
    else:
        lcd.setCursor(0,1)
        lcd.printout('Cant delete more')
        # print(f'remove_cycle: bad value {last_cycle_pos}')
    # print(f'{program_list=}')
    #   finally.... update this, or view code breaks
    navigator.set_program_list(program_list)

def calc_uptime()-> None:
    global ut_long, ut_short

    uptimesecs = time.time() - sys_start_time
    days  = int(uptimesecs / (60*60*24))
    hours = int(uptimesecs % (60*60*24) / (60*60))
    mins  = int(uptimesecs % (60*60) / 60)
    secs  = int(uptimesecs % 60)
    ut_long  = f'{days} d {hours:02}:{mins:02}:{secs:02}'
    ut_short = f'{days}d {hours:02}:{mins:02}'

def show_uptime():
    calc_uptime()
    lcd.clear()
    lcd.setCursor(0, 0)
    lcd.printout("Uptime:")
    lcd.setCursor(0, 1)
    lcd.printout(ut_long)

def show_version()-> None:
    lcd.setCursor(0,1)
    lcd.printout(f'Version: {SW_VERSION:<7}')

def make_more_space()->None:

    hitList: list[tuple] = []
    device_files = uos.listdir()
    tank_files = [x for x in device_files if ("tank " in x or "pressure " in x) and ".txt" in x]
    for f in tank_files:
        ftuple = uos.stat(f)
        kb = int(ftuple[6] / 1024)
        ts = ftuple[7]
        tstr = format_secs_long(int(ts))
        file_entry = tuple((f, kb, ts, tstr))
        hitList.append(file_entry)

    sorted_by_date = sorted(hitList, key=lambda x: x[2])
    print(f"Files by date:\n{sorted_by_date}")
    if free_space() < FREE_SPACE_LOWATER:
        ev_log.write(f"{now_time_long()} Deleting files\n")
        while free_space() < FREE_SPACE_HIWATER:
            df = sorted_by_date[0][0]
            print(f"removing file {df}")
            uos.remove(df)
            ev_log.write(f"{now_time_long()} Removed file {df} size{sorted_by_date[0][1]} Kb")
            sorted_by_date.pop(0)

        fs = free_space()
        print(f"After cleanup: {fs} Kb")
        ev_log.write(f"{now_time_long()} free space {fs}")

def enter_maint_mode()->None:
    global op_mode, info_display_mode, BlinkDelay, maint_mode_time

    event_ring.add("Enter MAINT mode (via menu)")
    op_mode = OP_MODE_MAINT
    info_display_mode = INFO_MAINT
    BlinkDelay = FAST_BLINK                 # fast LED flash to indicate maintenance mode
    lcd.setCursor(0, 1)
    lcd.printout(f'{"MAINT Mode":<16}')
    maint_mode_time = now_time_long()

def exit_maint_mode()->None:
    global op_mode, info_display_mode, BlinkDelay

    event_ring.add("Exit from MAINT mode")
    op_mode = OP_MODE_AUTO
    info_display_mode = INFO_AUTO
    BlinkDelay = SLOW_BLINK
    lcd.setCursor(0, 1)
    lcd.printout(f'{"AUTO mode":<16}')

def roll_logs()-> None:
# close & reopen new log files, so nothing becomes real large... helps with managing space on the drive
# simple method avoids the need to mess with filenames...
# All that remains is to ensure logs are saved/archived offline before DELETING in make-more-space... and to schedule roll_logs

    if tank_log is not None:
        tank_log.flush()
        tank_log.close()
    if pp_log is not None:
        pp_log.flush()
        pp_log.close()
    if ev_log is not None:
        ev_log.flush()
        ev_log.close()

    init_logging()          # start a new series

def add_to_email_queue(file:str)->None:
    global email_queue_head, email_queue_full

    if not email_queue_full:
        email_queue[email_queue_head] = file
        email_queue_head = (email_queue_head + 1) % EMAIL_QUEUE_SIZE
        email_queue_full = email_queue_head == email_queue_tail
        print(f'Queued file to send: {file}')
    else:
        print("Email queue full!")

def send_log()->None:

    # add_to_email_queue(eventlogname)
    add_to_email_queue("borepump_events.txt")
    lcd.setCursor(0, 1)
    lcd.printout(f'{"Log queued":<16}')
    # print(f"Log added to email queue")

Title_Str  = "title"
Value_Str  = "value"
ActionStr  = "action"
Step_Str   = "Step"

new_menu = {
    Title_Str: "L0 Main Menu",
    "items": [              # items[0]
      {
        Title_Str: "1 Display->",         # items[0]
        "items": [
          { Title_Str: "1.1 Pressure", ActionStr: display_pressure},
          { Title_Str: "1.2 Depth",    ActionStr: display_depth},
          { Title_Str: "1.3 Files",    ActionStr: show_dir},
          { Title_Str: "1.4 Space",    ActionStr: show_space},
          { Title_Str: "1.5 Uptime",   ActionStr: show_uptime},
          { Title_Str: "1.6 Version",  ActionStr: show_version},
          { Title_Str: "1.7 Go Back",  ActionStr: my_go_back}
        ]
      },
      {
        Title_Str: "2 History->",         # items[1]
        "items": [
          { Title_Str: "2.1 Events",     ActionStr: show_events},
          { Title_Str: "2.2 Switch",     ActionStr: show_switch},
          { Title_Str: "2.3 Pressure",   ActionStr: show_pressure},
          { Title_Str: "2.4 Errors",     ActionStr: show_errors},
          { Title_Str: "2.5 Program",    ActionStr: show_program},
          { Title_Str: "2.6 Stats",      ActionStr: show_duty_cycle},
          { Title_Str: "2.7 Go back",    ActionStr: my_go_back}
        ]
      },
      {
        Title_Str: "3 Actions->",         # items[2]
        "items": [
          { Title_Str: "3.1 Timed Water", ActionStr: start_irrigation_schedule},
          { Title_Str: "3.2 Cancel Prog", ActionStr: cancel_program},
          { Title_Str: "3.3 Flush",       ActionStr: flush_data},
          { Title_Str: "3.4 Make Space",  ActionStr: make_more_space},
          { Title_Str: "3.5 Email evlog", ActionStr: send_log},
          { Title_Str: "3.6 Email tank",  ActionStr: send_tank_logs},
          { Title_Str: "3.7 Email HFlog", ActionStr: send_last_HF_data},
          { Title_Str: "3.8 Reset",       ActionStr: my_reset},
          { Title_Str: "3.9 Test Beep",   ActionStr: beepx3},
          { Title_Str: "3.A Enter MAINT", ActionStr: enter_maint_mode},
          { Title_Str: "3.B Exit  MAINT", ActionStr: exit_maint_mode},
          { Title_Str: "3.C Go back",     ActionStr: my_go_back}
        ]
      },
      {
        Title_Str: "4 Config->",         # items[3]
        "items": [
          { Title_Str: "4.1 Set Config->",
            "items": [                  # items[3][0]
                { Title_Str : DELAY,         Value_Str: {"D_V": 15,   "W_V" : mydelay,              Step_Str : 5}},
                { Title_Str : LCD,           Value_Str: {"D_V": 5,    "W_V" : LCD_ON_TIME,          Step_Str : 2}},
                { Title_Str : MINDIST,       Value_Str: {"D_V": 500,  "W_V" : Min_Dist,             Step_Str : 100}},
                { Title_Str : MAXDIST,       Value_Str: {"D_V": 1400, "W_V" : Max_Dist,             Step_Str : 100}},
                { Title_Str : MAXPRESSURE,   Value_Str: {"D_V": 700,  "W_V" : MAX_LINE_PRESSURE,    Step_Str : 25}},                
                # { Title_Str : MINPRESSURE,   Value_Str: {"D_V": 300,  "W_V" : MIN_LINE_PRESSURE,    Step_Str : 25}},
                { Title_Str : NOPRESSURE,    Value_Str: {"D_V": 15,   "W_V" : NO_LINE_PRESSURE,     Step_Str : 5}},
                # { Title_Str : MAXDROP,       Value_Str: {"D_V": 15,   "W_V" : MAX_KPA_DROP,         Step_Str : 1}},
                { Title_Str : MAXRUNMINS,    Value_Str: {"D_V": 180,  "W_V" : MAX_CONTIN_RUNMINS,   Step_Str : 10}},
                { Title_Str : LOGHFDATA,     Value_Str: {"D_V": 0,    "W_V" : LOG_HF_PRESSURE,      Step_Str : 1}},
                { Title_Str: "Save config",  ActionStr: update_config},
                { Title_Str: "Go back",      ActionStr: my_go_back}
            ]
          },
           { Title_Str: "4.2 Set Timers->",
            "items": [                  # items[3][1]
                { Title_Str: "Start Delay",  Value_Str: {"D_V": 5,   "W_V" : 0,                     Step_Str : 15}},
                { Title_Str: "Duty Cycle",   Value_Str: {"D_V": 50,  "W_V" : DEFAULT_DUTY_CYCLE,    Step_Str : 5}},
                { Title_Str: "Cycle1",       Value_Str: {"D_V": 1,   "W_V" : DEFAULT_CYCLE,         Step_Str : 5}},
                { Title_Str: "Cycle2",       Value_Str: {"D_V": 2,   "W_V" : DEFAULT_CYCLE,         Step_Str : 5}},
                { Title_Str: "Cycle3",       Value_Str: {"D_V": 3,   "W_V" : DEFAULT_CYCLE,         Step_Str : 5}},
                { Title_Str: "Add cycle",      ActionStr: add_cycle},
                { Title_Str: "Delete cycle",   ActionStr: remove_cycle},
                { Title_Str: "Update program", ActionStr: update_program_data},
                { Title_Str: "Go back",        ActionStr: my_go_back}
            ]
          },
          { Title_Str: "4.3 Save Config",    ActionStr: update_config},
          { Title_Str: "4.4 Load Config",    ActionStr: "Load Config"},
          { Title_Str: "4.5 Go back",        ActionStr: my_go_back}
        ]
      },
    {
        Title_Str: "Exit", ActionStr: exit_menu
    }
    ]
}

# def encoder_a_IRQ(pin):
#     global enc_a_last_time, encoder_count

#     new_time = utime.ticks_ms()
#     if (new_time - enc_a_last_time) > DEBOUNCE_ROTARY:
#         if enc_a.value() == enc_b.value():
#             encoder_count += 1
#             # print("+", end="")
#             # navigator.next()
#         else:
#             encoder_count -= 1
#             # navigator.previous()
#     else:
#         print(".", end="")
#     # print(encoder_count)
#     enc_a_last_time = new_time

def encoder_btn_IRQ(pin):
    global enc_btn_last_time, encoder_btn_state

    new_time = utime.ticks_ms()
    if (new_time - enc_btn_last_time) > DEBOUNCE_BUTTON:
        encoder_btn_state = True
        # print("*", end="")
    # else:
    #     print("0", end="")
    enc_btn_last_time = new_time

def infobtn_cb(pin):
    global modebtn_last_time, info_display_mode

    # print("INFO", end="")
    new_time = utime.ticks_ms()
    old_mode = info_display_mode
    if (new_time - modebtn_last_time) > DEBOUNCE_BUTTON:
        new_mode = (info_display_mode + 1) % NUM_DISPLAY_MODES
        if new_mode == INFO_IRRIG :             # TODO Review changes to info mode, maybe do a state diag, B4 it gets out of control
            if op_mode != OP_MODE_IRRIGATE:
                new_mode = INFO_DIAG
        if new_mode != old_mode:
            info_display_mode = new_mode
            lcd4x20.clear()             # start with a blank sheet
            # print(f"Before calling DisplayInfo ...{info_display_mode=}")
            DisplayInfo()
            # print(f"Changing info display mode: {old_mode=} {info_display_mode=}")
    modebtn_last_time = new_time

# create the main menu navigator object
navigator   = MenuNavigator(new_menu, lcd) #, lcd4x20)

def pp_callback(pin):
    presspmp.irq(handler=None)
    v = pin.value()
    presspump.switch_pump(v)
    # print("Pressure Pump Pin triggered:", v)
    sleep_ms(100)
    presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)

def enc_cb(pos, delta):
    global encoder_count
    # print(pos, delta)
    if delta > 0:
        if DO_NEXT_IN_CB:
            navigator.next()
            # DisplayDebug()
        else:
            encoder_count += 1
    elif delta < 0:
        if DO_NEXT_IN_CB:
            navigator.previous()
            # DisplayDebug()
        else:
            encoder_count -= 1

def nav_up_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = utime.ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("U", end="")
        # navmode = navigator.mode
        # if navmode == "menu":
        #     exit_menu()
        # elif navmode == "value_change":
        #     if len(navigator.current_level) > 1:
        #         navigator.go_back()       # this is the up button
        # elif "view" in navmode:
        #     # print("--> goto first")
        #     navigator.goto_first()
        navigator.go_back()       # this is the up button... ALWAYS goes up a level
        DisplayInfo()
    nav_btn_last_time = new_time

def nav_dn_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = utime.ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("D", end="")
        navmode = navigator.mode
        if navmode == "menu":
            navigator.enter()   # this is the down button   
        elif navmode == "value_change":
            # print("--> set_default")
            navigator.set_default()
        elif "view" in navmode:
            # print("--> goto last")
            navigator.goto_last()
        DisplayInfo()
    nav_btn_last_time = new_time

def nav_OK_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = utime.ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("S", end="")
        if ui_mode == UI_MODE_MENU:
            navmode = navigator.mode
            if navmode == "menu":
                exit_menu()
            elif navmode == "value_change":
                navigator.set()     # this is the select button
            elif navmode == "wait":     # TODO Review wait mode in navigator
                navigator.go_back()
            else:
                navigator.goto_first()
            # print("Ignoring OK press")
            # lcd.setCursor(0,1)
            # lcd.printout("Not in edit mode")
        elif ui_mode == UI_MODE_NORM:
            Change_Mode(UI_MODE_MENU)
            navigator.go_to_start()
            navigator.display_current_item()
        else:
            print(f'Huh? {ui_mode=}')
        DisplayInfo()
    nav_btn_last_time = new_time

def nav_L_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = utime.ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("L", end="")
        navigator.previous()    # this is the back button
    DisplayInfo()

    nav_btn_last_time = new_time

def nav_R_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = utime.ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("R", end="")
        navigator.next()      # this is the enter button
    DisplayInfo()
    
    nav_btn_last_time = new_time

def enable_controls():
    global enc                      # added 18/5/25... encoder stopped working after DROP invoked timer.mgr
    
   # Enable the interupt handlers
    presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)
    enc = Encoder(px, py, v=0, div=4, vmin=None, vmax=None, callback=enc_cb)
    # enc_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_a_IRQ)
    enc_btn.irq(trigger=Pin.IRQ_FALLING, handler=encoder_btn_IRQ)

    lcdbtn.irq(trigger=Pin.IRQ_FALLING, handler=lcdbtn_new)
    infomode.irq(trigger=Pin.IRQ_FALLING, handler=infobtn_cb)

    nav_up.irq(trigger=Pin.IRQ_FALLING, handler=nav_up_cb)
    nav_dn.irq(trigger=Pin.IRQ_FALLING, handler=nav_dn_cb)
    nav_OK.irq(trigger=Pin.IRQ_FALLING, handler=nav_OK_cb)
    nav_L.irq(trigger=Pin.IRQ_FALLING, handler=nav_L_cb)
    nav_R.irq(trigger=Pin.IRQ_FALLING, handler=nav_R_cb)

# endregion
# region LCD
def lcdbtn_new(pin):
    global lcd_timer
# so far, with no debounce logic...
    lcd_on()
    if not lcd_timer is None:
        lcd_timer.deinit()
    lcd_timer = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)

# def lcdbtn_pressed(x):          # my lcd button ISR
#     global lcdbtnflag
#     lcdbtnflag = True
#     sleep_ms(300)

def lcd_off(x):
    # print(f'in lcd_off {ui_mode=}, called from timer={x}')
    # print("Stack trace:")
    # try:
    #     raise Exception("Trace")
    # except Exception as e:
    #     sys.print_exception(e)      # type: ignore
    if ui_mode != UI_MODE_MENU:
        lcd.setRGB(0,0,0)
        lcd4x20.backlight_off()

def lcd_on():
    if ui_mode == UI_MODE_MENU:
        lcd.setRGB(240, 30, 240)
    else:
        lcd.setRGB(170,170,138)
    lcd4x20.backlight_on()

# async def check_lcd_btn():
#     global lcdbtnflag
#     while True:
#         # async with lcd_flag_lock:  # type: ignore
#         #     if lcdbtnflag:
#         #         lcd_on()
#         #         if ui_mode != UI_MODE_MENU:
#         #             _ = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)
#         #         lcdbtnflag = False
#         await lcd_flag_lock.acquire()   # type: ignore
#         try:
#             if lcdbtnflag:
#                 lcd_on()    # turn on, and...
#                 if ui_mode != UI_MODE_MENU:                 # don't set timer for OFF in MENU
#                     _ = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)
#                 lcdbtnflag = False
#         finally:
#             lcd_flag_lock.release()
#         await asyncio.sleep(0.5)
# endregion
# region UNUSED methods
# def Pico_RTC():
#     tod   = rtc.timestamp()
#     year  = tod.split()[0].split("-")[0]
#     month = tod.split()[0].split("-")[1]
#     day   = tod.split()[0].split("-")[2]
#     shortyear = year[2:]
# endregion
# region MAIN METHODS
def init_logging():
    global year, month, day, shortyear
    global tank_log, ev_log, pp_log, eventlogname, hf_log

    now             = now_time_tuple()      # getcurrent time, convert to local SA time
    year            = now[0]
    month           = now[1]
    day             = now[2]
    shortyear       = str(year)[2:]
    datestr         = f"{shortyear}{month:02}{day:02}"
    tanklogname     = f'tank {datestr}.txt'
    pplogname       = f'pres {datestr}.txt'
    eventlogname    = 'borepump_events.txt'
    hfkpaname       = f'HF {datestr}.txt'
    tank_log        = open(tanklogname, "a")
    ev_log          = open(eventlogname, "a")
    pp_log          = open(pplogname, "a")
    hf_log          = open(hfkpaname, "a")

def get_fill_state(d):
    if d > config_dict[MAXDIST]:
        tmp = fill_states[len(fill_states) - 1]
    elif config_dict[MAXDIST] - Delta < d and d <= config_dict[MAXDIST]:
        tmp = fill_states[4]
    elif config_dict[MINDIST] + Delta < d and d <= config_dict[MAXDIST] - Delta:
        tmp = fill_states[3]
    elif config_dict[MINDIST] < d and d <= config_dict[MINDIST] + Delta:
        tmp = fill_states[2]
    elif OverFull < d and d <= config_dict[MINDIST]:
        tmp = fill_states[1]
    elif d <= OverFull:
        tmp = fill_states[0]
    return tmp

def calc_SMA_Depth()-> float:
    sum = 0.0
    n = 0
    for dval in ringbuf:
        if dval > 0:
            sum += dval
            n += 1
    if n > 0:
        return sum / n
    else:
        return 0.0
    
def count_HFkpa_ring()-> int: 
    count = 0
    for i in range(HI_FREQ_RINGSIZE):
        if hi_freq_kpa_ring[i] != 0:
            count += 1
    return count

def calc_average_HFpressure(start:int, length:int)->float:
    # if length > HI_FREQ_AVG_COUNT:
    #     print(f"***>>>calc_average_pressure: {start=} length {length} > {HI_FREQ_AVG_COUNT}")
    p = 0
    for i in range(length):
        mod_index = (hi_freq_kpa_index - start - i - 1) % HI_FREQ_RINGSIZE  # change to average hi_freq_kpa readings
        tmp = hi_freq_kpa_ring[mod_index]
        # print(f'  {mod_index=}, {tmp=}')
        # if tmp == 0 and hi_freq_kpa_index .... need to revisit thislogic   TODO
        # if tmp == 0 and hf_kpa_hiwater > 0 and (length - 1) >= hf_kpa_hiwater:
        if tmp == 0 and hf_kpa_hiwater >= mod_index and mod_index >= (hf_kpa_hiwater - length):
            print(f"***>>>ZERO hi_freq_kpa ring buffer at index {mod_index}, {hf_kpa_hiwater=}, {length=}")

        p += tmp
    return p/length

def get_tank_depth():
    global depth, tank_is

    d = distSensor.read()
    depth = (Tank_Height - d) / 1000
    tank_is = get_fill_state(d)

def set_baseline_kpa(timer: Timer):
    try:
        global baseline_pressure, baseline_set, zone, zone_minimum, zone_maximum, qa, qb, qc, zone_max_drop, kpa_peak, time_peak

        if avg_kpa_set:             # only do this if we have a valid average
# calculate WITHOUT making a function call...
            # p = 0
            # for i in range(BASELINE_AVG_COUNT):
            #     idx = (hi_freq_kpa_index - i - 1) % HI_FREQ_RINGSIZE    # need to -1 as index is the next write location
            #     tmp = hi_freq_kpa_ring[idx]  # change to average hi_freq_kpa readings
            #     # ev_log.write(f"set_baseline:{idx=} {tmp=}\n")
            #     p += tmp
            baseline_pressure = round(calc_average_HFpressure(0, BASELINE_AVG_COUNT))  # get average of last BASELINE_AVG_COUNT readings.
            baseline_set = True
            # bl_by_func = calc_average_HFpressure(0, BASELINE_AVG_COUNT)  # get average of last BASELINE_AVG_COUNT readings.
            bp_str = f"{now_time_long()} Baseline set to {baseline_pressure} kPa"
            print(bp_str)
            ev_log.write(bp_str + "\n")

            new_zone, zone_minimum, _, zone_maximum, qa, qb, qc, zone_max_drop  = get_zone_from_list(baseline_pressure)
            if new_zone != zone:
                if new_zone in peak_pressure_dict.keys():
                    peak_pressure_dict[new_zone] = (time_peak, kpa_peak, time_peak - last_ON_time)     # set in read_pressure
                else:
                    error_ring.add(errors.get_description(TankError.ZONE_NOTFOUND))
                z_str = f"{now_time_long()} Zone changed from {zone} to {new_zone}"
                zone = new_zone
                print(z_str)
                ev_log.write(z_str + "\n")

            if kpa_peak > 0:
                peak_str = f"{now_time_long()} Peak Pressure: {kpa_peak}"
                print(peak_str)
                ev_log.write(peak_str + "\n")
        else:                       # reset timer for another try
            print("No valid average kPa reading to set baseline.  Resetting timer...")
            ev_log.write(f"{now_time_long()} set_baseline_kpa: resetting timer for extra 15 seconds\n")
            timer.init(period=15 * 1000, mode=Timer.ONE_SHOT, callback=set_baseline_kpa)   # type: ignore

    except Exception as e:
        print(f"Error in set_baseline_kpa: {e}")

def set_average_kpa(timer: Timer):
    global average_kpa, avg_kpa_set

    if hf_kpa_hiwater >= AVG_KPA_DELAY - 1:
        tmp = int(calc_average_HFpressure(0, AVG_KPA_DELAY))  # get average of last AVG_KPA_DELAY readings
        if tmp > 0:
            average_kpa = tmp
            # print("set_average_kpa callback: Average kPa set: ", average_kpa)
            avg_kpa_set = True
            kpa_ring.add(average_kpa)         # add to ring buffer for later use
        else:
            print("set_average_kpa: Yikes!! Buffer has data, but average_kpa is 0")
            for i in range(5): print(f"{hi_freq_kpa_ring[i]} ", end=" ")  
    else:
        timer.init(period=AVG_KPA_DELAY * 1000, mode=Timer.ONE_SHOT, callback=set_average_kpa)   # type: ignore

def updateData():
    global tank_is
    global depth_str
    global pressure_str
    global depth
    global last_depth
    global depth_ROC
    global ringbuf, ringbufferindex, sma_depth
    global average_kpa, zone, avg_kpa_set
    global temp
  
    get_tank_depth()

    ringbuf[ringbufferindex] = depth ; ringbufferindex = (ringbufferindex + 1) % DEPTHRINGSIZE
    sma_depth = calc_SMA_Depth()
    time_factor = config_dict[DELAY] / 60
    if DEBUGLVL > 0:
        print(f"{sma_depth=} {last_depth=}  {depth_ROC=}")
    depth_ROC = (sma_depth - last_depth) / time_factor	# ROC in m/minute.  Save negatives also... for anomaly testing
    # if DEBUGLVL > 0: print(f"{sma_depth=} {last_depth=} {depth_ROC=:.3f}")
    last_depth = sma_depth				# track change since last reading
    depth_str = f"{depth:.2f}m " + tank_is
    # print(f"In updateData: ADC value: {pv}")
    # bp_kpa = kparing[kpaindex]        # get last kPa reading
    if hf_kpa_hiwater >= AVG_KPA_DELAY - 1:
        # print(f'In updateData: hi_freq count = {count_HFkpa_ring()}')
        tmp = int(calc_average_HFpressure(0, AVG_KPA_DELAY))  # get average of last AVG_KPA_DELAY readings.
        if tmp > 0:
            average_kpa = tmp
            avg_kpa_set = True
            kpa_ring.add(average_kpa)         # add to ring buffer for later use
            # print(f"Average kPa set in UpdateData to: {average_kpa}")
        else:
            print("Yikes!! HF_B full, but average_kpa is 0")
            for i in range(5): print(f"{hi_freq_kpa_ring[i]} ", end=" ")  

    pressure_str = f'B {baseline_pressure:>3} Av {int(average_kpa):>3} {zone:3}'    # might change this to be updated more frequently in a dedicated asyncio loop...
    temp = 27 - (temp_sensor.read_u16() * TEMP_CONV_FACTOR - 0.706)/0.001721

def get_pressure():
    adc_val = bp_pressure.read_u16()
    measured_volts = 3.3 * float(adc_val) / 65535
    sensor_volts = measured_volts / VDIV_Ratio
    kpa = max(0, round(sensor_volts * 200 - 100))     # 200 is 800 / delta v, ie 4.5 - 0.5  Changed int to round 13/5/25
    # print(f"ADC value: {adc_val=}")
    return adc_val, kpa
     
def updateClock():
    global str_time

    str_time = now_time_short()

def log_switch_error(new_state):
    print(f"!!! log_switch_error  !! {new_state}")
    ev_log.write(f"{now_time_long()} ERROR on switching to state {new_state}\n")
    event_ring.add(f"ERR swtch {new_state}")
    
def parse_reply(rply):
    if DEBUGLVL > 1: print(f"in parse arg is {rply}")
    if isinstance(rply, tuple):			# good...
        key = rply[0]
        val = rply[1]
#        print(f"in parse: key={key}, val={val}")
        if key.upper() == "STATUS":
            return True, val
        else:
            print(f"Unknown tuple: key {key}, val {val}")
            return False, -1
    else:
        print(f"Expected tuple... didn't get one.  Got {rply}")
        return False, False

def transmit_and_pause(msg, delay):
    if DEBUGLVL > 1: print(f"TX Sending {msg}, sleeping for {delay} ms")
    radio.send(msg)
    sleep_ms(delay)

def confirm_solenoid():
    solenoid_state = sim_detect()

    if op_mode == OP_MODE_AUTO:
        return solenoid_state
    elif op_mode == OP_MODE_IRRIGATE:
        return not solenoid_state

def radio_time(local_time):
    return(local_time + clock_adjust_ms)

def borepump_ON():
    global average_timer, baseline_timer, hf_kpa_hiwater, avg_kpa_set, baseline_set, last_ON_time, kpa_peak, kpa_low
    global steady_state, rec_num

    if SIMULATE_PUMP:
        print(f"{now_time_long()} SIM Pump ON")
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
                last_ON_time = time.time()          # for easy calculation of runtime to DROP pressure OFF    
                switch_ring.add("PUMP ON")
                # print(f"***********Setting timer for average_kpa at {now_time_long()}")    
                ev_log.write(f"{now_time_long()} ON\n")
                system.on_event("ON ACK")
                # print(f"***********Setting timer for baseline_kpa at {now_time_long()}")
                if kpa_sensor_found:
                    hf_kpa_hiwater = 0              # reset this to zero... for calc average_pressure
                    avg_kpa_set = False             # ? Should I also set hf_kpa_index to 0 ??
                    baseline_set = False
                    kpa_peak = 0
                    kpa_low = 1000
                    average_timer  = Timer(period=AVG_KPA_DELAY  * 1000, mode=Timer.ONE_SHOT, callback=set_average_kpa)  # start timer to record average after 5 seconds
                    baseline_timer = Timer(period=BASELINE_DELAY * 1000, mode=Timer.ONE_SHOT, callback=set_baseline_kpa)  # start timer to record baseline after 30 seconds
                    change_logging(True)
    # reset this to avoid spurious ALARMS as ROC average climbs to steady value... SMA issue
                steady_state = False
                rec_num = 0
            else:
                log_switch_error(new_state)

def borepump_OFF():

    if SIMULATE_PUMP:
        print(f"{now_time_long()} SIM Pump OFF")
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
                switch_ring.add("PUMP OFF")
                change_logging(False)
                ev_log.write(f"{now_time_long()} OFF\n")
                system.on_event("OFF ACK")
                if DEBUGLVL > 1: print("borepump_OFF: Closing valve")
                solenoid.value(1)               # wait until pump OFF confirmed before closing valve !!!
            else:
                log_switch_error(new_state)

def manage_tank_fill():
    global tank_is, radio, system
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
                raiseAlarm("NOT turning pump on... valve is CLOSED!", tank_is)
                error_ring.add(errors.get_description(TankError.VALVE_CLOSED))                
    elif tank_is == fill_states[0] or tank_is == fill_states[1]:	# Full or Overfull
#        bore_ctl.value(0)			# switch borepump OFF
        if borepump.state:			# pump is ON... need to turn OFF
            if DEBUGLVL > 0: print("in controlBorePump, switching pump OFF")
            borepump_OFF()

def dump_zone_peak()->None:
    print("\nZone Peak Pressures:")
    for z in peak_pressure_dict.keys():
        if peak_pressure_dict[z][1] > 0:
            str = f"{format_secs_long(peak_pressure_dict[z][0])}  Zone {z:<3}: peak {peak_pressure_dict[z][1]}kPa {peak_pressure_dict[z][2]} seconds after ON"
            print(str)
            ev_log.write(str + "\n")

def raiseAlarm(param, val):

    logstr = f"{now_time_long()} ALARM {param}, value {val:.3g}"
    ev_str = f"ALARM {param}, value {val:.3g}"
    print(logstr)
    ev_log.write(f"{logstr}\n")
    event_ring.add(ev_str)

def cancel_deadtime(timer:Timer)->None:
    global op_mode

    if previous_op_mode < OP_MODE_DISABLED:
        str = f'{now_time_long()} Disabled mode cancelled, returning to {previous_op_mode}'
        ev_log.write(f'{str}\n')
        print(str)
        event_ring.add("Disabled mode cancelled")
        op_mode = previous_op_mode

def kpadrop_cb(timer:Timer)->None:
    global kpa_drop_timer, alarm, op_mode, previous_op_mode, disable_timer, last_ON_time

    alarm.value(0)                  # turn off alarm
    
    if kpa_drop_timer is not None:  # kill this timer
        kpa_drop_timer.deinit()
        kpa_drop_timer = None

    # if op_mode == OP_MODE_IRRIGATE: # don't abort... just turn off pump, but let cycle continue
    previous_op_mode = op_mode  # save to restore later
    op_mode = OP_MODE_DISABLED

    borepump_OFF()              # turn off pump

    last_runsecs = time.time() - last_ON_time
#    recovery_time = int(last_runsecs * (100/timer_dict["Duty Cycle"] - 1))
    recovery_time = last_runsecs * 2        # simple version for quick test  TODO review recovery_time
    # disable_timer = Timer(period=recovery_time*1000, mode=Timer.ONE_SHOT, callback=cancel_deadtime)
    timer_mgr.create_timer('disable', recovery_time * 1000, cancel_deadtime)
    drop_str = f"{now_time_long()} kPa DROP detected - stopped pump, disabling operation for {recovery_time / 60} minutes"
    ev_log.write(drop_str + "\n")
    print(drop_str)
    # else:
    #     change_logging(False)
    #     abort_pumping("kPa drop - sucking air?")    # STOP pumping, and enter maintenance mode

def find_menu_index(param_name:str)->int:
    # menu_list:dict = new_menu['items'][3]['items'][0]
    # print(menu_list)
    # i = 0
    for param_index in range(len(config_dict)):
        param: str             = new_menu['items'][3]['items'][0]['items'][param_index]['title']
        # new_working_value: int = new_menu['items'][3]['items'][0]['items'][param_index]['value']['W_V']
        # print(f'{d=}, type is {type(d)}')
        if param_name in config_dict.keys():
            if param == param_name:          # special case... we need to map 1 to 0 for False
                # print(f"Found {param_name} at index {param_index}")
                return param_index
            else:
                continue
        else:
            print(f"{param_name} not in keys!")
    print(f"Did not find {param_name} in menu list config_dict")
    return -1

def change_logging(bv:bool)->None:
    val = 2 if bv else 1
    config_dict[LOGHFDATA] = val
    param_index = find_menu_index(LOGHFDATA)
    if param_index >= 0:
        print(f"Setting {new_menu['items'][3]['items'][0]['items'][param_index]['title']} to {val}")
        new_menu['items'][3]['items'][0]['items'][param_index]['value']['W_V'] = val

def quad(a: float, b: float, c: int, x: int) -> int:
    """Calculate the pressure at a given point using a quadratic equation"""
    return int(a * x*x + b * x + c)
    
def isRapidDrop(lookback:int, zone_max_drop: int)->bool:
    """
    Check if the pressure drop is rapid, or slow drift.  This is done by checking the average pressure over a lookback period.
    """
    global baseline_pressure, baseline_time

    prev_avg = calc_average_HFpressure(lookback, LO_FREQ_AVG_COUNT)     # only time I use lookback...
    return prev_avg - average_kpa < zone_max_drop
    # if prev_avg - average_kpa < zone_max_drop:   # looks like a slow drift, not a rapid drop
        # if abs(average_kpa - zone_minimum) < 5:  # if we are close to the minimum pressure, then don't reset baseline]:
        #     near_min_str = f"{now_time_long()} Pressure near zone minimum, not resetting baseline: {zone_minimum=}, {average_kpa=}"
        #     print(near_min_str)
        #     ev_log.write(near_min_str + "\n")
        #     return True
        # else:               # reset baseline pressure
        #     if DEBUGLVL > 1: print(f"prev_avg: {prev_avg}, average_kpa: {average_kpa}")
        #     old_baseline = baseline_pressure
        #     baseline_pressure = average_kpa
        #     bl_reset_str = f'{now_time_long()} Baseline reset from {old_baseline} to {baseline_pressure}'
        #     print(bl_reset_str)
        #     ev_log.write(bl_reset_str + "\n")
        #     event_ring.add("Baseline reset")
    #     return False
    # else:                   # looks like a rapid drop
    #     return True

def check_for_Baseline_Drift()->None:
    global baseline_pressure
    
    # prev_avg = calc_average_HFpressure(lookback, LO_FREQ_AVG_COUNT)
    if average_kpa > 0 and baseline_pressure / average_kpa > 1.1:         # average_kpa has dropped of more than 10% from previous baseline
        if abs(average_kpa - zone_minimum) < 5:
            near_min_str = f"{now_time_long()} Pressure near zone minimum, not resetting baseline: {zone_minimum=}, {average_kpa=}"
            print(near_min_str)
            ev_log.write(near_min_str + "\n")
        else:
            old_baseline = baseline_pressure
            baseline_pressure = average_kpa
            bl_reset_str = f'{now_time_long()} Baseline reset in check_for_Drift from {old_baseline} to {baseline_pressure}'
            print(bl_reset_str)
            ev_log.write(bl_reset_str + "\n")
            event_ring.add("Baseline reset")

def checkForAnomalies()->None:
    global borepump, depth_ROC, tank_is, average_kpa, kpa_drop_timer

    if borepump.state:                  # pump is ON
        if baseline_set and baseline_pressure > 0 and avg_kpa_set and hf_kpa_hiwater == HI_FREQ_RINGSIZE - 1: # this ensures we get a valid average kPa reading
            if baseline_set and baseline_pressure > 0 and average_kpa / baseline_pressure > 1.1:
                raiseAlarm(f"Baseline {baseline_pressure } lower than avg_kpa", average_kpa)
                error_ring.add(errors.get_description(TankError.BASELINE_LOW))

            # samples_since_last_ON = int((time.time() - last_ON_time) / (PRESSURE_PERIOD_MS / 1000))
            # expected_pressure_just_now = quad(qa, qb, qc, samples_since_last_ON - LOOKBACKCOUNT)
            # expected_pressure_now      = quad(qa, qb, qc, samples_since_last_ON)  # calculate expected pressure using quadratic equation
            # expected_drop = expected_pressure_just_now - expected_pressure_now    # TODO - this might need to look at cumulative runtime over say the last 12 hours
            av_p_prior  = calc_average_HFpressure(LOOKBACKCOUNT, HI_FREQ_AVG_COUNT)  # get average of last HI_FREQ_AVG_COUNT readings.
            av_p_now    = calc_average_HFpressure(0, HI_FREQ_AVG_COUNT)
            actual_pressure_drop = int(av_p_prior - av_p_now)       # Important!  Avoid rounding errors.. avg drop of 0.3 on HT triggered alarm without this!
            # if isRapidDrop(LOOKBACKCOUNT, expected_drop):   # check for rapid drop... if so, then set alarm and turn off pump
                                    # WARNING: this looks back 120 records ... hence ref to hf_kpa_hiwater above
            if actual_pressure_drop > zone_max_drop:     # This needs to be zone-specific - even if I don't use quad
                runtime = (time.time() - last_ON_time)
                runmins = int(runtime / 60)
                runseconds = runtime % 60
                # raiseAlarm(f"Pressure DROP after {runmins}:{runseconds:02}. Expected:{expected_drop}", actual_pressure_drop)
                raiseAlarm(f"Pressure DROP after {runmins}:{runseconds:02}  Exceeds zone max drop:{zone_max_drop}", actual_pressure_drop)
                error_ring.add(errors.get_description(TankError.PRESSUREDROP))
                alarm.value(1)                              # this might change... to ONLY if not in TWM/IRRIGATE    
                kpa_drop_timer = Timer(period=ALARMTIME * 1000, mode=Timer.ONE_SHOT, callback=kpadrop_cb)

            if op_mode == OP_MODE_IRRIGATE and  kpa_sensor_found and average_kpa < zone_minimum:
                raiseAlarm("Below Zone Min Pressure", average_kpa)
                error_ring.add(errors.get_description(TankError.BELOW_ZONE_MIN))

        if op_mode == OP_MODE_AUTO:
            if abs(depth_ROC) > MAX_ROC:
                raiseAlarm("Max ROC Exceeded", depth_ROC)
                error_ring.add(errors.get_description(TankError.MAX_ROC_EXCEEDED))               
            if tank_is == "Overflow":                           # ideally, refer to a Tank object... but this will work for now
                raiseAlarm("OVERFLOW and still ON", 999)        # probably should do more than this.. REALLY BAD scenario!
                error_ring.add(errors.get_description(TankError.OVERFLOW_ON))             
            
            if depth_ROC < -MIN_ROC and borepump.state:         # pump is ON but level is falling!
                raiseAlarm("DRAINING while ON", depth_ROC)                              
                error_ring.add(errors.get_description(TankError.DRAINWHILE_ON))
    
    else:           # pump is OFF
        if op_mode == OP_MODE_AUTO:
            if depth_ROC > MIN_ROC:      # pump is OFF but level is rising!
                raiseAlarm("FILLING while OFF", depth_ROC)
                error_ring.add(errors.get_description(TankError.FILLWHILE_OFF)) 

def abort_pumping(reason:str)-> None:
    global op_mode, BlinkDelay, info_display_mode, twm_timer, maint_mode_time
# if bad stuff happens, kill off any active timers, switch off, send notification, and enter maintenance state
    try:
        if twm_timer is not None:
            print("Killing my_timer...")
            twm_timer.deinit()
    except Exception as e:
        print(f"In ABORT : {e}")

    if borepump.state:              # pump is ON
        borepump_OFF()
    logstr = f"{now_time_long()} ABORT invoked! {reason}"
    print(logstr)
    event_ring.add("ABORT!!")
    ev_log.write(logstr + "\n")
    ev_log.flush()
    lcd.clear()
    lcd.setCursor(0,0)
    lcd.printout(now_time_short())
    lcd.setCursor(0,1)
    lcd.printout("MAINTENANCE MODE")
    BlinkDelay        = FAST_BLINK               # fast LED flash to indicate maintenance mode
    info_display_mode = INFO_MAINT
    op_mode           = OP_MODE_MAINT
    maint_mode_time = now_time_long()

def check_for_critical_states() -> None:
    if borepump.state:              # pump is ON
        run_minutes = (time.time() - borepump.last_time_switched) / 60

# This test needs to be done more frequently... after calculating high frequency kpa
        fast_average = calc_average_HFpressure(0, FAST_AVG_COUNT)     
        if kpa_sensor_found:        # if we have a pressure sensor, check for critical values
            if fast_average > 0:         # if we have a valid average kPa reading... but MUST be delayed until we have a few readings
                if fast_average > config_dict[MAXPRESSURE]:
                    raiseAlarm("Excess kPa", fast_average)
                    error_ring.add(errors.get_description(TankError.EXCESS_KPA))               
                    abort_pumping("check_for_critical_states: Excess kPa")

                if fast_average < config_dict[NOPRESSURE]:
                    raiseAlarm(NOPRESSURE, fast_average)
                    error_ring.add(errors.get_description(TankError.NO_PRESSURE))
                    abort_pumping("check_for_critical_states: No pressure")

        if run_minutes > config_dict[MAXRUNMINS]:            # if pump is on, and has been on for more than max... do stuff!
            raiseAlarm("RUNTIME EXCEEDED", run_minutes)
            error_ring.add(errors.get_description(TankError.RUNTIME_EXCEEDED))
            borepump_OFF()

def DisplayInfo()->None:
    global program_start_time, program_end_time

# NOTE: to avoid overlapping content on a line, really need to compose a full line string, then putstr the entire thing :20
#       moving to a field and updating bits doesn't relly work so well... at least not unless ALL modes use consistent field defs...
    now = time.time()
    if   ui_mode == UI_MODE_MENU:
        if   info_display_mode == INFO_AUTO:
            str_0 = f'Lvl: {navigator.current_level[-1]["index"]}'
            lcd4x20.move_to(0, 0)
            lcd4x20.putstr(str_0)
            str_0 = f'Idx: {navigator.current_menuindex:3}'
            lcd4x20.move_to(14, 0)
            lcd4x20.putstr(str_0)

            str_1 = f'{" ":^20}'
            if navigator.mode == "value_change":
                it = navigator.get_current_item()
                par = it[Title_Str]
                st = it[Value_Str][Step_Str]
                wv = it[Value_Str]["W_V"]
                str_1 = f'P:{par[0:4]} S:{st:2} V:{wv:4}'
            lcd4x20.move_to(0, 1)
            lcd4x20.putstr(str_1)
    elif ui_mode == UI_MODE_NORM:
        # if op_mode   == OP_MODE_AUTO:
        if   info_display_mode == INFO_AUTO:
            e_code = ""
            if error_ring.index > -1:
                entry = error_ring.buffer[error_ring.index]
                # print(f'{error_ring.index=} {entry=}')
                e_code = errors.get_code(entry[1])
            lcd4x20.move_to(0, 0)                # move to top left corner of LCD
            lcd4x20.putstr(f'EC:{e_code:<4}')

            lcd4x20.move_to(8, 0)
            lcd4x20.putstr(f"S{1 if steady_state else 0}    ")  

            lcd4x20.move_to(14, 0)
            lcd4x20.putstr(f"HF:{' ON' if config_dict[LOGHFDATA] > 1 else 'OFF'}")

            calc_uptime()
            lcd4x20.move_to(0, 1)
            lcd4x20.putstr(f'{ut_short} {calc_pump_runtime(borepump)}')        # runtime calcs

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr(f'D {depth:<.2f} R{depth_ROC:>5.2f} ZP {peak_pressure_dict[zone][1]:>3}')                # print depth & state in third line of LCD

            lcd4x20.move_to(0, 3)
            lcd4x20.putstr(f'BL:{baseline_pressure:>3} Av:{average_kpa:>3} IP:{hi_freq_kpa_ring[hi_freq_kpa_index]:>3}')        # print depth_ROC in third line of LCD
        elif info_display_mode == INFO_IRRIG:
        # elif op_mode == OP_MODE_IRRIGATE:

            delay_minutes   = int((program_start_time - now) / 60)
            start_hrs       = int(delay_minutes/60)
            start_mins      = delay_minutes % 60
            end_minutes     = int((program_end_time - now) / 60)
            end_hrs         = int(end_minutes/60)
            end_mins        = end_minutes % 60

            lcd4x20.move_to(0, 0)
            lcd4x20.putstr(f'S {start_hrs:>2}:{start_mins:02}  E {end_hrs:>2}:{end_mins:02}')        

            lcd4x20.move_to(0, 1)
            lcd4x20.putstr('Cycle       Remain')

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr(f'Z:{zone:<3} Min {zone_minimum:<3} ZP {peak_pressure_dict[zone][1]:<3}')

    # can ONLY transition here from AUTO... no need to update row 3

            # lcd4x20.move_to(0, 3)
            # lcd4x20.putstr(f'BL:{baseline_pressure:3} Av:{average_kpa:3} IP:{hi_freq_kpa_ring[hi_freq_kpa_index]:3}')        # print depth_ROC in third line of LCD
        
        elif info_display_mode == INFO_DIAG:
        # can ONLY transition here from IRRIG-1... only need to update row 0
            e_code = ""
            if error_ring.index > -1:
                entry = error_ring.buffer[error_ring.index]
                # print(f'{error_ring.index=} {entry=}')
                e_code = errors.get_code(entry[1])
            lcd4x20.move_to(0, 0)                # move to top left corner of LCD
            lcd4x20.putstr(f'EC:{e_code:<4}')

            lcd4x20.move_to(8, 0)
            lcd4x20.putstr(f"S{1 if steady_state else 0}")  

            lcd4x20.move_to(14, 0)
            lcd4x20.putstr(f"HF:{' ON' if config_dict[LOGHFDATA] > 1 else 'OFF'}")

            remain_str = f'{" ":^8}'
            opm_str = f'{opmode_dict[op_mode]:4}'
            if op_mode == OP_MODE_DISABLED: # show remaining time to pause
                if timer_mgr.is_pending('disable'):
                    secs_remaining = timer_mgr.get_time_remaining('disable')
                remain_hrs  = int(secs_remaining / (60 * 60))
                remain_mins = int(secs_remaining / 60) % 60
                remain_secs = secs_remaining % 60
                remain_str = f'{remain_hrs:02}:{remain_mins:02}:{remain_secs:02}'
                # print(f'Updated disable remain time: {remain_str}')
                lcd4x20.move_to(0, 1)
                lcd4x20.putstr(f'{opm_str} {remain_str}')

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr(f'OPM: {opmode_dict[op_mode]}  R#:{rec_num}')
        elif info_display_mode == INFO_MAINT:       # MAINTENANCE mode
            lcd4x20.move_to(0, 0)
            lcd4x20.putstr(f'{maint_mode_time:^20}')
        
            lcd4x20.move_to(0, 1)
            lcd4x20.putstr(f'{"MAINTENANCE_MODE":^20}')

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr("Hit RESET 2 continue")

            lcd4x20.move_to(0, 3)
            lcd4x20.putstr(f'{" ":^20}')
        else:
            lcd4x20.clear()
            lcd4x20.move_to(0, 1)
            lcd4x20.putstr(f'{"I_D_M Invalid":^20}')
 
    # lcd4x20.putstr(f'lvl:{len(navigator.current_level)} {navigator.current_index} {baseline_pressure:3}')        # print op_mode in third line of LCD
    # lcd4x20.move_to(0, 4)                # move to fourth line of LCD
    # lcd4x20.putstr(f'nav mode: {navigator.mode:<10}')        # print navigator.mode in fourth line of LCD

def DisplayData()->None:
    if ui_mode != UI_MODE_MENU:             # suspend overwriting LCD whist in MENU
        lcd.clear()
        lcd.setCursor(0, 0)
        lcd.printout(str_time)

# First, determine what to display on LCD 2x16
        if op_mode == OP_MODE_AUTO:
            if display_mode == "depth":
                display_str = depth_str
            elif display_mode == "pressure":
                display_str = pressure_str
            else:
                display_str = "no display mode"
        elif op_mode == OP_MODE_IRRIGATE:
            now = time.time()
            if program_pending:                                         # programmed cycle waiting to start
                delay_minutes = int((program_start_time - now) / 60)
                # print(f"{delay_minutes=}")
                start_hrs = int(delay_minutes/60)
                start_mins = delay_minutes % 60
                display_str = f"Prog strt {start_hrs:>2}:{start_mins:02}m"
            elif ON_cycle_end_time > 0:
                cycle_number    = int(sl_index / 3) + 1
                total_cycles    = int(num_cycles / 3)

                secs_remaining  = ON_cycle_end_time - now
                if secs_remaining > 0:                      # we are mid-ON cycle... how much longer for?
                    if secs_remaining > 60:
                        disp_time = f"{int(secs_remaining / 60)}m"
                    else:
                        disp_time = f"{secs_remaining}s"
                    display_str = f"C{cycle_number}/{total_cycles} {disp_time:4} {average_kpa}"
                else:                                       # we are in OFF time... 
                    secs_to_next_ON = next_ON_cycle_time - now 
                    if secs_to_next_ON < 0:                 # there is no next ON...
                        display_str = "End TWM soon"        # TODO ... fix this display to a proper time
                        # print(f"{format_secs_long(now)}: {secs_to_next_ON=}")
                    else:
                        if secs_to_next_ON < 60:
                            display_str = f"Wait {cycle_number}/{total_cycles} {secs_to_next_ON}s"
                        else:
                            display_str = f"Wait {cycle_number}/{total_cycles} {int(secs_to_next_ON / 60)}m"
            else:
                display_str = "IRRIG MODE...??"
        elif op_mode == OP_MODE_DISABLED:
            display_str = pressure_str          # just show pressure
        elif op_mode == OP_MODE_MAINT:
            display_str = "MAINT MODE"
        else:
            display_str = "OPM INVALID"
        lcd.setCursor(0, 1)
        lcd.printout(f"{display_str:<16}")

# now, update 2004 display...
        # if op_mode == OP_MODE_AUTO:
        #     lcd4x20.move_to(0, 2)
        #     lcd4x20.putstr(f"{depth_str:<20}")
        #     lcd4x20.move_to(0, 3)
        #     lcd4x20.putstr(f'BL:{baseline_pressure:3} Av:{average_kpa:3} IP:{hi_freq_kpa_ring[hi_freq_kpa_index]:3}')        # print depth_ROC in third line of LCD
 
        # elif op_mode == OP_MODE_IRRIGATE:
        #     lcd4x20.move_to(0, 2)
        #     lcd4x20.putstr(f"Zone: {zone:<8}")
        #     lcd4x20.move_to(0, 3)
        #     lcd4x20.putstr(f'BL:{baseline_pressure:3} Av:{average_kpa:3} IP:{hi_freq_kpa_ring[hi_freq_kpa_index]:3}')        # print depth_ROC in third line of LCD

def LogData()->None:
    global LOG_FREQ
    global level_init
    global last_logged_depth
    global last_logged_kpa

# Now, do the print and logging
    tempstr = f"{temp:.2f} C"  
    logstr  = str_time + f" {depth:.3f} {average_kpa:4}\n"
    dbgstr  = str_time + f" {depth:.3f}m {average_kpa:4}kPa"    
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
        if level_change > MIN_DEPTH_CHANGE_M:
            last_logged_depth = depth
            enter_log = True
        pressure_change = abs(last_logged_kpa - average_kpa)
        if pressure_change > MAX_KPA_CHANGE:        # TODO review MAX_KPA_CHANGE
            last_logged_kpa = average_kpa
            enter_log = True

        if enter_log: tank_log.write(logstr)
    # tank_log.write(logstr)          # *** REMOVE AFTER kPa TESTING ***
    print(dbgstr)

def listen_to_radio():
#This needs to be in a separate event task... next job is that
    global radio
    if radio.receive():
        msg = radio.message
        if isinstance(msg, str):
            print(msg)
            if "FAIL" in msg:
                print(f"Dang... something wrong...{msg}")
        elif isinstance(msg, tuple):
            print("Received tuple: ", msg[0], msg[1])

def init_radio():
    global radio, system
    
    print("Init radio...")
    if radio.receive():
        msg = radio.message
        print(f"Read {msg}")

    while not ping_RX():
        print("Waiting for RX...")
        sleep(1)

# if we get here, my RX is responding.
    # print("RX responded to ping... comms ready")
    system.on_event("ACK COMMS")

def ping_RX() -> bool:           # at startup, test if RX is listening
#    global radio

    ping_acknowleged = False
    transmit_and_pause("PING", RADIO_PAUSE)
    if radio.receive():                     # depending on time relative to RX Pico, may need to pause more here before testing?
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

def calc_pump_runtime(p:Pump) -> str:
    dc_secs = p.cum_seconds_on
    if p.state:
        dc_secs += (time.time() - p.last_time_switched)
    days  = int(dc_secs / (60*60*24))
    hours = int(dc_secs % (60*60*24) / (60*60))
    mins  = int(dc_secs % (60*60) / 60)
    secs  = int(dc_secs % 60)

    return f'{days}d {hours:02}:{mins:02}:{secs:02}'

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

    dc: float = p.calc_duty_cycle()
    
    ev_log.write(f"Last switch time:   {format_secs_long(p.last_time_switched)}\n")
    ev_log.write(f"Total switches this period: {p.num_switch_events}\n")
    ev_log.write(f"Cumulative runtime: {days} days {hours} hours {mins} minutes {secs} seconds\n")
    ev_log.write(f"Duty cycle: {dc:.2f}%\n")
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

def init_ringbuffers():
    global ringbuf, ringbufferindex, eventindex, switchindex, kpaindex, hi_freq_kpa_ring, hi_freq_kpa_index
    global event_ring, error_ring, switch_ring, kpa_ring

    ringbuf = [0.0]                 # start with a list containing zero...
    if DEPTHRINGSIZE > 1:             # expand it as needed...
        for x in range(DEPTHRINGSIZE - 1):
            ringbuf.append(0.0)
    if DEBUGLVL > 0: print("Ringbuf is ", ringbuf)
    ringbufferindex = 0

# Standard ring buffer for errors using the instance
    # error_ring = RingBuffer(
    #     size=ERRORRINGSIZE, 
    #     time_formatter=lambda t: format_secs_long(t),
    #     short_time_formatter=lambda t: format_secs_short(t),
    #     value_formatter=lambda x: errors.get_description(x),
    #     logger=ev_log.write
    # )

    switch_ring = RingBuffer(
        size=SWITCHRINGSIZE, 
        time_formatter=lambda t: format_secs_long(t),
        short_time_formatter=lambda t: format_secs_short(t),
        logger=ev_log.write
    )

    kpa_ring = RingBuffer(
        size=KPARINGSIZE, 
        time_formatter=lambda t: format_secs_long(t),
        short_time_formatter=lambda t: format_secs_short(t)
    )

    # Ring buffer with duplicate detection for events
    event_ring = DuplicateDetectingBuffer(
        size=EVENTRINGSIZE,
        time_limit=30,
        time_formatter=lambda t: format_secs_long(t),
        short_time_formatter=lambda t: format_secs_short(t),
        logger=ev_log.write
    )

    error_ring = DuplicateDetectingBuffer(
        size=ERRORRINGSIZE,
        time_limit=30,
        time_formatter=lambda t: format_secs_long(t),
        short_time_formatter=lambda t: format_secs_short(t),
        logger=ev_log.write
    )

    # for now, this one is different...
    hi_freq_kpa_ring = [0 for _ in range(HI_FREQ_RINGSIZE)]
    hi_freq_kpa_index = 0

def init_all():
    global borepump, steady_state, free_space_KB, presspump, vbus_status, vbus_on_time, report_outage
    global display_mode, navigator, encoder_count, encoder_btn_state, enc_a_last_time, enc_btn_last_time, modebtn_last_time
    global slist, program_pending, sys_start_time, rotary_btn_pressed, kpa_sensor_found
    global nav_btn_state, nav_btn_last_time
    global baseline_pressure, baseline_set, zone, zone_max_drop, zone_minimum, zone_maximum, hf_kpa_hiwater, stable_pressure, average_kpa, last_ON_time
    global ONESECBLINK, lcd_timer
    global ut_long, ut_short

    PS_ND               = "Pressure sensor not detected"
    str_msg             = "At startup, BorePump is "
    encoder_count       = 0       # to track rotary next/prevs
    now                 = utime.ticks_ms()
    enc_a_last_time     = now
    encoder_btn_state   = False
    enc_btn_last_time   = now
    modebtn_last_time   = now
    rotary_btn_pressed  = False
    nav_btn_last_time   = 0
    nav_btn_state       = False

    ev_log.write(f"\n{now_time_long()} Pump Monitor starting - sw ver:{SW_VERSION}\n")
    ev_log.write(f'{config_dict[DELAY]=}s {PRESSURE_PERIOD_MS=}ms {DEPTHRINGSIZE=}\n')
    
    slist=[]

    Change_Mode(UI_MODE_NORM)
    lcd_on()
    lcd4x20.clear()
    lcd4x20.display_on()
    lcd4x20.backlight_on()

# Get the current pump state and init my object    
    borepump            = Pump("BorePump", get_initial_pump_state())

# On start, valve should now be open... but just to be sure... and to verify during testing...
    if borepump.state:
        if DEBUGLVL > 0:
            print(str_msg + "ON  ... opening valve")
        solenoid.value(0)           # be very careful... inverse logic!
    else:
        if DEBUGLVL > 0:
            print(str_msg +  "OFF ... closing valve")
        solenoid.value(1)           # be very careful... inverse logic!

    presspump           = Pump("PressurePump", False)

    init_ringbuffers()                      # this is required BEFORE we raise any alarms...

    navigator.set_buffer("events", event_ring.buffer)
    navigator.set_buffer("switch", switch_ring.buffer)
    navigator.set_buffer("kpa",    kpa_ring.buffer)
    navigator.set_buffer("errors", error_ring.buffer)

    navigator.set_program_list(program_list)
    #  Note: filelist is set in show_dir

    free_space_KB = free_space()
    if free_space_KB < FREE_SPACE_LOWATER:
        raiseAlarm("Free space", free_space_KB)
        error_ring.add(errors.get_description(TankError.NOFREESPACE))                    
        make_more_space()

# ensure we start out right...
    steady_state        = False
    stable_pressure     = False
    now                 = time.time()
    if vbus_sense.value():
        vbus_status     = True
        vbus_on_time    = now 
        report_outage   = True
    else:
        vbus_status     = False         # just in case we start up without main power, ie, running on battery
        vbus_on_time    = now - 60 * 60        # looks like an hour ago
        report_outage   = False

    display_mode        = "pressure"
    program_pending     = False         # no program
    sys_start_time      = now            # must be AFTER we set clock ...
    
    average_kpa         = 0
    hf_kpa_hiwater      = 0              # this is in effect a count of seconds(samples) since the borepump was turned ON, modulo the size of the ring buffer
    baseline_set        = False
    baseline_pressure   = 0
    zone                = "???"
    zone_minimum        = 0
    zone_maximum        = 0
    zone_max_drop       = 15            # check after more tests
    last_ON_time        = 0
    ut_short            = ""
    ut_long             = ""
    startup_raw_ADC, startup_calibrated_pressure = get_pressure()
    kpa_sensor_found = startup_raw_ADC > BP_SENSOR_MIN    # are we seeing a valid pressure sensor reading?
    change_logging(True)
    if not kpa_sensor_found:
        lcd4x20.move_to(0, 3)
        lcd4x20.putstr(f'NO PS: kPa:{startup_calibrated_pressure:2}')
        print(f'{PS_ND} {startup_calibrated_pressure=}')
        ev_log.write(f"{now_time_long()}  {PS_ND} initial:{startup_calibrated_pressure:3} - HF kPa logging disabled\n")
        change_logging(False)
    else:
        print(f"Pressure sensor detected - {startup_raw_ADC=} {startup_calibrated_pressure=}")
        ev_log.write(f"{now_time_long()} Pressure sensor detected - logging enabled\n")

    enable_controls()               # enable rotary encoder, LCD B/L button etc
    ONESECBLINK         = 850          # 1 second blink time for LED
    lcd_timer           = None

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
        sleep_ms(400)           # what is appropriate sleep time?
        solenoid.value(1)       # High to close

def confirm_and_switch_solenoid(state):
#  NOTE: solenoid relay is reverse logic... LOW is ON
    global borepump
    str_valve = "Turning valve "
    if state:
        if DEBUGLVL > 0: print(str_valve + "ON")
        switch_valve(borepump.state)
    else:
        if borepump.state:          # not good to turn valve off while pump is ON !!!
            raiseAlarm("Solenoid OFF Invalid - Pump is ", borepump.state )
            error_ring.add(errors.get_description(TankError.NOVALVEOFFWHILEON))            
        else:
            if DEBUGLVL > 0: print(str_valve + "OFF")
            switch_valve(False)

def free_space()->int:
    # Get the filesystem stats
    stats = uos.statvfs('/')
    
    # Calculate free space
    block_size = stats[0]
    total_blocks = stats[2]
    free_blocks = stats[3]

    # Free space in bytes
    free_space_kb = free_blocks * block_size / 1024
    return free_space_kb

def do_enter_process():
    lcd_on()                        # but set no OFF timer...stay on until I exit menu 
    # navmode = navigator.mode

    if ui_mode == UI_MODE_MENU:
        navmode = navigator.mode
        if navmode == "menu":
            navigator.enter()
        elif navmode == "value_change":
            navigator.set()
        elif "view" in navmode:        # careful... if more modes are added, ensure they contain "view"
            navigator.go_back()
        elif navmode == "wait":         # added to provide compatibility with 5-way switch
            navigator.go_back()
    elif ui_mode == UI_MODE_NORM:
        # print("in do_enter_process: Entering MENU mode")
        Change_Mode(UI_MODE_MENU)
        # ui_mode = UI_MODE_MENU
        navigator.go_to_start()
        navigator.display_current_item()
    else:
        print(f'Huh? {ui_mode=}')

    # if ui_mode == UI_MODE_NORM:
    #     Change_Mode(UI_MODE_MENU)

# def sim_pressure_pump_detect(x)->bool:            # to be hacked when I connect the CT circuit
#     p = random.random()

#     return True if p > x else False

def sim_detect()->bool:
    return True

# endregion
# region ASYNCIO defs
async def monitor_vbus()->None:
    global vbus_on_time, report_outage, vbus_status
    str_lost = "VBUS LOST"
    str_restored = "VBUS RESTORED"

    while True:
        if vbus_sense.value():
            if not vbus_status:     # power has turned on since last test
                now = time.time()
                vbus_on_time = now
                report_outage = True
                s = f"{now_time_long()}  {str_restored}\n"
                print(s)
                event_ring.add(str_restored)
                ev_log.write(s)
                lcd.setCursor(0,1)
                lcd.printout(str_restored)
                vbus_status = True
        else:
            if report_outage:
                s = f"{now_time_long()}  {str_lost}\n"
                print(s)
                event_ring.add(str_lost)
                ev_log.write(s)
                lcd.setCursor(0,1)
                lcd.printout(str_lost)
                vbus_status = False
                report_outage = False

            now = time.time()
            if (now - vbus_on_time >= MAX_OUTAGE) and report_outage:
                s = f"{now_time_long()}  Power off more than {MAX_OUTAGE} seconds\n"
                print(s)
                ev_log.write(s)  # seconds since last saw power 
                event_ring.add("MAX_OUTAGE")
                report_outage = True
                # housekeeping(False)
        await asyncio.sleep(1)

async def read_pressure()->None:
    """
    Read the pressure sensor and update the hi_freq_kpa ring buffer.
    This function runs in a loop, reading the pressure sensor at hi frequency intervals.

    Also, rapid check for excess pressure... if so, turn off pump and solenoid.
    """
    global hi_freq_kpa_ring, hi_freq_kpa_index, hf_kpa_hiwater, kpa_peak, time_peak, kpa_low

    try:
        while True:
            if SIMULATE_KPA:
                bpp = random.randint(100, 600)
            else:
                raw_val, bpp = get_pressure()
            # print(f"Press: {bpp:>3} kPa, {hi_freq_kpa_index=}")
            if bpp > kpa_peak:
                kpa_peak = bpp       # record peak value.  Will be rest on borepump_ON, and fixed in set_baseline
                time_peak = time.time()
            if bpp < kpa_low:
                kpa_low = bpp
            hi_freq_kpa_ring[hi_freq_kpa_index] = bpp
            hi_freq_avg = calc_average_HFpressure(0, HI_FREQ_AVG_COUNT)           # short average count... last few readings
            hi_freq_kpa_index = (hi_freq_kpa_index + 1) % HI_FREQ_RINGSIZE
            if hi_freq_kpa_index > hf_kpa_hiwater:
                hf_kpa_hiwater = hi_freq_kpa_index       # for testing if calc average is valid
            # p_str = f'Raw:{raw_val:>5}'
            # lcd4x20.move_to(0, 0)                # move to third line of LCD
            # lcd4x20.putstr(p_str)
            lcd4x20.move_to(17, 3)
            lcd4x20.putstr(f"{bpp:>3}")
            if config_dict[LOGHFDATA] > 1:      # conditionally, write to logfile... but note I ALWAYS add to the ring buffer
                                            # This gets switched On/OFF depending on pump state... but NOTE: buffer updates happen ALWAYS!
                hf_log.write(f"{now_time_long()} {bpp:>3} {hi_freq_avg}\n")
            if ui_mode == UI_MODE_NORM:
                if op_mode ==  OP_MODE_AUTO: 
                    if display_mode == "pressure":
                        str = f'{int(hi_freq_avg):3} {zone}'
                        lcd.setCursor(9, 1)
                        lcd.printout(str)

            if hi_freq_avg > config_dict[MAXPRESSURE]:
                raiseAlarm("Excess H/F kPa", hi_freq_avg)
                error_ring.add(errors.get_description(TankError.EXCESS_KPA))                        
                borepump_OFF()
                solenoid.value(1)

            await asyncio.sleep_ms(PRESSURE_PERIOD_MS)

    except Exception as e:
        print(f"read_pressure exception: {e}, {kpaindex=}")

async def regular_flush(flush_seconds)->None:
    while True:
        tank_log.flush()
        pp_log.flush()
        ev_log.flush()
        hf_log.flush()
        await asyncio.sleep(flush_seconds)

async def send_file_list(to: str, subj: str, filenames: list):
    # print(f"Sending files {filenames}...")
    chunk_size = 3 * 170  # Read file in 1K byte chunks... but MUST be a multiple of 3 for base64 encoding

    t0 = time.ticks_ms()

        # Create MIME message
    hdrmsg = (
        f"From: {FROM_EMAIL}\r\n" +
        f"To: {to}\r\n" +
        f"Subject: {subj}\r\n" +
        "MIME-Version: 1.0\r\n" +
        "Content-Type: multipart/mixed; boundary=BOUNDARY\r\n" +
        "\r\n" +
        "--BOUNDARY\r\n" +
        "Content-Type: text/plain\r\n" +
        "\r\n" +
        "Please find attached files.\r\n" +
        "\r\n"
    )
    #hdrmsg = ('Some text to be sent as the body of the email\n')

    t1 = time.ticks_ms()
    smtp=umail.SMTP(SMTP_SERVER, SMTP_PORT, ssl=True)
    t2 = time.ticks_ms()
    # print("SMTP connection created")
    c, r = smtp.login(FROM_EMAIL, FROM_PASSWORD)
    t3 = time.ticks_ms()
    # print(f"After SMTP Login {c=} {r=}")
    smtp.to(TO_EMAIL)
    smtp.write(hdrmsg)  # Write headers and message part
    
    t4 = time.ticks_ms()
    # print("SMTP Headers written")
    await asyncio.sleep_ms(sleepms)

    total_chunks = 0

    # Process each file
    for filename in filenames:
        # Add attachment headers for this file
        print(f'Sending {filename}')
        attachment_header = (
            "--BOUNDARY\r\n" +
            f"Content-Type: text/plain; name=\"{filename}\"\r\n" +
            "Content-Transfer-Encoding: base64\r\n" +
            f"Content-Disposition: attachment; filename=\"{filename}\"\r\n" +
            "\r\n"
        )
        smtp.write(attachment_header)

        # freemem = gc.mem_free()
        # size = uos.stat(filename)[6]
        # print(f"Processing {filename}, free mem = {freemem}, size = {size}")

# Process file in chunks
        # chunks = 0
        with open(filename, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                # Encode chunk
                encoded = b64(chunk)
                
                # Split encoded data into 76-char lines
                for i in range(0, len(encoded), 76):
                    line = encoded[i:i+76]
                    smtp.write(line.decode() + '\r\n')
                    total_chunks += 1
                    if total_chunks % linegrp == 0:
                        print(".", end="")
                        await asyncio.sleep_ms(sleepms)
                
                # Free up memory
                del chunk
                del encoded
                # f.close()    do NOT do this... not needed in with context, and actually breaks things
                gc.collect()

        smtp.write('\r\n')  # Add separation between attachments

    # print(f"\r\nAfter reading files, free mem = {gc.mem_free()}")
    # End the MIME message
    smtp.write("\r\n--BOUNDARY--\r\n")

    t5 = time.ticks_ms()
    # f.close()
    # print(f"\r\nSMTP Files written in {total_chunks} chunks ")
    await asyncio.sleep_ms(sleepms)

    smtp.send()
    t6 = time.ticks_ms()
    # print(f"Files sent!")
    # print(f"Times: {t1-t0}, {t2-t1}, {t3-t2}, {t4-t3}, {t5-t4}, {t6-t5}")
    smtp.quit()

async def processemail_queue():
    global email_queue_tail, email_queue_full, email_task_running
    while True:
        if email_task_running:
            await asyncio.sleep_ms(2000)
            continue
            
        # Check if queue has items
        if email_queue_tail != email_queue_head or email_queue_full:
            files = email_queue[email_queue_tail]
            file_list = [files] #files.split(",")
            non_zero_files = [f for f in file_list if uos.stat(f)[6] > 0]   
            # print(f"Processing email queue: {email_queue_tail=} {email_queue_head=} {email_queue_full=} {file_list=} {files=}")
            if len(non_zero_files) > 0:
                print(f'Email queue: {non_zero_files}')
                email_task_running = True
                try:
                    gc.collect()
                    await send_file_list(TO_EMAIL, f"BPM Sending {files}...", non_zero_files)
                    # print(f"Email sent with result code {rc}")
                    lcd.setCursor(0,1)
                    lcd.printout(f"{'Email sent':<16}")

                except Exception as e:
                    print(f"Error email: {e}")
                    lcd.setCursor(0,1)
                    lcd.printout("EMAIL Error   ")
                finally:
                    email_task_running = False
                    
        # Clear slot and advance tail ... do this even if the file was zero-length
            email_queue[email_queue_tail] = ""
            email_queue_tail = (email_queue_tail + 1) % EMAIL_QUEUE_SIZE
            email_queue_full = False
                
        await asyncio.sleep_ms(1000)

async def check_rotary_state(menu_sleep:int)->None:
    global ui_mode, encoder_count, encoder_btn_state, nav_btn_state
    while True:
        async with enc_btn_lock:    # type: ignore

            if encoder_btn_state:               # button pressed
                do_enter_process()
                encoder_btn_state = False
                # DisplayDebug()

        if not DO_NEXT_IN_CB:           # OK... so we need to call next/prev as required here.
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

                # DisplayDebug()  # this updates 4x20 LCD on every rotary change

        await asyncio.sleep_ms(menu_sleep)

async def blinkx2():
    # changed sleeps to awaits to avoid blocking the main loop
    while True:
        led.value(1)
        await asyncio.sleep_ms(50)
        led.value(0)
        await asyncio.sleep_ms(50)
        led.value(1)
        await asyncio.sleep_ms(50)
        led.value(0)
        await asyncio.sleep_ms(BlinkDelay)     # adjust so I get a 1 second blink... or faster in maintenacne mode

async def do_main_loop():
    global ev_log, steady_state, rec_num, housetank, system, op_mode

    # start doing stuff
    buzzer.value(0)			    # turn buzzer off
    alarm.value(0)			    # turn alarm off
    lcd.clear()
    lcd_on()
    #radio.rfm69_reset

    if not system:              # yikes... don't have a SM ??
        if DEBUGLVL > 0:
            print("GAK... no State Machine")
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
    init_logging()          # needs correct time first!
    print(f"Main TX starting {format_secs_long(start_time)} swv:{SW_VERSION}")
    updateClock()				    # get DST-adjusted local time
    
    get_tank_depth()
    init_all()

    _ = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)

    str_msg = "Immediate switch pump "
    housetank.state = tank_is
    print(f"Initial tank state is {housetank.state}")
    if (housetank.state == "Empty" and not borepump.state):           # then we need to start doing somethin... else, we do NOTHING
        print(str_msg + "ON required")
    elif (borepump.state and (housetank.state == "Full" or housetank.state == "Overflow")):     # pump is ON... but...
        print(str_msg + "OFF required")
    else:
        print("No action required")

    # start coroutines..
    asyncio.create_task(blinkx2())                             # visual indicator we are running
    # asyncio.create_task(check_lcd_btn())                       # start up lcd_button widget
    asyncio.create_task(regular_flush(FLUSH_PERIOD))           # flush data every FLUSH_PERIOD minutes
    asyncio.create_task(check_rotary_state(ROTARY_PERIOD_MS))  # check rotary every ROTARY_PERIOD_MS milliseconds
    asyncio.create_task(processemail_queue())                  # check email queue
    asyncio.create_task(monitor_vbus())                        # watch for power every second
    if kpa_sensor_found:
        asyncio.create_task(read_pressure())                   # read pressure every PRESSURE_PERIOD_MS milliseconds    
    
    gc.collect()
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
    # micropython.mem_info()

    rec_num=0
    while True:
        updateClock()			                    # get datetime stuff
        if op_mode != OP_MODE_MAINT:
            updateData()			                # monitor water depth
            if borepump.state and steady_state:     # added SS... otherwise this can be triggered 1 se after pump ON (not good)
                check_for_Baseline_Drift()          # reset baseline pressure if pump is ON
            check_for_critical_states()             # do this regardless of steady_state
            if op_mode == OP_MODE_AUTO:             # changed, do nothing if OP_MODE_DISABLED or IRRIGATE
                # if DEBUGLVL > 0: print(f"in DML, op_mode is {op_mode} controlBP() starting")
                manage_tank_fill()		            # do nothing if in IRRIGATE mode
    #        listen_to_radio()		                # check for badness
            DisplayData()
            DisplayInfo()		                    # info display... one of several views
    # experimental...
            # if op_mode != OP_MODE_IRRIGATE and rec_num % LOG_FREQ == 0:
            if rec_num % LOG_FREQ == 0:           
                LogData()			                # record it
            if steady_state: checkForAnomalies()	# test for weirdness
            rec_num += 1
            if rec_num > DEPTHRINGSIZE and not steady_state: steady_state = True    # just ignore data until ringbuf is fully populated
            delay_ms = config_dict[DELAY] * 1000
            if heartbeat():                         # send heartbeat if ON... not if OFF.  For now, anyway
                delay_ms -= RADIO_PAUSE
            # print(f"{now_time_long()} main loop: {rec_num=}, {op_mode=}, {steady_state=}, {delay_ms=}")
        else:   # we are in OP_MODE_MAINT ... don't do much at all.  Respond to interupts... show stuff on LCD.  Permits examination of buffers etc
            DisplayData()
            DisplayInfo()            
        await asyncio.sleep_ms(delay_ms)

# endregion

def main() -> None:
    global ui_mode
    try:
        # micropython.qstr_info()
        # print('Sending test email ... no files')
        # send_email_msg(TO_EMAIL, "Test email 15", "Almost done...")    
        # print('...sent')

        asyncio.run(do_main_loop())

    except OSError:
        print("OSError... ")
        
    except KeyboardInterrupt:
        ui_mode = UI_MODE_NORM      # no point calling CHaneg... as I turn B/L off straight after anyway...
        lcd_off('')	                # turn off backlight
        lcd4x20.backlight_off()
        lcd4x20.display_off()
        print('\n### Program Interrupted by user')
        if op_mode == OP_MODE_IRRIGATE:
            cancel_program()
    # turn everything OFF
        if borepump is not None:                # in case i bail before this is defined...
            if borepump.state:
                borepump_OFF()

    #    confirm_and_switch_solenoid(False)     #  *** DO NOT DO THIS ***  If live, this will close valve while pump.
    #           to be real sure, don't even test if pump is off... just leave it... for now.

    # tidy up...
        housekeeping(False)
        shutdown()

if __name__ == '__main__':
     main()