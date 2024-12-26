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
        self.paramval = 0
        self.new_value = 0
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
            self.device.printout(item['value'])
#        print("Current Item: ", item)
#        print(f"Current Item: {item['title']}")

    def next(self):
        if self.mode == "menu":
            if self.current_index < len(self.current_level[-1]["items"]) - 1:
                self.current_index += 1
                self.display_current_item()
        else:
            item = self.get_current_item()
            if self.new_value == 0:
                self.new_value = item['value']
            self.new_value += 5
            self.device.setCursor(0, 1)
            self.device.printout(str(self.new_value) + "      ")

    def previous(self):
        if self.mode == "menu":
            if self.current_index > 0:
                self.current_index -= 1
                self.display_current_item()
        else:
            item = self.get_current_item()
            if self.new_value == 0:
                self.new_value = item['value']
            if self.new_value > 5:
                self.new_value -= 5
                self.device.setCursor(0, 1)
                self.device.printout(str(self.new_value) + "      ")
    
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
            action = item['action']
            if callable(action):
                action()                # do it...
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
            print(f' {param} = {val}')

        else:
            print("No further levels or actions available.")
    
    def set(self):
        item = self.get_current_item()
#        param = item['title']
#        val = self.new_value
#        print(f'New {param} = {val}')
        item['value'] = self.new_value
#        print(item)
        self.mode = "menu"