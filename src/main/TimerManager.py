import time
from machine import Timer

class TimerManager:
    def __init__(self):
        self.timers = {}          # Store Timer objects
        self.schedules = {}       # Store scheduled trigger times
        self.callbacks = {}       # Store original callbacks

    def create_timer(self, name: str, period: int, callback, mode=Timer.ONE_SHOT) -> Timer:
        """Create a timer with tracking of scheduled trigger time"""
        self.cancel_timer(name)
        
        # Store original callback and schedule time
        self.callbacks[name] = callback
        self.schedules[name] = time.time() + int(period / 1000)  # Convert ms to seconds.  The int() is CRITICAL
        
        # Create and store timer
        self.timers[name] = Timer(period=period, mode=mode, callback=callback)  # type: ignore
        return self.timers[name]

    def is_pending(self, name: str) -> bool:
        """Check if timer exists and hasn't triggered yet"""
        return (name in self.schedules and 
                self.schedules[name] >= time.time())

    def get_time_remaining(self, name: str) -> int:
        """Get seconds remaining until timer triggers"""
        if not self.is_pending(name):
            return 0
        return self.schedules[name] - time.time()

    def delay_timer(self, name: str, delay_seconds: int) -> None:
        """Delay a pending timer by specified seconds"""
        if not self.is_pending(name):
            return
            
        # Calculate new trigger time and period
        remaining = self.get_time_remaining(name)
        new_period = int(remaining + delay_seconds)  # Convert to ms
        
        # Update schedule and recreate timer
        self.schedules[name] = time.time() + new_period
        self.timers[name].deinit()
        self.timers[name] = Timer(
            period=new_period * 1000, 
            mode=Timer.ONE_SHOT,
            callback=self.callbacks[name]
        )   # type: ignore

    def cancel_timer(self, name: str) -> None:
        """Cancel and clean up a timer"""
        if name in self.timers:
            self.timers[name].deinit()
            del self.timers[name]
            del self.schedules[name]
            del self.callbacks[name]

    def cancel_all(self) -> None:
        """Cancel and clean up all active timers"""
        for name in list(self.timers.keys()):
            self.cancel_timer(name)