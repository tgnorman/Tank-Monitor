# my_states.py

from SM_state import State

# Start of our states
    
class PicoReset(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'ACK WIFI':
            return WIFI_READY()
        return self
    
class WIFI_READY(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'ACK NTP':
            return CLOCK_SET()
        return self

class CLOCK_SET(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'ACK COMMS':
            return COMMS_READY()
        return self
    
class COMMS_READY(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'ACK SYNC':
            return CLOCK_SYNCED()
        return self
            
class CLOCK_SYNCED(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == 'START_MONITORING':
            return READY()
        return self
                
class READY(State):
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
            return READY()
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