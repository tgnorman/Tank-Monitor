# This module's purpose is to:
#   1) Listen for pump control messages on radio from Transmitter
#   2) Take action requested
#   3) Confirm if action was implemented
#   4) Report failures.  Success is otherwise assumed ??

# Subtask: set up the Detect logic with an interupt handler that counts zero crossings
# Try starting a counter on a change event, let run for say 1 second, return number
#  Assumption:  switch state events are spaced well apart.

#
# Keep this side REALLY BASIC... no extra stuff that is not essential
#
# Don't 
from PiicoDev_Transceiver import PiicoDev_Transceiver
from PiicoDev_Unified import sleep_ms
from machine import Pin
import time
import network
import ntptime
from secrets import MyWiFi
from utils import now_time_short, now_time_long, format_secs_short, format_secs_long, now_time_tuple

# Configure your WiFi SSID and password
wf          = MyWiFi()
ssid        = wf.ssid
password    = wf.password

DEBUGLVL    = 0                        # Multi-level debug for better analysis. 0:None, 1: Some, 2:Lots

# region  initial declarations
RADIO_PAUSE = 500
LOOP_DELAY  = 400
MAX_NON_COMM_PERIOD = 60                # maximum seconds allowed between heartbeats, turn pump off if exceeded.  FAIL-SAFE
FLUSH_COUNT = 5 * 60 * 1000 / LOOP_DELAY  # flush logged data to flash every 5 minutes

# OK, initialise control pins
led 		= Pin('LED', Pin.OUT, value=0)
bore_ctl 	= Pin(18, Pin.OUT, value=0)
detect 		= Pin(22, Pin.IN, Pin.PULL_UP)

# create transceiver object, default params should be fine.  Uses 922 MHz, 15200 Baud
radio = PiicoDev_Transceiver()
# endregion

pump_state = False

def pulse_count(ch):
    global count
    count += 1

def count_next_period(mili):		# count how many crossings in the specified period in milliseconds
    global count, detect
    count = 0
    detect.irq(handler=pulse_count, trigger=Pin.IRQ_FALLING)	# turn on interupt handler
    sleep_ms(mili)
    detect.irq(handler=None)									# turn off interupt handler
    return count

def send_fail(req):
    global radio
    msg = "FAIL ON" if req else "FAIL OFF"
    if DEBUGLVL > 0: print(f"sending fail msg {msg}")
    transmit_and_pause(msg, RADIO_PAUSE)
    
def confirm_state(req, period):		            # test if reality agrees with last request
    expected_crosses = period / 50			    # 50Hz...
    min_crosses = expected_crosses / 2		    # allow for some inaccuracies...
    period_count = count_next_period(period)
    if req:				# request was to switch ON... count better be well above zero!
        if period_count > min_crosses:
            if DEBUGLVL > 1: print(f'Counted {period_count} pulses.. confirmed pump is indeed ON')
            msg = ("STATUS", 1)
            transmit_and_pause(msg, RADIO_PAUSE)
        else:
            if DEBUGLVL > 1: print(f'Gak!... Only saw {period_count} pulses in {period} milliseconds.  FAIL')
#            sleep_ms(RADIO_PAUSE)
            send_fail(req)
    else:				# request was to switch OFF... count should be close to zero...
        if period_count < min_crosses:
            if DEBUGLVL > 1: print(f'Counted {period_count} pulses.. confirmed pump is indeed OFF')
            msg = ("STATUS", 0)
            transmit_and_pause(msg, RADIO_PAUSE)
        else:
            if DEBUGLVL > 1: print(f'Zounds!... Saw {period_count} pulses in {period} milliseconds.  FAIL')
#            sleep_ms(RADIO_PAUSE)
            send_fail(req)
             
def check_state(period) -> bool:
    expected_crosses = period / 50			# 50Hz...
    min_crosses = expected_crosses / 2		# allow for some inaccuracies...
    period_count = count_next_period(period)
    return period_count > min_crosses

def switch_relay(state):
    global pump_state, state_changed
    if state:
        bore_ctl.value(1)			        # turn borepump ON to start
        led.value(1)
        logstr = f"{now_time_long()} ON\n"
    else:
        bore_ctl.value(0)			        # turn borepump OFF to start
        led.value(0)
        logstr = f"{now_time_long()} OFF\n"
    event_log.write(logstr) 
    state_changed = pump_state != state     # definitive relay state change status
    pump_state = state			            # keep track of new state... for confirmation tests

def init_radio():
    global radio, last_comms_time
    
    print("Initialising radio...")
    last_comms_time = time.time()       # not entirely true, but setting to zero triggers an immediate max silence condition
    if radio.receive():
        msg = radio.message
        if isinstance(msg, str):
            if msg == "PING":         # respond I am alive...
                resp_txt = "PING REPLY"
                print(f"REPLY: {resp_txt}")
                transmit_and_pause(resp_txt, RADIO_PAUSE)
            else:
                print(f"Read unknown message: {msg}")
    else:
        if DEBUGLVL > 0: print("nothing received in init")

def transmit_and_pause(msg, delay):
    global radio

    if DEBUGLVL > 1: print(f"RX Sending {msg}")
    radio.send(msg)
    sleep_ms(delay)

def connect_wifi():
# Connect to Wi-Fi
    global ssid, password
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.connect(ssid, password)
        while not wlan.isconnected():
            time.sleep(1)
    print('Connected to:', wlan.ifconfig())

def set_time():
# Set time using NTP server
    print("Syncing time with NTP...")
    ntptime.settime()  # This will set the system time to UTC

def init_clock():
    if time.localtime()[0] < 2024:  # if we reset, localtime will return 2021...
        connect_wifi()
        set_time()

def calculate_clock_diff() -> int:
    global radio

    count = 1
    sum_t = 0
 #   if radio.receive():
 #       junk = radio.message

    for n in range(count):
        if radio.receive():
            rcv_time = time.ticks_ms()
            m = radio.message
            if type(m) is tuple:
                if m[0] == "CLK":
                    tx_time = m[1]
                    time_diff = rcv_time - tx_time
                    sum_t += time_diff
    return int(sum_t / count)

def init_logging():
    global year, month, day, shortyear
    global f, event_log, pp_log

    now   = now_time_tuple()      # getcurrent time, convert to local SA time
    year  = now[0]
    month = now[1]
    day   = now[2]
    shortyear = str(year)[2:]
    datestr = f"{shortyear}{month:02}{day:02}"
    eventlogname = f'RX events {datestr}.txt'
    event_log = open(eventlogname, "a")

def housekeeping(close_files: bool):
    print("Flushing data to flash...")

    event_log.write(f"Receiver shutdown at {now_time_long()}\n")
    event_log.flush()
    if close_files:
        event_log.close()

def main():
    global bore_ctl, detect, led, pump_state, state_changed, last_ON_time, last_comms_time

    init_clock()
    init_logging()
    start_time = time.time()
    state_changed = False
    logstr = f"Receiver starting at {now_time_long()}\n"
    print(logstr)
    event_log.write(logstr + "\n")

    if check_state(500):             # pump is already ON...
        pump_state = True
        print("Pump is ON at start-up")
        event_log.write("Pump is ON at start-up\n")
        last_ON_time = start_time
    else:                       # pump is OFF at start...normal
        pump_state = False
        last_ON_time = 0            # fudge...
  
    init_radio()
  
    print("Listening for transmission...")

    flush_counter = 0          # do regular flushes without needing an async task, or a timer, or a division

    try:
        while True:
            if radio.receive():
                message = radio.message
                last_comms_time = time.time()
                if isinstance(message, str):
                    if DEBUGLVL > 2: print(message)
                    if message == "CHECK":
                        resp_txt = ("STATUS", 1 if check_state(500) else 0)
                        transmit_and_pause(resp_txt, RADIO_PAUSE)
                        if DEBUGLVL > 1: print(f"REPLY: {resp_txt}")
                    elif message == "PING":         # respond I am alive...
                        resp_txt = "PING REPLY"
                        transmit_and_pause(resp_txt, RADIO_PAUSE)
                        if DEBUGLVL > 1: print(f"REPLY: {resp_txt}")
                    elif message == "BABOOM":
                        if DEBUGLVL > 2: print("TX Heartbeat received")
                elif isinstance(message, tuple):
                    if DEBUGLVL > 1:
                        print("Received tuple: ", message[0], message[1])
                    if message[0] == "OFF":
                        if pump_state:		        # pump is ON.. take action
                            switch_relay(False)
                            if DEBUGLVL > 0: print(logstr)
                        else:
                            if DEBUGLVL > 1: print("Ignoring OFF... already OFF")
                    elif message[0] == "ON":
                        if not pump_state:		    # pump is OFF.. take action
                            switch_relay(True)
                            if DEBUGLVL > 0: print(logstr)
                            last_ON_time = message[1]
                        else:
                            if DEBUGLVL > 1: print("Ignoring ON... already ON")
                    elif message[0] == "CLK":
                        if DEBUGLVL > 1: print("Got CLK: ", message)
                        rcv_time = time.ticks_ms()
                        rp = message[1]
                        time_diff = rcv_time - rp
                        if DEBUGLVL > 1: print(f"time_diff: {time_diff} ms")
                        transmit_and_pause(("CLK", time_diff), 500)
                    else:                           # unrecognised tuple received...
                        print(f"WTF is message[0]? <{message[0]}>")
            else:
                message = ""         

            if state_changed:			        # test if the request is reflected in the detect circuit
                confirm_state(pump_state, 500)  # implied sleep...
                state_changed = False			# reset so we don't keep sending same data if nothing switched
            
            now = time.time()
            radio_silence_secs = now - last_comms_time
            if pump_state:
                if DEBUGLVL > 1: print(f"Radio silence period: {radio_silence_secs} seconds")
                if radio_silence_secs > MAX_NON_COMM_PERIOD:     # Houston, we have a problem...
                    logstr = f"{now_time_long()} Max radio silence period exceeded!"
                    print(logstr)
                    event_log.write(logstr + "\n")
                    switch_relay(False)             # pump_state now OFF
                    state_changed = False       # effectively go to starting loop, waiting for incoming ON/OFF or whatever
                    if DEBUGLVL > 1: print("Resetting to initial state")
            else:
                led.toggle()        # blink LED to show we are alive and waiting for a message

            if DEBUGLVL > 1: print(".", end="")    
            
            flush_counter += 1
            if flush_counter >= FLUSH_COUNT:	# do a flush every 5 minutes
                event_log.flush()
                flush_counter = 0
            
            sleep_ms(LOOP_DELAY)		    # if we did NOT do implied sleep in confirm_state... delay a bit.

    except KeyboardInterrupt:
        logstr = "\n***Turning pump OFF on KeyboardInterupt"
        print(logstr)
        event_log.write(logstr + "\n")
        switch_relay(False)
        housekeeping(True)

    except Exception as e:
        print(f"Something bad happened: {e}")

# Do the kosher check for main
if __name__ == '__main__':
    main()