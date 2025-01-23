# My first real OO class...

import time

class Pump:
    def __init__(self, ID, start_state):        # ability to start in ON state... need to sync with RX on startup
        self.state = start_state
        self.start_time = time.time()
        self.last_time_switched = self.start_time 	# localtime tuple would be nice... but need to write a decoder
        self.cum_seconds_on = 0					# NOTE:  Dependency on above in calc of cum_secs in switch_pump
        self.num_switch_events = 0
        self.ID = ID
#        self.radio = PiicoDev_Transceiver()
        print(f"New pump {ID} created")
        self.showstate()

    def calc_duty_cycle(self)->float:
        time_now = time.time()
        total_time = time_now - self.start_time
        dc = self.cum_seconds_on/total_time * 100
        print(f"Duty cycle of {self.ID} is: {dc:.2f}%")
        return dc

    def showstate(self):
        if self.state:
            print(f"Pump {self.ID}  is ON")
        else:
            print(f"Pump {self.ID} is OFF")
#        print(f"Pump {self.ID} has been on for {self.cum_seconds_on} seconds")
#        print(f"Total {self.num_switch_events} switch events for pump {self.ID}")

    def switch_pump(self, new_state):           # allow for starting in ON state
#        print(f"In switch_pump state is {self.state} and new_state is {new_state}")
#        tx_str = "ON" if new_state else "OFF"
#        print(f"In switch_pump: state is {self.state}, new_state is {new_state}")
        if new_state != self.state:				# OK... changing state
#            print("Updating pump attributes!")
            time_now = time.time()
            if self.state:					# then we were ON, now switching OFF... calc time we were ON
                self.cum_seconds_on += time_now - self.last_time_switched
            self.state = new_state
            self.last_time_switched = time_now
            self.num_switch_events += 1
#        else:
#            print("Nothing to do")
        
