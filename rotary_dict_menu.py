from machine import Pin
import utime
from utime import sleep
from MenuNavigator import MenuNavigator
import sys

# Create pins for encoder lines and the onboard button

enc_btn = Pin(18, Pin.IN, Pin.PULL_UP)
enc_a   = Pin(19, Pin.IN)
enc_b   = Pin(20, Pin.IN)
last_time = 0 # the last time we pressed the button
count = 0

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
    if (new_time - last_time) > 500:
        if enc_a.value() == enc_b.value():
            navigator.next()
        else:
            navigator.previous()
    last_time = new_time

def encoder_btn_IRQ(pin):
    global last_time

    new_time = utime.ticks_ms()
    # if it has been more that 1/5 of a second since the last event, we have a new event
    if (new_time - last_time) > 500: 
        navigator.enter()
        last_time = new_time

# Initialise the interupt to fire on rising edges
enc_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_a_IRQ)
enc_btn.irq(trigger=Pin.IRQ_FALLING, handler=encoder_btn_IRQ)
# Initialise the interupt to fire on rising edges
enc_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_a_IRQ)

# def show_help():
#     print("Help Menu Opened")

# def start_game():
#     print("Starting Game...")

# def exit_program():
#     print("Exiting Program...")

# menu_structure = {
#     "Main Menu": {
#         "Play": {"action": start_game},
#         "Help": {"action": show_help},
#         "Exit": {"action": exit_program},
#     }
# }

def display_depth():
    display_mode = "depth"
    print(f'{display_mode=}')

def display_pressure():
    display_mode = "pressure"
    print(f'{display_mode=}')

def my_exit():
    global process_menu
    process_menu = False


prod_menu_dict = {
    "title": "L0 Main Menu",
    "items": [
      {
        "title": "L1.1 Display->",
        "items": [
          { "title": "  L1.1.1 Depth", "action": display_depth},
          { "title": "  L1.1.2 Pressure", "action": display_pressure},
          { "title": "  L1.1.3 Go Back", "action":"go back"
          }
        ]
      },
      {
        "title": "L1.2 History->",
        "items": [
          { "title": "  L1.2.1 Events", "action": "Events" },
          { "title": "  L1.2.2 Depth", "action": "Depth" },
          { "title": "  L1.2.3 Pressure", "action": "Pressure" },
          { "title": "  L1.2.4 Manual Switch", "action": "Manual Switch" },
          { "title": "  L1.2.5 Timer", "action": "Timer" },
          { "title": "  L1.2.6 Stats", "action": "Stats" },
          { "title": "  L1.2.7 Go back", "action": "Go Back"}
        ]
      },
      {
        "title": "L1.3 Actions->",
        "items": [
          { "title": "  L1.3.1 Flush", "action": "Flush Data" },
          { "title": "  L1.3.2 Reset", "action": "Soft Reset" },
          { "title": "  L1.3.3 Go back", "action": "Go Back"}
        ]
      },
      {
        "title": "L1.4 Config->",
        "items": [
          { "title": "  L1.4.1 Show", "action": "Show Config" },
          { "title": "  L1.4.2 Set Config",
            "items": [
                { "title": "      L1.4.2.1 Delay", "action": "Set Delay"},
                { "title": "      L1.4.2.2 B/L Time", "action": "Set B/L Time"},
                { "title": "      L1.4.2.3 Min Depth", "action": "Set MIN"},
                { "title": "      L1.4.2.4 Max Depth", "action": "Set MAX"},
                { "title": "      L1.4.2.5 Go back", "action": "Go Back"}
            ]
          },
          { "title": "  L1.4.3 Save Config", "action": "Save Config" },
          { "title": "  L1.4.4 Load Config", "action": "Load Config" },
          { "title": "  L1.4.5 Go back", "action": "Go Back"}
        ]
      },
    {
        "title": "L1.5 Exit", "action": my_exit
    }
    ]
}

  
current_menu = menu_structure["Main Menu"]
print(f'current_menu is type {type(current_menu)}')
new_menu = prod_menu_dict
print(f'p_m_d is type {type(prod_menu_dict)}')
print(f'new_menu is type {type(new_menu)}')

# Initialize the navigator
navigator = MenuNavigator(new_menu)

print("Created navigator")
# Sample navigation sequence
navigator.display_current_item()  # Show the first item in the main menu

selection = "title"  # Simulate user input

process_menu = True
while process_menu:
    utime.sleep(0.2)

print("That's all, folks!")
#    print(count)
    # if enc_btn.value() == 0:
    #     print("Button pressed")
    # # Navigate and execute actions

    # if selection in current_menu:
    #     action = current_menu[selection].get("action")
    #     if callable(action):
    #         action()  # Call the function
    #     else:
    #         print("No action assigned to this option.")
    # else:
    #     print("Invalid selection")
    #     sleep(1)