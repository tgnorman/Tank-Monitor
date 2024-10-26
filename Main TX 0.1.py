#from PiicoDev_BME280 import PiicoDev_BME280
#from PiicoDev_VEML6030 import PiicoDev_VEML6030
from PiicoDev_VL53L1X import PiicoDev_VL53L1X
from PiicoDev_RV3028 import PiicoDev_RV3028
from PiicoDev_Transceiver import PiicoDev_Transceiver
import RGB1602
from time import sleep
from PiicoDev_Unified import sleep_ms
from machine import I2C, Pin, ADC # Import Pin

#import secrets
# Configure your WiFi SSID and password
#ssid = secrets.ssid_s
#password = secrets.password_s

# Create PiicoDev sensor objects

#First... I2C devices
distSensor 	= PiicoDev_VL53L1X()
rtc 		= PiicoDev_RV3028() # Initialise the RTC module, enable charging
lcd 		= RGB1602.RGB1602(16,2)

radio = PiicoDev_Transceiver()
RADIO_PAUSE = 1000

# Pins
temp_sensor = ADC(4)			# Internal temperature sensor is connected to ADC channel 4
backlight 	= Pin(6, Pin.IN)			# check if IN is correct!
#bore_ctl 	= Pin(18, Pin.OUT)
#bore_sense 	= Pin(22, Pin.IN)	# or should this be ADC()?
buzzer 		= Pin(16, Pin.OUT)
presspmp 	= Pin(15,Pin.IN)		# or should this be ADC()?
prsspmp_led = Pin(14, Pin.OUT)
#pot 	   = ADC(Pin(26))			# read a voltage... simulate pump current detector

# Misc stuff
conv_fac 	= 3.3 / 65535
Min_Voltage = 0.5

# New state... .
fill_states = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]
borepump_is_on = False 		# init to True... ie assume on, take action to turn off
BP_state_changed = False
Tank_Height = 1600
OverFull	= 150
Min_Dist    = 200       # full
Max_Dist    = 1000       # empty
Delta       = 50        # change indicating pump state change has occurred

# Various constants
mydelay = 5				# Sleep time... seconds, not ms...
log_freq = 5
depth = 0
last_depth = 0
last_logged_depth = 0
min_log_change_m = 0.1		# to save space... only write to file if significant change in level
level_init = False 		# to get started
depth_ROC = 0
max_ROC = 0.4			# change in metres/minute
counter = 0
tup = ""

# start doing stuff
buzzer.value(0)			# turn buzzer off
#bore_ctl.value(0)			# turn borepump OFF to start
lcd.clear()
rtc.getDateTime()

tod   = rtc.timestamp()
year  = tod.split()[0].split("-")[0]
month = tod.split()[0].split("-")[1]
day   = tod.split()[0].split("-")[2]
shortyear = year[2:]

daylogname = f'tank {shortyear}{month}{day}.txt'
f = open(daylogname, "a")

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

def log_switch_error(new_state):
    print(f">>> log_switch_error  !! {new_state}")
    
def parse_reply(rply):
    print(f"in parse arg is {rply}")
    if isinstance(rply, tuple):			# good...
        key = rply[0]
        val = rply[1]
        print(f"in parse: key={key}, val={val}")
        if key.upper() == "STATUS":
            return True, val
        else:
            print("Unknown reply from receiver")
            return False, -1
    else:
        print("Parse expected tuple... didn't get one")
        return False, False
     
def controlBorePump():
    global tank_is, counter, radio, borepump_is_on
    if tank_is == fill_states[0]:		# Overfull
        buzzer.value(1)			# raise alarm
#        borepump_is_on = True   probably best to  inquire rather than assume...
    else:
        buzzer.value(0)
    if tank_is == fill_states[len(fill_states) - 1]:		# Empty
#        bore_ctl.value(1)			# switch borepump ON, will also show LED
#        print(f"ctrlBP: tank is {tank_is}, pump_on is {borepump_is_on}")
        if not borepump_is_on:		# pump is off, we need to switch on
            counter += 1
            tup = ("ON", counter)
            print(tup)
            radio.send(tup)
            sleep_ms(RADIO_PAUSE)
            radio.send("CHECK")
            sleep_ms(RADIO_PAUSE)
            if radio.receive():
                rm = radio.message
                print(f"radio.message (rm): {rm}")
                rply = rm
                print(f"received response: rply is {rply}")
                valid_response, new_state = parse_reply(rply)
                print(f"in ctlBP: rply is {valid_response} and {new_state}")
                if valid_response and new_state > 0:
                    borepump_is_on = new_state > 0
                    print(f"Set borepump to state {borepump_is_on}")
                else:
                    log_switch_error(new_state)
            
    elif tank_is == fill_states[0] or tank_is == fill_states[1]:	# Full or Overfull
#        bore_ctl.value(0)			# switch borepump OFF
        if borepump_is_on:			# pump is ON... need to turn OFF
            counter -= 1
            tup = ("OFF", counter)
            print(tup)
            radio.send(tup)
            sleep_ms(RADIO_PAUSE)
            radio.send("CHECK")
            sleep_ms(RADIO_PAUSE)
            if radio.receive():
                rply = radio.message
                valid_response, new_state = parse_reply(rply)
                print(f"in ctlBP: rply is {valid_response} and {new_state}")
                if valid_response and not new_state:
                    borepump_is_on = False
                    print(f"Set borepump to state {borepump_is_on}")
                else:
                    log_switch_error(new_state)
                    
def raiseAlarm(xxx):
    pass
#    print(f"Yikes! This looks bad... abnormal {xxx} detected: ")
    
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
                print("Dang... something went wrong...")
        elif isinstance(msg, tuple):
            print("Received tuple: ", msg[0], msg[1])

def init_radio():
    global radio
    
    print("Initialising radio...")
    if radio.receive():
        msg = radio.message
        print(f"Read {msg}")
    else: print("nothing received in init")
    
rec_num=0
#radio.rfm69_reset

init_radio()
print("Starting MAIN")

try:
    while True:
        updateClock()			# get datetime stuff
        updateData()			# monitor water epth
        controlBorePump()		# do whatever
#        listen_to_radio()		# check for badness
        displayAndLog()			# record it
        checkForAnomalies(depth_ROC)	# test for weirdness
    #        rec_num += 1
        #    print(f"Sleeping for {mydelay} seconds")
        sleep(mydelay)
        
#except Exception as e:
#    print('Error occured: ', e)
except KeyboardInterrupt:
    f.flush()
    f.close()
    lcd.setRGB(0,0,0)		# turn off backlight
    print('Program Interrupted by the user')