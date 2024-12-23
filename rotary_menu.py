# A demo of a multi-level menu with contol using ONLY rotary encoder

import json
from machine import Pin
#from utime import sleep, ticks_ms
import utime

enc_btn = Pin(18, Pin.IN, Pin.PULL_UP)
enc_a   = Pin(19, Pin.IN)
enc_b   = Pin(20, Pin.IN)

last_time = 0 # the last time we pressed the button

menu_file:str = "menu2.json"

# Load the menu from JSON file
with open(menu_file) as f:
    menu = json.load(f)
print(f"opened JSON file {menu_file}...")

class MenuNavigator:
    def __init__(self, menu):
        self.menu = menu
        self.current_level = [menu]  # Stack to keep track of menu levels
        self.current_index = 0

    def get_current_item(self):
        return self.current_level[-1]["items"][self.current_index]

    def display_current_item(self):
        item = self.get_current_item()
        print(item['title'])
#        print("Current Item: ", item)
#        print(f"Current Item: {item['title']}")

    def next(self):
        if self.current_index < len(self.current_level[-1]["items"]) - 1:
            self.current_index += 1
            self.display_current_item()
        # else:
        #     print("End of menu reached.")

    def previous(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.display_current_item()
        # else:
        #     print("Start of menu reached.")
    
    def go_back(self):
        if len(self.current_level) > 1:
            self.current_level.pop()  # Go up one level in the menu
            self.current_index = 0
#            print(f"Going back to previous menu level {len(self.current_level)}")
            self.display_current_item()
        else:
            print("Already at the top-level menu.")

    def enter(self):
        item = self.get_current_item()
        if "items" in item:
            self.current_level.append(item)  # Go deeper into the submenu
            self.current_index = 0
#            print(f"Entering {item['title']} submenu - level {len(self.current_level)}")
            self.display_current_item()
        elif "action" in item:
            act = item['action']
            if "back" in act:
#                print("Going up a level...")
                self.go_back()
            else:
                print(f"Executing action: {item['action']}")
        else:
            print("No further levels or actions available.")



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

# Initialize the navigator
navigator = MenuNavigator(menu)

print("Created navigator")
# Sample navigation sequence
navigator.display_current_item()  # Show the first item in the main menu

while True:
    utime.sleep(0.5)
# navigator.next()  # Move to next item in the main menu
# navigator.enter()  # Enter the "Settings" submenu
# navigator.next()  # Move to next item in "Settings"
# navigator.enter()  # Enter the "Display" submenu
# navigator.go_back()  # Go back to "Settings"
# navigator.previous()  # Move to the previous item in "Settings"
# navigator.go_back()  # Go back to the main menu
