# This class assumes a menu containing entries with a title, possibly a list of sub-menu items, and items can have an action associated
# The action, if a string, will just be printed (for debugging purposes), but if it is a callable function, it will be called
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