"""
Really basic comms protocol definition... to be shared between TX and RX modules
"""

MSG_PING_REQ    = 'PING'
MSG_PING_RSP    = 'PING REPLY'
MSG_STATUS_RSP  = 'STATUS'
MSG_CHECK       = 'CHECK'
MSG_HEARTBEAT   = 'BABOOM'

MSG_REQ_ON      = 'ON'
MSG_REQ_OFF     = 'OFF'

MSG_CLOCK       = 'CLK'
MSG_ERROR       = 'FAIL'

# Basic Pico Tranceiver stuff...
RADIO_PAUSE     = 500