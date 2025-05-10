# A bit over the top... but might simplify some things.

_fill_states = ["Overflow", "Full", "Near full", "Part full", "Near Empty", "Empty"]

class Tank:
        def __init__(self, start_state):   
            self.state = start_state
            self.depth = 0
            self.last_depth = 0
            self.height = 1600
            self.depth_ROC = 0
            self.min_ROC = 0.15
            self.max_ROC = 0.4
            self.radius = 1620              # in millimetres...
            self.valve_state = False        # state of solenoid ball-valve

