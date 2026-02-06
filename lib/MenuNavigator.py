# This class assumes a menu containing entries with a title, possibly a list of sub-menu items, and items can have an action associated
# The action, if a string, will just be printed (for debugging purposes), but if it is a callable function, it will be called
# Some actions have the side-effect of updating self.mode... which is used to control display of lists linked to ring buffers, or other lists

# Added to git 30/3/2025

# Refactored 9/5/2025 to use structure advised by Claude
# Added file_manager

import time                         # type: ignore
from RGB1602 import RGB1602         # type: ignore
from utils import format_secs_short         # old methodsLCD_time, secs_to_localtime
from TMErrors import TankError

# This 4x20 lcd no longer used by navigator... maybe later I will return to this.
# from lcd_api import LcdApi
# from i2c_lcd import I2cLcd

# from machine import I2C, Pin
# I2C_ADDR            = 0x27
# I2C_NUM_ROWS        = 4
# I2C_NUM_COLS        = 20
# i2c                 = I2C(0, sda=Pin(8), scl=Pin(9), freq=400000)
# lcd4x20             = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)

# NOTE: I removed the variables used to retain the index position in ringbuffers, when I transitioned depth to a ring.
# So... always goes back to the start.  No biggie ... and simpler code.  19/9/25

class MenuNavigator:
    NAVMODE_MENU    = 'menu'
    NAVMODE_VIEW    = 'view'
    NAVMODE_VALUE   = 'value_change'
    NAVMODE_FMGR    = 'file_manager'
    MENU_TITLE      = "title"
    MENU_ITEMS      = "items"
    MENU_ACTION     = "action"
    MENU_VALUE      = "value"
    MENU_WV         = "W_V"
    MENU_DV         = "D_V"
    MENU_STEP       = "Step"
    VIEWRING        = "view_ring"
    VIEWPROG        = "view_prgrm"
    VIEWFILES       = "view_files"
    PRGRM_SUFFIX    = VIEWPROG.split("_")[1]
    FILES_SUFFIX    = VIEWFILES.split("_")[1]

    EVENTRING       = 'events'
    SWITCHRING      = 'switch'
    ERRORRING       = 'errors'
    KPARING         = 'kpa'
    DEPTHRING       = 'depth'

    def __init__(self, menu, dev2:RGB1602): #, dev4:I2cLcd):
        self.menu = menu
        # self.current_level = [menu]  # Stack to keep track of menu levels
        self.current_level = [{'submenu': menu, 'index': 0}]  # Stack to keep track of menu levels
        self.current_menuindex = 0
        self.LCD2R = dev2
        # self.LCD4R = lcd4x20
        self.mode = MenuNavigator.NAVMODE_MENU
        self.new_value = 0

        self.ring_buffers = {
            MenuNavigator.EVENTRING:    {'buffer': None, 'index': 0},
            MenuNavigator.SWITCHRING:   {'buffer': None, 'index': 0},
            MenuNavigator.KPARING:      {'buffer': None, 'index': 0},
            MenuNavigator.ERRORRING:    {'buffer': None, 'index': 0},
            MenuNavigator.DEPTHRING:    {'buffer': None, 'index': 0}      # added depth for consistency with other data structure 19/9/25
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
            
        direction = 1 if forward else -1
        self.display_navindex = (self.display_navindex + direction) % len(self.displaylist)
        hist_str = self.displaylist[self.display_navindex]      # moved to AFTER index update... 22/5/25
        return hist_str                                         # now consistent with handle_list_view

    def _format_display_entry(self, hist_str):
        """Format entry for LCD display"""
            
        if not hist_str:
            return f'{self.mode:<16}', "Nothing here"
        
        if not isinstance(hist_str, tuple):
            return "Err in display", "Hist not a tuple"
            
        if self.mode == MenuNavigator.VIEWRING:
            datestamp = format_secs_short(int(hist_str[0]))
            if self.displaylistname == "errors":
                tmp     = hist_str[1]
                if type(tmp) == str:
                    tmp = int(tmp.split(" ")[0])
                log_txt = self.errors.get_code(tmp)                 # needed since I added duplicate count after code
            else:
                log_txt = hist_str[1]
            if type(log_txt) == str: log_txt = log_txt[:16]         # trim to 16 chars
        elif self.mode == MenuNavigator.VIEWPROG:
            datestamp   = hist_str[0]
            prog        = hist_str[1]
            log_txt     = f'Run {prog["run"]} Off {prog["off"]}'
        else:
            datestamp   = hist_str[0]
            log_txt     = hist_str[1]
            if type(log_txt) == str: log_txt = log_txt[:16]         # trim to 16 chars
            
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
        menu_len = len(current['submenu'][MenuNavigator.MENU_ITEMS])
        self.current_menuindex = (self.current_menuindex + direction) % menu_len
        current['index'] = self.current_menuindex
        self.display_current_item()

    def _handle_value_change(self, increment=True):
        item = self.get_current_item()
        step = item[MenuNavigator.MENU_VALUE][MenuNavigator.MENU_STEP]
        if increment:
            self.new_value += step
        elif self.new_value > step:  # Only decrement if result would be > 0
            self.new_value -= step
        self.LCD2R.setCursor(0, 1)
        self.LCD2R.printout(f'{str(self.new_value):<16}')

    # For non-ring buffer lists like programs and files
    def _handle_list_view(self, list_name, forward=True):
        """Handle viewing regular (non-ring buffer) lists"""
        if list_name == MenuNavigator.PRGRM_SUFFIX:
            current_list = self.programlist
            index_attr = "program_navindex"
        elif list_name == MenuNavigator.FILES_SUFFIX:
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
        if list_name == MenuNavigator.PRGRM_SUFFIX:
            prog = current_list[new_index]
            prog_str = f'Run {prog[1]["run"]} Off {prog[1]["off"]}'
            return prog[0], prog_str
        else:
            # print(f"HLV: {new_index=} {current_list[new_index]=}")
            filename, filesize = current_list[new_index]
            return filename, filesize
        
    def get_current_item(self):
        current = self.current_level[-1]
        return current['submenu'][MenuNavigator.MENU_ITEMS][self.current_menuindex]
    
    def display_current_item(self):
        item = self.get_current_item()
        self.LCD2R.clear()
        self.LCD2R.setCursor(0,0)
        self.LCD2R.printout(f'{item[MenuNavigator.MENU_TITLE]:<16}')

        if MenuNavigator.MENU_VALUE in item:
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'{str(item[MenuNavigator.MENU_VALUE][MenuNavigator.MENU_WV]):<16}')

    def next(self):
        if self.mode == MenuNavigator.NAVMODE_MENU:
            self._handle_menu_move(forward=True)
        elif self.mode == MenuNavigator.NAVMODE_VALUE:
            self._handle_value_change(increment=True)
        elif self.mode == MenuNavigator.VIEWRING:
            hist_str = self._handle_ring_view(forward=True)
            self._update_display(*self._format_display_entry(hist_str))
        elif self.mode in [MenuNavigator.VIEWPROG, MenuNavigator.VIEWFILES]:
            list_name = self.mode.split("_")[1]
            timestamp, message = self._handle_list_view(list_name, forward=True)
            self._update_display(timestamp, message[:16])
        elif self.mode == MenuNavigator.NAVMODE_FMGR:
            list_name = 'files'
            timestamp, message = self._handle_list_view(list_name, forward=True)
            self._update_display(timestamp, message[:16])
        # elif self.mode == "wait":
        #     self.go_back()

    def previous(self):
        if self.mode == MenuNavigator.NAVMODE_MENU:
            self._handle_menu_move(forward=False)
        elif self.mode == MenuNavigator.NAVMODE_VALUE:
            self._handle_value_change(increment=False)
        elif self.mode == MenuNavigator.VIEWRING:
            hist_str = self._handle_ring_view(forward=False)
            self._update_display(*self._format_display_entry(hist_str))
        elif self.mode in [MenuNavigator.VIEWPROG, MenuNavigator.VIEWFILES]:
            list_name = self.mode.split("_")[1]
            timestamp, message = self._handle_list_view(list_name, forward=False)
            self._update_display(timestamp, message[:16])
        elif self.mode == MenuNavigator.NAVMODE_FMGR:
            list_name = 'files'
            timestamp, message = self._handle_list_view(list_name, forward=False)
            self._update_display(timestamp, message[:16])
        # elif self.mode == "wait":
        #     self.go_back()

    def goto_position(self, first=True):
        hist_str = None
        if self.mode == MenuNavigator.VIEWRING:
            if self.displaylist is not None:
                if len(self.displaylist) > 0:
                    pos = 0 if first else len(self.displaylist) - 1
                    self.display_navindex = pos
                    hist_str = self.displaylist[pos]
        elif self.mode == MenuNavigator.VIEWPROG:
            if self.programlist is not None:
                if len(self.programlist) > 0:
                    pos = 0 if first else len(self.programlist) - 1
                    self.program_navindex = pos
                    hist_str = self.programlist[pos]
        elif self.mode in [MenuNavigator.VIEWFILES, MenuNavigator.NAVMODE_FMGR]:
            if self.filelist is not None:
                if len(self.filelist) > 0:
                    pos = 0 if first else len(self.filelist) - 1
                    self.file_navindex = pos
                    hist_str = self.filelist[pos]

        if hist_str is None:
            hist_str = ("Err in display", "Nothing here")
        self._update_display(*self._format_display_entry(hist_str))

    def go_back(self):
        if len(self.current_level) > 1:
            self.current_level.pop()  # Go up one level in the menu
                # Restore previous level's index
            self.current_menuindex = self.current_level[-1]['index']
            self.mode = MenuNavigator.NAVMODE_MENU
            self.new_value = 0

            print(f"Going back to previous menu level {len(self.current_level)}")
            self.display_current_item()
        else:
            # print("Already at the top-level menu.  This should not happen...")
            # self.LCD2R.setCursor(0, 1)
            # self.LCD2R.printout(f'{"Exiting nav menu":<16}')
            self.exit_nav_menu()            # exit menu nav, and call exit_menu() in the menu structure
            
    def enter(self):
        item = self.get_current_item()
        if MenuNavigator.MENU_ITEMS in item:
            # self.current_level.append(item)  # Go deeper into the submenu
            # Save both menu and current index
            self.current_level.append({
                'submenu': item,
                'index': 0
            })
            self.current_menuindex = 0
#            print(f"Entering {item[MenuNavigator.MENU_TITLE]} submenu - level {len(self.current_level)}")
            self.display_current_item()
        elif MenuNavigator.MENU_ACTION in item:
            action = item[MenuNavigator.MENU_ACTION]
            if callable(action):
                action()                # do it...
            else:
                print(f"Simulate Executing action: {item[MenuNavigator.MENU_ACTION]}")
        elif MenuNavigator.MENU_VALUE in item:
            self.mode = MenuNavigator.NAVMODE_VALUE
            param = item[MenuNavigator.MENU_TITLE]
            val = item[MenuNavigator.MENU_VALUE]
            # print(f'In ENTER {param} = {val}')
            self.new_value = item[MenuNavigator.MENU_VALUE][MenuNavigator.MENU_WV]
            self.LCD2R.setCursor(0, 0)
            self.LCD2R.printout(f'{param} +-')
        else:
            print(f"Unknown type in item... check menu def.  {item}")
    
        # print(f"In ENTER, mode is now {self.mode}")

    def return_to_menu(self):
        self.mode = MenuNavigator.NAVMODE_MENU
        self.display_current_item()

    def set(self):
        item = self.get_current_item()
#        param = item[MenuNavigator.MENU_TITLE]
#        val = self.new_value
#        print(f'New {param} = {val}')
        # print(f'In SET before change, item is: {item}')
        if item[MenuNavigator.MENU_VALUE][MenuNavigator.MENU_WV] !=  self.new_value and self.new_value > 0:
            item[MenuNavigator.MENU_VALUE][MenuNavigator.MENU_WV] =  self.new_value
            # print(f"In SET, updated Working Value to {self.new_value}")
            self.LCD2R.setCursor(0, 1)
            self.LCD2R.printout(f'Set {str(self.new_value):<12}')   
        # print(f'In SET after  change, item is: {item}')
        self.LCD2R.setCursor(0, 1)
        self.LCD2R.printout(f"Set to {str(self.new_value):<9}")
        # self.new_value = 0          # reset this, or we copy previous remnant value
        # self.mode = "wait"          # wait for a 2nd press so that changed value is displayed before going back to menu
        # self.go_back()              # go back to previous menu level

    def set_default(self):
        # print("Setting default value")
        item = self.get_current_item()
        def_val = item[MenuNavigator.MENU_VALUE][MenuNavigator.MENU_DV]
        item[MenuNavigator.MENU_VALUE][MenuNavigator.MENU_WV] = def_val
        print(f"Value set to Default: {def_val}")
        self.LCD2R.setCursor(0, 1)
        self.LCD2R.printout(f"Set to DV {str(def_val):<6}")
        self.new_value = def_val          # reset this, or we copy previous remnant value
        # self.mode = "wait"          # wait for a 2nd press so that changed value is displayed before going back to menu
        # self.go_back()              # go back to previous menu level

    def goto_first(self):
        self.goto_position(True)

    def goto_last(self):
        self.goto_position(False)

    def go_to_start(self):
        self.current_menuindex = 0

    def exit_nav_menu(self)-> None:
    # since I can't reference exit_menu(), but I have a reference to it in the final menu structure, find it, then call it
        # print(f"exit_nav_menu...{self.current_menuindex=}")
        self.LCD2R.clear()
        self.LCD2R.setCursor(0, 0)
        self.LCD2R.printout(f'{"Exiting menu...":<16}')

        self.current_menuindex = 0      # reset to top of menu.

        for item in self.menu[MenuNavigator.MENU_ITEMS]:
            if item[MenuNavigator.MENU_TITLE] == "Exit":     # BEWARE ... dependency on finding "Exit" in the menu structure
                item[MenuNavigator.MENU_ACTION]()
                break

    def set_program_list(self, mylist):
        if self.programlist is not None:
            del self.programlist           # clean up old stuff...
        self.programlist = mylist

    def set_file_list(self, mylist):
        if self.filelist is not None:
            del self.filelist           # clean up old stuff...
        self.filelist = mylist