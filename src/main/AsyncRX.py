import uasyncio as asyncio
from PiicoDev_Transceiver import PiicoDev_Transceiver
from PiicoDev_Unified import sleep_ms
from machine import Pin
import time
import network
import ntptime
from secrets import MyWiFi
from utils import now_time_long, now_time_tuple
from TM_Protocol import *

from Radio import My_Radio
# from queue import Queue  # Peter Hinch's queue

SW_VERSION      = "2/11/2025 16:18"
DEBUGLVL        = 1                     # Multi-level debug for better analysis. 0:None, 1: Some, 2:Lots

# region initial declarations
# Configure your WiFi SSID and password
wf              = MyWiFi()
ssid            = wf.ssid
password        = wf.password

# RADIO_PAUSE = 500
RADIOPOLL_MS    = 20                    # poll radio for data every x millisecs
LOOP_DELAY      = 400                   # this actually determines LED blink rate... independant of radio check frequency.  Good...
CHECK_MS        = 500                   # how long to listen for power cross interupts
MAX_NON_COMM_PERIOD = 60                # maximum seconds allowed between heartbeats, turn pump off if exceeded.  FAIL-SAFE
LOGFLUSHSECS    = 5 * 60                # every 5 minutes

# OK, initialise control pins
led 		= Pin('LED', Pin.OUT, value=0)
bore_ctl 	= Pin(18, Pin.OUT, value=0)
detect 		= Pin(22, Pin.IN, Pin.PULL_UP)

# create transceiver object, default params should be fine.  Uses 922 MHz, 15200 Baud
radio_dev   = PiicoDev_Transceiver()
radio       = My_Radio(radio_dev)

# endregion

# Queues for async communication
# incoming_queue = Queue()  # Commands from master
# outgoing_queue = Queue()  # Responses to master

pump_state  = False
radio_alive = False

# ============================================
# Original methods from MainRX
# ============================================

def pulse_count(ch):
    global count
    count += 1

def count_next_period(mili):		# count how many crossings in the specified period in milliseconds
    global count, detect
    count = 0
    detect.irq(handler=pulse_count, trigger=Pin.IRQ_FALLING)	# turn on interupt handler
    sleep_ms(mili)                  # TODO make this asynch? Has LOTS of implications... refer to Claude chat
    detect.irq(handler=None)        # turn off interupt handler
    return count

# async def send_fail(req):         # this probably should be handled by [ON|OFF|STATUS_CHK] NAK reply]
#     global radio
#     msg = "FAIL ON" if req else "FAIL OFF"
#     if DEBUGLVL > 0: print(f"queueing fail msg {msg}")
#     # transmit_and_pause(msg, RADIO_PAUSE)
#     await radio.outgoing_queue.put(msg)    
    
# def confirm_state(req, period_ms):		            # test if reality agrees with last request
#     expected_crosses = (period_ms / 1000) * 50		# corrected formula 21/9/25
#     min_crosses     = int(expected_crosses / 2)		    # allow for some inaccuracies...
#     period_count    = count_next_period(period_ms)
#     if req:				# request was to switch ON... count better be well above zero!
#         if period_count > min_crosses:
#             if DEBUGLVL > 1: print(f'Counted {period_count} pulses in {period_ms}ms.. confirmed pump is indeed ON')
#             msg = (MSG_STATUS_ACK, 1)
#             transmit_and_pause(msg, RADIO_PAUSE)
#         else:
#             if DEBUGLVL > 1: print(f'Gak!... Only saw {period_count} pulses in {period_ms} milliseconds.  FAIL')
# #            sleep_ms(RADIO_PAUSE)
#             send_fail(req)
#     else:				# request was to switch OFF... count should be close to zero...
#         if period_count < min_crosses:
#             if DEBUGLVL > 1: print(f'Counted {period_count} pulses in {period_ms}ms.. confirmed pump is indeed OFF')
#             msg = (MSG_STATUS_ACK, 0)
#             transmit_and_pause(msg, RADIO_PAUSE)
#         else:
#             if DEBUGLVL > 1: print(f'Zounds!... Saw {period_count} pulses in {period_ms} milliseconds.  FAIL')
# #            sleep_ms(RADIO_PAUSE)
#             send_fail(req)
             
def check_state(period_ms) -> bool:
    expected_crosses = (period_ms / 1000) * 50	    # changed - now has correct formula  21/9/25
    min_crosses     = int(expected_crosses / 2)		# allow for some inaccuracies...
    period_count    = count_next_period(period_ms)
    return period_count > min_crosses

def switch_relay(req)->bool:
    global pump_state, state_changed

    try:
        bore_ctl.value(1 if req else 0)         # change GPIO to activate relay
        new_state = check_state(CHECK_MS)
        if req:                                 # request is to turn ON
            if new_state:
                led.value(1)
                logstr = f"{now_time_long()} ON\n"
            else:
                raise Exception
        else:
            if not new_state:
                led.value(0)
                logstr = f"{now_time_long()} OFF\n"
            else:
                raise Exception
            
        event_log.write(logstr) 
        # state_changed = pump_state != req       # definitive relay state change status
        pump_state = new_state			          # confirms state after req processed
        return True
    
    except:
        logstr = f"{now_time_long()} SWITCH FAILURE\n"
        event_log.write(logstr) 
        return False

def init_radio():
    global radio, last_comms_time
    
    print("Initialising radio...")
    last_comms_time = time.time()       # not entirely true, but setting to zero triggers an immediate max silence condition
    if radio.device.receive():
        msg = radio.device.message
        if DEBUGLVL > 0: print(f'init_radio: discarded {msg} on init')
        # if isinstance(msg, str):
        #     if msg == MSG_PING_REQ:         # respond I am alive...
        #         resp_txt = MSG_PING_RSP
        #         print(f"REPLY: {resp_txt}")
        #         transmit_and_pause(resp_txt, RADIO_PAUSE)
        #     else:
        #         print(f"Discarding unknown message: {msg}")
    else:
        if DEBUGLVL > 0: print("nothing received in init")

# def transmit_and_pause(msg, delay):
#     global radio

#     if DEBUGLVL > 1: print(f"{now_time_long()} RX Sending {msg}")
#     radio.device.send(msg)
#     sleep_ms(delay)

def init_wifi()->bool:
    global my_IP

# Connect to Wi-Fi
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.connect(ssid, password)
        while not wlan.isconnected():
            time.sleep(1)
    my_ifconfig = wlan.ifconfig()
    my_IP = my_ifconfig[0]
    print(f'Connected to {my_IP}')
    return True

def set_time():
# Set time using NTP server
    print("Syncing time with NTP...")
    ntptime.settime()  # This will set the system time to UTC

def calculate_clock_diff() -> int:
    global radio

    count = 1
    sum_t = 0
 #   if radio.receive():
 #       junk = radio.device.message

    for n in range(count):
        if radio.device.receive():
            rcv_time = time.ticks_ms()
            m = radio.device.message
            if type(m) is tuple:
                if m[0] == MSG_CLOCK:
                    tx_time = m[1]
                    time_diff = rcv_time - tx_time
                    sum_t += time_diff
    return int(sum_t / count)

def init_logging():
    global year, month, day, shortyear
    global f, event_log, pp_log

    now   = now_time_tuple()      # getcurrent time, convert to local SA time
    year  = now[0]
    month = now[1]
    day   = now[2]
    shortyear = str(year)[2:]
    datestr = f"{shortyear}{month:02}{day:02}"
    eventlogname = f'RX events {datestr}.txt'
    event_log = open(eventlogname, "a")

def housekeeping(close_files: bool):
    print("Flushing data to flash...")

    event_log.write(f"Receiver shutdown at {now_time_long()}\n")
    if DEBUGLVL > 1: print('Before flush')
    event_log.flush()
    if close_files:
        if DEBUGLVL > 1: print('Before close()')
        event_log.close()
        if DEBUGLVL > 1: print('After close()')

def process_radio_silence(radio_silence_secs):
    
    if radio.status:        # radio is (or was) alive...
        if DEBUGLVL > 1:
            print(f"Radio silence period: {radio_silence_secs} seconds")
        logstr = f"{now_time_long()} Max radio silence period exceeded! Turning pump OFF"
        print(logstr)
        event_log.write(logstr + "\n")
        _ = switch_relay(False)         # turn pump OFF... logging handled in switch_relay
        radio.status = False            # save status.  Needs something else to throw this switch to True
        # state_changed = False         # effectively go to starting loop, waiting for incoming ON/OFF or whatever
        if DEBUGLVL > 1:
            print("Resetting to initial state")

# ============================================
# Task 1: Radio Receiver (producer)
# ============================================
async def radio_receive_task():
    global last_comms_time

    """Continuously listen for radio messages and put them in queue"""
    while True:
        if radio.device.receive():  # Check if message waiting
            radio.status = True     # update status, needed for heartbeat check
            message = radio.device.message
            last_comms_time = time.time()
            if DEBUGLVL > 1: print(f'r_r_t: {message}')
            await radio.incoming_queue.put(message)
        await asyncio.sleep_ms(RADIOPOLL_MS)  # Don't hog CPU

# ============================================
# Task 2: Command Processor (consumer/producer)
# ============================================
async def command_processor_task():
    """Process commands from queue and generate responses"""
    while True:
        command = await radio.incoming_queue.get()  # Blocks until message arrives
        
        if DEBUGLVL > 0 and command != MSG_HEARTBEAT:   # don't bother with heartbeats..
            print(f'{now_time_long()} Processing command {command}')

        if isinstance(command, tuple):      # temp hack to sort-of work with orig protocol.  
            key = command[0]
            print(f'tuple... updating command to {key}')
            command = key

        if command == MSG_STATUS_CHK:
            resp_txt = MSG_STATUS_ACK if check_state(CHECK_MS) else MSG_STATUS_NAK   # reply encodes pump status
            # status = get_current_pump_status()  # Quick sync function
            await radio.outgoing_queue.put(resp_txt)
        
        elif command == MSG_REQ_ON:
            if not pump_state:
                result = switch_relay(True)  # Quick sync function
            else:
                result = True       # already on, but ACK the request anyway
            if result:
                await radio.outgoing_queue.put(MSG_ANY_ACK)
            else:
                await radio.outgoing_queue.put(MSG_ANY_NAK)
        
        elif command == MSG_REQ_OFF:
            if pump_state:
                result = switch_relay(False)
            else:
                result = False      # already OFF, but ACK the request anyway
            if result:
                await radio.outgoing_queue.put(MSG_ANY_ACK)
            else:
                await radio.outgoing_queue.put(MSG_ANY_NAK)
        
        elif command == MSG_PING_REQ:
            resp_txt = MSG_PING_RSP
            await radio.outgoing_queue.put(resp_txt)
            if DEBUGLVL > 1:
                print("Ping received and replied")
        
        elif command == MSG_HEARTBEAT:
            pass
            # resp_txt = MSG_HEART_RPLY
            # await radio.outgoing_queue.put(resp_txt)
            # if DEBUGLVL > 1:
            #     print("TX Heartbeat received")
        
        else:
            print(f"Unknown command: {command}")

# ============================================
# Task 3: Radio Transmitter (consumer)
# ============================================
async def radio_transmit_task():
    """Send responses from outgoing queue"""
    while True:
        message = await radio.outgoing_queue.get()  # Blocks until response ready
        if DEBUGLVL > 1: print(f'radio_tx_task: sending {message}')
        radio.device.send(message)      # NOTE: agnostic about type of message... string, tuple... whatever
        await asyncio.sleep_ms(RADIOPOLL_MS)  # Small delay between transmissions

# ============================================
# Task 4: Heartbeat Monitor (optional)
# ============================================
async def heartbeat_monitor_task():
    """Check if master is still alive"""
    
    while True:
        radio_silence_secs = time.time() - last_comms_time
        # if pump_state and radio_silence_secs > MAX_NON_COMM_PERIOD:
        if radio_silence_secs > MAX_NON_COMM_PERIOD:        # change to ALWAYS listen to radio, even when OFF
            process_radio_silence(radio_silence_secs)
        if not pump_state: led.toggle()         # blink LED to show we are alive and waiting for a message. Blink-rate depends on LOOP_DELAY
        await asyncio.sleep_ms(LOOP_DELAY)

# ============================================
# Task 5: flush logs to flash
# ============================================
async def flush_logs():
    while True:
        event_log.flush()
        await asyncio.sleep(LOGFLUSHSECS)

# ============================================
# Main Entry Point
# ============================================
def init_all():
    global state_changed, pump_state, last_ON_time
    # initialise everything that is NOT an async task
    if init_wifi(): pass
    set_time()
    init_logging()
    start_time = time.time()
    # state_changed = False
    logstr = f"\nReceiver version {SW_VERSION} starting at {now_time_long()}\n"
    print(logstr)
    event_log.write(logstr + "\n")

    if check_state(CHECK_MS):       # pump is already ON...
        pump_state = True
        print("Pump is ON at start-up")
        event_log.write("Pump is ON at start-up\n")
        last_ON_time = start_time
    else:                           # pump is OFF at start...normal
        pump_state = False
        last_ON_time = 0            # fudge...
  
    init_radio()        # maybe this should just clear the recieve buffer... start with a clean slate?  ie, NO PING reply...
                        # leave PING and  EVERYTHING else to receive-process-transmit trio
    print("Listening for transmission...")

async def async_main():
    # Start all tasks concurrently
    await asyncio.gather(
        radio_receive_task(),
        command_processor_task(),
        radio_transmit_task(),
        heartbeat_monitor_task(),
        flush_logs()
    )

def main():
    try:
# Start the async event loop
        init_all()

        asyncio.run(async_main())

    except KeyboardInterrupt:
        logstr = "\n***Turning pump OFF on KeyboardInterupt"
        print(logstr)
        event_log.write(logstr + "\n")
        switch_relay(False)
        housekeeping(True)

# Do the kosher check for main
if __name__ == '__main__':
    main()