class TankError:
    # Error IDs as class attributes
    BASELINE_LOW        = 0
    PRESSUREDROP        = 1
    BELOW_ZONE_MIN      = 2
    MAX_ROC_EXCEEDED    = 3
    OVERFLOW_ON         = 4
    FILLWHILE_OFF       = 5
    DRAINWHILE_ON       = 6
    VALVE_CLOSED        = 7
    EXCESS_KPA          = 8
    NO_PRESSURE         = 9
    RUNTIME_EXCEEDED    = 10
    NOFREESPACE         = 11
    NOVALVEOFFWHILEON   = 12
    HFKPA_ZONEMAX       = 13
    ZONE_NOTFOUND       = 14
    AVG_KPA_ZERO        = 15

    def __init__(self):
        # Define all error details in initialization
        self._errors = {
            self.BASELINE_LOW:      ("BLLO", "Baseline is low"),
            self.PRESSUREDROP:      ("DROP", "Pressure dropped"),
            self.BELOW_ZONE_MIN:    ("BZM", "Below zone minimum"),
            self.MAX_ROC_EXCEEDED:  ("MRX", "Max ROC exceeded"),
            self.OVERFLOW_ON:       ("OVWO", "Overflow still ON"),
            self.FILLWHILE_OFF:     ("FWO", "Filling while OFF"),
            self.DRAINWHILE_ON:     ("DWO", "Drain while ON"),
            self.VALVE_CLOSED:      ("GVC", "Gatevalve closed"),
            self.EXCESS_KPA:        ("XSP", "Excess pressure"),
            self.NO_PRESSURE:       ("NOP", "No pressure"),
            self.RUNTIME_EXCEEDED:  ("RTX", "Runtime exceeded"),
            self.NOFREESPACE:       ("NFS", "No Free Space"),
            self.NOVALVEOFFWHILEON: ("NGVO", "Cant turn GV off"),
            self.HFKPA_ZONEMAX:     ("ZMXX", "Zone MAX exceeded"),
            self.ZONE_NOTFOUND:     ("ZNF", "Zone not found"),
            self.AVG_KPA_ZERO:      ("AKP0", "Avg kPa zero")
        }
    
    def get_code(self, error_id):
        """Returns short code for the error"""
        return self._errors.get(error_id, ("???", "Unknown"))[0]
    
    def get_description(self, error_id):
        """Returns full description of the error"""
        return self._errors.get(error_id, ("???", "Unknown"))[1]