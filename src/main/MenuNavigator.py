# This class assumes a menu containing entries with a title, possibly a list of sub-menu items, and items can have an action associated
# The action, if a string, will just be printed (for debugging purposes), but if it is a callable function, it will be called
# Some actions have the side-effect of updating self.mode... which is used to control display of lists linked to ring buffers, or other lists

# Added to git 30/3/2025

# Refactored 9/5/2025 to use structure advised by Claude

import time
from RGB1602 import RGB1602
from utils import LCD_time, secs_to_localtime
from TMErrors import TankError
from ringbuffer import RingBuffer, DuplicateDetectingBuffer

# This 4x20 lcd no longer used by navigator... maybe later I will return to this.
# from lcd_api import LcdApi
# from i2c_lcd import I2cLcd

# from machine import I2C, Pin
# I2C_ADDR            = 0x27
# I2C_NUM_ROWS        = 4
# I2C_NUM_COLS        = 20
# i2c                 = I2C(0, sda=Pin(8), scl=Pin(9), freq=400000)
# lcd4x20             = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)

class MenuNavigator:
    def __init__(self, menu, dev2:RGB1602): #, dev4:I2cLcd):
        self.menu = menu
        # self.current_level = [menu]  # Stack to keep track of menu levels
        self.current_level = [{'submenu': menu, 'index': 0}]  # Stack to keep track of menu levels
        self.current_menuindex = 0
        # self.prev_index = 0
        self.LCD2R = dev2
        # self.LCD4R = lcd4x20
        self.mode = "menu"
        self.new_value = 0

        # NOTE The following group of lists are initialised with ringbuffer buffers.
        # These index values are for navigator scrolling... NOT to be confused with the actual ring's index
        # I have probably never tested this code after the ring wraps around past its end... TODO test navigator lists

        # self.eventlist = None
        # self.event_navindex = 0
        # self.switchlist = None
        # self.switch_navindex = 0
        # self.kpalist = None
        # self.kpa_navindex = 0
        # self.errorlist = None
        # self.error_navindex = 0

        self.ring_buffers = {
            'events': {'buffer': None, 'index': 0},
            'switch': {'buffer': None, 'index': 0},
            'kpa': {'buffer': None, 'index': 0},
            'errors': {'buffer': None, 'index': 0}
        }

        self.programlist = None     # no change to these ... yet
        self.program_navindex = 0
        self.filelist = None
        self.file_navindex = 0
        self.display_current_item()

        self.errors = TankError()
        self.displaylist = None     # hopefully, I can use this to consolidate my next/prev view_* code
        self.display_navindex = 0
        self.displaylistname = ""

    def _handle_ring_view(self, forward=True):
        """Handle viewing ring buffer contents"""
        if self.displaylist is None:
            return f"{self.displaylistname}list: None"
        
        if not self.displaylist:
            return f"{self.displaylistname}list: Empty"
            
        hist_str = self.displaylist[self.display_navindex]
        direction = 1 if forward else -1
        self.display_navindex = (self.display_navindex + direction) % len(self.displaylist)
        return hist_str

    def _format_display_entry(self, hist_str):
        """Format entry for LCD display"""
        if not isinstance(hist_str, tuple):
            return "Err in display", "hist not a tuple"
            
        if not hist_str:
            return f'{self.mode:<16}', "Nothing here"
            
        if self.mode == "view_ring":
            datestamp = LCD_time(secs_to_localtime(int(hist_str[0])))
            log_txt = (self.errors.get_code(hist_str[1]) 
                    if self.displaylistname == "errors" 
                    else hist_str[1])
        else:
            datestamp = hist_str[0]
            log_txt = hist_str[1]
            
        return datestamp, log_txt

    def set_display_list(self, list_name):
        """Set the current display list and name"""
        self.displaylist = self.ring_buffers[list_name]["buffer"]
        self.displaylistname = list_name
        self.display_navindex = 0

    def set_buffer(self, bufname, buff):
        self.ring_buffers[bufname]['buffer'] = buff

    def _update_display(self, datestamp, log_txt):
        """Update LCD display with formatted entries"""
        self.LCD2R.setCursor(0, 0)
        self.LCD2R.printout(f'{datestamp:<16}')
        self.LCD2R.setCursor(0, 1)
        self.LCD2R.printout(f'{log_txt:<16}')

    def _handle_menu_move(self, forward=True):
        direction = 1 if forward else -1
        current = self.current_level[-1]
        menu_len = len(current['submenu']["items"])
        self.current_menuindex = (self.current_menuindex + direction) % menu_len
        current['index'] = self.current_menuindex
        self.display_current_item()

    def _handle_value_change(self, increment=True):
        item = self.get_current_item()
        step = item['value']['Step']
        if increment:
            self.new_value += step
        elif self.new_value >= step:  # Only decrement if result would be >= 0
            self.new_value -= step
        self.LCD2R.setCursor(0, 1)
        self.LCD2R.printout(str(self.new_value) + "      ")

    # For non-ring buffer lists like programs and files
    def _handle_list_view(self, list_name, forward=True):
        """Handle viewing regular (non-ring buffer) lists"""
        if list_name == "program":
            current_list = self.programlist
            index_attr = "program_navindex"
        elif list_name == "files":
            current_list = self.filelist
            index_attr = "file_navindex"
        else:
            return "Unknown list", "type"

        if not current_list:
            return f"{list_name.title()} list:", "None"
        
        if len(current_list) == 0:
            return f"{list_name.title()} list:", "Empty"

        # Update index
        direction = 1 if forward else -1
        current_index = getattr(self, index_attr)
        new_index = (current_index + direction) % len(current_list)
        setattr(self, index_attr, new_index)
        
        # Format output based on list type
        if list_name == "program":
            prog = current_list[new_index]
            prog_str = f'Run {prog[1]["run"]} Off {prog[1]["off"]}'
            return prog[0], prog_str
        else:
            # print(f"HLV: {new_index=} {current_list[new_index]=}")
            filename, filesize = current_list[new_index]
            return filename, filesize
        
    # def get_current_item(self):
    #     return self.current_level[-1]["items"][self.current_menuindex]
    def get_current_item(self):
        current = self.current_level[-1]
        return current['submenu']["items"][self.current_menuindex]
    
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

#     def next(self):
#         # print(f"In NEXT, {self.mode=}")
#         if self.mode == "menu":
#             # menu_len = len(self.current_level[-1]["items"])
#             # if self.current_menuindex < len(self.current_level[-1]["items"]) - 1:
#             current = self.current_level[-1]
#             menu_len = len(current['submenu']["items"])
#             self.current_menuindex = (self.current_menuindex + 1) % menu_len
#             current['index'] = self.current_menuindex
#             self.display_current_item()
#         elif self.mode == "value_change":
#             item = self.get_current_item()
#             # print(f'In NEXT, item is {item}')
#             # if item['value']['W_V'] == 0:
#             # if self.new_value == 0:
#             #     print("Setting new_value to default...")
#             #     self.new_value = item['value']['D_V']
#             step = item['value']['Step']
# # no if need for inc...            
#             self.new_value += step
#             # print(f'In NEXT self.new_value is {self.new_value}')
#             self.LCD2R.setCursor(0, 1)
#             self.LCD2R.printout(str(self.new_value) + "      ")

#             # lcd4x20.move_to(0, 2)
#             # lcd4x20.putstr(str(self.new_value) + "      ")
#         elif "view_" in self.mode: #self.mode == "view_events" or self.mode == "view_switch":
#             # print(f'In NEXT {self.mode=}')
#             if self.mode == "view_ring":
#                 if self.displaylist is not None:
#                     # print(f"len = {len(self.eventlist)}")
#                     if len(self.displaylist) > 0:
#                         hist_str = self.displaylist[self.display_navindex]
#                         self.display_navindex = (self.display_navindex + 1) % len(self.displaylist)
#                     else:
#                         hist_str = f"{self.displaylistname}list: Empty"
#                 else:
#                     hist_str = f"{self.displaylistname}list: None"
#             # elif self.mode == "view_events":
#             #     if self.eventlist is not None:
#             #         # print(f"len = {len(self.eventlist)}")
#             #         if len(self.eventlist) > 0:
#             #             hist_str = self.eventlist[self.event_navindex]
#             #             self.event_navindex = (self.event_navindex + 1) % len(self.eventlist)
#             #         else:
#             #             hist_str = "Eventlist: Empty"
#             #     else:
#             #         hist_str = "Eventlist: None"
#             # elif self.mode == "view_switch":
#             #     if self.switchlist is not None:
#             #         if len(self.switchlist) > 0:
#             #             hist_str = self.switchlist[self.switch_navindex]
#             #             self.switch_navindex = (self.switch_navindex + 1) % len(self.switchlist)
#             #         else:
#             #             hist_str = "Switchlist: Empty"
#             #     else:
#             #         hist_str = "Switchlist: None"
#             # elif self.mode == "view_errors":
#             #     if self.errorlist is not None:
#             #         if len(self.errorlist) > 0:
#             #             ring_val = self.errorlist[self.error_navindex]
#             #             hist_str = self.errors.get_description(ring_val)
#             #             self.error_navindex = (self.error_navindex + 1) % len(self.errorlist)     # check if this is right
#             #         else:
#             #             hist_str = "Errorlist: Empty"
#             #     else:
#             #         hist_str = "Errorlist: None"              
#             # elif self.mode == "view_kpa":
#             #     # print(f'In NEXT , view_kpa... {self.mode=}')
#             #     if self.kpalist is not None:
#             #         # print(f'In NEXT {self.kpa_navindex=}')
#             #         if len(self.kpalist) > 0:
#             #             hist_str = self.kpalist[self.kpa_navindex]
#             #             self.kpa_navindex = (self.kpa_navindex + 1) % len(self.kpalist)
#             #         else:
#             #             hist_str = "kPalist: Empty"
#             #     else:
#             #         # print("In NEXT, kpalist is None")
#             #         hist_str = "kPalist: None"
#             elif self.mode == "view_program":
#                 if self.programlist is not None:
#                     if len(self.programlist) > 0:
#                         self.program_navindex = (self.program_navindex + 1) % len(self.programlist)
#                         prog_name = self.programlist[self.program_navindex][0]
#                         prog_duration = self.programlist[self.program_navindex][1]["run"]
#                         prog_wait = self.programlist[self.program_navindex][1]["off"]
#                         prog_str = f'Run {prog_duration} Off {prog_wait}'
#                         hist_str = tuple((prog_name, prog_str))
#                         # print(f'In NEXT {hist_str=}')
#                     else:
#                         hist_str = "Prog list: Empty"
#                 else:
#                     hist_str = "Prog list: None"
#             elif self.mode == "view_files":
#                 if self.filelist is not None:
#                     if len(self.filelist) > 0:
#                         self.file_navindex = (self.file_navindex + 1) % len(self.filelist)
#                         hist_str = self.filelist[self.file_navindex]
#                     else:
#                         hist_str = "File list: Empty"
#                 else:
#                     hist_str = "File list: None"
#             if type(hist_str) == tuple:
#                 if(len(hist_str) > 0):
#                     if self.mode == "view_ring":  # "view_events" or self.mode == "view_errors" or self.mode == "view_switch"or self.mode == "view_kpa":
#                         hs0 = int(hist_str[0])
#                         # print(f"in NEXT/events B4 nstl: {hs0=}")
#                         lt = secs_to_localtime(hs0)
#                         # print(f"in NEXT/events: {hs0=}  {lt=}")
#                         lcdt = LCD_time(lt)
#                         # print(f"SELF: {hist_str[0]=} of type {type(hist_str[0])}")
#                         datestamp = lcdt
#                     else:
#                         datestamp = hist_str[0]
#                     if self.mode == "view_ring" and self.displaylistname == "errors":      # special lookup required
#                         log_txt = self.errors.get_code(hist_str[1])
#                     else:
#                         log_txt   = hist_str[1]
#                     # print(f"in NEXT/events {log_txt=}")
#                 else:
#                     datestamp = f'{self.mode:<16}'
#                     log_txt   = "Nothing here"
#             else:
#                 datestamp = "Err in NEXT"
#                 log_txt   = "hist not a tuple"

#             self.LCD2R.setCursor(0, 0)
#             self.LCD2R.printout(f'{datestamp:<16}')
#             self.LCD2R.setCursor(0, 1)
#             self.LCD2R.printout(f'{log_txt:<16}')

#             # lcd4x20.move_to(0, 2)
#             # lcd4x20.putstr(f'{datestamp:<16}')
#             # lcd4x20.move_to(0, 3)
#             # lcd4x20.putstr(f'{log_txt:<16}')
#         elif self.mode == "wait":
#             # print(f'In NEXT, wait mode... {self.mode=}')
#             self.go_back()              # go back to previous menu level
#         else:
#             # print(f"In NEXT, {self.mode=}")
#             self.LCD2R.setCursor(0, 1)
#             self.LCD2R.printout(f'{self.mode=}')

    # def next(self):
    #     if self.mode == "menu":
    #         self._handle_menu_move(forward=True)
    #     elif self.mode == "value_change":
    #         self._handle_value_change(increment=True)
    #     elif "view_" in self.mode:
    #         hist_str = self._handle_ring_view(forward=True)
    #         datestamp, log_txt = self._format_display_entry(hist_str)
    #         self._update_display(datestamp, log_txt)
    #     elif self.mode == "wait":
    #         self.go_back()

    def next(self):
        if self.mode == "menu":
            self._handle_menu_move(forward=True)
        elif self.mode == "value_change":
            self._handle_value_change(increment=True)
        elif self.mode == "view_ring":
            hist_str = self._handle_ring_view(forward=True)
            self._update_display(*self._format_display_entry(hist_str))
        elif self.mode in ["view_program", "view_files"]:
            list_name = self.mode.split("_")[1]
            timestamp, message = self._handle_list_view(list_name, forward=True)
            self._update_display(timestamp, message)
        elif self.mode == "wait":
            self.go_back()

    def previous(self):
        if self.mode == "menu":
            self._handle_menu_move(forward=False)
        elif self.mode == "value_change":
            self._handle_value_change(increment=False)
        elif self.mode == "view_ring":
            hist_str = self._handle_ring_view(forward=False)
            self._update_display(*self._format_display_entry(hist_str))
        elif self.mode in ["view_program", "view_files"]:
            list_name = self.mode.split("_")[1]
            timestamp, message = self._handle_list_view(list_name, forward=False)
            self._update_display(timestamp, message)
        elif self.mode == "wait":
            self.go_back()
    # def previous(self):
    #     if self.mode == "menu":
    #         self._handle_menu_move(forward=False)
    #     elif self.mode == "value_change":
    #         self._handle_value_change(increment=False)
    #     elif "view_" in self.mode:
    #         hist_str = self._handle_ring_view(forward=False)
    #         datestamp, log_txt = self._format_display_entry(hist_str)
    #         self._update_display(datestamp, log_txt)
    #     elif self.mode == "wait":
    #         self.go_back()

    # def previous(self):
    #     # print(f'In PREV, {self.mode=}')
    #     if self.mode == "menu":
    #         # menu_len = len(self.current_level[-1]["items"])
    #         # if self.current_menuindex < len(self.current_level[-1]["items"]) - 1:
    #         current = self.current_level[-1]
    #         menu_len = len(current['submenu']["items"])
    #         self.current_menuindex = (self.current_menuindex - 1) % menu_len
    #         current['index'] = self.current_menuindex
    #         self.display_current_item()
    #     elif self.mode == "value_change":
    #         item = self.get_current_item()
    #         # print(f'In PREV, item is {item}')
    #         # if item['value']['W_V'] == 0:
    #         # if self.new_value == 0:
    #         #     print("Setting new_value to default...")
    #         #     self.new_value = item['value']['D_V']
    #         step = item['value']['Step']
    #         if self.new_value >= step:
    #             self.new_value -= step
    #             # print(f'In PREV self.new_value is {self.new_value}')
    #             self.LCD2R.setCursor(0, 1)
    #             self.LCD2R.printout(str(self.new_value) + "      ")
                
    #             # lcd4x20.move_to(0, 2)
    #             # lcd4x20.putstr(str(self.new_value) + "      ")
    #     elif "view_" in self.mode:  #self.mode == "view_events" or self.mode == "view_switch":
    #         # print(f'In PREV {self.mode=}')
    #         if self.mode == "view_ring":
    #             if self.displaylist is not None:
    #                 # print(f"len = {len(self.eventlist)}")
    #                 if len(self.displaylist) > 0:
    #                     hist_str = self.displaylist[self.display_navindex]
    #                     self.display_navindex = (self.display_navindex - 1) % len(self.displaylist)
    #                 else:
    #                     hist_str = f"{self.displaylistname}list: Empty"
    #             else:
    #                 hist_str = f"{self.displaylistname}list: None"
    #         # elif self.mode == "view_events":
    #         #     if self.eventlist is not None:
    #         #         # print(f"len = {len(self.eventlist)}")
    #         #         if len(self.eventlist) > 0:
    #         #             hist_str = self.eventlist[self.event_navindex]
    #         #             # print(hist_str)
    #         #             self.event_navindex = (self.event_navindex - 1) % len(self.eventlist)     # check if this is right
    #         #         else:
    #         #             hist_str = "Eventlist: Empty"                
    #         #     else:
    #         #         hist_str = "Eventlist: None"
    #         # elif self.mode == "view_switch":
    #         #     if self.switchlist is not None:
    #         #         if len(self.switchlist) > 0:
    #         #             hist_str = self.switchlist[self.switch_navindex]
    #         #             self.switch_navindex = (self.switch_navindex - 1) % len(self.switchlist)     # check if this is right
    #         #         else:
    #         #             hist_str = "Switchlist: Empty"
    #         #     else:
    #         #         hist_str = "Switchlist: None"
    #         # elif self.mode == "view_errors":
    #         #     if self.errorlist is not None:
    #         #         if len(self.errorlist) > 0:
    #         #             ring_val = self.errorlist[self.error_navindex]
    #         #             hist_str = self.errors.get_description(ring_val)
    #         #             self.error_navindex = (self.error_navindex - 1) % len(self.errorlist)     # check if this is right
    #         #         else:
    #         #             hist_str = "Errorlist: Empty"
    #         #     else:
    #         #         hist_str = "Errorlist: None"              
    #         # elif self.mode == "view_kpa":
    #         #     if self.kpalist is not None:
    #         #         if len(self.kpalist) > 0:
    #         #             hist_str = self.kpalist[self.kpa_navindex]
    #         #             self.kpa_navindex = (self.kpa_navindex - 1) % len(self.kpalist)
    #         #         else:
    #         #             hist_str = "kPalist: Empty"
    #         #     else:
    #         #         hist_str = "kPalist: None"
    #         # elif self.mode == "view_program":
    #         #     if self.programlist is not None:
    #         #         if len(self.programlist) > 0:
    #         #             self.program_navindex = (self.program_navindex - 1) % len(self.programlist)
    #         #             prog_name = self.programlist[self.program_navindex][0]
    #         #             prog_duration = self.programlist[self.program_navindex][1]["run"]
    #         #             prog_wait = self.programlist[self.program_navindex][1]["off"]
    #         #             prog_str = f'Run {prog_duration} Off {prog_wait}'
    #         #             hist_str = tuple((prog_name, prog_str))
    #         #         else:
    #         #             hist_str = "Prog list: Empty"
    #         #         # print(f'In PREV {hist_str=}')
    #         #     else:
    #         #         hist_str = "Prog list: None"
    #         elif self.mode == "view_files":
    #             if self.filelist is not None:
    #                 if len(self.filelist) > 0:
    #                     self.file_navindex = (self.file_navindex - 1) % len(self.filelist)
    #                     hist_str = self.filelist[self.file_navindex]
    #                 else:
    #                     hist_str = "Filelist: Empty"
    #             else:
    #                 hist_str = "File list: None"
    #         if type(hist_str) == tuple:
    #             if(len(hist_str) > 0):
    #                 if self.mode == "view_ring":  # "view_events" or self.mode == "view_errors" or self.mode == "view_switch"or self.mode == "view_kpa":
    #                     hs0 = int(hist_str[0])
    #                     # print(f"in NEXT/events B4 nstl: {hs0=}")
    #                     lt = secs_to_localtime(hs0)
    #                     # print(f"in NEXT/events: {hs0=}  {lt=}")
    #                     lcdt = LCD_time(lt)
    #                     # print(f"SELF: {hist_str[0]=} of type {type(hist_str[0])}")
    #                     datestamp = lcdt
    #                 else:
    #                     datestamp = hist_str[0]
    #                 if self.mode == "view_ring" and self.displaylistname == "errors":      # special lookup required
    #                     log_txt = self.errors.get_code(hist_str[1])
    #                 else:
    #                     log_txt   = hist_str[1]
    #                 # print(f"in NEXT/events {log_txt=}")
    #             else:
    #                 datestamp = f'{self.mode:<16}'
    #                 log_txt   = "Nothing here"
    #         else:
    #             datestamp = "Err in PREV"
    #             log_txt   = "hist not a tuple"

    #         self.LCD2R.setCursor(0, 0)
    #         self.LCD2R.printout(f'{datestamp:<16}')
    #         self.LCD2R.setCursor(0, 1)
    #         self.LCD2R.printout(f'{log_txt:<16}')

    #         # lcd4x20.move_to(0, 2)
    #         # lcd4x20.putstr(f'{datestamp:<16}')
    #         # lcd4x20.move_to(0, 3)
    #         # lcd4x20.putstr(f'{log_txt:<16}')
    #     elif self.mode == "wait":
    #         # print(f'In PREV, wait mode... {self.mode=}')
    #         self.go_back()              # go back to previous menu level
    #     else:
    #         # print(f"In PREV, {self.mode=}")
    #         self.LCD2R.setCursor(0, 1)
    #         self.LCD2R.printout(f'{self.mode=}')
    
    def go_back(self):
        if len(self.current_level) > 1:
            self.current_level.pop()  # Go up one level in the menu
            # self.current_index = self.prev_index
                # Restore previous level's index
            self.current_menuindex = self.current_level[-1]['index']
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
            self.current_menuindex = 0
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
            if self.mode == "view_ring":
                if self.displaylist is not None:
                    if len(self.displaylist) > 0:
                        pos = 0 if first else len(self.displaylist) - 1
                        self.display_navindex = pos
                        hist_str = self.displaylist[self.display_navindex]
                    else:
                        hist_str = "Eventlist: Empty"
                else:
                    hist_str = "Eventlist: None"     
            # elif self.mode == "view_events":
            #     if self.eventlist is not None:
            #         if len(self.eventlist) > 0:
            #             pos = 0 if first else len(self.eventlist) - 1
            #             self.event_navindex = pos
            #             hist_str = self.eventlist[self.event_navindex]
            #         else:
            #             hist_str = "Eventlist: Empty"
            #     else:
            #         hist_str = "Eventlist: None"
            # elif self.mode == "view_switch":
            #     if self.switchlist is not None:
            #         if len(self.switchlist) > 0:
            #             pos = 0 if first else len(self.switchlist) - 1
            #             self.switch_navindex = pos
            #             hist_str = self.switchlist[self.switch_navindex]
            #         else:
            #             hist_str = "Switchlist: Empty"
            #     else:
            #         hist_str = "Switchlist: None"
            # elif self.mode == "view_errors":
            #     if self.errorlist is not None:
            #         if len(self.errorlist) > 0:
            #             pos = 0 if first else len(self.errorlist) - 1       # semantics different for ringbuffs
            #             self.error_navindex = pos
            #             # hist_str = self.errorlist[self.error_navindex]
            #             ring_val = self.errorlist[self.error_navindex]
            #             hist_str = self.errors.get_description(ring_val)
            #         else:
            #             hist_str = "Errorlist: Empty"                        
            #     else:
            #         hist_str = "Errorlist: None"
            #       # Hmm.. I missed view_kpa
            #                    
            elif self.mode == "view_program":
                if self.programlist is not None:
                    if len(self.programlist) > 0:
                        pos = 0 if first else len(self.programlist) - 1
                        self.program_navindex = pos
                        prog_name = self.programlist[self.program_navindex][0]
                        prog_duration = self.programlist[self.program_navindex][1]["run"]
                        prog_wait = self.programlist[self.program_navindex][1]["off"]
                        prog_str = f'Run {prog_duration} Off {prog_wait}'
                        hist_str = tuple((prog_name, prog_str))
                    else:
                        hist_str = "Prog list: Empty"                        
                    # print(f'In goto_position {hist_str=}')
                else:
                    hist_str = "Prog list: None"
            elif self.mode == "view_files":
                if self.filelist is not None:
                    if len(self.filelist) > 0:
                        pos = 0 if first else len(self.filelist) - 1
                        self.file_navindex = pos
                        hist_str = self.filelist[self.file_navindex]
                    else:
                        hist_str = "File list: Empty"                        
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
        self.current_menuindex = 0

    def exit_nav_menu(self)-> None:
    # since I can't reference exit_menu(), but I have a reference to it in the final menu structure, find it, then call it
        print(f"exit_nav_menu...{self.current_menuindex=}")
        self.LCD2R.clear()
        self.LCD2R.setCursor(0, 0)
        self.LCD2R.printout("Exiting menu...")

        self.current_menuindex = 0      # reset to top of menu.

        for item in self.menu["items"]:
            if item['title'] == "Exit":     # BEWARE ... dependency on finding "Exit" in the menu structure
                item['action']()
                break

