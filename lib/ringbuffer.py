import time

class RingBuffer:
    def __init__(self, size, time_formatter=None, short_time_formatter=None, value_formatter=None, logger=print):
        self.buffer = []
        self.size = size
        self.index = -1
        self.time_formatter = time_formatter
        self.short_time_formatter = short_time_formatter
        self.value_formatter = value_formatter
        self.logger = logger  # Can be print function or file object's write method
    
    def add(self, message):
        """Basic add - no duplicate detection"""
        if not self.buffer:
            self.buffer.append((int(time.time()), message))
            self.index = 0
            return
            
        if len(self.buffer) < self.size:
            self.buffer.append((int(time.time()), message))
        else:
            self.index = (self.index + 1) % self.size
            self.buffer[self.index] = (int(time.time()), message)
        
        self.index = len(self.buffer) - 1
    
    def dump(self, short_time=False):
        if not self.buffer:
            self.logger("Buffer empty")
            return
        
        time_fmt = self.short_time_formatter if (short_time and self.short_time_formatter) else self.time_formatter
    
        entries = len(self.buffer)
        current = self.index
        
        for _ in range(entries):
            entry = self.buffer[current]
            if self.value_formatter:
                tmp = entry[1]                          # Yuk.  This scrambled code is because I now overload the tuple 2nd elemnt
                if type(tmp) == str:                    # error_ring has either an int... or an int followed by a repeat count string
                    tmp = int(tmp.split(" ")[0])        # Maybe there's a better way to do this...
                message = f"Log {current:2}: {time_fmt(entry[0])} {self.value_formatter(tmp)}\n"   # type: ignore
            else:
                message = f"Log {current:2}: {time_fmt(entry[0])} {entry[1]}\n"                         # type: ignore
            self.logger(message)
            current = (current - 1) % entries

    def get_formatted_entry(self, index, short_time=True):
        """Get a single entry formatted for display
        Args:
            index: Index of entry to format
            short_time: If True, use short time format
        Returns:
            tuple: (time_str, message_str)
        """
        buflen = len(self.buffer)
        if buflen == 0 or index >= buflen:
            return None
            
        entry = self.buffer[index]
        # Use short_time_formatter if available and requested, otherwise fall back to regular formatter
        time_fmt = self.short_time_formatter if (short_time and self.short_time_formatter) else self.time_formatter
        
        timestamp = time_fmt(entry[0])                                  # type: ignore
        message = self.value_formatter(entry[1]) if self.value_formatter else entry[1]  # entry[1] is message
        
        return (timestamp, message)

class DuplicateDetectingBuffer(RingBuffer):
    def __init__(self, size, time_limit, time_formatter=None, short_time_formatter=None, value_formatter=None, logger=print):
        super().__init__(size, time_formatter, short_time_formatter, value_formatter, logger=logger)
        self.time_limit = time_limit
        self.last_message = None
        self.last_message_time = 0
        self.repeat_count = 1
        
    def add(self, message):
        """Add with duplicate detection"""
        if not self.buffer:
            super().add(message)
            self.last_message = message
            self.last_message_time = int(time.time())
            return
            
        if message == self.last_message:
            if time.time() - self.last_message_time <= self.time_limit:
                self.repeat_count += 1
                # Update existing entry with repeat count
                self.buffer[self.index] = (self.last_message_time, 
                    f"{message} (repeated x{self.repeat_count})")
                return
                
        # Different message or time expired - add new entry
        self.repeat_count = 1
        super().add(message)
        self.last_message = message
        self.last_message_time = int(time.time())
