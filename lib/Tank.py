# All things pertaining to the house tank at 82...

class Tank:
    def __init__(self, start_state):   
        self.state = start_state
        self.depth = 0
        self.last_depth = 0
        self.height = 2600
        self.radius = 1620              # in millimetres...
        self.overfull = 300
        self.min_dist = 400
        self.max_dist = 1200
        self.delta = 50
        self.depth_ROC = 0
        self.min_ROC = 150              # ROC changes in mm/minute
        self.max_ROC = 400
        self.valve_state = False        # state of solenoid ball-valve
        self.fill_states = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]
        self.sensor_offset = 40

