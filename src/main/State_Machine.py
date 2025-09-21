# Combined three files into one to work around circular import dependency
# while still providing the desired naming of states and events 21/9/2025

class State(object):
    """
    We define a state object which provides some utility functions for the
    individual states within the state machine.
    """

    def __init__(self):
        print ('Current state:', str(self))

    def on_event(self, event):
        """
        Handle events that are delegated to this State.
        """
        pass

    def __repr__(self):
        """
        Leverages the __str__ method to describe the State.
        """
        return self.__str__()

    def __str__(self):
        """
        Returns the name of the State.
        """
        return self.__class__.__name__
    

class SimpleDevice(object):
    """ 
    A simple state machine that mimics the functionality of a device from a 
    high level.
    """
    STATE_PICO_READY    = 'READY'
    STATE_PICO_RESET    = 'PicoReset'
    STATE_WIFI_READY    = 'WIFI_READY'
    STATE_CLOCK_SET     = 'CLOCK_SET'
    STATE_COMMS_READY   = 'COMMS_READY'

    # and also list all events...
    SM_EV_ON_REQ        = 'ON REQ'
    SM_EV_ON_ACK        = 'ON ACK'
    SM_EV_ON_NAK        = 'ON NAK'
    SM_EV_OFF_REQ       = 'OFF REQ'
    SM_EV_OFF_ACK       = 'OFF ACK'
    SM_EV_OFF_NAK       = 'OFF NAK'
    SM_EV_COMMS_ACK     = 'ACK COMMS'
    SM_EV_WIFI_ACK      = 'ACK WIFI'
    SM_EV_NTP_ACK       = 'ACK NTP'

    SM_EV_SYS_START     = 'START MONITORING'

    def __init__(self):
        """ Initialize the components. """

        # Start with a default state.
        self.state = PicoReset()

    def on_event(self, event):
        """
        This is the bread and butter of the state machine. Incoming events are
        delegated to the given states which then handle the event. The result is
        then assigned as the new state.
        """

        # The next state will be the result of the on_event function.
        self.state = self.state.on_event(event)
        # print(f">> FSM: {str(self.state)}")
        #     
class PicoReset(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_WIFI_ACK:    # 'ACK WIFI':
            return WIFI_READY()
        return self
    
class WIFI_READY(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_NTP_ACK:     # 'ACK NTP':
            return CLOCK_SET()
        return self

class CLOCK_SET(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_COMMS_ACK:   # 'ACK COMMS':
            return COMMS_READY()
        return self
    
class COMMS_READY(State):
# Initial state on start-up 

    def on_event(self, event):
        # if event == 'CLK SYNC':
        #     return CLOCK_SYNCED()
        if event == SimpleDevice.SM_EV_SYS_START:
            return READY()
        return self
            
class CLOCK_SYNCED(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_SYS_START:
            return READY()
        return self
                
class READY(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_ON_REQ:
            return PumpPendingON()
        if event == SimpleDevice.SM_EV_ON_ACK:
            return PumpON()
        if event == SimpleDevice.SM_EV_ON_NAK:
            return self
        if event == SimpleDevice.SM_EV_OFF_REQ:
            return PumpPendingOFF()
        if event == SimpleDevice.SM_EV_OFF_ACK:
            return PumpOFF()
        if event == SimpleDevice.SM_EV_OFF_NAK:
            return self
        return self

class PumpPendingON(State):
# Request to turn ON sent... waiting confirmation

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_ON_ACK:
            return PumpON()
        if event == SimpleDevice.SM_EV_ON_NAK:
            return READY()
        return self
    
class PumpON(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_OFF_REQ:
            return PumpPendingOFF()
        return self
    
class PumpPendingOFF(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_OFF_ACK:
            return PumpOFF()
        if event == SimpleDevice.SM_EV_OFF_NAK:
            return PumpON()
        return self
    
class PumpOFF(State):
# Initial state on start-up 

    def on_event(self, event):
        if event == SimpleDevice.SM_EV_ON_REQ:
            return PumpPendingON()
        return self
               
# End of our states.
