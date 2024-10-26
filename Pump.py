# My first real OO class...
from PiicoDev_Transceiver import PiicoDev_Transceiver

import time

class Pump:
    def __init__(self):
        self.state = False
        self.last_time_switched = (0, 0, 0, 0, 0, 0, 0, 0)
        self.cum_seconds_on = 0
        self.num_switch_events = 0
        self.radio = PiicoDev_Transceiver()
        print("New pump created")
        self.showstate()

    def showstate(self):
        if self.state:
            print("Pump is ON")
        else:
            print("Pump is OFF")

    def get_timestamp(self, rtc):
        pass

    def switch_pump(self, new_state):
#        print(f"In switch_pump state is {self.state} and new_state is {new_state}")
        tx_str = "ON" if new_state else "OFF"
        time_now = time.time()
        if new_state != self.state:
            print("sending " + tx_str)
            self.radio.send(tx_str)
#            self.update_pump_state(new_state)
            
            if self.state:			# then we were ON, now switching OFF... calc time we were ON
                time_on_secs = time_now - time.mktime(self.last_time_switched)
                self.cum_seconds_on += time_on_secs
            self.state = new_state
            self.last_time_switched = time_now
            self.num_switch_events += 1
#        else:
#            print("Nothing to do")
        
