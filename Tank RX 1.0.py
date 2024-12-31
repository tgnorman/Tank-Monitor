# My Tank monitor... RECEIVER side
#from PiicoDev_VL53L1X import PiicoDev_VL53L1X
#from PiicoDev_RV3028 import PiicoDev_RV3028
#import RGB1602
from time import sleep
from machine import I2C, Pin, ADC # Import Pin
from PiicoDev_Transceiver import PiicoDev_Transceiver
from PiicoDev_Unified import sleep_ms

#import secrets
# Configure your WiFi SSID and password
#ssid = secrets.ssid_s
#password = secrets.password_s

# Create PiicoDev sensor objects

#First... I2C devices
#distSensor 	= PiicoDev_VL53L1X()
#rtc 		= PiicoDev_RV3028() # Initialise the RTC module, enable charging
#lcd 		= RGB1602.RGB1602(16,2)
radio = PiicoDev_Transceiver()		# get some comms...

# Pins
#backlight 	= Pin(6, Pin.IN)			# check if IN is correct!
temp_sensor = ADC(4)			# Internal temperature sensor is connected to ADC channel 4
bore_ctl 	= Pin(18, Pin.OUT)
bore_sense 	= Pin(22, Pin.IN)	# or should this be ADC()?
#buzzer 		= Pin(16, Pin.OUT)
#presspmp 	= Pin(15,Pin.IN)		# or should this be ADC()?
#prsspmp_led = Pin(14, Pin.OUT)
#pot 	   = ADC(Pin(26))			# read a voltage... simulate pump current detector

# Misc stuff
conv_fac 	= 3.3 / 65535
Min_Voltage = 0.5

# New state... .
fill_states = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]

#Tank_Height = 1700
#OverFull	= 150
#Min_Dist    = 200       # full
#Max_Dist    = 1000      # empty
#Delta       = 50        # change indicating pump state change has occurred

# Various constants
mydelay = 5				# Sleep time... seconds, not ms...
log_freq = 5
depth = 0
last_depth = 0
last_logged_depth = 0
min_log_change_m = 0.1		# to save space... only write to file if significant change in level
level_init = False 		# to get started
depth_ROC = 0
max_ROC = 0.4			# change in meters/minute

# start doing stuff
#buzzer.value(0)			# turn buzzer off
bore_ctl.value(0)			# turn borepump OFF to start
#lcd.clear()
#rtc.getDateTime()

#tod   = rtc.timestamp()
#year  = tod.split()[0].split("-")[0]
#month = tod.split()[0].split("-")[1]
#day   = tod.split()[0].split("-")[2]
#shortyear = year[2:]

#daylogname = f'tank {shortyear}{month}{day}.txt'
#f = open(daylogname, "a")

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
    depth_ROC = abs(depth - last_depth) / (mydelay / 60)	# ROC in m/minute
#    print(f"depth_ROC: {depth_ROC:.3f}")
    last_depth = depth				# track change since last reading
    depth = (Tank_Height - d) / 1000
    tank_is = get_fill_state(d)
    depth_str = f"{depth:.2f}m " + tank_is

def updateClock():
    global str_time
    tod   = rtc.timestamp()
    month = tod.split()[0].split("-")[1]
    day   = tod.split()[0].split("-")[2]
    short_time = tod.split()[1]
    str_time = month + "/" + day + " " + short_time    

def controlBorePump():
    global tank_is
    if tank_is == fill_states[0]:		# Overfull
        buzzer.value(1)			# raise alarm
    else:
        buzzer.value(0)
    if tank_is == fill_states[len(fill_states) - 1]:		# Empty
        bore_ctl.value(1)			# switch borepump ON, will also show LED 
    elif tank_is == fill_states[0] or tank_is == fill_states[1]:	# Full or Overfull
        bore_ctl.value(0)			# switch borepump OFF

def raiseAlarm(xxx):
    print(f"Yikes! This looks bad... abnormal {xxx} detected: ")
    
def checkForAnomalies(roc):
    global max_ROC
#    print(f'ROC is {roc:.2f} in CFA...')
    if roc > max_ROC:
        raiseAlarm("ROC")
    
def displayAndLog():
    global log_freq
    global rec_num
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
#        print(f"depth:{depth} last_logged_depth:{last_logged_depth} level_change: {level_change}")
        if level_change > min_log_change_m:
            last_logged_depth = depth
            f.write(logstr)      
#    print(str(rec_num) + ": " + dbgstr)
    print(dbgstr)

rec_num=0

while True:
    if radio.receive():
        message = radio.message
        print(message)
    sleep_ms(50)
