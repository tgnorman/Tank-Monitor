# Tank Monitor System
A MicroPython-based water tank and pump monitoring system for the Raspberry Pi Pico W.

## Features
- Water level monitoring using laser sensor
- Automated pump control
- Pressure monitoring with zone categorisation
- Programmable irrigation controller
- Email notifications
- LCD display interface 
- Menu-driven configuration
- Data logging and analysis
- Power outage detection
- Critical event alarms
- Remote slave unit with wireless communication between master (TX) and slave (RX) nodes

## Hardware Requirements
- Raspberry Pi Pico W (x 2)
- PiicoDev Transceivers (x 2)
- LCD Display (RGB1602... or 2004)
- Pressure sensor (800 kPa max)
- Water level sensor (VL53L1X)
- Current sensor (5A max with Voltage output)
- Mains relay including detect logic

## History
This project began as a simple means to automate turning our bore pump on/off depending on the water level in the holding tank next to our house.  It grew...a lot!

The initial implementation used a VL53L1X laser/LED distance sensor, connected to a single Pico W, which then controlled the bore pump via a mains relay which I constructed (from a kit).  I then added the ability to detect when the pressure pump, (which feeds water from said holding tank into our house), is running... as I was rapidly losing enthusiam for getting up at 3AM to investigate why this pump was running (or cycling).

Next, I really didn't like having a 4-core cable running between my holding tank and the mains meter box on the side of the house.  Either overhead cables, or digging a trench... neither were appealing, so, I figured I'd employ a slave unit, get the master and slave talking wirelessly, and that would be spiffy.  Check... done.

I had suspicions that something was amiss with our bore, and the addition of a pressure sensor confirmed what I feared... after about 40 minutes of pumping, it started sucking an air/water mix.  NOT GOOD!  This was the chief motivation for changing the direction of my project, to focus on managing our limited water resource.  The fact that we are currently in a record-breaking drought only increased the urgency of this change!  So, the project morphed into becoming a very bespoke programmable irrigation timer... as well as automatic tank filler... and pressure pump alarm system.  I can set the desired duty cycle, and instead of running the pump continuously for a few hours, it now runs for 30 minutes - stops, so the aquifer can replenish, and then pumps some more. Rinse and repeat.  All while I sleep!

Somewhere along the way, I figured it would be nice to drive all this with a multi-level menu system, which I managed to do with minimal hardware - an LCD and a rotary encoder.  And why not email my data logs to myself as required while I'm at it... and so, the code base grew and grew, until I recently hit the limits of the poor little Pico W, and I have recently upgraded to a Pico 2 W, with MUCH more flash memory.  I had space to spare on the flash drive... but micropython's internals ran out of heap space, which meant my SMTP connection to my email server just crashed immediately, due to lack of resources.  Sorted.

So... now it is all running nicely, albeit I have work to do to finish the physical installation.

This was my first ever project using microcontrollers, and my first exposure to writing Python code.  So, experienced Pythonistas... please cut me some slack!  It has been a massive learning curve.  Not to mention about 50 years since I dabbled in a bit of electronics.  But, it's been fun!

And of course... this is still a Work In Progress!!

## Next steps
1. Replace the rotary encoder with a 5-button navigation control system. Why?
    a. a more intuitive human interface, and
    b. the encoder interupt code stopped working when I upgraded to the Pico 2
2. Upgrade my 16x2 LCD to a 20x4
3. Add Home Assistant integration
4. Add more high-level logic, to make the system more intelligent
5. Add control of various gate valves (I have about 6) that determine where the water goes... either into the holding tank, or to one of various irrigation zones in a fairly expansive garden. (Unfortuneatly, this may require more trenching -  sigh...)

## Thanks
- The tech and sales team at [Core Electronics](https://core-electronics.com.au/)
- A LOT of invaluable electronics advice from Bob, aka Robert93820, on the Core Electronics forum, plus many other forum members
- Staff at my (sort of) local Altronics store
