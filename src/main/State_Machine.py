# Combined three files into one to work around circular import dependency
# while still providing the desired naming of states and events 21/9/2025

# Refactored with suggestions from chatGPT and refinements from Claude 22/9/25.
# Needed to invoke type: ignore to shut Pylance up... hopefully the code structure is now kosher.

class State(object):
    """
    We define a state object which provides some utility functions for the
    individual states within the state machine.
    """

    def __init__(self):
        print ('Current state:', str(self))

    def on_event(self, event, context):
        """
        Handle events that are delegated to this State.
        """
        pass

    def on_enter(self, context):
        """
        For anything that should run on EVERY entry to the state
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
    
class PICO_RESET(State):
    # def on_enter(self, context):
    #     print('PICO_RESET - on_enter')
    #     super().on_enter(context)
        # context.init_wifi()         # this CANNOT work here... system object is not yet created!!

    def on_enter(self, context):
        # context.boot_required = True
        context.lcd.clear()
        context.lcd.printout('PICO_RESET')
        return self
    
    def on_event(self, event, context):
        # print(f'PICO_RESET - ON_EVENT {event}')
        if event == SimpleDevice.SM_EV_WIFI_ACK:
            return WIFI_READY()                 # use a callback to existing code...
        return self
    
class WIFI_READY(State):
    def on_enter(self, context):
        context.lcd.clear()
        context.lcd.printout('WIFI')
        # print('WIFI_READY - on_enter')
        super().on_enter(context)
    
    def on_event(self, event, context):
        # print(f'WIFI_READY - ON_EVENT {event}')
        if event == SimpleDevice.SM_EV_NTP_ACK:
            return CLOCK_SET()
        return self

class CLOCK_SET(State):
    def on_enter(self, context):
        context.lcd.clear()
        context.lcd.printout('CLOCK')
        super().on_enter(context)
        # context.init_radio()
    
    def on_event(self, event, context):
        # print('CLOCK_SET - ON_EVENT')
        if event == SimpleDevice.SM_EV_RADIO_ACK:   # 'ACK RADIO':
            return RADIO_READY()
        return self

class CLOCK_SYNCED(State):              # currently NOT USED... no synchronisation of clocks possible (for now)
# Initial state on start-up 
    def on_event(self, event, context):
        # print('CLOCK_SYNCED - ON_EVENT')
        if event == SimpleDevice.SM_EV_SYS_START:
            return READY()
        return self
        
class RADIO_READY(State):
    def on_event(self, event, context):
        context.lcd.clear()
        context.lcd.printout('RADIO')
        if event == SimpleDevice.SM_EV_SYS_START:
            return READY()
        return self
                           
class READY(State):
# Initial state on start-up 

    def on_event(self, event, context):
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
    def on_event(self, event, context):
        if event == SimpleDevice.SM_EV_ON_ACK:
            return PumpON()
        if event == SimpleDevice.SM_EV_ON_NAK:
            return READY()
        return self
    
class PumpON(State):
# Initial state on start-up 
    def on_event(self, event, context):
        if event == SimpleDevice.SM_EV_OFF_REQ:
            return PumpPendingOFF()
        return self
    
class PumpPendingOFF(State):
# Initial state on start-up 
    def on_event(self, event, context):
        if event == SimpleDevice.SM_EV_OFF_ACK:
            return PumpOFF()
        if event == SimpleDevice.SM_EV_OFF_NAK:
            return PumpON()
        return self
    
class PumpOFF(State):
# Initial state on start-up 
    def on_event(self, event, context):
        if event == SimpleDevice.SM_EV_ON_REQ:
            return PumpPendingON()
        return self
               
# End of our states.
class SimpleDevice(object):
    """ 
    A simple state machine that mimics the functionality of a device from a high level.
    """
# region constants
    STATE_PICO_RESET    = 'PICO_RESET'
    STATE_CONNECTING    = 'WIFI_CONNECTING'
    STATE_WIFI_READY    = 'WIFI_READY'
    STATE_CLOCK_SET     = 'CLOCK_SET'
    STATE_CLOCKS_SYNC   = 'CLOCKS_SYNCED'       # Not yet in use... place-holder for future work
    STATE_RADIO_READY   = 'RADIO_READY'
    STATE_PICO_READY    = 'READY'
    STATE_PICO_SLEEP    = 'SNOOZING'            # also for future implementation, with VL53L1X XSHUT
    STATE_AUTO          = 'AUTO'
    STATE_IRRIGATE      = 'IRRIGATE'
    STATE_MAINTENANCE   = 'MAINTMODE'
    STATE_DOZING        = 'DOZING'              # to better name DISABLED... when waiting to resume paused pumping
    STATE_DISABLED      = 'DISABLED'            # so...what is this now?
    STATE_MENU          = 'MENUMODE'

    STATE_PUMP_ON       = 'PUMP_ON'
    STATE_PUMP_OFF      = 'PUMP_OFF'
    STATE_PENDING_ON    = 'BP_PENDING_ON'
    STATE_PENDING_OFF   = 'BP_PENDING_OFF'

    # and also list all events...
    SM_EV_ON_REQ        = 'ON REQ'
    SM_EV_ON_ACK        = 'ON ACK'
    SM_EV_ON_NAK        = 'ON NAK'
    SM_EV_OFF_REQ       = 'OFF REQ'
    SM_EV_OFF_ACK       = 'OFF ACK'
    SM_EV_OFF_NAK       = 'OFF NAK'
    SM_EV_RADIO_ACK     = 'RADIO ACK'
    SM_EV_WIFI_ACK      = 'WIFI ACK'
    SM_EV_NTP_ACK       = 'NTP ACK'

    SM_EV_SYS_INIT      = 'SYS INIT'
    SM_EV_SYS_START     = 'START MONITORING'
# endregion
    def __init__(self, context):
        self.version = '24/9/2025'
        self.context = context
        self.state = PICO_RESET()            # NOTE: when my SimpleDevice instance is created, start in state PICO_RESET
        self.state.on_enter(context)

    def on_event(self, event):
        """
        This is the bread and butter of the state machine. Incoming events are
        delegated to the given states which then handle the event. The result is
        then assigned as the new state.

        TN added on_enter, to provide a means to 'do stuff' when a new state is entered.
        *** IMPORTANT CAVEAT:   NEVER, NEVER, add code in on_enter that directly OR indirectly triggers events or state changes !!!
        Strictly for passive stuff... initialise an attribute etc.  Basic, simple logic only!
        """
        # The next state will be the result of the on_event function.
        #self.state = self.state.on_event(event, self.context)
        # print(f">> FSM: {str(self.state)}")
        new_state = self.state.on_event(event, self.context)
        if new_state is not self.state:
            self.state = new_state
            self.state.on_enter(self.context)   # type: ignore