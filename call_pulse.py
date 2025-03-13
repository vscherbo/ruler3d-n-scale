#!/usr/bin/env python3

import ctypes
import time

# Load the shared library
gpio_lib = ctypes.CDLL("./gpio_pulse.so")

# Define function argument types
gpio_lib.generate_pulse.argtypes = [ctypes.c_char_p, ctypes.c_int]

# Pass a bytes string (C-compatible)
chip_name = b"/dev/gpiochip0"  # Convert to bytes (b"string")
gpio_line = 229


#t_start = time.perf_counter()
# Call the C function
#/dev/gpiochip0
gpio_lib.generate_pulse(chip_name, gpio_line)

#delta_time = (time.perf_counter() - t_start)*1000
#print(f'{delta_time} ms')

print("Single 10 µs pulse generated.")
