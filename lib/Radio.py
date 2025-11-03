# a class to create an abstract radio device with in/out buffers
from queue import Queue  # Peter Hinch's queue

class My_Radio():
    def __init__(self, device):
        self.device = device
        self.status = True
        self.incoming_queue = Queue()
        self.outgoing_queue = Queue()
        self.packets_in     = 0
        self.packets_out    = 0

    def read(self):
        pass

    def write(self, msg):
        pass