# This class assumes a menu containing entries with a title, possibly a list of sub-menu items, and items can have an action associated
# The action, if a string, will just be printed (for debugging purposes), but if it is a callable function, it will be called

from RGB1602 import RGB1602

DEBUG = True

class MenuNavigator:
    def __init__(self, menu, dev:RGB1602):
        self.menu = menu
        # self.current_level = [menu]  # Stack to keep track of menu levels
        self.current_level = [{'submenu': menu, 'index': 0}]  # Stack to keep track of menu levels
        self.current_index = 0
        # self.prev_index = 0
        self.device = dev
        self.mode = "menu"
        self.new_value = 0
        self.eventlist = None
        self.event_index = 0          # for log scrolling
        self.switchlist = None
        self.switch_index = 0
        self.programlist = None
        self.program_index = 0
        self.filelist = None
        self.file_index = 0
        self.kpalist = None
        self.kpa_index = 0
        self.display_current_item()

    # def get_current_item(self):
    #     return self.current_level[-1]["items"][self.current_index]
    def get_current_item(self):
        current = self.current_level[-1]
        return current['submenu']["items"][self.current_index]
    
    def display_current_item(self):
        item = self.get_current_item()
        self.device.clear()
        self.device.setCursor(0,0)
        self.device.printout(item['title'])
        # print(item['title'])
        if "value" in item:
            self.device.setCursor(0, 1)
            self.device.printout(item['value']['W_V'])
#        print("Current Item: ", item)
#        print(f"Current Item: {item['title']}")

    def next(self):
        print(f"In NEXT, {self.mode=}")
        if self.mode == "menu":
            # menu_len = len(self.current_level[-1]["items"])
            # if self.current_index < len(self.current_level[-1]["items"]) - 1:
            current = self.current_level[-1]
            menu_len = len(current['submenu']["items"])
            self.current_index = (self.current_index + 1) % menu_len
            current['index'] = self.current_index
            self.display_current_item()
        elif self.mode == "value_change":
            item = self.get_current_item()
            print(f'In NEXT, item is {item}')
            # if item['value']['W_V'] == 0:
            # if self.new_value == 0:
            #     print("Setting new_value to default...")
            #     self.new_value = item['value']['D_V']
            step = item['value']['Step']
# no if neeed for inc...            
            self.new_value += step
            print(f'In NEXT self.new_value is {self.new_value}')
            self.device.setCursor(0, 1)
            self.device.printout(str(self.new_value) + "      ")
        elif "view_" in self.mode: #self.mode == "view_events" or self.mode == "view_switch":
            # print(f'In NEXT {self.mode=}')
            if self.mode == "view_events":
                if self.eventlist is not None:
                    if len(self.eventlist) > 0:
                        hist_str = self.eventlist[self.event_index]
                        self.event_index = (self.event_index + 1) % len(self.eventlist)
                else:
                    hist_str = "Eventlist: None"
            elif self.mode == "view_switch":
                if self.switchlist is not None:
                    if len(self.switchlist) > 0:
                        hist_str = self.switchlist[self.switch_index]
                        self.switch_index = (self.switch_index + 1) % len(self.switchlist)
                else:
                    hist_str = "Switchlist: None"
            elif self.mode == "view_program":
                if self.programlist is not None:
                    if len(self.programlist) > 0:
                        self.program_index = (self.program_index + 1) % len(self.programlist)
                        prog_name = self.programlist[self.program_index][0]
                        prog_duration = self.programlist[self.program_index][1]["run"]
                        prog_wait = self.programlist[self.program_index][1]["off"]
                        prog_str = f'Run {prog_duration} Off {prog_wait}'
                        hist_str = tuple((prog_name, prog_str))
                        # print(f'In NEXT {hist_str=}')
                else:
                    hist_str = "Prog list: None"
            elif self.mode == "view_files":
                if self.filelist is not None:
                    if len(self.filelist) > 0:
                        self.file_index = (self.file_index + 1) % len(self.filelist)
                        hist_str = self.filelist[self.file_index]
                else:
                    hist_str = "File list: None"
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
        else:
            print(f"In NEXT, {self.mode=}")
            self.device.setCursor(0, 1)
            self.device.printout(f'{self.mode=}')

    def previous(self):
        print(f'In PREV, {self.mode=}')
        if self.mode == "menu":
            # menu_len = len(self.current_level[-1]["items"])
            # if self.current_index < len(self.current_level[-1]["items"]) - 1:
            current = self.current_level[-1]
            menu_len = len(current['submenu']["items"])
            self.current_index = (self.current_index - 1) % menu_len
            current['index'] = self.current_index
            self.display_current_item()
        elif self.mode == "value_change":
            item = self.get_current_item()
            print(f'In PREV, item is {item}')
            # if item['value']['W_V'] == 0:
            # if self.new_value == 0:
            #     print("Setting new_value to default...")
            #     self.new_value = item['value']['D_V']
            step = item['value']['Step']
            if self.new_value >= step:
                self.new_value -= step
                print(f'In PREV self.new_value is {self.new_value}')
                self.device.setCursor(0, 1)
                self.device.printout(str(self.new_value) + "      ")
        elif "view_" in self.mode:  #self.mode == "view_events" or self.mode == "view_switch":
            # print(f'In PREV {self.mode=}')
            if self.mode == "view_events":
                if self.eventlist is not None:
                    if len(self.eventlist) > 0:
                        hist_str = self.eventlist[self.event_index]
                        self.event_index = (self.event_index - 1) % len(self.eventlist)     # check if this is right
                else:
                    hist_str = "Eventlist: None"
            elif self.mode == "view_switch":
                if self.switchlist is not None:
                    if len(self.switchlist) > 0:
                        hist_str = self.switchlist[self.switch_index]
                        self.switch_index = (self.switch_index - 1) % len(self.switchlist)     # check if this is right
                else:
                    hist_str = "Switchlist: None"
            elif self.mode == "view_program":
                if self.programlist is not None:
                    if len(self.programlist) > 0:
                        self.program_index = (self.program_index - 1) % len(self.programlist)
                        prog_name = self.programlist[self.program_index][0]
                        prog_duration = self.programlist[self.program_index][1]["run"]
                        prog_wait = self.programlist[self.program_index][1]["off"]
                        prog_str = f'Run {prog_duration} Off {prog_wait}'
                        hist_str = tuple((prog_name, prog_str))
                    # print(f'In PREV {hist_str=}')
                else:
                    hist_str = "Prog list: None"
            elif self.mode == "view_files":
                if self.filelist is not None:
                    if len(self.filelist) > 0:
                        self.file_index = (self.file_index - 1) % len(self.filelist)
                        hist_str = self.filelist[self.file_index]
                else:
                    hist_str = "File list: None"
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
        else:
            print(f"In PREV, {self.mode=}")
            self.device.setCursor(0, 1)
            self.device.printout(f'{self.mode=}')
    
    def go_back(self):
        if len(self.current_level) > 1:
            self.current_level.pop()  # Go up one level in the menu
            # self.current_index = self.prev_index
                # Restore previous level's index
            self.current_index = self.current_level[-1]['index']
            self.mode = "menu"
            self.new_value = 0
#            print(f"Going back to previous menu level {len(self.current_level)}")
            self.display_current_item()
        else:
            print("Already at the top-level menu.  This should not happen...")
            self.device.setCursor(0, 1)
            self.device.printout("Cant go back")

    def enter(self):
        item = self.get_current_item()
        if "items" in item:
            # self.current_level.append(item)  # Go deeper into the submenu
            # self.prev_index = self.current_index
            # Save both menu and current index
            self.current_level.append({
                'submenu': item,
                'index': 0
            })
            self.current_index = 0
#            print(f"Entering {item['title']} submenu - level {len(self.current_level)}")
            self.display_current_item()
        elif "action" in item:
            action = item['action']
            if callable(action):
                action()                # do it...
            else:
                print(f"Simulate Executing action: {item['action']}")
        elif "value" in item:
            self.mode = "value_change"
            param = item['title']
            val = item['value']
            self.new_value = item['value']['W_V']
            print(f'In ENTER {param} = {val}')
        else:
            print(f"Unknown type in item... check menu def.  {item}")
    
        # print(f"In ENTER, mode is now {self.mode}")

    def set(self):
        item = self.get_current_item()
#        param = item['title']
#        val = self.new_value
#        print(f'New {param} = {val}')
        print(f'In SET before change, item is: {item}')
        if item['value']['W_V'] !=  self.new_value and self.new_value > 0:
            item['value']['W_V'] =  self.new_value
            print(f"In SET, updated Working Value to {self.new_value}")
        # print(f'In SET after  change, item is: {item}')

        self.new_value = 0          # reset this, or we copy previous remnant value
        self.mode = "menu"

    def set_default(self):
        print("Setting default value")
        item = self.get_current_item()
        def_val = item['value']['D_V']
        item['value']['W_V'] = def_val
        print(f"Default value set to {def_val}")
        
        self.new_value = 0          # reset this, or we copy previous remnant value
        self.mode = "menu"

    def goto_position(self, first=True):
        if "view_" in self.mode:  #self.mode == "view_events" or self.mode == "view_switch":
            print(f'In goto_position {self.mode=}, {first=}')
            if self.mode == "view_events":
                if self.eventlist is not None:
                    if len(self.eventlist) > 0:
                        pos = 0 if first else len(self.eventlist) - 1
                        self.event_index = pos
                        hist_str = self.eventlist[self.event_index]
                else:
                    hist_str = "Eventlist: None"
            elif self.mode == "view_switch":
                if self.switchlist is not None:
                    if len(self.switchlist) > 0:
                        pos = 0 if first else len(self.switchlist) - 1
                        self.switch_index = pos
                        hist_str = self.switchlist[self.switch_index]
                else:
                    hist_str = "Switchlist: None"
            elif self.mode == "view_program":
                if self.programlist is not None:
                    if len(self.programlist) > 0:
                        pos = 0 if first else len(self.programlist) - 1
                        self.program_index = pos
                        prog_name = self.programlist[self.program_index][0]
                        prog_duration = self.programlist[self.program_index][1]["run"]
                        prog_wait = self.programlist[self.program_index][1]["off"]
                        prog_str = f'Run {prog_duration} Off {prog_wait}'
                        hist_str = tuple((prog_name, prog_str))
                    # print(f'In PREV {hist_str=}')
                else:
                    hist_str = "Prog list: None"
            elif self.mode == "view_files":
                if self.filelist is not None:
                    if len(self.filelist) > 0:
                        pos = 0 if first else len(self.filelist) - 1
                        self.file_index = pos
                        hist_str = self.filelist[self.file_index]
                else:
                    hist_str = "File list: None"
            if type(hist_str) == tuple:
                if(len(hist_str) > 0):
                    datestamp = hist_str[0]
                    log_txt   = hist_str[1]
                else:
                    datestamp = f'{self.mode:<16}'
                    log_txt   = "Nothing here"
            else:
                datestamp = "Err in FIRST"
                log_txt   = "hist not a tuple"

            self.device.setCursor(0, 0)
            self.device.printout(f'{datestamp:<16}')
            self.device.setCursor(0, 1)
            self.device.printout(f'{log_txt:<16}')
        else:
            self.device.setCursor(0, 1)
            self.device.printout("Not in VIEW mode")

    def goto_first(self):
        self.goto_position(True)

    def goto_last(self):
        self.goto_position(False)

    def set_event_list(self, myeventlist):
        self.eventlist = myeventlist

    def set_switch_list(self, myswitchlist):
        self.switchlist = myswitchlist

    def set_program_list(self, mylist):
        if self.programlist is not None:
            del self.programlist           # clean up old stuff...
        self.programlist = mylist

    def set_file_list(self, mylist):
        if self.filelist is not None:
            del self.filelist           # clean up old stuff...
        self.filelist = mylist

    def set_kpa_list(self, mylist):
        if self.kpalist is not None:
            del self.kpalist           # clean up old stuff...  
        self.kpalist = mylist
        
    def go_to_first(self):
        self.current_index = 0
