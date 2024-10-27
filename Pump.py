# My first real OO class...
#from PiicoDev_Transceiver import PiicoDev_Transceiver... no radio stuff yet

import time

class Pump:
    def __init__(self, start_state):            # ability to start in ON state... need to sync with RX on startup
        self.state = start_state
        self.last_time_switched = 0             # localtime tuple would be nice... but need to write a decoder
        self.cum_seconds_on = 0
        self.num_switch_events = 0
#        self.radio = PiicoDev_Transceiver()
        print("New pump created")
        self.showstate()

    def showstate(self):
        if self.state:
            print("Pump is ON")
        else:
            print("Pump is OFF")

    def switch_pump(self, new_state):           # allow for starting in ON state
#        print(f"In switch_pump state is {self.state} and new_state is {new_state}")
#        tx_str = "ON" if new_state else "OFF"
        
        if new_state != self.state:
#            print("sending " + tx_str)
#            self.radio.send(tx_str)
#            self.update_pump_state(new_state)
            time_now = time.time()
            if self.state:			# then we were ON, now switching OFF... calc time we were ON
                time_on_secs = time_now - self.last_time_switched
                self.cum_seconds_on += time_on_secs
            self.state = new_state
            self.last_time_switched = time_now
            self.num_switch_events += 1
#        else:
#            print("Nothing to do")
        
