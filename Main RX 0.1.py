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

DEBUG = False

RADIO_PAUSE = 500
LOOP_DELAY  = 400

# OK, initialise control pins
led 		= Pin('LED', Pin.OUT, value=0)
bore_ctl 	= Pin(18, Pin.OUT, value=0)
detect 		= Pin(22, Pin.IN, Pin.PULL_UP)
# create transceiver object, default params should be fine.  Uses 922 MHz, 15200 Baud
radio = PiicoDev_Transceiver()
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
    if DEBUG: print(f"sending fail msg {msg}")
    transmit_and_pause(msg, RADIO_PAUSE)
    
def confirm_state(req, period):		# test if reality agrees with last request
    expected_crosses = period / 50			# 50Hz...
    min_crosses = expected_crosses / 2		# allow for some inaccuracies...
    period_count = count_next_period(period)
    if req:				# request was to switch ON... count better be well above zero!
        if period_count > min_crosses:
            if DEBUG: print(f'Counted {period_count} pulses.. confirmed pump is indeed ON')
            msg = ("STATUS", 1)
            transmit_and_pause(msg, RADIO_PAUSE)
        else:
            if DEBUG: print(f'Gak!... Only saw {period_count} pulses in {period} milliseconds.  FAIL')
#            sleep_ms(RADIO_PAUSE)
            send_fail(req)

    else:				# request was to switch OFF... count should be close to zero...
        if period_count < min_crosses:
            if DEBUG: print(f'Counted {period_count} pulses.. confirmed pump is indeed OFF')
            msg = ("STATUS", 0)
            transmit_and_pause(msg, RADIO_PAUSE)
        else:
            if DEBUG: print(f'Zounds!... Saw {period_count} pulses in {period} milliseconds.  FAIL')
#            sleep_ms(RADIO_PAUSE)
            send_fail(req)
             
def check_state(period) -> bool:
    expected_crosses = period / 50			# 50Hz...
    min_crosses = expected_crosses / 2		# allow for some inaccuracies...
    period_count = count_next_period(period)
    if period_count > min_crosses:
        return True
    else:
        return False

def switch_relay(state):
    global pump_state, state_changed
    if state:
        bore_ctl.value(1)			# turn borepump OFF to start
        led.value(1)
    else:
        bore_ctl.value(0)			# turn borepump OFF to start
        led.value(0)
    pump_state = state			# keep track of state... for confirmation tests
    state_changed = True

def init_radio():
    global radio
    
    print("Initialising radio...")
    if radio.receive():
        msg = radio.message
        if isinstance(msg, str):
            if msg == "PING":         # respond I am alive...
                resp_txt = "PING REPLY"
                transmit_and_pause(resp_txt, RADIO_PAUSE)
                print(f"REPLY: {resp_txt}")
            else:
                print(f"Read unknown message: {msg}")
    else:
        if DEBUG: print("nothing received in init")

def transmit_and_pause(msg, delay):
    global radio

    radio.send(msg)
    sleep_ms(delay)

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
    
def main():
    global bore_ctl, detect, led, pump_state, state_changed

#Initialise state vars

    print("Switching bore pump OFF...")
    switch_relay(False)
    state_changed = False		# override initial state
  
#   print("Resetting radio...")
#   radio.rfm69_reset
    init_radio()
    
    print("Listening for transmission...")

    try:
        while True:
            if radio.receive():
                message = radio.message
        #        print(message)
                if isinstance(message, str):
                    print(message)
                    if message == "CHECK":
                        resp_txt = ("STATUS", 1 if check_state(500) else 0)
                        transmit_and_pause(resp_txt, RADIO_PAUSE)
                        print(f"REPLY: {resp_txt}")
                    elif message == "PING":         # respond I am alive...
                        resp_txt = "PING REPLY"
                        transmit_and_pause(resp_txt, RADIO_PAUSE)
                        print(f"REPLY: {resp_txt}")
                elif isinstance(message, tuple):
                    if DEBUG: print("Received tuple: ", message[0], message[1])
                    if message[0] == "OFF":
    #                    bore_ctl.value(0)			# turn borepump OFF
    #                    led.value(0)
                        if pump_state:		# pump is ON.. take action
                            switch_relay(False)
                            print(f"OFF: Switching pump OFF at {display_time(secs_to_localtime(message[1]))}")
                        else:
                            if DEBUG: print("Ignoring OFF... already OFF")
                    elif message[0] == "ON":
                        if not pump_state:		# pump is OFF.. take action
                            switch_relay(True)
                            print(f"ON: Switching pump ON at {display_time(secs_to_localtime(message[1]))}")
                        else:
                            if DEBUG: print("Ignoring ON... already ON")
                            state_changed = True        # YUK... tricks other code into sending confirmation
                            # This necessary as if I start TX when pump is already ON... I don't acknowledge, so TX stays in pump_is_off state
                    else:
                        print("WTF is message[0]?")
            else:
                message = ""         

            if state_changed:			#test if the request is reflected in the detect circuit
                confirm_state(pump_state, 500)
                state_changed = False			# reset so we don't keep sending same data if nothing switched
            else:
                sleep_ms(LOOP_DELAY)		# a real quick sleep... until I sort asynch, or threads..

    except KeyboardInterrupt:
        print("\n***Turning pump OFF on KeyboardInterupt")
        switch_relay(0)

# Do the kosher check for main
if __name__ == '__main__':
    main()