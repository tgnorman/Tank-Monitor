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
        self.loglist = None
        self.log_index = 0          # for log scrolling
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
            if self.new_value == 0:
                print("Setting new_value to default...")
                self.new_value = item['value']['Default_val']
            self.new_value += 5
            print(f'In NEXT self.new_value is {self.new_value}')
            self.device.setCursor(0, 1)
            self.device.printout(str(self.new_value) + "      ")
        elif self.mode == "view_history":
            if self.loglist is not None:
                self.log_index = (self.log_index + 1) % len(self.loglist)     # check if this is right
                hist_str = self.loglist[self.log_index]
                print(f'in NEXT can I see loglist index {self.log_index} is {hist_str}')
                self.device.setCursor(0, 1)
                self.device.printout(f'{hist_str:<15}')
            else:
                print("in NEXT loglist is None")
                self.device.setCursor(0, 1)
                self.device.printout("Loglist is None")

    def previous(self):
        if self.mode == "menu":
            menu_len = len(self.current_level[-1]["items"])
            # if self.current_index < len(self.current_level[-1]["items"]) - 1:
            self.current_index = (self.current_index - 1) % menu_len
            # if self.current_index > 0:
                # self.current_index -= 1
            self.display_current_item()
        elif self.mode == "value_change":
            item = self.get_current_item()
            # if item['value']['Working_val'] == 0:
            if self.new_value == 0:
                self.new_value = item['value']['Default_val']
            if self.new_value > 5:
                self.new_value -= 5
                print(f'In PREV self.new_value is {self.new_value}')
                self.device.setCursor(0, 1)
                self.device.printout(str(self.new_value) + "      ")
        elif self.mode == "view_history":
            if self.loglist is not None:
                self.log_index = (self.log_index - 1) % len(self.loglist)     # check if this is right
                hist_str = self.loglist[self.log_index]
                print(f'in PREV can I see loglist index {self.log_index} is {hist_str}')
                self.device.setCursor(0, 1)
                self.device.printout(f'{hist_str:<15}')
            else:
                print("in PREV loglist is None")
                self.device.setCursor(0, 1)
                self.device.printout("Loglist is None")
    
    def go_back(self):
        if len(self.current_level) > 1:
            self.current_level.pop()  # Go up one level in the menu
            self.current_index = 0
            self.mode = "menu"
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
            elif "show_" in action:
                print("--> Setting mode to view_history")
                self.mode = "view_history"
            else:
    #             if "BACK" in action.upper():
    # #                print("Going up a level...")
    #                 self.go_back()
    #             else:
                print(f"Executing action: {item['action']}")
        elif "value" in item:
            self.mode = "value_change"
            param = item['title']
            val = item['value']
            print(f'In ENTER {param} = {val}')
        else:
            print("No further levels or actions available.")
    
        print(f"In ENTER, mode is now {self.mode}")

    def set(self):
        item = self.get_current_item()
#        param = item['title']
#        val = self.new_value
#        print(f'New {param} = {val}')
        print(f'In SET before change, item is: {item}')
        item['value']['Working_val'] =  self.new_value
        print(f'In SET after  change, item is: {item}')

        self.new_value = 0          # reset this, or we copy previous remnant value
        self.mode = "menu"

    def set_log_list(self, myloglist):
        self.loglist = myloglist
        # print(f'set_log_list: {self.loglist}')