# This class assumes a menu containing entries with a title, possibly a list of sub-menu items, and items can have an action associated
# The action, if a string, will just be printed (for debugging purposes), but if it is a callable function, it will be called

from RGB1602 import RGB1602

class MenuNavigator:
    def __init__(self, menu, dev:RGB1602):
        self.menu = menu
        self.current_level = [menu]  # Stack to keep track of menu levels
        self.current_index = 0
        self.device = dev
        self.mode = "menu"
        self.new_value = 0
        self.eventlist = None
        self.event_index = 0          # for log scrolling
        self.switchlist = None
        self.switch_index = 0
        self.display_current_item()

    def get_current_item(self):
        return self.current_level[-1]["items"][self.current_index]

    def display_current_item(self):
        item = self.get_current_item()
        self.device.clear()
        self.device.setCursor(0,0)
        self.device.printout(item['title'])
        print(item['title'])
        if "value" in item:
            self.device.setCursor(0, 1)
            self.device.printout(item['value']['Working_val'])
#        print("Current Item: ", item)
#        print(f"Current Item: {item['title']}")

    def next(self):
        if self.mode == "menu":
            menu_len = len(self.current_level[-1]["items"])
            # if self.current_index < len(self.current_level[-1]["items"]) - 1:
            self.current_index = (self.current_index + 1) % menu_len
            self.display_current_item()
        elif self.mode == "value_change":
            item = self.get_current_item()
            print(f'In NEXT, item is {item}')
            # if item['value']['Working_val'] == 0:
            # if self.new_value == 0:
            #     print("Setting new_value to default...")
            #     self.new_value = item['value']['Default_val']
            step = item['value']['Step']
# no if neeed for inc...            
            self.new_value += step
            print(f'In NEXT self.new_value is {self.new_value}')
            self.device.setCursor(0, 1)
            self.device.printout(str(self.new_value) + "      ")
        elif self.mode == "view_events" or self.mode == "view_switch":
            if self.mode == "view_events":
                if self.eventlist is not None:
                    hist_str = self.eventlist[self.event_index]
                    self.event_index = (self.event_index + 1) % len(self.eventlist)
                else:
                    hist_str = "Eventlist: None"
            elif self.mode == "view_switch":
                if self.switchlist is not None:
                    hist_str = self.switchlist[self.switch_index]
                    self.switch_index = (self.switch_index + 1) % len(self.switchlist)
                else:
                    hist_str = "Switchlist: None"
            if type(hist_str) == tuple:
                if(len(hist_str) > 0):
                    datestamp = hist_str[0]
                    log_txt   = hist_str[1]
                else:
                    datestamp = f'{self.mode:<16}'
                    log_txt   = "Nothing here"
            else:
                datestamp = "Err in NEXT"
                log_txt   = "hist not a tuple"

            self.device.setCursor(0, 0)
            self.device.printout(f'{datestamp:<16}')
            self.device.setCursor(0, 1)
            self.device.printout(f'{log_txt:<16}')

    def previous(self):
        if self.mode == "menu":
            menu_len = len(self.current_level[-1]["items"])
            # if self.current_index < len(self.current_level[-1]["items"]) - 1:
            self.current_index = (self.current_index - 1) % menu_len
            self.display_current_item()
        elif self.mode == "value_change":
            item = self.get_current_item()
            print(f'In PREV, item is {item}')
            # if item['value']['Working_val'] == 0:
            # if self.new_value == 0:
            #     print("Setting new_value to default...")
            #     self.new_value = item['value']['Default_val']
            step = item['value']['Step']
            if self.new_value > step:
                self.new_value -= step
                print(f'In PREV self.new_value is {self.new_value}')
                self.device.setCursor(0, 1)
                self.device.printout(str(self.new_value) + "      ")
        elif self.mode == "view_events" or self.mode == "view_switch":
            if self.mode == "view_events":
                if self.eventlist is not None:
                    hist_str = self.eventlist[self.event_index]
                    self.event_index = (self.event_index - 1) % len(self.eventlist)     # check if this is right
                else:
                    hist_str = "Eventlist: None"
            elif self.mode == "view_switch":
                if self.switchlist is not None:
                    hist_str = self.switchlist[self.switch_index]
                    self.switch_index = (self.switch_index - 1) % len(self.switchlist)     # check if this is right
                else:
                    hist_str = "Switchlist: None"
            if type(hist_str) == tuple:
                if(len(hist_str) > 0):
                    datestamp = hist_str[0]
                    log_txt   = hist_str[1]
                else:
                    datestamp = f'{self.mode:<16}'
                    log_txt   = "Nothing here"
            else:
                datestamp = "Err in PREV"
                log_txt   = "hist not a tuple"

            self.device.setCursor(0, 0)
            self.device.printout(f'{datestamp:<16}')
            self.device.setCursor(0, 1)
            self.device.printout(f'{log_txt:<16}')
    
    def go_back(self):
        if len(self.current_level) > 1:
            self.current_level.pop()  # Go up one level in the menu
            self.current_index = 0
            self.mode = "menu"
            self.new_value = 0
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
            action = item['action']
            if callable(action):
                action()                # do it...
            else:
                print(f"Executing action: {item['action']}")
        elif "value" in item:
            self.mode = "value_change"
            param = item['title']
            val = item['value']
            self.new_value = item['value']['Working_val']
            print(f'In ENTER {param} = {val}')
        else:
            print("No further levels or actions available.")
    
        # print(f"In ENTER, mode is now {self.mode}")

    def set(self):
        item = self.get_current_item()
#        param = item['title']
#        val = self.new_value
#        print(f'New {param} = {val}')
        # print(f'In SET before change, item is: {item}')
        if item['value']['Working_val'] !=  self.new_value and self.new_value > 0:
            item['value']['Working_val'] =  self.new_value
            print(f"In SET, updated Working Value to {self.new_value}")
        # print(f'In SET after  change, item is: {item}')

        self.new_value = 0          # reset this, or we copy previous remnant value
        self.mode = "menu"

    def set_event_list(self, myeventlist):
        self.eventlist = myeventlist

    def set_switch_list(self, myswitchlist):
        self.switchlist = myswitchlist

    def go_to_first(self):
        self.current_index = 0
