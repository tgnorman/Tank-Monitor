from machine import Pin
import utime
from utime import sleep
from MenuNavigator import MenuNavigator
import sys
import RGB1602

# Create pins for encoder lines and the onboard button

enc_btn = Pin(18, Pin.IN, Pin.PULL_UP)
enc_a   = Pin(19, Pin.IN)
enc_b   = Pin(20, Pin.IN)
last_time = 0 # the last time we pressed the button
count = 0

# for debug testing... a variable I will try t access from class Navigator method...
logring = ["first", "second", "third"]
# Define a handler function for encoder line A
# def encoder_a_IRQ(pin):
#     global count
#     if enc_a.value() == enc_b.value():
#         count += 1
#     else:
#         count -= 1

# Define a handler function for encoder line A
def encoder_a_IRQ(pin):
    global last_time

    new_time = utime.ticks_ms()
    if (new_time - last_time) > 200:
        if enc_a.value() == enc_b.value():
            navigator.next()
        else:
            navigator.previous()
    last_time = new_time

def encoder_btn_IRQ(pin):
    global last_time

    new_time = utime.ticks_ms()
    # if it has been more that 1/5 of a second since the last event, we have a new event
    mode = navigator.mode
    if (new_time - last_time) > 200:
      if mode == "menu":
          navigator.enter()
      elif mode == "value_change":
          navigator.set()
      elif mode == "view_history":
          navigator.go_back()
    last_time = new_time

def rotary_menu_mode():
    
  # Initialise the interupt to fire on rising edges
  enc_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_a_IRQ)
  enc_btn.irq(trigger=Pin.IRQ_FALLING, handler=encoder_btn_IRQ)

def display_depth():
    display_mode = "depth"
    print(f'{display_mode=}')

def display_pressure():
    display_mode = "pressure"
    print(f'{display_mode=}')

def my_exit():
    global process_menu
    process_menu = False

def set_delay():
    sleep_time = 0

def my_go_back():
    navigator.go_back()

def dump_config(menu: dict):
    for x, y in menu.items():
      print(x, y)
    # v1 = menu[' Delay']['Working_val]']
    # v2 = menu[' B/L Time']['Working_val]']
    # v3 = menu[' Min Depth']['Working_val]']
    # v4 = menu[' Max Depth']['Working_val]']
    # print(f'{v1=} {v2=} {v3=} {v4=}')

def show_events():
    pass

def show_depth():
    navigator.mode = "view_history"

def show_pressure():
    pass

def housekeeping():
    pass
           
prod_menu_dict = {
    "title": "L0 Main Menu",
    "items": [
      {
        "title": "1 Display->",
        "items": [
          { "title": "1.1 Depth", "action": display_depth},
          { "title": "1.2 Pressure", "action": display_pressure},
          { "title": "1.3 Go Back", "action": my_go_back
          }
        ]
      },
      {
        "title": "2 History->",
        "items": [
          { "title": "2.1 Events", "action": show_events},
          { "title": "2.2 Depth", "action": show_depth},
          { "title": "2.3 Pressure", "action": show_pressure},
          { "title": "2.4 Manual Switch", "action": "Manual Switch"},
          { "title": "2.5 Timer", "action": "Timer"},
          { "title": "2.6 Stats", "action": "Stats"},
          { "title": "2.7 Go back", "action": my_go_back}
        ]
      },
      {
        "title": "3 Actions->",
        "items": [
          { "title": "3.1 Flush", "action": housekeeping},
          { "title": "3.2 Reset", "action": "Soft Reset"},
          { "title": "3.3 Go back", "action": my_go_back}
        ]
      },
      {
        "title": "4 Config->",
        "items": [
          { "title": "4.1 Set Config->",
            "items": [
                { "title": " Delay",     "value": {"Default_val": 15,   "Working_val" : 0}},
                { "title": " B/L Time",  "value": {"Default_val": 20,   "Working_val" : 0}},
                { "title": " Min Depth", "value": {"Default_val": 400,  "Working_val" : 0}},
                { "title": " Max Depth", "value": {"Default_val": 1700, "Working_val" : 0}},
                { "title": " Go back",  "action": my_go_back}
            ]
          },
          { "title": "4.2 Save Config", "action": "Save Config"},
          { "title": "4.3 Load Config", "action": "Load Config"},
          { "title": "4.4 Go back", "action": my_go_back}
        ]
      },
    {
        "title": "5 Exit", "action": my_exit
    }
    ]
}
  
new_menu = prod_menu_dict

# Initialize the navigator
lcd 		= RGB1602.RGB1602(16,2)
lcd.clear()
navigator = MenuNavigator(new_menu, lcd)

print("Created navigator")
# Sample navigation sequence

rotary_menu_mode()
navigator.display_current_item()  # Show the first item in the main menu
navigator.set_log_list(logring)

process_menu = True
while process_menu:
    utime.sleep(0.2)

print("That's all, folks!")
lcd.clear()
lcd.setRGB(0,0,0)
# print("new_menu Dump:")
# dump_config(new_menu)