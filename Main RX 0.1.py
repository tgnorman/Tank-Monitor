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

RADIO_PAUSE = 1000

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
    print(f"sending fail msg {msg}")
    radio.send(msg)
    sleep_ms(RADIO_PAUSE)
    
def confirm_state(req, period) -> bool:		# test if reality agrees with last request
    expected_crosses = period / 50			# 50Hz...
    min_crosses = expected_crosses / 2		# allow for some inaccuracies...
    period_count = count_next_period(period)
    if req:				# request was to switch ON... count better be well above zero!
        if period_count > min_crosses:
            print(f'Counted {period_count} pulses.. confirmed pump is indeed ON')
            return True
        else:
            print(f'Gak!... Only saw {period_count} pulses in {period} milliseconds.  FAIL')
#            sleep_ms(RADIO_PAUSE)
            send_fail(req)
            sleep_ms(RADIO_PAUSE)
            return False
    else:				# request was to switch OFF... count should be close to zero...
        if period_count < min_crosses:
            print(f'Counted {period_count} pulses.. confirmed pump is indeed OFF')
            return True
        else:
            print(f'Zounds!... Saw {period_count} pulses in {period} milliseconds.  FAIL')
#            sleep_ms(RADIO_PAUSE)
            send_fail(req)
            sleep_ms(RADIO_PAUSE)
            return False
            
def check_state(period) -> bool:
    expected_crosses = period / 50			# 50Hz...
    min_crosses = expected_crosses / 2		# allow for some inaccuracies...
    period_count = count_next_period(period)
    if period_count > min_crosses:
        return True
    else:
        return False

def switch_relay(state):
    global pump_state
    if state:
        bore_ctl.value(1)			# turn borepump OFF to start
        led.value(1)
    else:
        bore_ctl.value(0)			# turn borepump OFF to start
        led.value(0)
    pump_state = state			# keep track of state... for confirmation tests
    state_changed = True

# OK, initialise control pins
led 		= Pin('LED', Pin.OUT, value=0)
bore_ctl 	= Pin(18, Pin.OUT, value=0)
detect 		= Pin(22, Pin.IN, Pin.PULL_UP)
# create transceiver object, default params should be fine.  Uses 922 MHz, 15200 Baud
radio = PiicoDev_Transceiver()
pump_state = False

def init_radio():
    global radio
    
    print("Initialising radio...")
    if radio.receive():
        msg = radio.message
        print(f"Read {msg}")
    else: print("nothing received in init")
    
def main():
    global bore_ctl, detect, led, pump_state

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
                        radio.send(resp_txt)
                        sleep_ms(RADIO_PAUSE)
                        print(f"REPLY: {resp_txt}")
                elif isinstance(message, tuple):
                    print("Received tuple: ", message[0], message[1])
                    if message[0] == "OFF":
    #                    bore_ctl.value(0)			# turn borepump OFF
    #                    led.value(0)
                        if pump_state:		# pump is ON.. take action
                            switch_relay(False)
                            print(f"OFF: Switching pump OFF at {message[1]}")
                        else:
                            print("Ignoring OFF... already OFF")
                    elif message[0] == "ON":
                        if not pump_state:		# pump is OFF.. take action
                            switch_relay(True)
                            print(f"ON: Switching pump ON at {message[1]}")
                        else:
                            print("Ignoring ON... already ON")
                    else:
                        print("WTF is message[0]?")
            else:
                message = ""
            # sleep for a bit... to allow pump circuits to settle down.  5 mains cycles should be plenty...
            sleep_ms(1000)		# a real quick sleep... until I sort asynch, or threads..
            if state_changed:			#test if the request is reflected in the detect circuit
                confirm_state(pump_state, 500)
                state_changed = False			# reset so we don't keep sending same data if nothing switched

    except KeyboardInterrupt:
        print("Turning pump OFF on KeyboardInterupt")
        switch_relay(0)

# Do the kosher check for main
if __name__ == '__main__':
    main()