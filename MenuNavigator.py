# This class assumes a menu containing entries with a title, possibly a list of sub-menu items, and items can have an action associated
# The action, if a string, will just be printed (for debugging purposes), but if it is a callable function, it will be called

# Added to git 30/3/2025

import time
from machine import I2C, Pin
from RGB1602 import RGB1602
from lcd_api import LcdApi
from i2c_lcd import I2cLcd

I2C_ADDR            = 0x27
I2C_NUM_ROWS        = 4
I2C_NUM_COLS        = 20
i2c                 = I2C(0, sda=Pin(8), scl=Pin(9), freq=400000)
lcd4x20             = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)

DEBUG = True

def nav_secs_to_localtime(s):
    tupltime    = time.localtime(s)
    year        = tupltime[0]
    DST_end     = time.mktime((year, 4,(7-(int(5*year/4+4)) % 7),2,0,0,0,0,0)) # Time of April   change to end DST
    DST_start   = time.mktime((year,10,(7-(int(year*5/4+5)) % 7),2,0,0,0,0,0)) # Time of October change to start DST
    
    if DST_end < s and s < DST_start:		# then adjust
#        print("Winter ... adding 9.5 hours")
        adj_time = time.localtime(s + int(9.5 * 3600))
    else:
#        print("DST... adding 10.5 hours")
        adj_time = time.localtime(s + int(10.5 * 3600))
    return(adj_time)

def LCD_time(t)-> str:
    now   = nav_secs_to_localtime(t)          # getcurrent time, convert to local SA time
    # year  = now[0]
    month = now[1]
    day   = now[2]
    hour  = now[3]
    min   = now[4]
    sec   = now[5]
    HMS = f"{hour:02}:{min:02}:{sec:02}"
    return f"{month:02}/{day:02} {HMS}"

class MenuNavigator:
    def __init__(self, menu, dev2:RGB1602): #, dev4:I2cLcd):
        self.menu = menu
        # self.current_level = [menu]  # Stack to keep track of menu levels
        self.current_level = [{'submenu': menu, 'index': 0}]  # Stack to keep track of menu levels
        self.current_index = 0
        # self.prev_index = 0
        self.LCD2R = dev2
        # self.LCD4R = lcd4x20
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
        self.errorlist = None
        self.error_index = 0
        self.display_current_item()

    # def get_current_item(self):
    #     return self.current_level[-1]["items"][self.current_index]
    def get_current_item(self):
        current = self.current_level[-1]
        return current['submenu']["items"][self.current_index]
    
    def display_current_item(self):
        item = self.get_current_item()
        self.LCD2R.clear()
        self.LCD2R.setCursor(0,0)
        self.LCD2R.printout(item['title'])

        # lcd4x20.move_to(0, 1)
        # lcd4x20.putstr(str(item['title']))
        # print(item['title'])
        if "value" in item:
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(item['value']['W_V'])

            # lcd4x20.move_to(0, 2)
            # lcd4x20.putstr(str(item['value']['W_V']))
#        print("Current Item: ", item)
#        print(f"Current Item: {item['title']}")

    def next(self):
        # print(f"In NEXT, {self.mode=}")
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
            # print(f'In NEXT, item is {item}')
            # if item['value']['W_V'] == 0:
            # if self.new_value == 0:
            #     print("Setting new_value to default...")
            #     self.new_value = item['value']['D_V']
            step = item['value']['Step']
# no if need for inc...            
            self.new_value += step
            # print(f'In NEXT self.new_value is {self.new_value}')
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(str(self.new_value) + "      ")

            # lcd4x20.move_to(0, 2)
            # lcd4x20.putstr(str(self.new_value) + "      ")
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
            elif self.mode == "view_errors":
                if self.errorlist is not None:
                    if len(self.errorlist) > 0:
                        hist_str = self.errorlist[self.error_index]
                        self.error_index = (self.error_index + 1) % len(self.errorlist)     # check if this is right
                else:
                    hist_str = "Errorlist: None"              
            elif self.mode == "view_kpa":
                # print(f'In NEXT , view_kpa... {self.mode=}')
                if self.kpalist is not None:
                    # print(f'In NEXT {self.kpa_index=}')
                    if len(self.kpalist) > 0:
                        hist_str = self.kpalist[self.kpa_index]
                        self.kpa_index = (self.kpa_index + 1) % len(self.kpalist)
                else:
                    print("In NEXT, kpalist is None")
                    hist_str = "kPalist: None"
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
                    if self.mode == "view_events":
                        datestamp = LCD_time(nav_secs_to_localtime(hist_str[0]))
                    else:
                        datestamp = hist_str[0]
                    log_txt   = hist_str[1]
                else:
                    datestamp = f'{self.mode:<16}'
                    log_txt   = "Nothing here"
            else:
                datestamp = "Err in NEXT"
                log_txt   = "hist not a tuple"

            self.LCD2R.setCursor(0, 0)
            self.LCD2R.printout(f'{datestamp:<16}')
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'{log_txt:<16}')

            # lcd4x20.move_to(0, 2)
            # lcd4x20.putstr(f'{datestamp:<16}')
            # lcd4x20.move_to(0, 3)
            # lcd4x20.putstr(f'{log_txt:<16}')
        elif self.mode == "wait":
            # print(f'In NEXT, wait mode... {self.mode=}')
            self.go_back()              # go back to previous menu level
        else:
            # print(f"In NEXT, {self.mode=}")
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'{self.mode=}')

    def previous(self):
        # print(f'In PREV, {self.mode=}')
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
            # print(f'In PREV, item is {item}')
            # if item['value']['W_V'] == 0:
            # if self.new_value == 0:
            #     print("Setting new_value to default...")
            #     self.new_value = item['value']['D_V']
            step = item['value']['Step']
            if self.new_value >= step:
                self.new_value -= step
                # print(f'In PREV self.new_value is {self.new_value}')
                self.LCD2R.setCursor(0, 1)
                self.LCD2R.printout(str(self.new_value) + "      ")
                
                # lcd4x20.move_to(0, 2)
                # lcd4x20.putstr(str(self.new_value) + "      ")
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
            elif self.mode == "view_errors":
                if self.errorlist is not None:
                    if len(self.errorlist) > 0:
                        hist_str = self.errorlist[self.error_index]
                        self.error_index = (self.error_index - 1) % len(self.errorlist)     # check if this is right
                else:
                    hist_str = "Errorlist: None"              
            elif self.mode == "view_kpa":
                if self.kpalist is not None:
                    if len(self.kpalist) > 0:
                        hist_str = self.kpalist[self.kpa_index]
                        self.kpa_index = (self.kpa_index - 1) % len(self.kpalist)
                else:
                    hist_str = "kPalist: None"
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
                    if self.mode == "view_events":
                        datestamp = LCD_time(nav_secs_to_localtime(hist_str[0]))
                    else:
                        datestamp = hist_str[0]                    
                        log_txt   = hist_str[1]
                else:
                    datestamp = f'{self.mode:<16}'
                    log_txt   = "Nothing here"
            else:
                datestamp = "Err in PREV"
                log_txt   = "hist not a tuple"

            self.LCD2R.setCursor(0, 0)
            self.LCD2R.printout(f'{datestamp:<16}')
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'{log_txt:<16}')

            # lcd4x20.move_to(0, 2)
            # lcd4x20.putstr(f'{datestamp:<16}')
            # lcd4x20.move_to(0, 3)
            # lcd4x20.putstr(f'{log_txt:<16}')
        elif self.mode == "wait":
            # print(f'In PREV, wait mode... {self.mode=}')
            self.go_back()              # go back to previous menu level
        else:
            # print(f"In PREV, {self.mode=}")
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'{self.mode=}')
    
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
            # print("Already at the top-level menu.  This should not happen...")
            print("Exiting nav menu from go_back")
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout("Exiting nav menu")
            self.exit_nav_menu()            # exit menu nav, and call exit_menu() in the menu structure
            
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
            # print(f'In ENTER {param} = {val}')
        else:
            print(f"Unknown type in item... check menu def.  {item}")
    
        # print(f"In ENTER, mode is now {self.mode}")

    def set(self):
        item = self.get_current_item()
#        param = item['title']
#        val = self.new_value
#        print(f'New {param} = {val}')
        # print(f'In SET before change, item is: {item}')
        if item['value']['W_V'] !=  self.new_value and self.new_value > 0:
            item['value']['W_V'] =  self.new_value
            # print(f"In SET, updated Working Value to {self.new_value}")
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'Set {str(self.new_value):<12}')   
        # print(f'In SET after  change, item is: {item}')
        self.LCD2R.setCursor(0, 1)
        self.LCD2R.printout(f"Set to {str(self.new_value):<8}")
        self.new_value = 0          # reset this, or we copy previous remnant value
        self.mode = "wait"          # wait for a 2nd press so that changed value is displayed before going back to menu
        # self.go_back()              # go back to previous menu level

    def set_default(self):
        # print("Setting default value")
        item = self.get_current_item()
        def_val = item['value']['D_V']
        item['value']['W_V'] = def_val
        print(f"Value set to Default: {def_val}")
        self.LCD2R.setCursor(0, 1)
        self.LCD2R.printout(f"Set to {str(def_val):<8}")
        self.new_value = 0          # reset this, or we copy previous remnant value
        self.mode = "wait"          # wait for a 2nd press so that changed value is displayed before going back to menu
        # self.go_back()              # go back to previous menu level

    # def cont_back(self)->None:
    #     self.go_back()              # go back to previous menu level
        
    def goto_position(self, first=True):
        if "view_" in self.mode:  #self.mode == "view_events" or self.mode == "view_switch":
            # print(f'In goto_position {self.mode=}, {first=}')
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
            elif self.mode == "view_errors":
                if self.errorlist is not None:
                    if len(self.errorlist) > 0:
                        pos = 0 if first else len(self.errorlist) - 1
                        self.error_index = pos
                        hist_str = self.errorlist[self.error_index]
                else:
                    hist_str = "Errorlist: None"                   
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
                    # print(f'In goto_position {hist_str=}')
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

            self.LCD2R.setCursor(0, 0)
            self.LCD2R.printout(f'{datestamp:<16}')
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'{log_txt:<16}')
        else:
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout("Not in VIEW mode")

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
        # if self.kpalist is not None:
        #     del self.kpalist           # clean up old stuff...  
        self.kpalist = mylist

    def set_error_list(self, mylist):
        self.errorlist = mylist

    def go_to_start(self):
        self.current_index = 0

    def exit_nav_menu(self)-> None:
    # since I can't reference exit_menu(), but I have a reference to it in the final menu structure, find it, then call it
        print(f"exit_nav_menu...{self.current_index=}")
        self.LCD2R.clear()
        self.LCD2R.setCursor(0, 0)
        self.LCD2R.printout("Exiting menu...")

        self.current_index = 0      # reset to top of menu.

        # time.sleep(1)
        for item in self.menu["items"]:
            if item['title'] == "Exit":     # BEWARE ... dependency on finding "Exit" in the menu structure
                item['action']()
                break

