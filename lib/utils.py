# refactored from original code 20/5/25

import time  # type: ignore

# --- Time Conversion ---

def secs_to_localtime(secs: int) -> tuple:
    """Convert seconds since epoch to localtime tuple, handling DST for South Australia."""
    tupltime = time.localtime(secs)
    year = tupltime[0]
    DST_end = time.mktime((year, 4, (7 - (int(5 * year / 4 + 4)) % 7), 2, 0, 0, 0, 0, 0))
    DST_start = time.mktime((year, 10, (7 - (int(year * 5 / 4 + 5)) % 7), 2, 0, 0, 0, 0, 0))
    if DST_end < secs < DST_start:
        adj_time = time.localtime(secs + int(9.5 * 3600))
    else:
        adj_time = time.localtime(secs + int(10.5 * 3600))
    return adj_time

# --- Formatting Helpers ---

def format_time_short(t: tuple) -> str:
    """MM/DD HH:MM:SS (for 16-char LCD)"""
    return f"{t[1]:02}/{t[2]:02} {t[3]:02}:{t[4]:02}:{t[5]:02}"

def format_time_long(t: tuple) -> str:
    """YYYY/MM/DD HH:MM:SS"""
    return f"{t[0]:4}/{t[1]:02}/{t[2]:02} {t[3]:02}:{t[4]:02}:{t[5]:02}"

# --- "Now" Helpers ---

def now_time_tuple() -> tuple:
    """Current local time tuple."""
    return secs_to_localtime(time.time())

def now_time_short() -> str:
    """Current time, short format."""
    return format_time_short(now_time_tuple())

def now_time_long() -> str:
    """Current time, long format."""
    return format_time_long(now_time_tuple())

# --- Format from seconds ---

def format_secs_short(secs: int) -> str:
    """Short format from seconds."""
    return format_time_short(secs_to_localtime(secs))

def format_secs_long(secs: int) -> str:
    """Long format from seconds."""
    return format_time_long(secs_to_localtime(secs))