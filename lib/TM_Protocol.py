"""
Really basic comms protocol definition... to be shared between TX and RX modules
"""

MSG_PING_REQ    = 'PING'
MSG_PING_RSP    = 'PING ACK'
# MSG_STATUS_RSP  = 'STATUS'
MSG_STATUS_CHK  = 'CHECK'
MSG_HEARTBEAT   = 'BABOOM'
# MSG_HEART_RPLY  = 'ALIVE'

MSG_STATUS_ACK  = "STAT ACK"
MSG_STATUS_NAK  = "STAT NAK"

MSG_REQ_ON      = 'ON'
MSG_REQ_OFF     = 'OFF'

MSG_ON_ACK      = "ON ACK"
MSG_ON_NAK      = "ON NAK"

MSG_OFF_ACK     = "OFF ACK"
MSG_OFF_NAK     = "OFF NAK"

MSG_ANY_ACK     = "ACK"
MSG_ANY_NAK     = "NAK"

MSG_CLOCK       = 'CLK'
MSG_ERROR       = 'FAIL'

# Basic Pico Tranceiver stuff...
RADIO_PAUSE     = 300       # full async app should not need or use this!
TIMEOUT_MS      = 1000      # 1 second roundtrip, or else call it a NAK.   Max PING is ~100ms, allowing for overhead, 1 sec is HUGE 
                            # HOWEVER... in SYNC version, with 400ms loop delay, worst-case round-trip could be > 800 ms... so check this 