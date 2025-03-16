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
from utime import sleep, ticks_us, ticks_diff
from PiicoDev_Unified import sleep_ms
from PiicoDev_VL53L1X import PiicoDev_VL53L1X
from PiicoDev_Transceiver import PiicoDev_Transceiver
from umachine import Timer, Pin, ADC, soft_reset # Import Pin
from Pump import Pump               # get our Pump class
from Tank import Tank
from secrets import MyWiFi
from MenuNavigator import MenuNavigator
# from encoder import Encoder
from ubinascii import b2a_base64 as b64

from SM_SimpleFSM import SimpleDevice

# endregion
# region INITIALISE

# micropython.mem_info()
# gc.collect()

# constant/enums
OP_MODE_AUTO        = 0
OP_MODE_IRRIGATE    = 1
OP_MODE_MAINT       = 2

UI_MODE_NORM        = 0
UI_MODE_MENU        = 1

TIMERSCALE          = 60            # permits fast speed debugging... normally, set to 60 for "minutes" in timed ops
DEFAULT_CYCLE       = 30            # for timed stuff... might eliminate the default thing...
DEFAULT_DUTY_CYCLE  = 40            # % ON time for irrigation program

RADIO_PAUSE         = 1000
FREE_SPACE_LOWATER  = 150           # in KB...
FREE_SPACE_HIWATER  = 400

FLUSH_PERIOD        = 5
DEBOUNCE_ROTARY     = 10            # determined from trial... see test_rotary_irq.py
DEBOUNCE_BUTTON     = 100
ROTARY_PERIOD_MS    = 200           # needs to be short... check rotary ISR variables
PRESSURE_PERIOD_MS  = 1000

EVENTRINGSIZE       = 20            # max log ringbuffer length
SWITCHRINGSIZE      = 20
PRESSURERINGSIZE    = 20

MAX_OUTAGE          = 30            # seconds of no power

BP_SENSOR_MIN       = 5000          # raw ADC read... this will trigger sensor detect logic
VDIV_R1             = 2000          # ohms
VDIV_R2             = 5000
VDIV_Ratio          = VDIV_R2/(VDIV_R1 + VDIV_R2)

#All menu-CONFIGURABLE parameters
mydelay             = 15            # seconds, main loop period
LCD_ON_TIME         = 15            # seconds
Min_Dist            = 500           # full
Max_Dist            = 1400          # empty
MAX_LINE_PRESSURE   = 700           # TBC... but this seems about right
MIN_LINE_PRESSURE   = 300           # tweak after running... and this ONLY applies in OP_MODE_IRRIG
NO_LINE_PRESSURE    = 15            # tweak this too... applies in ANY pump-on mode
MAX_CONTIN_RUNMINS  = 360            # 3 hours max runtime.  More than this looks like trouble

SIMULATE_PUMP       = False         # debugging aid...replace pump switches with a PRINT
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
LOG_FREQ            = 1
last_logged_depth   = 0
last_logged_kpa     = 0
min_log_change_m    = 0.02          # to save space... only write to file if significant change in level
MAX_KPA_CHANGE      = 10            # update after pressure sensor active
level_init          = False 		# to get started

ringbufferindex     = 0             # for SMA calculation... keep last n measures in a ring buffer
eventindex          = 0             # for scrolling through error logs on screen
switchindex         = 0
kpaindex            = 0            # for scrolling through pressure logs on screen

lcdbtnflag          = True          # this should immediately trigger my asyncio timer on startup...

# Misc stuff
steady_state        = False         # if not, then don't check for anomalies
clock_adjust_ms     = 0             # will be set later... this just to ensure it is ALWAYS something
report_outage       = True          # do I report next power outage?
sys_start_time      = 0             # for uptime report
kpa_sensor_armed    = True          # set to True if pressure sensor is detected  

SW_VERSION          = "16/3/25"       # for display

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

# Create pins for encoder lines and the onboard button

enc_btn             = Pin(18, Pin.IN, Pin.PULL_UP)
enc_a               = Pin(19, Pin.IN)
enc_b               = Pin(20, Pin.IN)
# px                  = Pin(20, Pin.IN, Pin.PULL_UP)
# py                  = Pin(19, Pin.IN, Pin.PULL_UP)
last_time           = 0
count               = 0

system              = SimpleDevice()                    # initialise my FSM.
wf                  = MyWiFi()

# Create PiicoDev sensor objects
distSensor 	        = PiicoDev_VL53L1X()
lcd 		        = RGB1602.RGB1602(16,2)
radio               = PiicoDev_Transceiver()
#rtc 		        = PiicoDev_RV3028()                 # Initialise the RTC module, enable charging

# Configure WiFi SSID and password
ssid                = wf.ssid
password            = wf.password

SMTP_SERVER         = "smtp.gmail.com"
SMTP_PORT           = 465

# Email account credentials
FROM_EMAIL          = "gmtgn55@gmail.com"
FROM_PASSWORD       = wf.gmailAppPassword
TO_EMAIL            = "trevor.norman4@icloud.com"

# things for async SMTP file processing
sleepms = 100
linegrp = 100

EMAIL_QUEUE_SIZE    = 20  # Adjust size as needed
email_queue         = ["" for _ in range(EMAIL_QUEUE_SIZE)]
email_queue_head    = 0
email_queue_tail    = 0
email_queue_full    = False
email_task_running  = False

# Pressure to Zone mapping...
P0 = "Zero"
P1 = "Air1"
P2 = "HT"
P3 = "Z45"
P4 = "Z3"
P5 = "Z2"
P6 = "Z4"
P7 = "Z1"
P8 = "XP"
PRESSURE_THRESHOLDS = [0, 15, 25, 290, 390, 480, 500, 600]  # Ascending order
PRESSURE_CATEGORIES = [P0, P1, P2, P3, P4, P5, P6, P7, P8]
KPA_AVERAGE_COUNT   = 3
average_kpa         = 0

def get_pressure_category(pressure: int) -> str:
    """Map pressure value to category using linear search"""
    for i, threshold in enumerate(PRESSURE_THRESHOLDS):
        if pressure <= threshold:
            return PRESSURE_CATEGORIES[i]
    return PRESSURE_CATEGORIES[-1]  # Return last category if pressure exceeds all thresholds

def get_pressure_category_binary(pressure: int) -> str:
    """Map pressure value to category using binary search"""
    left, right = 0, len(PRESSURE_THRESHOLDS)
    while left < right:
        mid = (left + right) // 2
        if pressure <= PRESSURE_THRESHOLDS[mid]:
            right = mid
        else:
            left = mid + 1
    return PRESSURE_CATEGORIES[left]

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
    'Start Delay'   : 0,
    'Duty Cycle'    : DEFAULT_DUTY_CYCLE
              }
    
program_list = [
              ("Cycle1", {"init" : 0, "run" : 30, "off" : 45}),
              ("Cycle2", {"init" : 1, "run" : 30, "off" : 45}),
              ("Cycle3", {"init" : 1, "run" : 30, "off" : 0})]

def update_config():
    
    for param_index in range(len(config_dict)):
        param: str             = new_menu['items'][3]['items'][0]['items'][param_index]['title']
        new_working_value: int = new_menu['items'][3]['items'][0]['items'][param_index]['value']['W_V']
        if param in config_dict.keys():
            # print(f"in update_config {param}: dict is {config_dict[param]} nwv is {new_working_value}")
            if new_working_value > 0 and config_dict[param] != new_working_value:
                config_dict[param] = new_working_value
                # print(f'Updated config_dict {param} to {new_working_value}')
                lcd.clear()
                lcd.setCursor(0,0)
                lcd.printout(f'Updated {param}')
                lcd.setCursor(0,1)
                lcd.printout(f'to {new_working_value}')
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

# endregion
# region TIMED IRRIGATION
def toggle_borepump(x:Timer):
    global my_timer, timer_state, op_mode, sl_index, cyclename, ON_cycle_end_time, next_ON_cycle_time, program_pending

    program_pending = False
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
                # print(f"{current_time()}: TOGGLE - turning pump OFF")
                borepump_OFF()       #turn_off()
            elif timer_state == 0:
                pass
                # diff = slist[sl_index + 1] - slist[sl_index]
                # nextcycle_ON_time = now + diff * TIMERSCALE
                # print(f"{current_time()}: TOGGLE - Doing nothing")
            if sl_index == len(slist) - 2:              # we must be in penultimate cycle, or last cycle
                next_ON_cycle_time = now - 2 * TIMERSCALE

            # print(f" end cycle {display_time(secs_to_localtime(ON_cycle_end_time))}\nnext cycle {display_time(secs_to_localtime(next_ON_cycle_time))}")
            # now, set up next timer
            sl_index += 1
            diff = slist[sl_index] - slist[sl_index - 1]
            print(f"Creating timer for index {sl_index}, {slist[sl_index]}, {diff=}")

            my_timer = Timer(period=diff*TIMERSCALE*1000, mode=Timer.ONE_SHOT, callback=toggle_borepump)
            # print(f"{timer_state=}")
        else:
            prog_str = f"{current_time()}: Ending timed watering..."
            print(prog_str)
            add_to_event_ring("End PROG")
            ev_log.write(prog_str + "\n")

            op_mode = OP_MODE_AUTO
            DisplayData()       # show status immediately, don't wait for next loop ??

            # print(f"{current_time()}: in TOGGLE... END IRRIGATION mode !  Now in {op_mode}")
            if borepump.state:
                borepump_OFF()       # to be sure, to be sure...
                print(f"{current_time()}:in toggle, at END turning bp OFF.  Should already be OFF...")
        if mem < 60000:
            print("Collecting garbage...")              # moved to AFTER timer created... might avoid the couple seconds discrepancy.  TBC
            gc.collect()
    else:
        print(f'{current_time()} in toggle {op_mode=}.  Why are we here??')

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
    global my_timer, timer_state, op_mode, slist, sl_index, ON_cycle_end_time, num_cycles, program_pending, program_start_time        # cycle mod 3

    try:
        if op_mode == OP_MODE_IRRIGATE:
            print(f"Can't start program... already in mode {op_mode}")
            lcd.setCursor(0,1)
            lcd.printout("Already running!")
        else:
            # apply_duty_cycle()                  # what it says
            swl=sorted(program_list, key = lambda x: x[0])      # so, the source of things is program_list... need to ensure that is updated
            prog_str = f"{current_time()}: Starting timed watering..."
            print(prog_str)
            add_to_event_ring("Start PROG")
            ev_log.write(prog_str + "\n")
            op_mode          = OP_MODE_IRRIGATE          # the trick is, how to reset this when we are done...

            timer_state      = 0
            sl_index         = 0
            # next_switch_time = timer_dict["Start Delay"] ... no, we add this in in the loop below.  
            next_switch_time = 0
            ON_cycle_end_time= 0
            num_cycles       = 0
            
            slist.clear()

            for s in swl:
                cyclename = s[0]
                # print(f"Adding timer nodes to slist for cycle {cyclename}")
                for k in ["init", "run", "off"]:
                    t=s[1][k]
                    # if k == "init" and t == 0:
                    #     print(f"Skipping {cyclename}")
                    #     break
                    # else:
                    next_switch_time += t
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
            my_timer = Timer(period=slist[0]*TIMERSCALE*1000, mode=Timer.ONE_SHOT, callback=toggle_borepump)
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
    if newmode == UI_MODE_MENU:
        ui_mode = UI_MODE_MENU
        lcd.setRGB(240, 30, 240)
    elif newmode == UI_MODE_NORM:
        ui_mode = UI_MODE_NORM
        lcd.setRGB(170,170,138)
    else:
        print(f"Change_Mode: Unknown mode {newmode}")

def exit_menu():                      # exit from MENU mode
    global ui_mode
    # process_menu = False
    lcd.setCursor(0,1)
    lcd.printout(f'{"Exit & Update":<16}')
    update_config()
    update_timer_params()
    Change_Mode(UI_MODE_NORM)
    # ui_mode = UI_MODE_NORM
    tim=Timer(period=config_dict["LCD"] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)

def cancel_program()->None:
    global program_pending, op_mode

    program_pending = False
    op_mode = OP_MODE_AUTO

    if my_timer is not None:
        my_timer.deinit()
        print("Timer CANCELLED")

    if borepump.state:
        borepump_OFF()

    lcd.setCursor(0,1)
    lcd.printout("Prog CANCELLED")

    add_to_event_ring("Prog cancelled")
    ev_log.write(f"{current_time()}: Prog cancelled\n")
    
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
    navigator.go_back()
               
def show_events():
    navigator.mode = "view_events"
               
def show_program():
    navigator.mode = "view_program"

def show_switch():
    navigator.mode = "view_switch"

def show_depth():
    print("Not implemented")

def show_pressure():
    print("Not implemented")

def show_space():
    lcd.setCursor(0,1)
    lcd.printout(f'Free KB: {free_space():<6}')

def my_reset():
    ev_log.write(f"{event_time} SOFT RESET")
    shutdown()
    lcd.setRGB(0,0,0)
    soft_reset()

def hardreset():
    # ev_log.write(f"{event_time} HARD RESET")
    # housekeeping(True)
    pass

def flush_data():
    tank_log.flush()
    ev_log.flush()
    pp_log.flush()
    lcd.setCursor(0,1)
    lcd.printout(f'{"Logs flushed":<16}')

def housekeeping(close_files: bool)->None:
    print("Flushing data...")
    start_time = time.ticks_us()
    tank_log.flush()
    ev_log.flush()
    pp_log.flush()
    end_time = time.ticks_us()
    if close_files:
        tank_log.close()
        ev_log.close()
        pp_log.close()
    print(f"Cleanup completed in {int(time.ticks_diff(end_time, start_time) / 1000)} ms")

def shutdown()->None:
    ev_log.write(f"{event_time} STOP")
    ev_log.write(f"\nMonitor shutdown at {display_time(secs_to_localtime(time.time()))}\n")
    if borepump is not None: dump_pump_arg(borepump)
    if presspump is not None: dump_pump_arg(presspump)
    dump_event_ring()
    tank_log.close()
    ev_log.close()
    pp_log.close()

def send_tank_logs():
    # filelist: list[tuple] = []
# this also allocs memory... needs to change to static buffer
    filenames = [x for x in uos.listdir() if x.startswith("tank") and x.endswith(".txt") ]

    for f in filenames:
        # fstat = uos.stat(f)
        # fsize = fstat[6]
        # fdate = fstat[7]
        add_to_email_queue(f)
        # print(f'{f}: {fsize:>7} bytes, time {display_time(secs_to_localtime(fdate))}')
    print(f'Email queue has {email_queue_head - email_queue_tail} items')
    lcd.setCursor(0,1)
    lcd.printout(f'{"Data emailed":<16}')

def show_dir():

# This code works fine... but breaks ISR no-mem allocation rules.
# Needs to be rewritten using a static buffer

    filelist: list[tuple] = []  
    filenames = [x for x in uos.listdir() if x.endswith(".txt") and (x.startswith("tank") or x.startswith("pres"))]

    for f in filenames:
        fstat = uos.stat(f)
        # print(f'file {f}:  stat returns: {fstat}')
        fsize = fstat[6]
        fdate = fstat[7]
        print(f'{f}: {fsize:>7} bytes, time {display_time(secs_to_localtime(fdate))}')

        filelist.append((f, f'Size: {fsize}'))        # this is NOT kosher... allocating mem in ISR context

    navigator.set_file_list(filelist)
    navigator.mode = "view_files"

    # for f in uos.ilistdir():
    #     fn = f[0]
    #     if "tank" in fn:
    #         fstat = uos.stat(fn)
    #         fdate = fstat[7]
    #         print(f'{fn}: time {display_time(secs_to_localtime(fdate))}')

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
    sub_menu_list: list = navigator.current_level[-1]["items"]          # this is a stack... get last entry
    # print(f'{navigator.current_index=}')
    # print(f'{sub_menu_list}')
    # print(f'sub_menu_list is type {type(sub_menu_list)}')
    old_menu_item:dict = sub_menu_list[navigator.current_index - 1]     # YUK WARNING: bad dependency here !!!
    new_menu_item = old_menu_item.copy()
    new_menu_value: dict = old_menu_item["value"].copy()
    new_menu_item["title"] = new_cycle_name
    new_menu_item["value"] = new_menu_value                             # be very careful to NOT use ref to old dict
    # print(f'{new_menu_item=}')
    sub_menu_list.insert(navigator.current_index, new_menu_item)        # only go back 1 slot
    navigator.current_index += 1        # is this needed ???
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
        sub_menu_list: list = navigator.current_level[-1]["items"]         # this is a stack... get last entry
        # print(f'{navigator.current_index=}')
        # print(f'{sub_menu_list}')
        # print(f'sub_menu_list is type {type(sub_menu_list)}')
        # new_menu_item = sub_menu_list[navigator.current_index - 2]
        # new_menu_item["title"] = new_cycle_name
        # print(f'{new_menu_item=}')
        if "Cycle" in sub_menu_list[navigator.current_index - 2]["title"]:
            del sub_menu_list[navigator.current_index - 2]      # check the 2...
            navigator.current_index -= 1        # is this needed ???
        # print(f'{sub_menu_list=}')
    else:
        lcd.setCursor(0,1)
        lcd.printout('Cant delete more')
        # print(f'remove_cycle: bad value {last_cycle_pos}')
    # print(f'{program_list=}')
    #   finally.... update this, or view code breaks
    navigator.set_program_list(program_list)

def show_uptime():
    uptimesecs = time.time() - sys_start_time
    days  = int(uptimesecs / (60*60*24))
    hours = int(uptimesecs % (60*60*24) / (60*60))
    mins  = int(uptimesecs % (60*60) / 60)
    secs  = int(uptimesecs % 60)
    ut = f'{days} d {hours:02}:{mins:02}:{secs:02}'
    lcd.clear()
    lcd.setCursor(0, 0)
    lcd.printout("Uptime:")
    lcd.setCursor(0, 1)
    lcd.printout(ut)

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
        tstr = display_time(secs_to_localtime(ts))
        file_entry = tuple((f, kb, ts, tstr))
        hitList.append(file_entry)

    sorted_by_date = sorted(hitList, key=lambda x: x[2])
    print(f"Files by date:\n{sorted_by_date}")
    if free_space() < FREE_SPACE_LOWATER:
        ev_log.write(f"{event_time} Deleting files\n")
        while free_space() < FREE_SPACE_HIWATER:
            df = sorted_by_date[0][0]
            print(f"removing file {df}")
            uos.remove(df)
            ev_log.write(f"{event_time}: Removed file {df} size{sorted_by_date[0][1]} Kb")
            sorted_by_date.pop(0)

        fs = free_space()
        print(f"After cleanup: {fs} Kb")
        ev_log.write(f"{event_time}: free space {fs}")

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
    global email_queue, email_queue_head, email_queue_full

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
    lcd.printout(f'{"Email queued":<16}')
    # print(f"Log added to email queue")

new_menu = {
    "title": "L0 Main Menu",
    "items": [              # items[0]
      {
        "title": "1 Display->",         # items[0]
        "items": [
          { "title": "1.1 Depth",    "action": display_depth},
          { "title": "1.2 Pressure", "action": display_pressure},
          { "title": "1.3 Files",    "action": show_dir},
          { "title": "1.4 Space",    "action": show_space},
          { "title": "1.5 Uptime",   "action": show_uptime},
          { "title": "1.6 Version",  "action": show_version},
          { "title": "1.7 Go Back",  "action": my_go_back
          }
        ]
      },
      {
        "title": "2 History->",         # items[1]
        "items": [
          { "title": "2.1 Events",   "action": show_events},
          { "title": "2.2 Switch",   "action": show_switch},
          { "title": "2.3 Program",  "action": show_program},
          { "title": "2.4 Stats",    "action": show_duty_cycle},
          { "title": "2.5 Depth",    "action": show_depth},
          { "title": "2.6 Pressure", "action": show_pressure},
          { "title": "2.7 Go back",  "action": my_go_back}
        ]
      },
      {
        "title": "3 Actions->",         # items[2]
        "items": [
          { "title": "3.1 Timed Water", "action": start_irrigation_schedule},
          { "title": "3.2 Cancel Prog", "action": cancel_program},
          { "title": "3.3 Flush",       "action": flush_data},
          { "title": "3.4 Make Space",  "action": make_more_space},
          { "title": "3.5 Email evlog", "action": send_log},
          { "title": "3.6 Email tank",  "action": send_tank_logs},
          { "title": "3.7 Reset",       "action": my_reset},
          { "title": "3.8 Go back",     "action": my_go_back}
        ]
      },
      {
        "title": "4 Config->",         # items[3]
        "items": [
          { "title": "4.1 Set Config->",
            "items": [                  # items[3][0]
                { "title": "Delay",        "value": {"D_V": 15,   "W_V" : mydelay,                  "Step" : 5}},
                { "title": "LCD",          "value": {"D_V": 5,    "W_V" : LCD_ON_TIME,              "Step" : 2}},
                { "title": "MinDist",      "value": {"D_V": 500,  "W_V" : Min_Dist,                 "Step" : 100}},
                { "title": "MaxDist",      "value": {"D_V": 1400, "W_V" : Max_Dist,                 "Step" : 100}},
                { "title": "Max Pressure", "value": {"D_V": 700,  "W_V" : MAX_LINE_PRESSURE,        "Step" : 25}},                
                { "title": "Min Pressure", "value": {"D_V": 300,  "W_V" : MIN_LINE_PRESSURE,        "Step" : 25}},
                { "title": "No Pressure",  "value": {"D_V": 15,   "W_V" : NO_LINE_PRESSURE,         "Step" : 5}},
                { "title": "Max RunMins",  "value": {"D_V": 180,  "W_V" : MAX_CONTIN_RUNMINS,       "Step" : 10}},
                { "title": "Save config",  "action": update_config},
                { "title": "Go back",      "action": my_go_back}
            ]
          },
           { "title": "4.2 Set Timers->",
            "items": [                  # items[3][1]
                { "title": "Start Delay",  "value": {"D_V": 5,   "W_V" : 0,                     "Step" : 15}},
                { "title": "Duty Cycle",   "value": {"D_V": 50,  "W_V" : DEFAULT_DUTY_CYCLE,    "Step" : 5}},
                { "title": "Cycle1",       "value": {"D_V": 1,   "W_V" : DEFAULT_CYCLE,         "Step" : 5}},
                { "title": "Cycle2",       "value": {"D_V": 2,   "W_V" : DEFAULT_CYCLE,         "Step" : 5}},
                { "title": "Cycle3",       "value": {"D_V": 3,   "W_V" : DEFAULT_CYCLE,         "Step" : 5}},
                { "title": "Add cycle",      "action": add_cycle},
                { "title": "Delete cycle",   "action": remove_cycle},
                { "title": "Update program", "action": update_program_data},
                { "title": "Go back",        "action": my_go_back}
            ]
          },
          { "title": "4.3 Save Config", "action": update_config},
          { "title": "4.4 Load Config", "action": "Load Config"},
          { "title": "4.5 Go back",     "action": my_go_back}
        ]
      },
    {
        "title": "5 Exit", "action": exit_menu
    }
    ]
}

def encoder_a_IRQ(pin):
    global enc_a_last_time, encoder_count

    new_time = utime.ticks_ms()
    if (new_time - enc_a_last_time) > DEBOUNCE_ROTARY:
        if enc_a.value() == enc_b.value():
            encoder_count += 1
            # print("+", end="")
            # navigator.next()
        else:
            encoder_count -= 1
            # navigator.previous()
    else:
        print(".", end="")
    # print(encoder_count)
    enc_a_last_time = new_time

def encoder_btn_IRQ(pin):
    global enc_btn_last_time, encoder_btn_state

    new_time = utime.ticks_ms()
    if (new_time - enc_btn_last_time) > DEBOUNCE_BUTTON:
        encoder_btn_state = True
    enc_btn_last_time = new_time

navigator   = MenuNavigator(new_menu, lcd)

def pp_callback(pin):
    presspmp.irq(handler=None)
    v = pin.value()
    presspump.switch_pump(v)
    # print("Pressure Pump Pin triggered:", v)
    sleep_ms(100)
    presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)

def cb(pos, delta):
        # print(pos, delta)
    if delta > 0:
        navigator.next()
    elif delta < 0:
        navigator.previous()

def enable_controls():
    
   # Enable the interupt handlers
    presspmp.irq(trigger=Pin.IRQ_RISING|Pin.IRQ_FALLING, handler=pp_callback)
    # enc = Encoder(px, py, v=0, div=4, vmin=None, vmax=None, callback=cb)
    enc_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_a_IRQ)
    enc_btn.irq(trigger=Pin.IRQ_FALLING, handler=encoder_btn_IRQ)

    lcdbtn.irq(trigger=Pin.IRQ_RISING, handler=lcdbtn_new)

# endregion
# region LCD
def lcdbtn_new(pin):
# so far, with no debounce logic...
    lcd_on()
    tim=Timer(period=config_dict["LCD"] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)

def lcdbtn_pressed(x):          # my lcd button ISR
    global lcdbtnflag
    lcdbtnflag = True
    sleep_ms(300)

def lcd_off(x):
    if ui_mode != UI_MODE_MENU:
        lcd.setRGB(0,0,0)

def lcd_on():
    if ui_mode == UI_MODE_MENU:
        lcd.setRGB(240, 30, 240)
    else:
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
        await asyncio.sleep(0.5)
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
    global tank_log, ev_log, pp_log, eventlogname

    now             = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
    year            = now[0]
    month           = now[1]
    day             = now[2]
    shortyear       = str(year)[2:]
    datestr         = f"{shortyear}{month:02}{day:02}"
    tanklogname     = f'tank {datestr}.txt'
    pplogname       = f'pres {datestr}.txt'
    eventlogname    = 'borepump_events.txt'
    tank_log        = open(tanklogname, "a")
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
    
def calc_average_pressure(n:int)->int:
    p = 0
    for i in range(n):
        mod_index = (kpaindex - i) % PRESSURERINGSIZE
        p += kparing[mod_index]
    return round(p/n)

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
    depth_ROC = (sma_depth - last_depth) / (config_dict["Delay"] / 60)	# ROC in m/minute.  Save negatives also... for anomaly testing
    if DEBUGLVL > 0: print(f"depth_ROC: {depth_ROC:.3f}")
    last_depth = sma_depth				# track change since last reading
    depth_str = f"{depth:.2f}m " + tank_is
    # print(f"In updateData: ADC value: {pv}")
    bp_kpa = kparing[kpaindex]        # get last kPa reading
    # bp_kpa = 350 + ringbufferindex * 2
    zone = get_pressure_category(average_kpa)
    pressure_str = f'{bp_kpa:3} kPa ({zone})'    # might change this to be updated more frequently in a dedicated asyncio loop...
    temp = 27 - (temp_sensor.read_u16() * TEMP_CONV_FACTOR - 0.706)/0.001721

def get_pressure()-> int:
    adc_val = bp_pressure.read_u16()
    measured_volts = 3.3 * float(adc_val) / 65535
    sensor_volts = measured_volts / VDIV_Ratio
    kpa = max(0, int(sensor_volts * 200 - 100))     # 200 is 800 / delta v, ie 4.5 - 0.5
    # print(f"ADC value: {adc_val=}")
    return kpa
     
def current_time()-> str:
    now   = secs_to_localtime(time.time())          # getcurrent time, convert to local SA time
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
            print(f"Unknown tuple: key {key}, val {val}")
            return False, -1
    else:
        print(f"Expected tuple... didn't get one.  Got {rply}")
        return False, False

def transmit_and_pause(msg, delay):
    global radio

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
    global clock_adjust_ms
    return(local_time + clock_adjust_ms)

def borepump_ON():
    if SIMULATE_PUMP:
        print(f"{display_time(secs_to_localtime(time.time()))} SIM Pump ON")
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
        print(f"{display_time(secs_to_localtime(time.time()))} SIM Pump OFF")
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
        eventring[eventindex] = (current_time(), msg)
    else:
        if len(eventring) < EVENTRINGSIZE:
#            print("Appending...")
            eventring.append((str_time, msg))
            eventindex = (eventindex + 1) % EVENTRINGSIZE
        else:
            eventindex = (eventindex + 1) % EVENTRINGSIZE
#            print(f"Overwriting index {eventindex}")
            eventring[eventindex] = (current_time(), msg)

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
                if len(s) > 0: print(f"Event log {i}: {s[0]} {s[1]}")
        else:
            i = (eventindex - 1) % EVENTRINGSIZE            # start with last log entered
            for k in range(EVENTRINGSIZE):
                s = eventring[i]
                if len(s) > 0: print(f"Event log {i}: {s[0]} {s[1]}")
                i = (i - 1) % EVENTRINGSIZE
    else:
        print("Eventring empty")
    
def raiseAlarm(param, val):

    logstr = f"{event_time} ALARM {param}, value {val:.3g}"
    ev_str = f"ALARM {param}, value {val:.3g}"
    print(logstr)
    ev_log.write(f"{logstr}\n")
    add_to_event_ring(ev_str)
    
def checkForAnomalies():
    global borepump, max_ROC, depth_ROC, tank_is, bp_kpa

    if borepump.state:                  # pump is ON
        if op_mode == OP_MODE_IRRIGATE and  kpa_sensor_armed and bp_kpa < config_dict["Min Pressure"]:
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
    add_to_event_ring("ABORT!!")
    ev_log.write(logstr + "\n")
    lcd.clear()
    lcd.setCursor(0,0)
    lcd.printout(str_time)
    lcd.setCursor(0,1)
    lcd.printout("MAINTENANCE MODE")
    op_mode = OP_MODE_MAINT

def check_for_critical_states() -> None:
    str_NP = "No pressure"
    if borepump.state:              # pump is ON
        run_minutes = (time.time() - borepump.last_time_switched) / 60

        if kpa_sensor_armed:        # if we have a pressure sensor, check for critical values
            if bp_kpa > config_dict["Max Pressure"]:
                raiseAlarm("Excess kPa", bp_kpa)
                abort_pumping()

            if bp_kpa < config_dict[str_NP]:
                raiseAlarm(str_NP, bp_kpa)
                abort_pumping()
        if run_minutes > config_dict["Max RunMins"]:            # if pump is on, and has been on for more than max... do stuff!
            raiseAlarm("RUNTIME EXCEEDED", run_minutes)
            borepump_OFF()

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
                    display_str = f"C{cycle_number}/{total_cycles} {disp_time} {pressure_str}"
                else:                                       # we are in OFF time... 
                    secs_to_next_ON = next_ON_cycle_time - now 
                    if secs_to_next_ON < 0:                 # there is no next ON...
                        display_str = "End TWM soon"
                        # print(f"{display_time(secs_to_localtime(now))}: {secs_to_next_ON=}")
                    else:
                        if secs_to_next_ON < 60:
                            display_str = f"Wait {cycle_number}/{total_cycles} {secs_to_next_ON}s"
                        else:
                            display_str = f"Wait {cycle_number}/{total_cycles} {int(secs_to_next_ON / 60)}m"
            else:
                display_str = "IRRIG MODE...??"

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
        if pressure_change > MAX_KPA_CHANGE:
            last_logged_kpa = bp_kpa
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

    dc: float = p.calc_duty_cycle()
    
    ev_log.write(f"Last switch time:   {display_time(secs_to_localtime(p.last_time_switched))}\n")
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

def init_ringbuffers():
    global  ringbuf, ringbufferindex, eventring, eventindex, switchring, switchindex, kparing, kpaindex

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
    kparing = [0 for _ in range(PRESSURERINGSIZE)]
    kpaindex    = 0

def init_all():
    global borepump, steady_state, free_space_KB, presspump, vbus_status, vbus_on_time, report_outage
    global display_mode, navigator, encoder_count, encoder_btn_state, enc_a_last_time, enc_btn_last_time
    global slist, program_pending, sys_start_time, rotary_btn_pressed, kpa_sensor_armed

    PS_ND = "Pressure sensor not detected"
    str_msg = "At startup, BorePump is "
    encoder_count       = 0       # to track rotary next/prevs
    enc_a_last_time     = utime.ticks_ms()
    encoder_btn_state   = False
    enc_btn_last_time   = enc_a_last_time
    rotary_btn_pressed  = False

    slist=[]

    Change_Mode(UI_MODE_NORM)
    lcd_on()  
# Get the current pump state and init my object    
    borepump = Pump("BorePump", get_initial_pump_state())

# On start, valve should now be open... but just to be sure... and to verify during testing...
    if borepump.state:
        if DEBUGLVL > 0:
            print(str_msg + "ON  ... opening valve")
        solenoid.value(0)           # be very careful... inverse logic!
    else:
        if DEBUGLVL > 0:
            print(str_msg +  "OFF ... closing valve")
        solenoid.value(1)           # be very careful... inverse logic!

    presspump = Pump("PressurePump", False)

    init_ringbuffers()                      # this is required BEFORE we raise any alarms...

    navigator.set_event_list(eventring)
    navigator.set_switch_list(switchring)
    navigator.set_program_list(program_list)

    free_space_KB = free_space()
    if free_space_KB < FREE_SPACE_LOWATER:
        raiseAlarm("Free space", free_space_KB)
        make_more_space()

# ensure we start out right...
    steady_state = False
    now = time.time()
    if vbus_sense.value():
        vbus_status = True
        vbus_on_time = now 
        report_outage = True
    else:
        vbus_status = False         # just in case we start up without main power, ie, running on battery
        vbus_on_time = now - 60 * 60        # looks like an hour ago
        report_outage = False

    display_mode = "depth"
    program_pending = False         # no program
    sys_start_time = now            # must be AFTER we set clock ...

    kpa_sensor_armed = bp_pressure.read_u16() > BP_SENSOR_MIN    # are we seeing a valid pressure sensor reading?
    if not kpa_sensor_armed:
        print(PS_ND)
        ev_log.write(f"{display_time(secs_to_localtime(time.time()))}  {PS_ND}\n")

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
    str_valve = "Turning valve "
    if state:
        if DEBUGLVL > 0: print(str_valve + "ON")
        switch_valve(borepump.state)
    else:
        if borepump.state:          # not good to turn valve off while pump is ON !!!
            raiseAlarm("Solenoid OFF Invalid - Pump is ", borepump.state )
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
                s = f"{display_time(secs_to_localtime(time.time()))}  {str_restored}\n"
                print(s)
                add_to_event_ring(str_restored)
                ev_log.write(s)
                lcd.setCursor(0,1)
                lcd.printout(str_restored)
                vbus_status = True
        else:
            if report_outage:
                s = f"{display_time(secs_to_localtime(time.time()))}  {str_lost}\n"
                print(s)
                add_to_event_ring(str_lost)
                ev_log.write(s)
                lcd.setCursor(0,1)
                lcd.printout(str_lost)
                vbus_status = False
                report_outage = False

            now = time.time()
            if (now - vbus_on_time >= MAX_OUTAGE) and report_outage:
                s = f"{display_time(secs_to_localtime(time.time()))}  Power off more than {MAX_OUTAGE} seconds\n"
                print(s)
                ev_log.write(s)  # seconds since last saw power 
                add_to_event_ring("MAX_OUTAGE")
                report_outage = True
                # housekeeping(False)
        await asyncio.sleep(1)

async def read_pressure()->None:
    global kparing, kpaindex, average_kpa

    try:
        while True:
            bpp = get_pressure()
            # print(f"Press: {bpp:>3} kPa, {kpaindex=}")
            kpaindex = (kpaindex + 1) % PRESSURERINGSIZE
            kparing[kpaindex] = bpp
            average_kpa = calc_average_pressure(KPA_AVERAGE_COUNT)
            await asyncio.sleep_ms(PRESSURE_PERIOD_MS)
    except Exception as e:
        print(f"read_pressure exception: {e}, {kpaindex=}")

async def regular_flush(flush_seconds)->None:
    while True:
        tank_log.flush()
        pp_log.flush()
        ev_log.flush()
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
    # smtp.write(f"From: {FROM_EMAIL}\r\n")
    # smtp.write(f"To: {to}\r\n")
    # smtp.write(f"Subject: {subj}\r\n")
    # smtp.write("MIME-Version: 1.0\r\n")
    # smtp.write("Content-Type: multipart/mixed; boundary=BOUNDARY\r\n")
    # smtp.write("\r\n")
    # smtp.write("--BOUNDARY\r\n")
    # smtp.write("Content-Type: text/plain\r\n")
    # smtp.write("\r\n")
    # smtp.write("Please find attached files.\r\n")
    # smtp.write("\r\n")
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
            await asyncio.sleep_ms(1000)
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
                    await send_file_list(TO_EMAIL, f"Sending {files}...", non_zero_files)
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
    global ui_mode, encoder_count, encoder_btn_state
    while True:
        if encoder_btn_state:               # button pressed
            lcd_on()                        # but set no OFF timer...stay on until I exit menu
            navmode = navigator.mode

            if ui_mode == UI_MODE_MENU:
                navmode = navigator.mode
                if navmode == "menu":
                    navigator.enter()
                elif navmode == "value_change":
                    navigator.set()
                elif "view" in navmode:        # careful... if more modes are added, ensure they contain "view"
                    navigator.go_back()
            elif ui_mode == UI_MODE_NORM:
                Change_Mode(UI_MODE_MENU)
                # ui_mode = UI_MODE_MENU
                navigator.go_to_first()
                navigator.display_current_item()
            else:
                print(f'Huh? {ui_mode=}')

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

        await asyncio.sleep_ms(menu_sleep)

async def blinkx2():
    while True:
        led.value(1)
        sleep_ms(50)
        led.value(0)
        sleep_ms(50)
        led.value(1)
        sleep_ms(50)
        led.value(0)
        await asyncio.sleep_ms(1000)

async def do_main_loop():
    global event_time, ev_log, steady_state, housetank, system, op_mode

    # start doing stuff
    buzzer.value(0)			    # turn buzzer off
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
    init_logging()          # needs corect time first!
    print(f"Main TX starting {display_time(secs_to_localtime(start_time))}")
    updateClock()				    # get DST-adjusted local time
    
    get_tank_depth()
    init_all()

    tim=Timer(period=config_dict["LCD"] * 1000, mode=Timer.ONE_SHOT, callback=lcd_off)

    str_msg = "Immediate switch pump "
    housetank.state = tank_is
    print(f"Initial tank state is {housetank.state}")
    if (housetank.state == "Empty" and not borepump.state):           # then we need to start doing somethin... else, we do NOTHING
        print(str_msg + "ON required")
    elif (borepump.state and (housetank.state == "Full" or housetank.state == "Overflow")):     # pump is ON... but...
        print(str_msg + "OFF required")
    else:
        print("No action required")

    ev_log.write(f"\nPump Monitor starting: {event_time}\n")

    # start coroutines..
    asyncio.create_task(blinkx2())                             # visual indicator we are running
    asyncio.create_task(check_lcd_btn())                       # start up lcd_button widget
    asyncio.create_task(regular_flush(FLUSH_PERIOD))           # flush data every FLUSH_PERIOD minutes
    asyncio.create_task(check_rotary_state(ROTARY_PERIOD_MS))  # check rotary every ROTARY_PERIOD_MS milliseconds
    asyncio.create_task(processemail_queue())                 # check email queue
    asyncio.create_task(read_pressure())                       # read pressure every PRESSURE_PERIOD_MS milliseconds    
    asyncio.create_task(monitor_vbus())                        # watch for power every second
    
    gc.collect()
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
    # micropython.mem_info()

    rec_num=0
    while True:
        updateClock()			                    # get datetime stuff
        updateData()			                    # monitor water depth
        check_for_critical_states()
        if op_mode != OP_MODE_MAINT:
            if op_mode != OP_MODE_IRRIGATE: 
                # if DEBUGLVL > 0: print(f"in DML, op_mode is {op_mode} controlBP() starting")
                controlBorePump()		            # do nothing if in IRRIGATE mode
    #        listen_to_radio()		                # check for badness
            DisplayData()
# experimental...
            # if op_mode != OP_MODE_IRRIGATE and rec_num % LOG_FREQ == 0:
            if rec_num % LOG_FREQ == 0:           
                LogData()			                # record it
            if steady_state: checkForAnomalies()	# test for weirdness
            rec_num += 1
            if rec_num > ROC_AVERAGE and not steady_state: steady_state = True    # just ignore data until ringbuf is fully populated
            delay_ms = config_dict["Delay"] * 1000
            if heartbeat():                         # send heartbeat if ON... not if OFF.  For now, anyway
                delay_ms -= RADIO_PAUSE
        # print(f"{event_time} main loop: {rec_num=}, {op_mode=}, {steady_state=}")
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