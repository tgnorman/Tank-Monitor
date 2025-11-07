# Trev's super dooper Tank/Pump monitoring system

# region IMPORTS
import sys
import time
# import sys
# import micropython
import random
import gc
from secrets import MyWiFi
from utime import sleep, ticks_us, ticks_diff, ticks_ms
import RGB1602
import umail # type: ignore
import uos
import uasyncio as asyncio
import ntptime
import network
from PiicoDev_Unified import sleep_ms
# from PiicoDev_VL53L1X import PiicoDev_VL53L1X
from TN_VL53L1X import TN_PiicoDev_VL53L1X
from PiicoDev_Transceiver import PiicoDev_Transceiver
from PiicoDev_SSD1306 import *
from umachine import Timer, Pin, ADC, soft_reset, I2C
from MenuNavigator import MenuNavigator
from encoder import Encoder
from ubinascii import b2a_base64 as b64
from State_Machine import SimpleDevice
from i2c_lcd import I2cLcd
from Pump import Pump
from Tank import Tank
from TMErrors import TankError
from TimerManager import TimerManager
from stats import linear_regression
from ringbuffer import RingBuffer, DuplicateDetectingBuffer
from utils import now_time_short, now_time_long, format_secs_short, format_secs_long, now_time_tuple
from Pushbutton import Pushbutton

from TM_Protocol import *
# from ringbuf_queue import RingbufQueue

from Radio import My_Radio

# from uasyncio import Event
from queue import Queue
#import aioprof

# endregion

# region INITIALISE
SW_VERSION          = "7/11/25 18:19"      # post-merge of async branch
DEBUGLVL            = 1

# micropython.mem_info()
# gc.collect()

# region MODES
PRODUCTION_MODE     = False         # change to True when no longer in development cycle
CALIBRATE_MODE      = True

OP_MODE_AUTO        = 0
OP_MODE_IRRIGATE    = 1
OP_MODE_MAINT       = 2
OP_MODE_DISABLED    = 9             # experimental ... pumping disabled due to low water level.  Must be > other modes

UI_MODE_NORM        = 0
UI_MODE_MENU        = 1

NUM_DISPLAY_MODES   = 3             # NOT counting MAINT mode!! for more flexible display of info data
INFO_AUTO           = 0             # TODO make this more pythonic... use a list of tuples? Beware -1 for MAINT
INFO_IRRIG          = 1
INFO_DIAG           = 2
INFO_MAINT          = -1            # special case... cannot cycle to here, only set explicitly as required

op_mode             = OP_MODE_AUTO
ui_mode             = UI_MODE_NORM
info_display_mode   = INFO_AUTO     # start somewhere
# endregion
# region DELAYS
# Delay periods
MYDELAY             = 5             # seconds, main loop period
lcd_on_time         = 90            # LCD time seconds
FLUSH_PERIOD        = 7             # seconds ... should avoid clashes with most other processes
DEBOUNCE_ROTARY     = 10            # determined from trial... see test_rotary_irq.py
DEBOUNCE_BUTTON     = 400           # 50 was still registering spurious presses... go real slow.
ROTARY_PERIOD_MS    = 200           # needs to be short... check rotary ISR variables
PRESSURE_PERIOD_MS  = 1000          # ms
SLOW_BLINK          = 850           # ms
FAST_BLINK          = 300           # ms
BlinkDelay          = SLOW_BLINK    # for blinking LED... 1 second, given LED is on for 150ms, off for 850ms
# endregion
# region RINGBUFFS
# Ring buffers
EVENTRINGSIZE       = 30            # max log ringbuffer length
SWITCHRINGSIZE      = 20
KPARINGSIZE         = 20            # size of ring buffer for pressure logging... NOT for calculation of average
ERRORRINGSIZE       = 20            # max error log ringbuffer length
HI_FREQ_RINGSIZE    = 120           # for high frequency pressure logging.  At 1 Hz that's 2 minutes of data
DEPTHRINGSIZE       = 12            # since adding fast_average in critical_states, this no longer is a concern, but is used for ROC SMA calc

# endregion
# region COUNTERS
# Counters... for averaging or event timing
HI_FREQ_AVG_COUNT   = 7             # for high frequency pressure check
ZONE_AVG_COUNT      = 10            # for zone pressure calculation
AVG_KPA_COUNT       = 30
LOOKBACKCOUNT       = 75            # for looking back at pressure history... to see if kPa drop is normal or not
MAX_OUTAGE          = 30            # seconds of no power
ALARMTIME           = 10            # seconds of beep on/off time
STABLE_KPA_COUNT    = 75            # time to allow kPa to settle
FAST_AVG_COUNT      = 3             # for checking critical pressure states
# D_STD_DEV_COUNT     = 10            # standard deviation calcs
P_STD_DEV_COUNT     = 60
ZONE_DELAY          = 60            # seconds to wait before taking zone pressure.  Needs to be large enough to ensure calc_average doesn't crap out
AVG_KPA_DELAY       = AVG_KPA_COUNT + 5   # seconds to wait before taking average pressure, ensures enough values recorded
# endregion
# region PRESSURE
# Pressure related things
stable_pressure     = False         # if not, then don't check for anomalies or critical states
KPA_DROP_DC         = 2.5           # Ratio of OFF/ON time after kPa drop detected
BP_SENSOR_MIN       = 250           # raw ADC read... this will trigger sensor detect logic.  Changed for 12-bit range
VDIV_R1             = 12000         # ohms
VDIV_R2             = 33000
VDIV_Ratio          = VDIV_R2/(VDIV_R1 + VDIV_R2)
MAX_LINE_PRESSURE   = 700           # sort of redundant... now zone-specific. Might keep this as absolute critical value
NO_LINE_PRESSURE    = 8             # tweak this too... applies in ANY pump-on mode
kpa_sensor_found    = True          # set to True if pressure sensor is detected  
avg_kpa_set         = False         # set to True if kpa average is set
kpa_peak            = 0             # track peak pressure for each zone
kpa_low             = 1000
DEPTH_SD_MAX        = 3             # Optimisation: calc SD of residuals after removing linear trend... it matters! Then reduce 5 to about 2!
PRESS_SD_MAX        = 3             # test this too.  Was 3.6 before I changed to calc on residuals... not bare kPa
kPa_sd_multiple     = 3             # 10X so that is 2.5 std devs ... a LOT of wiggle room.  Divide by 10 later...
hf_xvalues          = [i for i in range(HI_FREQ_RINGSIZE)]  # 
dr_xvalues          = [i for i in range(DEPTHRINGSIZE)]
dr_yvalues          = [0 for i in range(DEPTHRINGSIZE)]
# endregion
# region SYSTEM
FREE_SPACE_LOWATER  = 150           # in KB...
FREE_SPACE_HIWATER  = 400
MAX_CONTIN_RUNMINS  = 360           # 3 hours max runtime.  More than this looks like trouble

SIMULATE_PUMP       = False         # debugging aid...replace pump switches with a PRINT
SIMULATE_KPA        = False         # debugging aid...replace pressure sensor with a PRINT

report_max_outage   = True          # do I report next power outage?
sys_start_time      = 0             # for uptime report
my_IP               = None

pump_action_queue   = Queue()       # Queue to hold async on/off requests, processed asynchronously

# endregion
# region LOGGING
# logging stuff...
LOGHFDATA           = True          # log 1 second interval kPa data
LOG_FREQ            = 1
last_logged_depth   = 0
last_logged_kpa     = 0
LOG_MIN_DEPTH_CHANGE_MM  = 5      # reset after test run. to save space... only write to file if significant change in level
LOG_MIN_KPA_CHANGE  = 10            # update after pressure sensor active
level_init          = False 		# to get started
# endregion
# region PHYSICAL_DEVICES
# Pins
#vsys                = ADC(3)                            # one day I'll monitor this for over/under...
temp_sensor         = ADC(4)			                # Internal temperature sensor is connected to ADC channel 4
solenoid            = Pin(2, Pin.OUT, value=0)          # MUST ensure we don't close solenoid on startup... pump may already be running !!!  Note: Low == Open
lcdbtn 	            = Pin(6, Pin.IN, Pin.PULL_UP)		# soon to be replaced with 5X double-click UP
presspmp            = Pin(15, Pin.IN, Pin.PULL_UP)      # prep for pressure pump monitor.  Needs output from opamp circuit
screamer 		    = Pin(16, Pin.OUT)                  # emergency situation !! Needs action taken...
vbus_sense          = Pin('WL_GPIO2', Pin.IN)           # external power monitoring of VBUS
led                 = Pin('LED', Pin.OUT)
bp_pressure         = ADC(0)                            # read line pressure

# add buttons for 5-way nav control
nav_UP 	            = Pin(10, Pin.IN, Pin.PULL_UP)		# UP button
nav_DN 	            = Pin(11, Pin.IN, Pin.PULL_UP)		# DOWN button  
nav_RR              = Pin(12, Pin.IN, Pin.PULL_UP)		# RIGHT button
nav_LL              = Pin(13, Pin.IN, Pin.PULL_UP)		# LEFT button  
nav_OK              = Pin(14, Pin.IN, Pin.PULL_UP)		# SELECT button

# Create pins for encoder lines and the onboard button

enc_btn             = Pin(18, Pin.IN, Pin.PULL_UP)
# enc_a               = Pin(19, Pin.IN)
# enc_b               = Pin(20, Pin.IN)
px                  = Pin(20, Pin.IN)
py                  = Pin(19, Pin.IN)
last_time           = 0

beeper              = Pin(21, Pin.OUT)                  # for audible feedback
infomode            = Pin(27, Pin.IN, Pin.PULL_UP)      # for changing display mode ... replace with 5X double DOWN

TEMP_CONV_FACTOR 	= 3.3 / 65535   # looks like 3.3V / max res of 16-bit ADC ??

# new 2004 LCD...
I2C_ADDR            = 0x27
I2C_NUM_ROWS        = 4
I2C_NUM_COLS        = 20
i2c                 = I2C(0, sda=Pin(8), scl=Pin(9), freq=400000)
lcd4x20             = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)
display             = create_PiicoDev_SSD1306()

# Create PiicoDev sensor objects
distSensor          = TN_PiicoDev_VL53L1X()             # use my custom driver, with extra snibbo's
lcd 		        = RGB1602.RGB1602(16,2)
radio_dev           = PiicoDev_Transceiver()
radio               = My_Radio(radio_dev)
#rtc 		        = PiicoDev_RV3028()                 # Initialise the RTC module, enable charging
housetank           = Tank("Empty")                     # make my tank object

# endregion
# region MISC
errors              = TankError()
timer_mgr           = TimerManager()

wf                  = MyWiFi()

# Configure WiFi SSID and password
SSID                = wf.ssid
PASSWORD            = wf.password

BAR_THICKNESS       = 15            # OLED display bargraph

program_cancelled   = False         # to provide better reporting
DO_NEXT_IN_CB       = True          # this could be a config param... but probably not worth it
TWM_TIMER_NAME      = 'TWM_timer'   # for consistent ref
DISABLE_TIMER_NAME  = 'Disable_timer'
KPA_DROP_TIMER_NAME = "DROP_TIMER"
ZONE_TIMER_NAME     = "ZONE_TIMER"
AVG_KPA_TIMER_NAME  = "AVG_KPA"
TIMERSCALE          = 60            # permits fast speed debugging... normally, set to 60 for "minutes" in timed ops
DEFAULT_CYCLE       = 38            # for timed stuff... might eliminate the default thing...
DEFAULT_DUTY_CYCLE  = 24            # % ON time for irrigation program

clock_adjust_ms     = 0             # will be set later... this just to ensure it is ALWAYS something
# Code Review suggestions to avoid race conditions
depth_lock          = asyncio.Lock()        # TODO Review Lock things
pressure_lock       = asyncio.Lock()
email_queue_lock    = asyncio.Lock()
enc_btn_lock        = asyncio.Lock()

# And now... with T's improved driver... I can set TimeBudget!
TIMEBUDGET_MS       = 300       # note ... scale up to uS B4 calling method
ROISIZE             = 12

VBUS_LOST           = "VBUS LOST"
VBUS_RESTORED       = "VBUS RESTORED"

# Some modes
DM_DEPTH            = 'depth'
DM_PRESSURE         = 'pressure'

sleep_mins          = 60            # how long to sleep with XSHUT

last_activity_time  = 0             # for sleepmode calcs
# endregion
# region Async_Comms
pending_request     = {}            # to track what we are waiting for

depthringindex      = 0             # testing linreg residual SD stuff...

# endregion
# region EMAIL
SMTP_SERVER         = "smtp.gmail.com"
SMTP_PORT           = 465

# Email account credentials
FROM_EMAIL          = wf.fromaddr
FROM_PASSWORD       = wf.gmailAppPassword
TO_EMAIL            = wf.toaddr

# things for async SMTP file processing
SMTPSLEEPMS = 100
SMTPLINEGROUP = 100

EMAIL_QUEUE_SIZE    = 20  # Adjust size as needed
email_queue         = ["" for _ in range(EMAIL_QUEUE_SIZE)]
email_queue_head    = 0
email_queue_tail    = 0
email_queue_full    = False
email_task_running  = False

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
MINDIST_STR         = "MinDist"
MAXDIST_STR         = "MaxDist"
# MINPRESSURE         = "Min Pressure"
MAXPRESSURE         = "Max Pressure"
# MAXDROP             = "Max Drop"
NOPRESSURE          = "No Pressure"
MAXRUNMINS          = "Max RunMins"
KPASTDEVMULT        = "P SD Mult"
SLEEPMODE_MINS      = "Sleep Mins"

config_dict         = {
    DELAY           : MYDELAY,
    MINDIST_STR     : housetank.min_dist,
    MAXDIST_STR     : housetank.max_dist,
    MAXPRESSURE     : MAX_LINE_PRESSURE,
    # MINPRESSURE     : MIN_LINE_PRESSURE,
    # MAXDROP         : MAX_KPA_DROP,
    NOPRESSURE      : NO_LINE_PRESSURE,
    MAXRUNMINS      : MAX_CONTIN_RUNMINS,
    LCD             : lcd_on_time,
    KPASTDEVMULT    : kPa_sd_multiple,
    SLEEPMODE_MINS  : sleep_mins
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
# this dict needed to store individual zone peak pressure. Can't do it in immutable zone_list tuple...
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
program_list = [
              ("Cycle1", {"init" : 0, "run" : 22, "off" : 55}),
              ("Cycle2", {"init" : 0, "run" : 22, "off" : 55}),
              ("Cycle3", {"init" : 0, "run" : 22, "off" : 55}),
              ("Cycle4", {"init" : 1, "run" : 22, "off" : 1})]

# zone_list... zone ID, min, start-up, max pressures, SD multiplier, quadratic eq  a,b,c coefficients, and zone_max_drop
# TODO need to test each zone's starting pressure...from full bore state, and adjust the min/max values accordingly.
# TODO revisit SD multiplier lookups
# Then... when we have no water shortage, run for extended period to get quadratic profile of each zone.
zone_list:list[tuple[str, int, int, int, float, float, float, int, int]] = [
    (P0, 0,   0,   5,    3.0, 2E-5, -0.1021, 0,   0),     # ZERO 
    (P1, 6,   15,  20,   3.0, 2E-5, -0.1021, 2,   0),     # AIR
    (P2, 10,  20,  40,   3.0, 8E-7, -0.0042, 30,  5),     # HT: don't make this min higher... I want to resume from a cancelled cycle, not abort in HT mode
    (P3, 70,  35,  350,  3.5, 1E-5, -0.1021, 340, 20),    # Z45
    (P4, 300, 350, 450,  3.5, 2E-5, -0.1021, 445, 20),    # Z3
    (P5, 350, 420, 580,  3.5, 2E-5, -0.1021, 575, 20),    # Z2
    (P6, 390, 550, 580,  3.5, 2E-5, -0.1021, 585, 20),    # Z1
    (P7, 450, 650, 680,  3.5, 2E-5, -0.1021, 620, 20),    # Z4
    (P8, 600, 700, 800,  3.5, 2E-5, -0.1021, 650, 20)     # XP
]
# endregion
# region TIMED IRRIGATION
def toggle_borepump(x:Timer):
    """
    Toggle borepump ON/OFF, driven by timers created from slist.
    I need to document this logic better... next_ON_cycle_time is used in DisplayData, and at end of program,
    it falls down ... no idea of what to do.  Maybe I can refer to program_end_time??
    """
    global timer_state, op_mode, sl_index, cyclename, ON_cycle_end_time, next_ON_cycle_time, program_pending

    program_pending = False
    x_str = f'{x}'
    period: int = int(int(x_str.split(',')[2].split('=')[1][0:-1]) / 1000)
    milisecs = period
    # secs = int(milisecs / 1000)
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
                borepump_ON("Toggle op")        #turn_on()
            elif timer_state == 2:
                # diff = slist[sl_index + 2] - slist[sl_index]
                # nextcycle_ON_time = now + diff * TIMERSCALE
                # print(f"{now_time_long()}: TOGGLE - turning pump OFF")
                if not borepump.state:      # then it looks like a kpa test paused this cycle
                    print(f"{now_time_long()}: TOGGLE - cycle paused - did we detect pressure drop?")

                borepump_OFF("Toggle op")       #turn_off()
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
            timer_mgr.create_timer(TWM_TIMER_NAME, period=diff*TIMERSCALE*1000, callback=toggle_borepump)

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
                borepump_OFF("Timer END")       # to be sure, to be sure...
                print(f"{now_time_long()} in toggle, at END turning bp OFF.  Should already be OFF...")
        if mem < 60000:
            print("Collecting garbage...")              # moved to AFTER timer created... might avoid the couple seconds discrepancy.  TBC
            gc.collect()
    else:
        if not program_cancelled:       # this can happen on entering DISABLE mode... should now be fixed.  TEST
            print(f'{now_time_long()} in toggle op_mode is {opmode_dict[op_mode]}.  Why are we here?? Program has NOT been cancelled')

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
    global timer_state, op_mode, slist, sl_index, ON_cycle_end_time, num_cycles, program_pending, program_start_time, program_end_time, program_cancelled        # cycle mod 3

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
            program_end_time   = time.time() + total_time * 60
            # twm_timer = Timer(period=slist[0]*TIMERSCALE*1000, mode=Timer.ONE_SHOT, callback=toggle_borepump)
            timer_mgr.create_timer(TWM_TIMER_NAME, period=slist[0]*TIMERSCALE*1000, callback=toggle_borepump)
            print(slist)
            # print(f"{sched_start=}")
            lcd.setCursor(0,1)
            lcd.printout(f"Schd strt {start_hrs}:{start_mins:02}m")
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
def update_config() -> None:
    """Update configuration dictionary from menu working values."""
    
    # Find path to config submenu
    config_path = find_menu_path(new_menu, "Set Config->")
    if not config_path:
        print("Could not find config submenu!")
        return

    # Navigate to config items
    current_menu = new_menu
    for index in config_path:
        current_menu = current_menu[Item_Str][index]
    
    # Check each config item
    config_items = current_menu.get(Item_Str, [])
    update_fill_state = False
    for item in config_items:
        param = item.get(Title_Str)
        if param in config_dict.keys():
            new_working_value = item[Value_Str][Working_Str]
            if new_working_value > 0 and config_dict[param] != new_working_value:
                old_value = config_dict[param]
                config_dict[param] = new_working_value
                if param in (MINDIST_STR, MAXDIST_STR):
                    update_fill_state = True
                lcd.clear()
                lcd.setCursor(0,0)
                lcd.printout(f'Updated {param}')
                lcd.setCursor(0,1)
                lcd.printout(f'to {new_working_value}')
                ev_log.write(f"{now_time_long()} Updated {param} to {new_working_value}\n")
                print(f"in update_config {param}: dict was {old_value} is now {new_working_value}")
    if update_fill_state:
        get_tank_depth()

def update_timer_params() -> None:
    """Update timer dictionary from menu working values."""
    
    # Find path to timer submenu
    timer_path = find_menu_path(new_menu, "Set Timers->")
    if not timer_path:
        print("Could not find timer submenu!")
        return

    # Navigate to timer items
    current_menu = new_menu
    for index in timer_path:
        current_menu = current_menu[Item_Str][index]
    
    # Check each timer item
    timer_items = current_menu.get(Item_Str, [])
    for item in timer_items:
        param = item.get(Title_Str)
        if param in timer_dict.keys():
            new_working_value = item[Value_Str][Working_Str]
            if new_working_value > 0 and timer_dict[param] != new_working_value:
                timer_dict[param] = new_working_value
                lcd.clear()
                lcd.setCursor(0,0)
                lcd.printout('Updated param')
                lcd.setCursor(0,1)
                lcd.printout(f'{param}: {new_working_value}')

def update_program_list_from_menu() -> None:
    """Update program list from menu working values and apply duty cycle."""
    
    # Find path to timer submenu
    timer_path = find_menu_path(new_menu, "Set Timers->")
    if not timer_path:
        print("Could not find timer submenu!")
        return

    # First, update timer_dict
    update_timer_params()

    dc = timer_dict["Duty Cycle"]
    adjusted_dc = max(min(dc, 95), 5)  # NORMALISE TO RANGE 5 - 95
    
    # Navigate to timer items
    current_menu = new_menu
    for index in timer_path:
        current_menu = current_menu[Item_Str][index]
    
    timer_items = current_menu.get(Item_Str, [])

    i = 0  # find first Cycle in menu.  Assumption: Title looks like "Cycle[N]"
    while not timer_items[i][Title_Str].startswith("Cycle"):
        i += 1

    for s in program_list:
        cycle_name = s[0]
        if i < len(timer_items):  # Protect against index out of range
            menu_item = timer_items[i]
            if cycle_name == menu_item[Title_Str]:
                on_time = menu_item[Value_Str][Working_Str]
                off_time = int(on_time * (100/adjusted_dc - 1))
                s[1]["run"] = on_time
                s[1]["off"] = off_time
            else:
                print(f"Found {menu_item[Title_Str]}, expecting {cycle_name}")
        i += 1

    # Set start delay and fix last cycle
    program_list[0][1]["init"] = timer_dict["Start Delay"]
    program_list[-1][1]["off"] = 1  # reset last cycle OFF time to 1

    # navigator.set_program_list(program_list)
    lcd.setCursor(0,1)
    lcd.printout("program updated")

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
        lcd_timer.deinit()
    lcd_timer = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)    # type: ignore

def cancel_program()->None:
    global program_pending, op_mode, program_cancelled

    program_pending = False
    program_cancelled = True
    op_mode = OP_MODE_AUTO

    try:
        # if twm_timer is not None:        # this is not enough... need to catch the case where my_timer is not defined, so need try/except
        #     twm_timer.deinit()
        #     print("Timer CANCELLED")
        if timer_mgr.is_pending(TWM_TIMER_NAME):
            timer_mgr.cancel_timer(TWM_TIMER_NAME)
            print(f'Timer {TWM_TIMER_NAME} cancelled in cancel_program')

        if borepump.state:
            borepump_OFF("Timer CANCEL")

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

    display_mode = DM_DEPTH
    print(f'{display_mode=}')
    lcd.setCursor(0,1)
    lcd.printout(f'{"Display depth":<16}')

def display_pressure():
    global display_mode

    display_mode = DM_PRESSURE
    print(f'{display_mode=}')
    lcd.setCursor(0,1)
    lcd.printout(f'{"Display kPa":<16}')

def my_go_back():
    # print(f'in my_go_bacK, len(nav.c_l): {len(navigator.current_level)}')
    navigator.go_back()
               
def show_program():
    navigator.mode = navigator.VIEWPROG           # not to be confused with list "program"
               
def show_events():
    if event_ring.index > -1:
        navigator.set_display_list(MenuNavigator.EVENTRING)
        navigator.mode           = MenuNavigator.VIEWRING
        navigator.goto_first()
    else:
        lcd.setCursor(0,1)
        lcd.printout("No events")

def show_switch():
    if switch_ring.index > -1:
        navigator.set_display_list(MenuNavigator.SWITCHRING)
        navigator.mode           = MenuNavigator.VIEWRING
        navigator.goto_first()
    else:
        lcd.setCursor(0,1)
        lcd.printout("No switches")

def show_errors():
    if error_ring.index > -1:
        navigator.set_display_list(MenuNavigator.ERRORRING)
        navigator.mode           = MenuNavigator.VIEWRING
        navigator.goto_first()
    else:
        lcd.setCursor(0,1)
        lcd.printout("No errors")

def show_pressure():
    if kpa_ring.index > -1:
        navigator.set_display_list(MenuNavigator.KPARING)
        navigator.mode           = MenuNavigator.VIEWRING
        navigator.goto_first()
    else:
        lcd.setCursor(0,1)
        lcd.printout("No kPa's")        

def show_depth():
    if depth_ring.index > -1:
        navigator.set_display_list(MenuNavigator.DEPTHRING)
        navigator.mode           = MenuNavigator.VIEWRING
        navigator.goto_first()
    else:
        lcd.setCursor(0,1)
        lcd.printout("No depth vals")

def show_space():
    lcd.setCursor(0,1)
    lcd.printout(f'Free KB: {free_space():<6}')

def my_reset():
    ev_log.write(f"{now_time_long()} SOFT RESET\n")
    lcd.setCursor(0,1)
    lcd.printout("Please wait...")
    shutdown()
    sleep(FLUSH_PERIOD + 1)
    beepx3()
    lcd.setCursor(0,1)
    lcd.printout("Reset in 10 secs")
    sleep(10)
    lcd.setRGB(0,0,0)
    lcd4x20.display_off()
    lcd4x20.backlight_off()
    display.poweroff()

    soft_reset()

def cancel_alarm()->None:
    ev_log.write(f"{now_time_long()} ALARM CANCELLED!\n")
    screamer.value(0)

def beepx3()->None:
    beeper.value(1)
    sleep_ms(100)
    beeper.value(0)
    sleep_ms(100)
    beeper.value(1)
    sleep_ms(100)
    beeper.value(0)
    sleep_ms(100)
    beeper.value(1)
    sleep_ms(100)
    beeper.value(0)

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
    start_time = ticks_us()
    tank_log.flush()
    ev_log.flush()
    pp_log.flush()
    hf_log.flush()
    end_time = ticks_us()
    if close_files:
        tank_log.close()
        ev_log.close()
        pp_log.close()
        hf_log.close()
    print(f"Cleanup completed in {int(ticks_diff(end_time, start_time) / 1000)} ms")

def shutdown()->None:
    if op_mode == OP_MODE_IRRIGATE:
        cancel_program()
    if borepump is not None:                # in case i bail before this is defined...
        if borepump.state:                  # to be sure...
            borepump_OFF("System SHUTDOWN")
    ev_log.write(f"{now_time_long()} STOP Monitor\n")
    if borepump is not None:
        if borepump.num_switch_events > 0:
            dump_pump_arg(borepump)
    if presspump is not None:
        if presspump.num_switch_events > 0:
            dump_pump_arg(presspump)

# Stop anything new starting...
    ev_log.write(f"{now_time_long()} Cancelling all timers...\n")
    timer_mgr.cancel_all()

    dump_zone_peak()

    if event_ring.index > -1:
        ev_log.write("\nevent_ring dump:\n")
        event_ring.dump()
    if switch_ring.index > -1:
        ev_log.write("\nSwitch activity:\n")
        switch_ring.dump()
    if error_ring.index > -1:
        ev_log.write("\nerror_ring dump:\n")
        error_ring.dump()

    tank_log.flush()
    tank_log.close()
    ev_log.flush()
    ev_log.close()
    pp_log.flush()
    pp_log.close()
    hf_log.flush()
    hf_log.close()

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
    navigator.mode = navigator.VIEWFILES
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

def sync_programlist_to_menu()->None:
    # First remove all existing timer menu items with title "cycle[n]

    # Find path to timer submenu
    timer_path = find_menu_path(new_menu, "Set Timers->")
    if not timer_path:
        print("Could not find timer submenu!")
        return

    # Navigate to timer items
    current_menu = new_menu
    for index in timer_path:
        current_menu = current_menu[Item_Str][index]
    
    timer_items = current_menu.get(Item_Str, [])
    for item in timer_items[:]:                 # iterate over a shallow copy
        if item[Title_Str].startswith("Cycle"):
            timer_items.remove(item)
    
    # Then, create menu items for all programs in program_list

# Find the index of "Duty Cycle"
    duty_cycle_index = next(
        (i for i, item in enumerate(timer_items) if item.get('title', '').startswith("Duty Cycle"))
        )
  
    # Insert each new cycle after "Duty Cycle"
    insert_pos = duty_cycle_index + 1
    for prog in program_list:
        cycle_name = prog[0]
        run_time = prog[1]["run"]
        new_menu_item = {
            Title_Str: cycle_name,
            Value_Str: {Default_Str: 1, Working_Str: run_time, Step_Str: 5}
        }
        timer_items.insert(insert_pos, new_menu_item)
        insert_pos += 1  # So cycles are inserted in order

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

    # update program list.. later, update menu.  Until I resolve the duplication
    program_list.insert(last_cycle_pos + 1, new_tuple)
    lcd.setCursor(0,1)
    lcd.printout(f'{new_cycle_name} added')
    # print("Now... try to update the menu itself!!")
    sub_menu_list: list = navigator.current_level[-1]['submenu'][Item_Str]          # this is a stack... get last entry
    # print(f'{navigator.current_index=}')
    # print(f'{sub_menu_list}')
    # print(f'sub_menu_list is type {type(sub_menu_list)}')
    old_menu_item:dict = sub_menu_list[navigator.current_menuindex - 1]     # YUK WARNING: bad dependency here !!!
    new_menu_item = old_menu_item.copy()
    new_menu_value: dict = old_menu_item[Value_Str].copy()
    new_menu_item[Title_Str] = new_cycle_name
    new_menu_item[Value_Str] = new_menu_value                             # be very careful to NOT use ref to old dict
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
        sub_menu_list: list = navigator.current_level[-1]['submenu'][Item_Str]         # this is a stack... get last entry
        # print(f'{navigator.current_index=}')
        # print(f'{sub_menu_list}')
        # print(f'sub_menu_list is type {type(sub_menu_list)}')
        # new_menu_item = sub_menu_list[navigator.current_index - 2]
        # new_menu_item[Title_Str] = new_cycle_name
        # print(f'{new_menu_item=}')
        if "Cycle" in sub_menu_list[navigator.current_menuindex - 2][Title_Str]:
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

def secs_to_DHMS(t:int)->tuple:
    D = int(t / (60*60*24))
    H = int(t % (60*60*24) / (60*60))
    M = int(t % (60*60) / 60)
    S = int(t % 60)
    return D, H, M, S

def calc_uptime()-> None:
    global ut_long, ut_short

    uptimesecs = time.time() - sys_start_time
    # days  = int(uptimesecs / (60*60*24))
    # hours = int(uptimesecs % (60*60*24) / (60*60))
    # mins  = int(uptimesecs % (60*60) / 60)
    # secs  = int(uptimesecs % 60)
    days, hours, mins, secs = secs_to_DHMS(uptimesecs)
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
    lcd.printout(f'{SW_VERSION}')

def show_IP()-> None:
    lcd.setCursor(0,1)
    lcd.printout(f'{my_IP}')

def make_more_space()->None:

    hitList: list[tuple] = []
    device_files = uos.listdir()
    tank_files = [x for x in device_files if x.endswith('.txt') and (x.startswith('tank') or x.startswith('HF') or x.startswith('pres ') or x.startswith('BPEV'))]
    for f in tank_files:
        ftuple = uos.stat(f)
        kb = int(ftuple[6] / 1024)
        ts = ftuple[7]
        tstr = format_secs_long(int(ts))
        file_entry = tuple((f, kb, ts, tstr))
        hitList.append(file_entry)

    sorted_by_date = sorted(hitList, key=lambda x: x[2])
    print(f"Files by date:\n{sorted_by_date}")
    starting_free = free_space()
    if starting_free < FREE_SPACE_LOWATER:
        count = 0
        ev_log.write(f"{now_time_long()} Deleting files\n")
        while len(sorted_by_date) > 0 and free_space() < FREE_SPACE_HIWATER:
            datafile = sorted_by_date[0][0]
            print(f"removing file {datafile}")
            try:
                uos.remove(datafile)
                ev_log.write(f"{now_time_long()} Removed file {datafile} size {sorted_by_date[0][1]} Kb\n")
                count += 1
            except Exception as e:
                print(f'Dang... {e}')   # probably looking at current/open file... just move on
            sorted_by_date.pop(0)

        ending_free = free_space()
        reclaimed = ending_free - starting_free
        print(f"After cleanup: {ending_free} Kb")
        ev_log.write(f"{now_time_long()} free space {ending_free} kb.  Reclaimed {reclaimed} Kb in {count} files\n")
        lcd.setCursor(0, 1)
        lcd.printout(f'Saved {reclaimed} Kb')

def enter_maint_mode_reason(reason:str)->None:
    global op_mode, info_display_mode, BlinkDelay, maint_mode_time

    event_ring.add(f"Enter MAINT mode {reason}")
    lcd.clear()
    lcd.setCursor(0,0)
    lcd.printout(now_time_short())
    lcd.setCursor(0,1)
    lcd.printout("MAINTENANCE MODE")
    op_mode           = OP_MODE_MAINT
    info_display_mode = INFO_MAINT
    BlinkDelay        = FAST_BLINK              # fast LED flash to indicate maintenance mode
    maint_mode_time = now_time_long()
    logstr = f'{now_time_long()} Entered MAINT mode - {reason}'
    ev_log.write(logstr + '\n')
    print(logstr)

def enter_maint_mode()->None:
    enter_maint_mode_reason("(via menu)")

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

    add_to_email_queue(eventlogname)
    # add_to_email_queue("borepump_events.txt")
    lcd.setCursor(0, 1)
    lcd.printout(f'{"Log queued":<16}')
    # print(f"Log added to email queue")

def toggle_prod_mode():
    global PRODUCTION_MODE
    PRODUCTION_MODE = not PRODUCTION_MODE
    lcd.setCursor(0, 1)
    lcd.printout(f'PRODMODE  {' ON' if PRODUCTION_MODE else 'OFF'}')

def toggle_calibration_mode():
    global CALIBRATE_MODE
    CALIBRATE_MODE = not CALIBRATE_MODE
    lcd.setCursor(0, 1)
    lcd.printout(f'CALIBMODE {' ON' if CALIBRATE_MODE else 'OFF'}')

def toggle_HFLOGGING():
    global LOGHFDATA
    LOGHFDATA = not LOGHFDATA
    lcd.setCursor(0, 1)
    lcd.printout(f'LOGHFDATA {' ON' if LOGHFDATA else 'OFF'}')

def toggle_click()->None:
    global btn_click
    btn_click = not btn_click

Item_Str    = MenuNavigator.MENU_ITEMS
Title_Str   = MenuNavigator.MENU_TITLE
Value_Str   = MenuNavigator.MENU_VALUE
Action_Str  = MenuNavigator.MENU_ACTION
Step_Str    = MenuNavigator.MENU_STEP
Default_Str = MenuNavigator.MENU_DV
Working_Str = MenuNavigator.MENU_WV

# added new admin menu section...
new_menu = {
    Title_Str: "Main Menu",
    Item_Str: [              # items[0]
      {
        Title_Str: "Display->",         # items[0]
        Item_Str: [
          { Title_Str: "Pressure",      Action_Str: display_pressure},
          { Title_Str: "Depth",         Action_Str: display_depth},
          { Title_Str: "Files",         Action_Str: show_dir},
          { Title_Str: "Space",         Action_Str: show_space},
          { Title_Str: "Uptime",        Action_Str: show_uptime},
          { Title_Str: "IP Addr",       Action_Str: show_IP},
          { Title_Str: "Version",       Action_Str: show_version},
          { Title_Str: "Go Back",       Action_Str: my_go_back}
        ]
      },
      {
        Title_Str: "History->",         # items[1]
        Item_Str: [
          { Title_Str: "Events",        Action_Str: show_events},
          { Title_Str: "Switch",        Action_Str: show_switch},
          { Title_Str: "Pressure",      Action_Str: show_pressure},
          { Title_Str: "Depth",         Action_Str: show_depth},
          { Title_Str: "Errors",        Action_Str: show_errors},
          { Title_Str: "Program",       Action_Str: show_program},
          { Title_Str: "Stats",         Action_Str: show_duty_cycle},
          { Title_Str: "Go Back",       Action_Str: my_go_back}
        ]
      },
      {
        Title_Str: "Actions->",         # items[2]
        Item_Str: [
          { Title_Str: "Timed Water",   Action_Str: start_irrigation_schedule},
          { Title_Str: "Cancel Prog",   Action_Str: cancel_program},
          { Title_Str: "Flush",         Action_Str: flush_data},
          { Title_Str: "Email evlog",   Action_Str: send_log},
          { Title_Str: "Email tank",    Action_Str: send_tank_logs},
          { Title_Str: "Email HFlog",   Action_Str: send_last_HF_data},
          { Title_Str: "CANCEL ALARM",  Action_Str: cancel_alarm},
          { Title_Str: "Go Back",       Action_Str: my_go_back}
        ]
      },
      {
        Title_Str: "Config->",         # items[3]
        Item_Str: [
          { Title_Str: "Set Config->",
            Item_Str: [                  # items[3][0]
                { Title_Str : DELAY,         Value_Str: {Default_Str: 15,   Working_Str : MYDELAY,              Step_Str : 5}},
                { Title_Str : LCD,           Value_Str: {Default_Str: 60,   Working_Str : lcd_on_time,          Step_Str : 2}},
                { Title_Str : MINDIST_STR,   Value_Str: {Default_Str: 400,  Working_Str : housetank.min_dist,   Step_Str : 100}},
                { Title_Str : MAXDIST_STR,   Value_Str: {Default_Str: 1200, Working_Str : housetank.max_dist,   Step_Str : 100}},
                { Title_Str : MAXPRESSURE,   Value_Str: {Default_Str: 700,  Working_Str : MAX_LINE_PRESSURE,    Step_Str : 25}},                
                { Title_Str : NOPRESSURE,    Value_Str: {Default_Str: 15,   Working_Str : NO_LINE_PRESSURE,     Step_Str : 5}},
                { Title_Str : MAXRUNMINS,    Value_Str: {Default_Str: 60,   Working_Str : MAX_CONTIN_RUNMINS,   Step_Str : 10}},
                { Title_Str : KPASTDEVMULT,  Value_Str: {Default_Str: 25,   Working_Str : kPa_sd_multiple,      Step_Str : 1}},
                { Title_Str : SLEEPMODE_MINS,Value_Str: {Default_Str: 60,   Working_Str : sleep_mins,           Step_Str : 15}},
                { Title_Str: "Save config",  Action_Str: update_config},
                { Title_Str: "Go Back",      Action_Str: my_go_back}
            ]
          },
           { Title_Str: "Set Timers->",
            Item_Str: [                  # items[3][1]
                { Title_Str: "Start Delay",     Value_Str: {Default_Str: 5,   Working_Str : 0,                   Step_Str : 15}},
                { Title_Str: "Duty Cycle",      Value_Str: {Default_Str: 50,  Working_Str : DEFAULT_DUTY_CYCLE,  Step_Str : 5}},
                { Title_Str: "Cycle1",          Value_Str: {Default_Str: 1,   Working_Str : DEFAULT_CYCLE,       Step_Str : 5}},
                { Title_Str: "Cycle2",          Value_Str: {Default_Str: 2,   Working_Str : DEFAULT_CYCLE,       Step_Str : 5}},
                { Title_Str: "Cycle3",          Value_Str: {Default_Str: 3,   Working_Str : DEFAULT_CYCLE,       Step_Str : 5}},
                { Title_Str: "Add cycle",       Action_Str: add_cycle},
                { Title_Str: "Delete cycle",    Action_Str: remove_cycle},
                { Title_Str: "Update program",  Action_Str: update_program_list_from_menu},
                { Title_Str: "Go Back",         Action_Str: my_go_back}
            ]
          },
          {
            Title_Str: "Go Back",           Action_Str: my_go_back
          }
        ]
      },
        { Title_Str: "Admin->",
         Item_Str: [
          { Title_Str: "Flush",             Action_Str: flush_data},
          { Title_Str: "Make Space",        Action_Str: make_more_space},
          { Title_Str: "Test Beep",         Action_Str: beepx3},
          { Title_Str: "Toggle Click",      Action_Str: toggle_click},
          { Title_Str: "Toggle HFLOG",      Action_Str: toggle_HFLOGGING},
          { Title_Str: "Toggle PROD",       Action_Str: toggle_prod_mode},
          { Title_Str: "Toggle CALIB",      Action_Str: toggle_calibration_mode},
          { Title_Str: "Enter MAINT",       Action_Str: enter_maint_mode},
          { Title_Str: "Exit  MAINT",       Action_Str: exit_maint_mode},         
          { Title_Str: "Reset",             Action_Str: my_reset},
          { Title_Str: "Go Back",           Action_Str: my_go_back}
         ]
      },
    {
        Title_Str: "Exit", Action_Str: exit_menu
    }
    ]
}

def click()->None:
    beeper.value(1)
    sleep_ms(30)
    beeper.value(0)
    
def encoder_btn_IRQ(pin):
    global enc_btn_last_time, encoder_btn_state

    new_time = ticks_ms()
    if (new_time - enc_btn_last_time) > DEBOUNCE_BUTTON:
        encoder_btn_state = True
        # print("*", end="")
    # else:
    #     print("0", end="")
    enc_btn_last_time = new_time

def infobtn_cb(pin):
    global modebtn_last_time, info_display_mode

    # print("INFO", end="")
    new_time = ticks_ms()
    old_mode = info_display_mode
    if (new_time - modebtn_last_time) > DEBOUNCE_BUTTON:
        new_mode = (info_display_mode + 1) % NUM_DISPLAY_MODES
        if new_mode == INFO_IRRIG :             # TODO Review changes to info mode, maybe do a state diag, B4 it gets out of control
            if op_mode != OP_MODE_IRRIGATE:     # so if NOT in OP_IRRIGATE, just toggle between AUTO and DIAG
                new_mode = INFO_DIAG
        if new_mode != old_mode:
            info_display_mode = new_mode
            lcd4x20.clear()             # start with a blank sheet
            DisplayInfo()
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
        else:
            encoder_count += 1
    elif delta < 0:
        if DO_NEXT_IN_CB:
            navigator.previous()
        else:
            encoder_count -= 1

def enc_press()->None:
    do_enter_process()

def btn_OK()->None:
    if btn_click : click()
    lcd_on()                        # but set no OFF timer...stay on until I exit menu 

    if ui_mode == UI_MODE_MENU:
        navmode = navigator.mode
        if navmode == MenuNavigator.NAVMODE_MENU:
            exit_menu()   
        elif navmode == MenuNavigator.NAVMODE_VALUE:
            navigator.set()
        elif "view" in navmode:
            navigator.go_back()
    elif ui_mode == UI_MODE_NORM:
        Change_Mode(UI_MODE_MENU)
        navigator.go_to_start()
        navigator.display_current_item()
    else:
        print(f'Huh? {ui_mode=}')
    DisplayInfo()

def btn_UP()->None:
    if btn_click : click()
    navmode = navigator.mode
    if navmode == MenuNavigator.NAVMODE_MENU:    
        navigator.go_back()
    elif "view" in navmode:
        navigator.goto_first()
    elif navmode == "value_change":
        navigator.go_back()
    DisplayInfo()

def btn_DN()->None:
    if btn_click : click()
    navmode = navigator.mode
    if navmode == MenuNavigator.NAVMODE_MENU:
        navigator.enter()   # this is the down button   
    elif "view" in navmode:
        # print("--> goto last")
        navigator.goto_last()
    elif navmode == "value_change":
        # print("--> set_default")
        navigator.set_default()
    DisplayInfo()

def btn_LL()->None:
    if btn_click : click()
    navigator.previous()
    DisplayInfo()     # shouldn't be necessary, next/prev don'tchange mode... but might change IDX ???

def btn_RR()->None:
    if btn_click : click()
    navigator.next()
    DisplayInfo()

def nav_up_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("U", end="")

        navigator.go_back()       # this is the up button... ALWAYS goes up a level
        DisplayInfo()
    nav_btn_last_time = new_time

def nav_dn_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("D", end="")
        navmode = navigator.mode
        if navmode == MenuNavigator.NAVMODE_MENU:
            navigator.enter()   # this is the down button   
        elif "view" in navmode:
            # print("--> goto last")
            navigator.goto_last()
        elif navmode == "value_change":
            # print("--> set_default")
            navigator.set_default()
        DisplayInfo()
    nav_btn_last_time = new_time

def nav_OK_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("S", end="")
        if ui_mode == UI_MODE_MENU:
            navmode = navigator.mode
            if navmode == MenuNavigator.NAVMODE_MENU:
                exit_menu()
            elif navmode == "value_change":
                navigator.set()     # this is the select button
            else:
                navigator.goto_first()
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

    new_time = ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("L", end="")
        navigator.previous()    # this is the back button
    DisplayInfo()

    nav_btn_last_time = new_time

def nav_R_cb(pin):
    global nav_btn_state, nav_btn_last_time

    new_time = ticks_ms()
    if (new_time - nav_btn_last_time) > DEBOUNCE_BUTTON:
        nav_btn_state = True
        print("R", end="")
        navigator.next()      # this is the enter button
    DisplayInfo()
    
    nav_btn_last_time = new_time

def enable_controls():
    global enc, pb_OK, pb_UP, pb_DN, pb_LL, pb_RR           # added 18/5/25... encoder stopped working after DROP invoked timer.mgr
#                                                           21/8/25 added pb objects... Peter Hinch stuff
   # Enable the interupt handlers
    presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)
    enc = Encoder(px, py, v=0, div=4, vmin=None, vmax=None, callback=enc_cb)
    # enc_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_a_IRQ)

    lcdbtn.irq(trigger=Pin.IRQ_FALLING, handler=lcdbtn_new)
    infomode.irq(trigger=Pin.IRQ_FALLING, handler=infobtn_cb)

    # enc_btn.irq(trigger=Pin.IRQ_FALLING, handler=encoder_btn_IRQ)
    # move to wider use of PH's great stuff!
    pb_enc = Pushbutton(enc_btn, ())            # type: ignore

    pb_enc.press_func(enc_press, ())            # type: ignore

    # nav_up.irq(trigger=Pin.IRQ_FALLING, handler=nav_up_cb)
    # nav_dn.irq(trigger=Pin.IRQ_FALLING, handler=nav_dn_cb)
    # nav_OK.irq(trigger=Pin.IRQ_FALLING, handler=nav_OK_cb)
    # nav_L.irq(trigger=Pin.IRQ_FALLING, handler=nav_L_cb)
    # nav_R.irq(trigger=Pin.IRQ_FALLING, handler=nav_R_cb)

# create button objects - Peter Hinch style
    pb_OK = Pushbutton(nav_OK, suppress=True)   # type:ignore
    pb_UP = Pushbutton(nav_UP, suppress=True)   # type:ignore
    pb_DN = Pushbutton(nav_DN, suppress=True)   # type:ignore
    pb_LL = Pushbutton(nav_LL, ())              # type:ignore
    pb_RR = Pushbutton(nav_RR, ())              # type:ignore
# and assign normal actions
    pb_OK.release_func(btn_OK, ())              # type: ignore
    pb_UP.release_func(btn_UP, ())              # type: ignore
    pb_DN.release_func(btn_DN, ())              # type: ignore
    pb_LL.press_func(btn_LL, ())                # type: ignore
    pb_RR.press_func(btn_RR, ())                # type: ignore
# and special cases...
    pb_OK.long_func(exit_menu, ())              # type: ignore
    pb_UP.long_func(lcdbtn_new, (None, ))       # type: ignore 
    pb_UP.double_func(lcdbtn_new, (None, ))     # type: ignore
    pb_DN.long_func(infobtn_cb, (None, ))       # type: ignore
    pb_DN.double_func(infobtn_cb, (None, ))     # type: ignore

# endregion
# region LCD
def lcdbtn_new(pin):
    global lcd_timer
# so far, with no debounce logic... really not needed.  If we get a bounce... so what?
    lcd_on()
    if not lcd_timer is None:
        lcd_timer.deinit()
    lcd_timer = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)    # type:ignore

# def lcdbtn_pressed(x):          # my lcd button ISR
#     global lcdbtnflag
#     lcdbtnflag = True
#     sleep_ms(300)

def lcd_off(pin):
    # print(f'in lcd_off {ui_mode=}, called from timer={x}')
    # print("Stack trace:")
    # try:
    #     raise Exception("Trace")
    # except Exception as e:
    #     sys.print_exception(e)      # type: ignore
    if ui_mode != UI_MODE_MENU:
        lcd.setRGB(0,0,0)
        lcd4x20.backlight_off()
        display.poweroff()

def lcd_on():
    if ui_mode == UI_MODE_MENU:
        lcd.setRGB(240, 30, 240)
    else:
        lcd.setRGB(170,170,138)
    lcd4x20.backlight_on()
    display.poweron()

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
def get_zone_from_list(pressure: int):
    """ Get zone, min and max by searching through the zone list for the first zone that exceeds the pressure """  
    i = len(zone_list)
    szl = sorted(zone_list, key=lambda x: x[2], reverse=True)  # Sort by average pressure in descending order
    # print(szl)
    for _, _, avg_pressure, _, _, _, _, _, _ in szl:
        # print(avg_pressure)
        if pressure >= avg_pressure:
            # print(f'{pressure=} is >= {avg_pressure}')
            return zone_list[i-1][0], zone_list[i-1][1], zone_list[i-1][2], zone_list[i-1][3], zone_list[i-1][4], zone_list[i-1][5], zone_list[i-1][6], zone_list[i-1][7], zone_list[i-1][8]
        else:
            # print(f'{pressure=} is <= {avg_pressure}')
            i -= 1
            # print(f'Index {i}')
    return "???", 0, 0, 0, 0, 0, 0, 0, 0  # Return None if no zone found

def init_logging():
    # global year, month, day, shortyear
    global tank_log, ev_log, pp_log, eventlogname, hf_log

    now             = now_time_tuple()      # getcurrent time, convert to local SA time
    year            = now[0]
    month           = now[1]
    day             = now[2]
    shortyear       = str(year)[2:]
    datestr         = f"{shortyear}{month:02}{day:02}"
    tanklogname     = f'tank {datestr}.txt'
    pplogname       = f'pres {datestr}.txt'
    eventlogname    = f'BPEV {datestr}.txt'
    hfkpaname       = f'HF {datestr}.txt'
    try:
        tank_log        = open(tanklogname, "a")
        ev_log          = open(eventlogname, "a")
        pp_log          = open(pplogname, "a")
        hf_log          = open(hfkpaname, "a")
    except Exception as e:
        print(f'Init_logging: file open exception - {e}')
        sys.exit()
    print("All log files opened")

def get_fill_state(d):
    if d > config_dict[MAXDIST_STR]:                                                    # empty
        tmp = housetank.fill_states[len(housetank.fill_states) - 1]
    elif config_dict[MAXDIST_STR] - housetank.delta < d and d <= config_dict[MAXDIST_STR]:            # near empty
        tmp = housetank.fill_states[4]
    elif config_dict[MINDIST_STR] + housetank.delta < d and d <= config_dict[MAXDIST_STR] - housetank.delta:    # part full
        tmp = housetank.fill_states[3]
    elif config_dict[MINDIST_STR] < d and d <= config_dict[MINDIST_STR] + housetank.delta:            # near full
        tmp = housetank.fill_states[2]
    elif housetank.overfull < d and d <= config_dict[MINDIST_STR]:                                # full
        tmp = housetank.fill_states[1]
    elif d <= housetank.overfull:                                                             # overflow
        tmp = housetank.fill_states[0]
    return tmp

def calc_SMA(buff:list)-> float:
    dsum = 0
    n = 0
    for tup in buff:
        dval = tup[1]       # life's different now with ringbuffer...
        if dval > 0:
            dsum += dval
            n += 1
    if n > 0:
        return dsum / n
    else:
        return 0.0
    
def calc_average_HFpressure(offset_back:int, length:int)->float:
    """
    This is a cut-down version of mean_stdev... and should probably be replaced.
    It is also confusing, as it is NOT the same semantics... offset is RELATIVE to hi_freq_kpa_index !!!
    And ringsize is built-in, not a param

    Finally, note it does some checking on mod_index not done elsewhere
    """

    if offset_back + length > HI_FREQ_RINGSIZE:     # then we will wrap back over previously used values
        event_ring.add(f'WARNING: Invalid params {offset_back + length} in calc_average_HFpressure')

    p = 0
    for i in range(length):
        mod_index = (hi_freq_kpa_index - offset_back - i - 1) % HI_FREQ_RINGSIZE  # change to average hi_freq_kpa readings
        p += hi_freq_kpa_ring[mod_index]
    return p/length

def get_tank_depth():
    global tank_is

    d = int(distSensor.read()) - housetank.sensor_offset
    housetank.depth = (housetank.height - d)
    tank_is = get_fill_state(d)

def set_zone(timer: Timer):
    global zone, zone_minimum, zone_maximum, qa, qb, qc, zone_max_drop, kpa_peak, time_peak, kPa_sd_multiple

    if avg_kpa_set:             # only do this if we have a valid average
        zone_pressure = round(calc_average_HFpressure(0, ZONE_AVG_COUNT))  # get average of last several readings.

        new_zone, zone_minimum, _, zone_maximum, zsdm, qa, qb, qc, zone_max_drop  = get_zone_from_list(zone_pressure)
        if new_zone != zone:
            if new_zone in peak_pressure_dict.keys():
                peak_pressure_dict[new_zone] = (time_peak, kpa_peak, time_peak - last_ON_time)     # set in read_pressure
            else:
                error_ring.add(TankError.ZONE_NOTFOUND)
            kPa_sd_multiple = zsdm
            z_str = f"{now_time_long()} Zone changed from {zone} to {new_zone}. Peak Pressure: {kpa_peak} SDM: {kPa_sd_multiple}"
            zone = new_zone
            print(z_str)
            ev_log.write(z_str + "\n")

    else:                       # reset timer for another try
        print("No valid average kPa reading to set zone.")
        ev_log.write(f"{now_time_long()} set_zone: resetting timer for extra 15 seconds\n")
        timer.init(period=15 * 1000, mode=Timer.ONE_SHOT, callback=set_zone)   # type: ignore

def set_average_kpa(timer: Timer):
    global average_kpa, avg_kpa_set

    if read_count_since_ON > AVG_KPA_COUNT:
        tmp = calc_average_HFpressure(0, AVG_KPA_COUNT)  # get average of last AVG_KPA_COUNT readings
        if tmp > 0:
            average_kpa = round(tmp, 2)
            print("set_average_kpa callback: Average kPa set: ", average_kpa)
            avg_kpa_set = True
            kpa_ring.add(average_kpa)         # add to ring buffer for later use
            event_ring.add(f'Avg kpa set: {average_kpa}')
        else:
            print("set_average_kpa: Yikes!! Buffer has data, but average_kpa is 0")
            for i in range(5): print(f"{hi_freq_kpa_ring[hi_freq_kpa_index - i - 1]} ", end=" ")
    else:
        print('set_average_kpa: rcso <= AVG_KPA_COUNT.  Should not happen')
        event_ring.add('set_average_kpa: rcso <= AVG_KPA_COUNT.  Should not happen')
        timer.init(period=15 * 1000, mode=Timer.ONE_SHOT, callback=set_average_kpa)   # type: ignore

def updateData():
    global tank_is
    global depth_str
    global pressure_str
    global average_kpa, zone, avg_kpa_set
    global temp
    global depthringindex

    get_tank_depth()

    # depthringbuf[depthringindex] = housetank.depth; depthringindex = (depthringindex + 1) % DEPTHRINGSIZE
    depth_ring.add(housetank.depth)
    sma_depth = calc_SMA(depth_ring.buffer)            # this calculates average of non-zero values... regardless of how many entries in the ring
    time_factor = config_dict[DELAY] / 60               # dont move this - DELAY may be changed on the fly
    housetank.depth_ROC = int((sma_depth - housetank.last_depth) / time_factor)	# ROC in mm/minute.  Save negatives also...
    if DEBUGLVL > 2: print(f"{sma_depth=} {housetank.last_depth=} {housetank.depth_ROC=}")
    housetank.last_depth = sma_depth				# track ROC since last reading using SMA_DEPTH... NOT raw depth
    depth_str = f"{housetank.depth/1000:.2f}m " + tank_is

    if kpa_sensor_found and read_count_since_ON >= AVG_KPA_COUNT:
        tmp = round(calc_average_HFpressure(0, AVG_KPA_COUNT))  # get average of last AVG_KPA_COUNT readings.
        if tmp > 0:
            average_kpa = tmp
            avg_kpa_set = True
            kpa_ring.add(average_kpa)         # kpa_ring values are ONLY used to view history via menu... no other function
            # print(f"Average kPa set in UpdateData to: {average_kpa}")
        else:
            print("Yikes!! HF_B full, but average_kpa is 0")
            for i in range(5): print(f"{hi_freq_kpa_ring[hi_freq_kpa_index - i - 1]} ", end=" ")

    prev_index = (hi_freq_kpa_index - 1) % HI_FREQ_RINGSIZE     # because hi_freq_kpa_index refers to pos to write next value
    pressure_str = f'P {hi_freq_kpa_ring[prev_index]:>3} Av {int(average_kpa):>3} {zone:3}'
      
    temp = 27 - (temp_sensor.read_u16() * TEMP_CONV_FACTOR - 0.706)/0.001721

def get_pressure():
    adc_val = bp_pressure.read_u16() >> 4
    measured_volts = 3.3 * float(adc_val) / 4095    # 65535
    sensor_volts = measured_volts / VDIV_Ratio
    kpa = max(0, round(sensor_volts * 200 - 100))     # 200 is 800 / delta v, ie 4.5 - 0.5  Changed int to round 13/5/25
    # print(f"ADC value: {adc_val=}")
    return adc_val, kpa
     
def log_switch_error(new_state):
    print(f"!!! log_switch_error  !! {new_state}")
    ev_log.write(f"{now_time_long()} ERROR on switching to state {new_state}\n")
    event_ring.add(f"ERR swtch {new_state}")
    
# def parse_reply(rply):
#     if DEBUGLVL > 1: print(f"in parse arg is {rply}")
#     if isinstance(rply, tuple):			# good...
#         key = rply[0].upper()
#         val = rply[1]
# #        print(f"in parse: key={key}, val={val}")
#         if key == MSG_STATUS_ACK:       # *** THIS IS NO LONGER VALID... Slave no longer returns a tuple... either ACK or NAK.
#             return True, val
#         elif MSG_ERROR in key:
#             resp = key.split(" ")
#             return False, -1
#         else:
#             print(f"Unknown tuple: key {key}, val {val}")
#             return False, -1
#     else:
#         print(f"Expected tuple... didn't get one.  Got {rply}")
#         return False, False

# def transmit_and_pause(msg, delay):
#     if DEBUGLVL > 1: print(f"tx_and_pause: Sending {msg}, sleeping for {delay} ms")
#     radio.device.send(msg)
#     sleep_ms(delay)

def confirm_solenoid():
    solenoid_state = sim_detect()

    if op_mode == OP_MODE_AUTO:
        return solenoid_state
    elif op_mode == OP_MODE_IRRIGATE:
        return not solenoid_state

def radio_time(local_time):
    return local_time + clock_adjust_ms

def reset_state():
    global read_count_since_ON, stable_pressure, avg_kpa_set, kpa_peak, kpa_low

    read_count_since_ON = 0
    stable_pressure = False
    avg_kpa_set = False             # ? Should I also set hf_kpa_index to 0 ??
    kpa_peak = 0
    kpa_low = 1000

def borepump_ON(reason:str):
    global last_ON_time, LOGHFDATA, average_timer, zone_timer

    system.on_event(SimpleDevice.SM_EV_ON_REQ)
    pump_action_queue.put_nowait(('ON', reason))

    # tup = (MSG_REQ_ON, radio_time(time.time()))   # was previosuly counter... now, time

#            print(tup)
    # system.on_event(SimpleDevice.SM_EV_ON_REQ)
    # transmit_and_pause(tup, 2 * RADIO_PAUSE)
    # transmit_and_pause(MSG_REQ_ON, RADIO_PAUSE)
# try implicit CHECK... which should happen in my RX module as state_changed
#            radio.device.send(MSG_CHECK)
#            sleep_ms(RADIO_PAUSE)
    # if radio.device.receive():
    #     rply = radio.device.message
    # #                print(f"radio.device.message (rm): {rm}")
    #     print(f"BPO: received response: rply is {rply}")
    #     # valid_response, new_state = parse_reply(rply)
    #     if rply == MSG_ON_ACK:
    #                print(f"in ctlBP: rply is {valid_response} and {new_state}")
        # if valid_response and new_state > 0:
    # borepump.switch_pump(True)
    # switch_ring.add("PUMP ON")
    # last_ON_time = time.time()          # for easy calculation of runtime to DROP pressure OFF    
    # LOGHFDATA = True
    # # print(f"***********Setting timer for average_kpa at {now_time_long()}")    
    # # print(f"***********Setting timer for avg & set_zone at {now_time_long()}")
    # if kpa_sensor_found:
    #     reset_state()
    #     # timer_mgr.create_timer(name=AVG_KPA_TIMER_NAME, period=AVG_KPA_DELAY * 1000, callback=set_average_kpa)
    #     # timer_mgr.create_timer(name=ZONE_TIMER_NAME, period=ZONE_DELAY * 1000, callback=set_zone)
    #     average_timer = Timer(period=AVG_KPA_DELAY  * 1000, mode=Timer.ONE_SHOT, callback=set_average_kpa)      # type:ignore # start timer to record average after 5 seconds
    #     zone_timer    = Timer(period=ZONE_DELAY * 1000,     mode=Timer.ONE_SHOT, callback=set_zone)      # type:ignore # start timer to record zone after 30 seconds
        
    # ev_log.write(f"{now_time_long()} ON {reason}\n")
    # system.on_event(SimpleDevice.SM_EV_ON_ACK)
        # else:
            # log_switch_error(1)

def borepump_OFF(reason:str):
    global LOGHFDATA

    # if DEBUGLVL>0: print(f'{tank_is=} {borepump.state=}... SM.on_event {SimpleDevice.SM_EV_OFF_REQ}')
    system.on_event(SimpleDevice.SM_EV_OFF_REQ)
    pump_action_queue.put_nowait(('OFF', reason))
#     success, response = await send_command_with_timeout(MSG_REQ_OFF, MSG_OFF_ACK)
#     if success:
#         borepump_OFF("Tank FULL")
#         # borepump.switch_pump(False)
#         # switch_ring.add("PUMP OFF")
#         # LOGHFDATA = False
#         if DEBUGLVL > 1: print("borepump_OFF: Closing valve")
#         solenoid.value(1)
#         if DEBUGLVL>0: print(f'SUCCESS: {tank_is=} {borepump.state=}... SM.on_event {SimpleDevice.SM_EV_OFF_ACK}')
#         system.on_event(SimpleDevice.SM_EV_OFF_ACK)
#     else:
#         ev_log.write(f"{now_time_long()} AUTO_FILL FAIL OFF\n")
# # alt code: log_switch_error(0)                    
#         if DEBUGLVL>0: print(f'FAIL:    {tank_is=} {borepump.state=}... SM.on_event {SimpleDevice.SM_EV_OFF_NAK}')
#         system.on_event(SimpleDevice.SM_EV_OFF_NAK)



#     borepump.switch_pump(False)
#     switch_ring.add("PUMP OFF")
#     LOGHFDATA = False
#     ev_log.write(f"{now_time_long()} OFF {reason}\n")
    # system.on_event(SimpleDevice.SM_EV_OFF_ACK)
               # wait until pump OFF confirmed before closing valve !!!

def manage_tank_fill():
    global tank_is
    if tank_is == housetank.fill_states[0]:		# Overfull
        screamer.value(1)			        # raise alarm
    else:
        screamer.value(0)
    if tank_is == housetank.fill_states[len(housetank.fill_states) - 1]:		# Empty
        if not borepump.state:		# pump is off, we need to switch on
            if op_mode == OP_MODE_AUTO:
                if DEBUGLVL > 1: print("Opening valve b4 ON")
                solenoid.value(0)
            if confirm_solenoid():
                if DEBUGLVL > 1: print("manage_tank_fill: calling borepump_ON")
                borepump_ON("Tank EMPTY")
            else:               # dang... want to turn pump on, but solenoid looks OFF
                raiseAlarm("NOT turning pump on... valve is CLOSED!", tank_is)
                error_ring.add(TankError.VALVE_CLOSED)                
    elif tank_is == housetank.fill_states[0] or tank_is == housetank.fill_states[1]:	# Full or Overfull
#        bore_ctl.value(0)			# switch borepump OFF
        if borepump.state:			# pump is ON... need to turn OFF
            if DEBUGLVL > 0: print("in controlBorePump, switching pump OFF")
            borepump_OFF("Tank FULL")

def dump_zone_peak()->None:
    print("\nZone Peak Pressures:")
    ev_log.write("\nZone Peak Pressures:")
    for z in peak_pressure_dict.keys():
        if peak_pressure_dict[z][1] > 0:
            lstr = f"{format_secs_long(peak_pressure_dict[z][0])}  Zone {z:<3}: peak {peak_pressure_dict[z][1]} kPa {peak_pressure_dict[z][2]:.1f} seconds after ON"
            print(lstr)
            ev_log.write(lstr + "\n")

def raiseAlarm(param, val):

    logstr = f"{now_time_long()} ALARM {param}, value {val:.3g}"
    ev_str = f"ALARM {param}, value {val:.4g}"
    print(logstr)
    ev_log.write(f"{logstr}\n")
    event_ring.add(ev_str)

def cancel_deadtime(timer:Timer)->None:
    global op_mode

    if previous_op_mode < OP_MODE_DISABLED:
        logstr = f'{now_time_long()} Disabled mode cancelled, returning to {opmode_dict[previous_op_mode]}, switching pump back ON'
        ev_log.write(f'{logstr}\n')
        # print(logstr)
        event_ring.add("Disabled mode cancelled")
        op_mode = previous_op_mode
        borepump_ON("Resuming after pause")       # this is really the critical bit !!
        # print(f'{now_time_long()} cancel_deadtime: setting pump_on_event')
        # pump_on_event.set()

def kpadrop_cb(timer:Timer)->None:
    global beeper, op_mode, previous_op_mode, last_ON_time

    # logstr = f'{now_time_long()} kpadrop_cb called'
    # ev_log.write(f'{logstr}\n')

    beeper.value(0)                  # turn off alarm
    
    # if kpa_drop_timer is not None:  # kill this timer
    #     kpa_drop_timer.deinit()
    #     kpa_drop_timer = None
    if timer_mgr.is_pending(KPA_DROP_TIMER_NAME):
        logstr = f'{now_time_long()} Cancelling pending timer {KPA_DROP_TIMER_NAME}'
        ev_log.write(f'{logstr}\n')
        timer_mgr.cancel_timer(KPA_DROP_TIMER_NAME)
        
    # if op_mode == OP_MODE_IRRIGATE: # don't abort... just turn off pump, but let cycle continue
    previous_op_mode = op_mode  # save to restore later
    op_mode = OP_MODE_DISABLED

    borepump_OFF("kPA DROP")              # turn off pump

    last_runsecs = time.time() - last_ON_time
#    recovery_time = int(last_runsecs * (100/timer_dict["Duty Cycle"] - 1))
    recovery_seconds = int(last_runsecs * KPA_DROP_DC)      # simple version for quick test  TODO review recovery_time

    _, recovery_hrs, recovery_mins, recovery_secs = secs_to_DHMS(recovery_seconds)
    recovery_duration = f'{recovery_hrs}:{recovery_mins:02}:{recovery_secs:02}'
    # disable_timer = Timer(period=recovery_time*1000, mode=Timer.ONE_SHOT, callback=cancel_deadtime)

    timer_mgr.create_timer(DISABLE_TIMER_NAME, recovery_seconds * 1000, cancel_deadtime)
    drop_str = f"{now_time_long()} kPa DROP detected in {opmode_dict[previous_op_mode]} zone {zone}- disabling operation for {recovery_duration}"
    ev_log.write(drop_str + "\n")
    print(drop_str)

# now... delay any pending TWM operations    
    if timer_mgr.is_pending(TWM_TIMER_NAME):
        timer_mgr.delay_timer(TWM_TIMER_NAME, recovery_seconds)
        drop_str = f"{now_time_long()} Timer {TWM_TIMER_NAME} delayed for {recovery_duration}"
        ev_log.write(drop_str + "\n")
        print(drop_str)
    # else:
    #     abort_pumping("kPa drop - sucking air?")    # STOP pumping, and enter maintenance mode

def find_menu_path(menu: dict, target_title: str) -> list[int]:
    """Find the path to a menu item by its title.
    Returns a list of indices to reach the target, or empty list if not found."""
    
    def search_menu(menu_item: dict, path: list[int]) -> list[int]:
        if menu_item.get(Title_Str) == target_title:
            return path
        
        items = menu_item.get(Item_Str, [])
        for i, item in enumerate(items):
            new_path = search_menu(item, path + [i])
            if new_path:
                return new_path
        return []

    return search_menu(menu, [])

def find_menu_index(param_name: str) -> int:
    """Find index of a parameter in the config submenu.
    Returns -1 if not found."""
    
    # First find path to "Set Config->" submenu
    config_path = find_menu_path(new_menu, "Set Config->")
    if not config_path:
        print("Could not find config submenu!")
        return -1
        
    # Navigate to config items
    current_menu = new_menu
    for index in config_path:
        current_menu = current_menu[Item_Str][index]
    
    # Search for parameter in config items
    config_items = current_menu.get(Item_Str, [])
    for i, item in enumerate(config_items):
        if item.get(Title_Str) == param_name:
            return i
            
    print(f"Did not find {param_name} in config menu")
    return -1

def make_dr_lists():
    """
    Pull (x,y) values out of depth ring buffer for linear regression, using actual x (time) ordinates
    """
    global dr_xvalues, dr_yvalues
    offset_secs = 1762484000            # translate time axis... or we hit overflow issues

    start = depth_ring.index
    for i in range(DEPTHRINGSIZE):
        modidx = (start - i) % DEPTHRINGSIZE
        d_tup = depth_ring.buffer[modidx]       # get tuple from ring
        dr_xvalues[i] = d_tup[0] - offset_secs  # should be timestamp part of tuple
        dr_yvalues[i] = d_tup[1]                # should be depth 

def quad(a: float, b: float, c: int, x: int) -> int:
    """Calculate the pressure at a given point using a quadratic equation"""
    return int(a * x*x + b * x + c)
    
def checkForAnomalies()->None:
    global borepump, tank_is, average_kpa, stdev_Depth, stdev_Press

    try:
        if borepump.state:                          # pump is ON
            if kpa_sensor_found:        # only check for kPa stuff if we have kPa readings...
                if avg_kpa_set and read_count_since_ON > (LOOKBACKCOUNT + HI_FREQ_AVG_COUNT):   # == HI_FREQ_RINGSIZE - 1: # this ensures we get a valid average kPa reading

        # NOTE: calc_average_HFpressure behaves differently to other stats methods lin_reg and mean_stddev
                    av_p_prior  = calc_average_HFpressure(LOOKBACKCOUNT, HI_FREQ_AVG_COUNT) # get average of readings LOOKBACK seconds ago.
                    av_p_now    = calc_average_HFpressure(0, HI_FREQ_AVG_COUNT)             # zero offset == immediately prior values
                    actual_pressure_drop = round(av_p_prior - av_p_now, 2)     # Important!  Avoid rounding errors.. avg drop of 0.3 on HT triggered alarm without int()!
                    # if isRapidDrop(LOOKBACKCOUNT, expected_drop):   # check for rapid drop... if so, then set alarm and turn off pump
        # NOTE: the startidx param is CRITICAL!!  we need to do LR on the data BEFORE pressure dropped...
                    idx =  (hi_freq_kpa_index - 1 - (LOOKBACKCOUNT - P_STD_DEV_COUNT)) % HI_FREQ_RINGSIZE
                    k_slope, k_intercept, _, prior_stdev_Press, r2 = linear_regression(hf_xvalues, hi_freq_kpa_ring, P_STD_DEV_COUNT, idx, HI_FREQ_RINGSIZE)
                    slope_drop = round(abs(k_slope) * LOOKBACKCOUNT, 2)     # changed from incorrect P_STD_DEV_COUNT 19/7/25
                    SD_drop    = round(prior_stdev_Press * kPa_sd_multiple, 1)
                    max_drop   = slope_drop + SD_drop
                    # max_drop = abs(k_slope * LOOKBACKCOUNT) + stdev_Press * float(config_dict[KPASTDEVMULT])
                    # if actual_pressure_drop > zone_max_drop:     # This needs to be zone-specific - even if I don't use quad
        # TODO remove zone_max_drop from zone dict... assuming linreg thing works out
                    if actual_pressure_drop > max_drop and op_mode != OP_MODE_DISABLED:         # replaced zone=specific const with calculated value from linreg
                        if not timer_mgr.is_pending(KPA_DROP_TIMER_NAME):
                            runtime = time.time() - last_ON_time
                            _, H, M, S = secs_to_DHMS(runtime)
                            run_str = f'{H}:{M:02}:{S:02}'
                            # raiseAlarm(f"Pressure DROP after {runmins}:{runseconds:02}. Expected:{expected_drop}", actual_pressure_drop)
                            raiseAlarm(f"kPa DROP {run_str} after ON  Exceeds max drop:{max_drop:.1f} {k_slope=:.4f} {r2=:.3f} {slope_drop=:.1f} {SD_drop=:.1f}", actual_pressure_drop)
                            error_ring.add(TankError.PRESSUREDROP)
                            beeper.value(1)                              # this might change... to ONLY if not in TWM/IRRIGATE    
                            # kpa_drop_timer = Timer(period=ALARMTIME * 1000, mode=Timer.ONE_SHOT, callback=kpadrop_cb)
                            timer_mgr.create_timer(KPA_DROP_TIMER_NAME, ALARMTIME * 1000, kpadrop_cb)
                # now get the CURRENT stdev_Press... which will go higher on kpadrop, but for alarm purposes, only interested in residual SD
                    _,_, _, stdev_Press, _ = linear_regression(hf_xvalues, hi_freq_kpa_ring, P_STD_DEV_COUNT, hi_freq_kpa_index, HI_FREQ_RINGSIZE)
                    if stdev_Press > PRESS_SD_MAX:      # now ignores trend...
                        raiseAlarm("XS P SDEV", stdev_Press)
                        error_ring.add(TankError.HI_VAR_PRES)

                    # if op_mode == OP_MODE_IRRIGATE and  kpa_sensor_found and average_kpa < zone_minimum:
                    if average_kpa < zone_minimum:   # this could happen in AUTO/HT tank-fill mode also...
                        raiseAlarm("Below Zone Min Pressure", average_kpa)
                        error_ring.add(TankError.BELOW_ZONE_MIN)
                        if PRODUCTION_MODE: abort_pumping("kPa below Zone min")

            if not CALIBRATE_MODE:                              # easy way to prevent pesky alarms while testing
                if tank_is == "Overflow":                       # ideally, refer to a Tank object... but this will work for now
                    raiseAlarm("OVERFLOW - ON", 999)
                    error_ring.add(TankError.OVERFLOW_ON)
                    abort_pumping("OVERFLOW!")                  # requires manual intervention!
                
                if housetank.depth_ROC < - housetank.min_ROC and borepump.state:     # pump is ON but level is falling!
                    raiseAlarm("DRAINING - ON", housetank.depth_ROC)                              
                    error_ring.add(TankError.DRAINWHILE_ON)     # in PROD, this should also trigger ABORT... something seriously wrong
                    if PRODUCTION_MODE: abort_pumping("Draining but ON")

                if abs(housetank.depth_ROC) > housetank.max_ROC:                    # this one is less critical...
                    raiseAlarm("XS ROC", housetank.depth_ROC)
                    error_ring.add(TankError.MAX_ROC_EXCEEDED)

            # changed to get SD of residuals after removing trend... which is significant on normal depth change during tank fill
            if len(depth_ring.buffer) == DEPTHRINGSIZE:
                make_dr_lists()         # pull (x, y) coordinates.  Should now work no matter time distribution of ring_buffer entries
                _,_,_, stdev_Depth, r2 = linear_regression(dr_xvalues, dr_yvalues, DEPTHRINGSIZE, depth_ring.index, DEPTHRINGSIZE)
                if stdev_Depth > DEPTH_SD_MAX:
                    raiseAlarm("XS D SDEV", stdev_Depth)
                    error_ring.add(TankError.HI_VAR_DIST)

        else:                                       # pump is OFF
            if op_mode == OP_MODE_AUTO:
                if housetank.depth_ROC > housetank.min_ROC and not CALIBRATE_MODE:                         # pump is OFF but level is rising!
                    raiseAlarm("FILLING - OFF", housetank.depth_ROC)
                    error_ring.add(TankError.FILLWHILE_OFF)
                    if PRODUCTION_MODE:
                        enter_maint_mode_reason("Filling - OFF")

    except Exception as e:
        ex_str = f'{now_time_long()} checkforanomalies exception: {e}\n'
        ev_log.write(ex_str)
        print(ex_str)
        if depth_ring.index > -1:
            ev_log.write(f"\ndepth_ring dump: {depth_ring.index=}\n")
            depth_ring.dump()
            ev_log.write("\ndr_xvalues:\n")
            for i in dr_xvalues:
                ev_log.write(str(i) + '\n')

def abort_pumping(reason:str)-> None:
    global op_mode, BlinkDelay, info_display_mode, maint_mode_time
# if bad stuff happens, kill off any active timers, switch off, send notification, and enter maintenance state
    if timer_mgr.is_pending(TWM_TIMER_NAME):
        timer_mgr.cancel_timer(TWM_TIMER_NAME)
        print(f'Timer {TWM_TIMER_NAME} cancelled in ABORT')

    if borepump.state:              # pump is ON
        borepump_OFF(f'Abort {reason}')
    logstr = f"{now_time_long()} ABORT invoked! {reason}"
    print(logstr)
    event_ring.add("ABORT!!")
    ev_log.write(logstr + "\n")
    ev_log.flush()

    enter_maint_mode_reason(reason)

def check_for_critical_states() -> None:
    if borepump.state:              # pump is ON

# This test needs to be done more frequently... after calculating high frequency kpa
        if kpa_sensor_found:        # if we have a pressure sensor, check for critical values
            fast_average = calc_average_HFpressure(0, FAST_AVG_COUNT)
            if fast_average > 0:         # if we have a valid average kPa reading... but MUST be delayed until we have a few readings
                if fast_average > config_dict[MAXPRESSURE]:
                    raiseAlarm("XS kPa", fast_average)
                    error_ring.add(TankError.EXCESS_KPA)               
                    abort_pumping("check_for_critical_states: Excess kPa")

                if stable_pressure and fast_average < config_dict[NOPRESSURE]:
                    raiseAlarm(NOPRESSURE, fast_average)
                    error_ring.add(TankError.NO_PRESSURE)
                    abort_pumping("check_for_critical_states: No pressure")

        run_minutes = (time.time() - borepump.last_time_switched) / 60
        if run_minutes > config_dict[MAXRUNMINS]:               # if pump is on, and has been on for more than max... do stuff!
            raiseAlarm("RUNTIME EXCEEDED", run_minutes)
            error_ring.add(TankError.RUNTIME_EXCEEDED)
            # borepump_OFF()
            abort_pumping("XS Runtime")                         # this too warrants manual intervention

def DisplayInfo()->None:

# NOTE: to avoid overlapping content on a line, really need to compose a full line string, then putstr the entire thing :20
#       moving to a field and updating bits doesn't relly work so well... at least not unless ALL modes use consistent field defs...
#
#   More important: Don't leave remnant stuff behind!  That means writing blanks unless there is something to report in the current mode
#   Finally... dealing with 3 separate modes: ui_mode, op_mode, & info_mode.  BEWARE !!!

    now = time.time()
    if   ui_mode == UI_MODE_MENU:
        if   info_display_mode == INFO_AUTO:
            str_0 = f'Lvl: {len(navigator.current_level):>2}'      # Now actually shows menu level.
            lcd4x20.move_to(0, 0)
            lcd4x20.putstr(str_0)
            str_0 = f'Idx: {navigator.current_menuindex:>3}'
            lcd4x20.move_to(12, 0)
            lcd4x20.putstr(str_0)

            str_1 = f'{" ":^20}'
            if navigator.mode == navigator.NAVMODE_VALUE:
                it = navigator.get_current_item()
                par = it[Title_Str]
                st = it[Value_Str][Step_Str]
                wv = it[Value_Str][Working_Str]
                str_1 = f'P:{par[0:4]} S:{st:2} V:{wv:4}'
            lcd4x20.move_to(0, 1)
            lcd4x20.putstr(str_1)

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr(f'NavMod: {navigator.mode:>12}')
    
    elif ui_mode == UI_MODE_NORM:
        # if op_mode   == OP_MODE_AUTO:
        if   info_display_mode == INFO_AUTO:
            e_code = "   "
            rep_count = 0
            if error_ring.index > -1:
                entry  = error_ring.buffer[error_ring.index]
                tmp = entry[1]              # entry is either an int, or a string consisting of an int followed by a repeat count
                if type(tmp) == str:
                    if len(tmp) > 0:
                        er_str = tmp.split(" ")
                        # print(f'{er_str=}')             # should look like [code_str, repeat_string_str]
                        enum_str = er_str[0]
                        # print(f'{enum_str=}')
                        rep_count_str = er_str[2]       # looks like 'x3)' ... slice off 1st and last chars to get count, convert to int 
                        rep_count = int(rep_count_str[1:-1])
                        tmp = int(enum_str)
                    # tmp = int(tmp.split(" ")[0])
                else:
                    tmp=int(tmp)
                e_code = errors.get_code(tmp)
            lcd4x20.move_to(0, 0)                # move to top left corner of LCD
            lcd4x20.putstr(f'EC:{e_code:<4}')

            lcd4x20.move_to(7, 0)
            rstr = f'x{rep_count:<2}' if rep_count > 0 else "   "
            lcd4x20.putstr(rstr)

            lcd4x20.move_to(11, 0)
            lcd4x20.putstr(f"{'S' if stable_pressure else 'U'}P ")

            lcd4x20.move_to(14, 0)
            lcd4x20.putstr(f"HF:{' ON' if LOGHFDATA else 'OFF'}")

            calc_uptime()
            lcd4x20.move_to(0, 1)
            lcd4x20.putstr(f'{ut_short} {calc_pump_runtime(borepump)}')        # runtime calcs

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr(f'D {housetank.depth/1000:<.2f} R{housetank.depth_ROC:>4} SD {stdev_Depth:>4.1f}')

            lcd4x20.move_to(0, 3)
            prev_index = (hi_freq_kpa_index - 1) % HI_FREQ_RINGSIZE
            lcd4x20.putstr(f'ZP {peak_pressure_dict[zone][1]:>3} Av:{average_kpa:>3.0f} IP:{hi_freq_kpa_ring[prev_index]:>3.0f}')
        
        elif info_display_mode == INFO_IRRIG:
        # elif op_mode == OP_MODE_IRRIGATE:
            delay_secs = program_start_time - now
            end_secs   = program_end_time - now
            _, start_hrs, start_mins, start_secs  = secs_to_DHMS(delay_secs)
            _, end_hrs, end_mins, end_secs        = secs_to_DHMS(end_secs)
            if delay_secs <= 0:         # in the past
                start_str = "<-PAST-"
            else:
                start_str = f'{start_hrs}:{start_mins:02}:{start_secs:02}'
            if end_secs <= 0:         # in the past.  This should never happen... if we are past end, shpuld not be in IRRIG
                end_str = "<-PAST-"
            else:
                end_str = f'{end_hrs}:{end_mins:02}:{end_secs:02}'
            lcd4x20.move_to(0, 0)
            lcd4x20.putstr(f'S {start_str} E {end_str}')        

            lcd4x20.move_to(0, 1)
            lcd4x20.putstr('Cycle       Remain')        # I could call time_mgr.get_remaining here... maybe later

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr(f'Z:{zone:<3} Min {zone_minimum:<3} ZP {peak_pressure_dict[zone][1]:<3}')

    # can ONLY transition here from AUTO... no need to update row 3
       
        elif info_display_mode == INFO_DIAG:
        # can ONLY transition here from IRRIG-1... only need to update row 0
            # e_code = ""
            # if error_ring.index > -1:
            #     entry = error_ring.buffer[error_ring.index]
            #     # print(f'{error_ring.index=} {entry=}')
            #     e_code = errors.get_code(entry[1])
            # lcd4x20.move_to(0, 0)                # move to top left corner of LCD
            # lcd4x20.putstr(f'EC:{e_code:<4}')

            # lcd4x20.move_to(8, 0)
            # lcd4x20.putstr(f"S{1 if stable_pressure else 0}")  

            # lcd4x20.move_to(14, 0)
            # lcd4x20.putstr(f"HF:{' ON' if LOGHFDATA else 'OFF'}")

            # lcd4x20.move_to(0, 0)                # move to top left corner of LCD
            ev_len = len(event_ring.buffer)
            er_len = len(error_ring.buffer)
            lcd4x20.move_to(0, 0)
            lcd4x20.putstr(f'EV:{ev_len:2}/{er_len:2} P:{stdev_Press:.1f} D:{stdev_Depth:.1f}')

            remain_str = f'{" ":^8}'
            opm_str = f'{opmode_dict[op_mode]:4}'
            if op_mode == OP_MODE_DISABLED: # show remaining time to pause
                if timer_mgr.is_pending(DISABLE_TIMER_NAME):
                    secs_remaining = timer_mgr.get_time_remaining(DISABLE_TIMER_NAME)
                    _, remain_hrs, remain_mins, remain_secs = secs_to_DHMS(secs_remaining)
                    remain_str = f'{remain_hrs:02}:{remain_mins:02}:{remain_secs:02}'
            lcd4x20.move_to(0, 1)
            lcd4x20.putstr(f'M:{opm_str} R: {remain_str}')

            lcd4x20.move_to(0, 2)
            lcd4x20.putstr(f'R#:{rec_num:>6} C#:{read_count_since_ON:>6}')
        
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
 
    # lcd4x20.move_to(0, 4)                # move to fourth line of LCD
    # lcd4x20.putstr(f'nav mode: {navigator.mode:<10}')        # print navigator.mode in fourth line of LCD

def DisplayData()->None:
    if ui_mode != UI_MODE_MENU:             # suspend overwriting LCD whist in MENU
        lcd.clear()
        lcd.setCursor(0, 0)
        lcd.printout(now_time_short())

# First, determine what to display on LCD 2x16
        if op_mode == OP_MODE_AUTO:
            if display_mode == DM_DEPTH:
                display_str = depth_str
            elif display_mode == DM_PRESSURE:
                display_str = pressure_str
            else:
                display_str = "no Display Mode"
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
                    if secs_to_next_ON < 0:                 # there is no next ON... this is flag to indicate end-of-program
                        secs_to_end = program_end_time - now
                        mins_to_end = 0
                        if secs_to_end > 60:
                            mins_to_end = int(secs_to_end / 60)
                            secs_to_end = secs_to_end % 60
                        display_str = f"TWM end:   {mins_to_end}:{secs_to_end:02}"
                        # display_str = "End TWM soon"
                        # print(f"{format_secs_long(now)}: {secs_to_next_ON=}")
                    else:
                        if secs_to_next_ON < 60:
                            display_str = f"Wait {cycle_number}/{total_cycles} {secs_to_next_ON}s"
                        else:
                            display_str = f"Wait {cycle_number}/{total_cycles} {int(secs_to_next_ON / 60)}m"
            else:
                display_str = "IRRIG MODE...??"
        elif op_mode == OP_MODE_DISABLED:
            if display_mode == DM_DEPTH:
                display_str = depth_str
            elif display_mode == DM_PRESSURE:
                display_str = pressure_str
        elif op_mode == OP_MODE_MAINT:
            display_str = "MAINT MODE"
        else:
            display_str = "OPM INVALID"
        lcd.setCursor(0, 1)
        lcd.printout(f"{display_str:<16}")

def DisplayGraph():
    scaled_bar   = int(housetank.depth * WIDTH / housetank.height)
    # print(f'{scaled_bar=}')
    percent      = int(100 * housetank.depth/housetank.height)
    display.fill(0)
    display.text(f"Depth {housetank.depth/1000:<.2f}M {percent:>2}%", 0, 0, 1)

    # display.updateGraph2D(graphkPa, scaled_press)
    display.fill_rect(0, HEIGHT-BAR_THICKNESS, scaled_bar, BAR_THICKNESS, 1)
    display.show()

def LogData()->None:
    global level_init
    global last_logged_depth
    global last_logged_kpa

# Now, do the print and logging
    tempstr = f"{temp:.2f} C"  
    logstr  = now_time_short() + f" {housetank.depth/1000:.3f} {average_kpa:4}\n"
    dbgstr  = now_time_short() + f" {housetank.depth/1000:.3f}m {average_kpa:4}kPa"    

    enter_log = False
    if not level_init:                  # only start logging after we allow level readings to stabilise
        level_init = True
        last_logged_depth = housetank.depth
    else:
        level_change = abs(housetank.depth - last_logged_depth)
        if level_change > LOG_MIN_DEPTH_CHANGE_MM or CALIBRATE_MODE:
            last_logged_depth = housetank.depth
            enter_log = True
        pressure_change = abs(last_logged_kpa - average_kpa)
        if pressure_change > LOG_MIN_KPA_CHANGE or CALIBRATE_MODE:
            last_logged_kpa = average_kpa
            enter_log = True

        if enter_log: tank_log.write(logstr)
    # tank_log.write(logstr)          # *** REMOVE AFTER kPa TESTING ***
    print(dbgstr)

# def init_radio_nowait():
#     global radio, system
    
#     print("Init radio...")

#     radio.device.off()
#     radio.device.on()       # should clear receive buffers
#     if radio.device.receive():
#         msg = radio.device.message
#         print(f"Read & discarded {msg}.  Should not happen if rcv buffer cleared")
    

# def init_radio()->bool:
#     global radio, system
    
#     print("Init radio...")
#     if radio.device.receive():
#         msg = radio.device.message
#         print(f"Read & discarded {msg}")

#     while not ping_RX():
#         print("Waiting for RX...")
#         sleep(1)

# if we get here, my RX is responding.
    # print("RX responded to ping... comms ready")
    # return True
    # system.on_event(SimpleDevice.SM_EV_RADIO_ACK)

# def ping_RX() -> bool:           # at startup, test if RX is listening
# #    global radio

#     ping_acknowleged = False
#     transmit_and_pause(MSG_PING_REQ, RADIO_PAUSE)
#     if radio.device.receive():                     # depending on time relative to RX Pico, may need to pause more here before testing?
#         msg = radio.device.message
#         if isinstance(msg, str):
#             if msg == MSG_PING_RSP:
#                 ping_acknowleged = True

#     return ping_acknowleged

# def get_initial_pump_state() -> bool:

#     initial_state = False
#     transmit_and_pause(MSG_STATUS_CHK,  RADIO_PAUSE)
#     if radio.device.receive():
#         rply = radio.device.message
#         valid_response, new_state = parse_reply(rply)
#         if valid_response and new_state > 0:
#             initial_state = True
#     return initial_state

def calc_pump_runtime(p:Pump) -> str:
    dc_secs = p.cum_seconds_on
    if p.state:
        dc_secs += (time.time() - p.last_time_switched)
    days, hours, mins, secs = secs_to_DHMS(dc_secs)

    return f'{days}d {hours:02}:{mins:02}:{secs:02}'

def dump_pump_arg(p:Pump):
    global ev_log

# write pump object stats to log file, typically when system is closed/interupted
    ev_log.flush()
    ev_log.write(f"Stats for pump {p.ID}\n")

    days, hours, mins, secs = secs_to_DHMS(p.cum_seconds_on)
    dc: float = p.calc_duty_cycle()
    
    ev_log.write(f"Last switch time:   {format_secs_long(p.last_time_switched)}\n")
    ev_log.write(f"Total switches this period: {p.num_switch_events}\n")
    ev_log.write(f"Cumulative runtime: {days} days {hours} hours {mins} minutes {secs} seconds\n")
    ev_log.write(f"Duty cycle: {dc:.2f}%\n")
    ev_log.flush()

def init_wifi()->bool:
    global my_IP

# Connect to Wi-Fi
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            print(">", end="")
            sleep(1)
    my_ifconfig = wlan.ifconfig()
    my_IP = my_ifconfig[0]
    print(f'Connected to {my_IP}')
    return True
    # system.on_event(SimpleDevice.SM_EV_WIFI_ACK)
   
def set_time():
 # Set time using NTP server
    print("Syncing time with NTP...")
    ntptime.settime()  # This will set the system time to UTC
    print('Time set to ntp time')
    
def init_clock()->bool:

    print("Initialising local clock")
#   if time.localtime()[0] < 2024:  # if we reset, localtime will return 2021...
#        connect_wifi()
    set_time()
    return True
    # system.on_event(SimpleDevice.SM_EV_NTP_ACK)

# def calibrate_clock():
#     global radio

#     delay=500
# #   for i in range(1):
#     p = ticks_ms()
#     s = MSG_CLOCK
#     t=(s, p)
#     transmit_and_pause(t, delay)

def init_ringbuffers():
    global hi_freq_kpa_ring, hi_freq_kpa_index
    global event_ring, error_ring, switch_ring, kpa_ring, depth_ring
    # global depthringbuf, depthringindex     # revert to old style for linreg/residual analysis of SD

    # depthringbuf = [0]                # start with a list containing zero...
    # if DEPTHRINGSIZE > 1:             # expand it as needed...
    #     for _ in range(DEPTHRINGSIZE - 1):
    #         depthringbuf.append(0)
    # if DEBUGLVL > 0: print("Ringbuf is ", depthringbuf)
    # depthringindex = 0

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

    depth_ring = RingBuffer(
        size=DEPTHRINGSIZE, 
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
        value_formatter=lambda t: errors.get_description(t),
        logger=ev_log.write
    )

    # for now, this one is different...
    hi_freq_kpa_ring = [0 for _ in range(HI_FREQ_RINGSIZE)]
    hi_freq_kpa_index = 0

def change_TB(newTB_ms):
    distSensor.stopRanging()
    if not distSensor.setMeasurementTimingBudget(newTB_ms * 1000):      # convert to uSecs
        print("setTB failed!")
    distSensor.startRanging()

def init_all():
    global borepump, free_space_KB, presspump, vbus_prev_status, vbus_last_OFF_time, report_max_outage
    global display_mode, navigator, encoder_count, encoder_btn_state, enc_a_last_time, enc_btn_last_time, modebtn_last_time
    global slist, program_pending, sys_start_time, rotary_btn_pressed, kpa_sensor_found
    global nav_btn_state, nav_btn_last_time
    global zone, zone_max_drop, zone_minimum, zone_maximum, stable_pressure, average_kpa, last_ON_time, kPa_sd_multiple
    global ONESECBLINK, lcd_timer
    global ut_long, ut_short
    global stdev_Depth, stdev_Press
    global LOGHFDATA, read_count_since_ON
    global btn_click
    global last_activity_time

    PS_ND               = "Pressure sensor not detected"
    str_msg             = "At startup, BorePump is "
    encoder_count       = 0       # to track rotary next/prevs
    now                 = ticks_ms()
    enc_a_last_time     = now
    encoder_btn_state   = False
    enc_btn_last_time   = now
    modebtn_last_time   = now
    rotary_btn_pressed  = False
    nav_btn_last_time   = 0
    nav_btn_state       = False

    ev_log.write(f"\n{now_time_long()} Pump Monitor starting - SW ver:{SW_VERSION}  ")      # no \n...
    ev_log.write(f'params ({config_dict[DELAY]}s, {int(PRESSURE_PERIOD_MS/1000)}ms, {DEPTHRINGSIZE=})\n')
    
    slist=[]

    Change_Mode(UI_MODE_NORM)
    lcd_on()
    lcd4x20.clear()
    lcd4x20.display_on()
    lcd4x20.backlight_on()
    display.fill(0)
    display.show()   

# Get the current pump state and init my object    
    # borepump            = Pump("BorePump", get_initial_pump_state())
    borepump            = Pump("BorePump", context.ini_pump_state)

# On start, valve should now be open... but just to be sure... and to verify during testing...
    if borepump.state:
        if DEBUGLVL > 0:
            print(str_msg + "ON  ... opening valve")
        solenoid.value(0)           # be very careful... inverse logic!
    else:
        if DEBUGLVL > 0:
            print(str_msg + "OFF ... closing valve")
        solenoid.value(1)           # be very careful... inverse logic!

    presspump           = Pump("PressurePump", False)

    init_ringbuffers()                      # this is required BEFORE we raise any alarms...

    navigator.set_buffer(MenuNavigator.EVENTRING,  event_ring.buffer)
    navigator.set_buffer(MenuNavigator.SWITCHRING, switch_ring.buffer)
    navigator.set_buffer(MenuNavigator.KPARING,    kpa_ring.buffer)
    navigator.set_buffer(MenuNavigator.ERRORRING,  error_ring.buffer)
    navigator.set_buffer(MenuNavigator.DEPTHRING,  depth_ring.buffer)

    navigator.set_program_list(program_list)
    #  Note: filelist is set in show_dir... DO NOT set here !!

    sync_programlist_to_menu()

    free_space_KB = free_space()
    if free_space_KB < FREE_SPACE_LOWATER:
        print(f'Low free-space: {free_space_KB} Calling make_more_space')
        raiseAlarm("Free space", free_space_KB)
        error_ring.add(TankError.NOFREESPACE)                    
        make_more_space()

# ensure we start out right...
    stable_pressure     = False
    read_count_since_ON = 0
    now                 = time.time()
    if vbus_sense.value():
        vbus_prev_status     = True
        vbus_last_OFF_time    = now 
        report_max_outage   = True
    else:
        vbus_prev_status     = False         # just in case we start up without main power, ie, running on battery
        vbus_last_OFF_time    = now - 60 * 60        # looks like an hour ago
        report_max_outage   = False

    display_mode        = DM_PRESSURE
    program_pending     = False         # no program
    sys_start_time      = now            # must be AFTER we set clock ...
    
    average_kpa         = 0
    zone                = "???"
    zone_minimum        = 0
    zone_maximum        = 0
    zone_max_drop       = 15            # check after more tests
    kPa_sd_multiple     = float(config_dict[KPASTDEVMULT])      # this is now just default starting value... overwritten in set_zone
    last_ON_time        = 0
    ut_short            = ""
    ut_long             = ""
    startup_raw_ADC, startup_calibrated_pressure = get_pressure()
    kpa_sensor_found = startup_raw_ADC > BP_SENSOR_MIN    # are we seeing a valid pressure sensor reading?
    
    stdev_Press         = 0
    stdev_Depth         = 0
    LOGHFDATA           = kpa_sensor_found

    if not kpa_sensor_found:
        lcd4x20.move_to(0, 3)
        lcd4x20.putstr(f'NO PS: kPa:{startup_calibrated_pressure:2}')
        print(f'{PS_ND} - {startup_calibrated_pressure=}')
        ev_log.write(f"{now_time_long()} {PS_ND} initial:{startup_calibrated_pressure:3} - HF kPa logging disabled\n")
    else:
        print(f"Pressure sensor detected - {startup_raw_ADC=} {startup_calibrated_pressure=}")
        ev_log.write(f"{now_time_long()} Pressure sensor detected - logging enabled\n")

    enable_controls()                   # enable rotary encoder, LCD B/L button etc
    ONESECBLINK         = 850           # 1 second blink time for LED
    lcd_timer           = None

    btn_click = False

#   Do spiffy stuff with VL53L1X if I can...
    if hasattr(distSensor, "setMeasurementTimingBudget"):
        change_TB(TIMEBUDGET_MS)         # this line only called if my driver is loaded.
        distSensor.stopRanging()
        distSensor.setDistanceMode('medium')
        sleep_ms(200)
        distSensor.setROISize(ROISIZE, ROISIZE)
        sleep_ms(200)
        distSensor.startRanging()
        sleep_ms(500)
        _ = distSensor.read()
        _ = distSensor.read()
        _ = distSensor.read()       # couple of dummy reads to make sure things have settled
        ev_log.write(f"{now_time_long()} Set VL53L1X TimeBudget to {TIMEBUDGET_MS} ms, ROI to {ROISIZE}, DM to 'medium'\n")
        print(f"{now_time_long()} Set VL53L1X TimeBudget to {TIMEBUDGET_MS} ms, ROI to {ROISIZE}, and DM to 'medium'")
    else:
        ev_log.write(f"{now_time_long()} setMeasurementTimingBudget not available in this driver.\n")
        print("setMeasurementTimingBudget not available in this driver.")
    
    last_activity_time = now    # start now... check "regularly" - whatever that is
    # pump_on_event.clear()       # ensure we start out with this unset

# def heartbeat() -> bool:
#     global borepump

#     if borepump.state:
#         # print("sending HEARTBEAT")
#         transmit_and_pause(MSG_HEARTBEAT, RADIO_PAUSE)       # this might be a candidate for a shorter delay... if no reply expected
#     return borepump.state

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
            error_ring.add(TankError.NOVALVEOFFWHILEON)            
        else:
            if DEBUGLVL > 0: print(str_valve + "OFF")
            switch_valve(False)

def free_space()->int:
    # Get the filesystem stats
    stats = uos.statvfs('/')        # type: ignore   YUK, but wasted too much time trying to fix Pylance...
    
    # Calculate free space
    block_size = stats[0]
    free_blocks = stats[3]

    # Free space in bytes
    free_space_kb = free_blocks * block_size / 1024
    return free_space_kb

def do_enter_process():
    lcd_on()                        # but set no OFF timer...stay on until I exit menu 
    # navmode = navigator.mode

    if ui_mode == UI_MODE_MENU:
        navmode = navigator.mode
        if navmode == MenuNavigator.NAVMODE_MENU:
            navigator.enter()
        elif navmode == MenuNavigator.NAVMODE_VALUE:
            navigator.set()
        elif "view" in navmode:        # careful... if more modes are added, ensure they contain "view"
            navigator.go_back()
    elif ui_mode == UI_MODE_NORM:
        Change_Mode(UI_MODE_MENU)
        navigator.go_to_start()
        navigator.display_current_item()
    else:
        print(f'Huh? {ui_mode=}')

def sim_detect()->bool:
    return True

# endregion
# region AppContext
class AppContext:
    def __init__(self):
        self.wlan = None
        self.my_IP = None
        self.lcd = RGB1602.RGB1602(16,2)        # type ignore
        self.ini_pump_state:bool = False        # assume pump is OFF to start... will update as required in init_all
        # Add references to functions if needed
        # self.log_event = log_event
        # self.update_ringbuffer = update_ringbuffer
        # ...etc...
context             = AppContext()
context.lcd         = lcd

system              = SimpleDevice(context)       
# endregion
# region ASYNCIO defs

async def monitor_vbus()->None:
    """
    Monitor power supplied to VBUS, report outages, and check for long outages > MAX_OUTAGE seonds
    """
    global vbus_last_OFF_time, report_max_outage, vbus_prev_status

    while True:
        if vbus_sense.value():          # we have power
            if not vbus_prev_status:    # power has turned on since last test
                now = time.time()
                outage_duration = now - vbus_last_OFF_time
                s = f"{now_time_long()} {VBUS_RESTORED}\n"
                print(s)
                event_ring.add(VBUS_RESTORED)
                ev_log.write(s)
                lcd.setCursor(0,1)
                lcd.printout(VBUS_RESTORED)
                print(f'{outage_duration=}')
                report_max_outage = True
                vbus_prev_status = True
        else:                           # NO POWER
            now = time.time()
            if vbus_prev_status:        # we had power previous loop - now LOST POWER...
                vbus_last_OFF_time = now
                s = f"{now_time_long()} {VBUS_LOST}\n"
                print(s)
                event_ring.add(VBUS_LOST)
                ev_log.write(s)
                lcd.setCursor(0,1)
                lcd.printout(VBUS_LOST)
                vbus_prev_status = False
            else:                       # still no power, same as last loop
                time_off_so_far = now - vbus_last_OFF_time
                if (time_off_so_far >= MAX_OUTAGE) and report_max_outage:
                    s = f"{now_time_long()} VBUS off more than {MAX_OUTAGE} seconds\n"
                    print(s)
                    ev_log.write(s)
                    lcd.setCursor(0,1)
                    lcd.printout("MAX_OUTAGE") 
                    event_ring.add("MAX_OUTAGE")
                    report_max_outage = False       # OK... reported, now shut up until next long outage event
                    housekeeping(False)             # save stuff... but don't close files
        await asyncio.sleep(1)

async def read_pressure()->None:
    """
    Read the pressure sensor and update the hi_freq_kpa ring buffer.
    This function runs in a loop, reading the pressure sensor at hi frequency intervals.

    Also, rapid check for excess pressure... if so, turn off pump and solenoid.
    """
    global hi_freq_kpa_ring, hi_freq_kpa_index, kpa_peak, time_peak, kpa_low, stable_pressure
    global read_count_since_ON
    try:
        while True:
            if SIMULATE_KPA:
                bpp = random.randint(100, 600)
            else:
                raw_val, bpp = get_pressure()
            # print(f"Press: {bpp:>3} kPa, {hi_freq_kpa_index=}")
            if bpp > kpa_peak:
                kpa_peak = bpp       # record peak value.  Will be reset on borepump_ON, and fixed in set_zone
                time_peak = time.time()
            if bpp < kpa_low:
                kpa_low = bpp
            hi_freq_kpa_ring[hi_freq_kpa_index] = bpp
            hi_freq_kpa_index = (hi_freq_kpa_index + 1) % HI_FREQ_RINGSIZE
            hi_freq_avg = calc_average_HFpressure(0, HI_FREQ_AVG_COUNT)           # short average count... last few readings
            read_count_since_ON += 1
            if read_count_since_ON > STABLE_KPA_COUNT: 
                stable_pressure = True                  # need to reset in pump_ON

            lcd4x20.move_to(17, 3)
            lcd4x20.putstr(f"{bpp:>3}")
            if LOGHFDATA:       # conditionally, write to logfile... but note I ALWAYS add to the ring buffer
                                # This gets switched On/OFF depending on pump state... but NOTE: buffer updates happen ALWAYS!
                # error_bar = bpp - round(stdev_Press * float(config_dict[KPASTDEVMULT] / 10 ), 2)
                error_bar = bpp - round(stdev_Press * kPa_sd_multiple, 1)   # make consistent with calc max_drop in checkforanomalies
                hf_log.write(f"{now_time_long()} {bpp:>3} {hi_freq_avg:.1f} {error_bar:.1f}\n")
            if ui_mode == UI_MODE_NORM:
                if op_mode ==  OP_MODE_AUTO: 
                    if display_mode == DM_PRESSURE:
                        lstr = f'{int(hi_freq_avg):3} {zone}'
                        lcd.setCursor(9, 1)
                        lcd.printout(lstr)

            if hi_freq_avg > float(config_dict[MAXPRESSURE]):
                raiseAlarm("XS H/F kPa", hi_freq_avg)
                error_ring.add(TankError.EXCESS_KPA)                        
                # borepump_OFF()
                abort_pumping("Max kPa exceeded")       # this is safer
                confirm_and_switch_solenoid(False)      # TODO Problem !! Turning solenoid off needs to aysnc confirm pump is OFF so... also needs to be async.
                # solenoid.value(1)

            await asyncio.sleep_ms(PRESSURE_PERIOD_MS)

    except Exception as e:
        print(f"read_pressure exception: {e}")

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

    t0 = ticks_ms()

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

    t1 = ticks_ms()
    smtp=umail.SMTP(SMTP_SERVER, SMTP_PORT, ssl=True)
    t2 = ticks_ms()
    # print("SMTP connection created")
    c, r = smtp.login(FROM_EMAIL, FROM_PASSWORD)
    t3 = ticks_ms()
    # print(f"After SMTP Login {c=} {r=}")
    smtp.to(TO_EMAIL)
    smtp.write(hdrmsg)  # Write headers and message part
    
    t4 = ticks_ms()
    # print("SMTP Headers written")
    await asyncio.sleep_ms(SMTPSLEEPMS)

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
                    if total_chunks % SMTPLINEGROUP == 0:
                        print(".", end="")
                        await asyncio.sleep_ms(SMTPSLEEPMS)
                
                # Free up memory
                del chunk
                del encoded
                # f.close()    do NOT do this... not needed in with context, and actually breaks things
                gc.collect()

        smtp.write('\r\n')  # Add separation between attachments

    # print(f"\r\nAfter reading files, free mem = {gc.mem_free()}")
    # End the MIME message
    smtp.write("\r\n--BOUNDARY--\r\n")

    t5 = ticks_ms()
    # f.close()
    # print(f"\r\nSMTP Files written in {total_chunks} chunks ")
    await asyncio.sleep_ms(SMTPSLEEPMS)

    smtp.send()
    t6 = ticks_ms()
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

async def pump_action_processor():
    """Process pump actions from queue, handle success/failure differently for ON/OFF"""
    global average_timer, zone_timer, last_ON_time, LOGHFDATA

    while True:
        act_tuple = await pump_action_queue.get()
        cmd = act_tuple[0]
        reason = act_tuple[1]
        qlen = pump_action_queue.qsize()
        if DEBUGLVL > 1: print(f'{now_time_long()} pap after get {qlen=}')
        if DEBUGLVL > 0: print(f'{now_time_long()} waiting on SCWT {cmd}')

        success, response = await send_command_with_timeout(cmd, MSG_ANY_ACK)

        if cmd == MSG_REQ_ON:
            if success:
                # Handle successful ON request
                borepump.switch_pump(True)
                LOGHFDATA = True
                switch_ring.add("PUMP ON")
                last_ON_time = time.time()
                if kpa_sensor_found:
                    reset_state()
                    average_timer   = Timer(period=AVG_KPA_DELAY * 1000, mode=Timer.ONE_SHOT, callback=set_average_kpa)  # type:ignore
                    zone_timer      = Timer(period=ZONE_DELAY * 1000,    mode=Timer.ONE_SHOT, callback=set_zone)  # type:ignore
                logstr = f'{now_time_long()} p_a_p {cmd} processed {reason}, pump switched ON'
                ev_log.write(f'{logstr}\n')
                print(logstr)
                event_ring.add("PUMP ON")
                system.on_event(SimpleDevice.SM_EV_ON_ACK)
            else:
                # Handle failed ON request
                if response is None:
                    enter_maint_mode_reason("PAP Timeout on ON request")
                else:
                    logstr = f'{now_time_long()} ON request FAILED'
                    ev_log.write(f'{logstr}\n')
                    print(logstr)
                    system.on_event(SimpleDevice.SM_EV_ON_NAK)

        elif cmd == MSG_REQ_OFF:
            if success:
                # Handle successful OFF request
                borepump.switch_pump(False)
        # TODO Do solenoid stuff here...
                LOGHFDATA = False
                switch_ring.add("PUMP OFF")
                logstr = f'{now_time_long()} p_a_p {cmd} processed {reason}, pump switched OFF'
                ev_log.write(f'{logstr}\n')
                print(logstr)
                event_ring.add("PUMP OFF")
                system.on_event(SimpleDevice.SM_EV_OFF_ACK)
            else:
                # Handle failed OFF request - potentially more serious
                if response is None:
                    logstr = f'{now_time_long()} PAP Timeout on OFF request'
                    ev_log.write(f'{logstr}\n')
                    print(logstr)                
                    enter_maint_mode_reason("PAP Timeout on OFF request")
                    error_ring.add(TankError.PUMP_OFF_FAILED)
                else:
                    logstr = f'{now_time_long()} OFF request FAILED - pump state uncertain'
                    ev_log.write(f'{logstr}\n')
                    print(logstr)
                    error_ring.add(TankError.PUMP_OFF_FAILED)
                    system.on_event(SimpleDevice.SM_EV_OFF_NAK)

        else:
            logstr = f'Unknown command {cmd}'
            ev_log.write(f'{logstr}\n')
            print(logstr)
                 
# ============================================
# Task 1: Radio Receiver (producer)
# ============================================
async def radio_receive_task():
    """Continuously listen for radio messages and put them in queue"""
    global last_comms_time

    while True:
        if radio.device.receive():  # Check if message waiting
            radio.status = True     # update status, needed for heartbeat check
            message = radio.device.message
            if DEBUGLVL > 1: print(f'{now_time_long()} MASTER rrt: {message=}')
            last_comms_time = time.time()
            await radio.incoming_queue.put(message)
        await asyncio.sleep_ms(200)  # Don't hog CPU

# ============================================
# Task 2: Response Handler
# ============================================
async def response_handler_task():
    """Process received responses and match them to pending requests"""
    while True:
        response = await radio.incoming_queue.get()     # blocking get
        if DEBUGLVL > 1: print(f"RHT: Received: {response}")
        
        # Store the response so other tasks can check for it
        if 'expected_response' in pending_request:
            if response == pending_request['expected_response']:    # TODO this if seems pointless... probably should refactor this
                pending_request['received'] = True
                pending_request['response'] = response
            elif response.endswith(' NAK'):
                pending_request['received'] = True
                pending_request['response'] = response
        
        # TODO Outer "if" seems silly... we create pending_request with an 'expected_response' key...

        # Could also handle unsolicited messages here if needed
# ============================================
# Helper: Send command and wait for response
# ============================================
async def send_command_with_timeout(command, expected_response, timeout=5, max_retries=4):
    """
    Send a command and wait for expected response with timeout and retries.
    Returns: (success, response)

    Note:  RX slave takes about 7-8 seconds to boot from power-off to ready to receive... So...
    If I want to allow TX to cater for a brief power outage on RX (with no LiPo), need to cope with
    timeout of say 15 seconds??

    """

    if DEBUGLVL > 0: print(f'{now_time_long()} Entered S_C_W_T cmd {command}')

    for attempt in range(max_retries):
        # Set up pending request tracker
        pending_request.clear()
        pending_request['command'] = command
        pending_request['expected_response'] = expected_response
        pending_request['received'] = False
        pending_request['response'] = None
        
        # Send the command
        await radio.outgoing_queue.put(command)
        
        # Wait for response with timeout
        start_time = time.time()
        while time.time() - start_time < timeout:
            if pending_request.get('received'):
                response = pending_request['response']
                if response == expected_response:
                    if DEBUGLVL > 0: print(f'{now_time_long()} SCWT: received expected response {response} on {attempt=}')
                    return (True, response)
                else:
                    # Got NAK or unexpected response
                    return (False, response)
            await asyncio.sleep_ms(250)
        
        # Timeout occurred
        print(f"{now_time_long()} Timeout on {command}, attempt {attempt + 1}/{max_retries}")
    
    # All retries failed.  
    return (False, None)

# ============================================
# Task 3: Radio Transmitter (consumer)
# ============================================
async def radio_transmit_task():
    """Send responses from outgoing queue"""
    while True:
        message = await radio.outgoing_queue.get()  # Blocks until response ready
        radio.device.send(message)
        if DEBUGLVL > 1: print(f'radio_tx_task: sent {message}')
        await asyncio.sleep_ms(RADIO_PAUSE)  # Small delay between transmissions

# ============================================
# Task 4: Main Control Loop (your existing logic)
# ============================================
async def main_control_task():
    """Main control logic - initialise SM, then reads sensors, control pump, manage auto mode operations"""
    global borepump, last_ON_time, LOGHFDATA, rec_num

    screamer.value(0)			    # turn alarm off
    beeper.value(0)			        # turn beeper off
    lcd.clear()
    lcd_on()

    if DEBUGLVL > 0: print('Entered main_control_task')

    asyncio.create_task(radio_receive_task())
    asyncio.create_task(response_handler_task())
    asyncio.create_task(radio_transmit_task())                 # the missing piece...

    while str(system.state) != SimpleDevice.STATE_PICO_READY:      # TODO add a "standby" state... requires wiring XSHUT to VL53L1X
        current_state = str(system.state)
        print(f'in MCT: {current_state=}')

        # Startup sequence
        if current_state == SimpleDevice.STATE_PICO_RESET:
            # system.on_event(SimpleDevice.SM_EV_SYS_INIT)
            if init_wifi():
                system.on_event(SimpleDevice.SM_EV_WIFI_ACK)
        
        if current_state == SimpleDevice.STATE_WIFI_READY:
            if init_clock():
                system.on_event(SimpleDevice.SM_EV_NTP_ACK)
        
        if current_state == SimpleDevice.STATE_CLOCK_SET:
            radio.device.off()
            radio.device.on()       # this should clear send/receive buffers
            success, response = await send_command_with_timeout(MSG_PING_REQ, MSG_PING_RSP, timeout=2)
            if success:
                system.on_event(SimpleDevice.SM_EV_RADIO_ACK)
            else:
                print('SLAVE not responding')
                continue
        
        if current_state == SimpleDevice.STATE_RADIO_READY:
            success, response = await send_command_with_timeout(MSG_STATUS_CHK, MSG_STATUS_ACK, timeout=2)
            if success:
                context.ini_pump_state = True
                system.on_event(SimpleDevice.SM_EV_INI_ACK)
            else:
                context.ini_pump_state = False
                system.on_event(SimpleDevice.SM_EV_INI_NAK)
            # continue

        if current_state == SimpleDevice.STATE_INITIALPUMP:
            # print(f'in MCT INITIALPUMP: {current_state=}')
            system.on_event(SimpleDevice.SM_EV_SYS_START)
            # print(f'...and now... {system.state=}')
        
        await asyncio.sleep_ms(750)  # initial/start-up loop cycle time

    print('Woohoo.. we made it to READY!')

    start_time = time.time()
    print(f"Main TX starting {format_secs_long(start_time)} SM version:{system.version} TX version:{SW_VERSION}")
    init_logging()          # needs correct time first!
    
    asyncio.create_task(blinkx2())                              # visual indicator we are running
    # asyncio.create_task(check_lcd_btn())                       # start up lcd_button widget
    asyncio.create_task(regular_flush(FLUSH_PERIOD))            # flush data every FLUSH_PERIOD minutes
    asyncio.create_task(check_rotary_state(ROTARY_PERIOD_MS))   # check rotary every ROTARY_PERIOD_MS milliseconds
    asyncio.create_task(processemail_queue())                   # check email queue
    asyncio.create_task(monitor_vbus())
    if kpa_sensor_found:
        asyncio.create_task(read_pressure())                    # read pressure every PRESSURE_PERIOD_MS milliseconds    
    
    asyncio.create_task(heartbeat_task())                       # send heartbeats independent of other stuff: DELAY until async Comms running
    # asyncio.create_task(resume_pumping())                       # if pump stopped by kpa_drop... resume when event triggered
    asyncio.create_task(pump_action_processor())                # a generic handler for async ON/OFF actions

    gc.collect()
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
    # micropython.mem_info()

    init_all()              # includes device config...
    get_tank_depth()        # defer until after devices configured.  First reading might be more accurate now...

    _ = Timer(period=config_dict[LCD] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)    # type:ignore

    str_msg = "Immediate switch pump "
    housetank.state = tank_is
    print(f"Initial tank state is {housetank.state}")
    if (housetank.state == "Empty" and not borepump.state):           # then we need to start doing somethin... else, we do NOTHING
        print(str_msg + "ON required")
    elif (borepump.state and (housetank.state == "Full" or housetank.state == "Overflow")):     # pump is ON... but...
        print(str_msg + "OFF required")
    else:
        print("No action required")

# Now the real monitoring loop begins...

    rec_num=0
    while True:
        if op_mode != OP_MODE_MAINT:
            updateData()			                    # monitor water depth in tank, also sets tank_is
            if borepump.state and read_count_since_ON > FAST_AVG_COUNT:     # stable_pressure set when we have required number of readings to get average_kpa
                check_for_critical_states()             # fast acting check - mainly for XS KPA
            if op_mode == OP_MODE_AUTO:                 # changed, do nothing if OP_MODE_DISABLED or IRRIGATE
                if tank_is == housetank.fill_states[0]:		# Overfull
                    screamer.value(1)			        # raise alarm
                else:
                    screamer.value(0)

                if tank_is == housetank.fill_states[len(housetank.fill_states) - 1] and not borepump.state:		# Empty
                    pump_action_queue.put_nowait(("ON", "Tank Empty"))
                    if DEBUGLVL > 0:
                        print(f'{now_time_long()} after putting ON in PA queue... qlen: {pump_action_queue.qsize()}')
                
                elif (tank_is == housetank.fill_states[0] or tank_is == housetank.fill_states[1]) and borepump.state:	# Full or Overfull
                    pump_action_queue.put_nowait(("OFF", "Tank FULL"))

            DisplayData()
            DisplayInfo()		                    # info display... one of several views
            DisplayGraph()

            if stable_pressure:
                checkForAnomalies()	                # test for weirdness
            if rec_num % LOG_FREQ == 0:           
                LogData()			                # record it
            rec_num += 1

        else:   # we are in OP_MODE_MAINT ... don't do much at all.  Respond to interupts... show stuff on LCD.  Permits examination of buffers etc
            DisplayData()
            DisplayInfo()  
            DisplayGraph()
        
        await asyncio.sleep_ms(config_dict[DELAY] * 1000)

# ============================================
# Task 5: Heartbeat Sender
# ============================================
async def heartbeat_task():
    """Send periodic heartbeat to slave"""
    while True:
        await radio.outgoing_queue.put(MSG_HEARTBEAT)
        await asyncio.sleep(5)  # Every 5 seconds

# async def get_to_ready_state():
#     while  str(system.state) != SimpleDevice.STATE_PICO_READY:
#         current_state = str(system.state)       # NOTE: BY caching system.state this forces only one state transition per loop
#         # print(current_state)        
#         if current_state == SimpleDevice.STATE_PICO_RESET:
#             # system.on_event(SimpleDevice.SM_EV_SYS_INIT)
#             if init_wifi():
#                 system.on_event(SimpleDevice.SM_EV_WIFI_ACK)

#         if current_state == SimpleDevice.STATE_WIFI_READY:
#             if init_clock():
#                 system.on_event(SimpleDevice.SM_EV_NTP_ACK)

#         if current_state == SimpleDevice.STATE_CLOCK_SET:
#             if init_radio():
#                 system.on_event(SimpleDevice.SM_EV_RADIO_ACK)

#         if current_state == SimpleDevice.STATE_RADIO_READY:
#             system.on_event(SimpleDevice.SM_EV_SYS_START)
            
#         await asyncio.sleep(1)

# endregion
# region MAIN
def main() -> None:
    global ui_mode
    try:
        # micropython.qstr_info()
        # print('Sending test email ... no files')
        # send_email_msg(TO_EMAIL, "Test email 15", "Almost done...")    
        # print('...sent')

        # asyncio.run(do_main_loop())
        gc.collect()

        asyncio.run(main_control_task())        # new way of living...

    except OSError:
        print("OSError... ")
        
    except KeyboardInterrupt:
        ui_mode = UI_MODE_NORM      # no point calling Change... as I turn B/L off straight after anyway...
        lcd_off('')	                # turn off backlight
        lcd4x20.backlight_off()
        lcd4x20.display_off()
        print('\n### Program Interrupted by user')
        if op_mode == OP_MODE_IRRIGATE:
            cancel_program()
    # turn everything OFF
        if borepump is not None:                # in case I bail before this is defined...
            if borepump.state:
                borepump_OFF("Kbd interupt")    # TODO cant await SCWT - MAIN is not async
                                    # so pump time/DC will be a bit wrong... since we must wait for Rx to time out to turn OFF

    #    confirm_and_switch_solenoid(False)     #  *** DO NOT DO THIS ***  If live, this will close valve while pump ON.
    #           to be real sure, don't even test if pump is off... just leave it... for now.

    # tidy up...
        housekeeping(False)
        shutdown()

if __name__ == '__main__':
    main()
# endregion