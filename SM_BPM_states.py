# my_states.py

from SM_state import State

# Start of our states
    
class PicoReset(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'OFF REQ':
            return WIFI_READY()
        return self
    
class WIFI_READY(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'OFF REQ':
            return CLOCK_SYNC()
        return self
    
class CLOCK_SYNC(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'OFF REQ':
            return Init()
        return self
                
class Init(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'ON REQ':
            return PumpPendingON()
        if event == "ON ACK":
            return PumpON()
        if event == "ON NAK":
            return self
        if event == "OFF REQ":
            return PumpPendingOFF()
        if event == "OFF ACK":
            return PumpOFF()
        if event == "OFF NAK":
            return self
        return self

class PumpPendingON(State):
# Request to turn ON sent... waiting confirmation

    def on_event(self, event):
        if event == 'ON ACK':
            return PumpON()
        if event == "ON NAK":
            return Init()
        return self
    
class PumpON(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'OFF REQ':
            return PumpPendingOFF()
        return self
    
class PumpPendingOFF(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'OFF ACK':
            return PumpOFF()
        if event == "OFF NAK":
            return PumpON()
        return self
    
class PumpOFF(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'ON REQ':
            return PumpPendingON()
        return self
    
# End of our states.