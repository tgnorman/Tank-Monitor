import time # type: ignore

#  Time-related utility functions

def secs_to_localtime(secs)-> tuple:
    """
        Typically called with time.time() as arg... or other source of seconds since epoch
    """
    tupltime    = time.localtime(secs)
    year        = tupltime[0]
    DST_end     = time.mktime((year, 4,(7-(int(5*year/4+4)) % 7),2,0,0,0,0,0)) # Time of April   change to end DST
    DST_start   = time.mktime((year,10,(7-(int(year*5/4+5)) % 7),2,0,0,0,0,0)) # Time of October change to start DST
    
    if DST_end < secs and secs < DST_start:		# then adjust
#        print("Winter ... adding 9.5 hours")
        adj_time = time.localtime(secs + int(9.5 * 3600))
    else:
#        print("DST... adding 10.5 hours")
        adj_time = time.localtime(secs + int(10.5 * 3600))
    return(adj_time)

def LCD_time(t:tuple)-> str:
    """ 
    called with a tuple arg... eg as returned by secs_to_localtime.
    Returns a string that fits on 2x16 LCD
    """
    year  = t[0]
    month = t[1]
    day   = t[2]
    hour  = t[3]
    min   = t[4]
    sec   = t[5]
    short_year = year % 100
    time_str = f"{month:02}/{day:02} {hour:02}:{min:02}:{sec:02}"
    return time_str

def display_time(t:tuple)-> str:
    """ 
    called with a tuple arg... eg as returned by secs_to_localtime
    """
    year    = t[0]
    month   = t[1]
    day     = t[2]
    hour    = t[3]
    min     = t[4]
    sec     = t[5]
    tim_str = f"{year}/{month:02}/{day:02} {hour:02}:{min:02}:{sec:02}"
    return tim_str

def short_time()-> str:
    """
    a short form time display for NOW, fits on a 16 char LCD
    """
    now   = secs_to_localtime(time.time())          # getcurrent time, convert to local SA time
    year  = now[0]
    month = now[1]
    day   = now[2]
    hour  = now[3]
    min   = now[4]
    sec   = now[5]
    short_year = year % 100
    HMS   = f"{hour:02}:{min:02}:{sec:02}"
    return f"{month:02}/{day:02} {HMS}"

def long_time()-> str:
    """
    Long form time NOW, ie full Y/M/D hh:mm:ss format
    """
    now   = secs_to_localtime(time.time())      # getcurrent time, convert to local SA time
    year  = now[0]
    month = now[1]
    day   = now[2]
    hour  = now[3]
    min   = now[4]
    sec   = now[5]
    HMS   = f"{hour:02}:{min:02}:{sec:02}"
    return f"{year:4}/{month:02}/{day:02} {HMS}"

def format_local_time(secs:int)->str:
    return display_time(secs_to_localtime(secs))

def format_local_time_short(secs: int)->str:
    return LCD_time(secs_to_localtime(secs))