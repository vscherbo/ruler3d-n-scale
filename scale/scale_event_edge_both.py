#!/usr/bin/env python3

import time
import logging
import threading
from typing import Optional
import gpiod  # Modern GPIO library for Raspberry Pi
from gpiod.line import Direction, Value, Edge

class HX711:
    """
    HX711 driver class for reading data from the load cell amplifier.
    """
    def __init__(self, chip_name: str, data_line: int, clock_line: int, gain: int = 128):
        """
        Initialize the HX711.

        :param chip_name: The GPIO chip name (e.g., "gpiochip0").
        :param data_line: Line number for the data pin of the HX711.
        :param clock_line: Line number for the clock pin of the HX711.
        :param gain: Gain setting for the HX711 (128, 64, or 32).
        """
        self.gain = gain
        self.offset = 0
        self.scale = 1

        self.chip_name = chip_name
        self.chip = gpiod.Chip(chip_name)
        self.data_line = data_line
        self.clock_line = clock_line
        
        self.request_lines()
        self.set_gain(gain)
    
    def request_lines(self):
        """Request GPIO lines using gpiod.request_lines."""
        #config_data = gpiod.LineSettings(direction=Direction.INPUT, edge_detection=Edge.BOTH)
        config_data = gpiod.LineSettings(edge_detection=Edge.BOTH)
        #config_data = gpiod.LineSettings(edge_detection=Edge.RISING)
        #config_data = gpiod.LineSettings(edge_detection=Edge.FALLING)
        config_clock = gpiod.LineSettings(direction=Direction.OUTPUT)
        """
        self.line_request = self.chip.request_lines(
            consumer="hx711",
            config={
                self.data_line: config_data,
                self.clock_line: config_clock
            },
            output_values={self.clock_line: Value.INACTIVE}
        )
        """

        self.data_request = gpiod.request_lines(
            self.chip_name,
            consumer="hx711_data",
            config={
                self.data_line: config_data
            }
        )

        self.clock_request = gpiod.request_lines(
            self.chip_name,
            consumer="hx711_clock",
            config={
                self.clock_line: config_clock
            },
            output_values={self.clock_line: Value.INACTIVE}
        )

        #self.data_request.read_edge_events()
    
    def set_gain(self, gain: int):
        """
        Set the gain factor for the HX711.

        :param gain: Gain setting (128, 64, or 32).
        """
        self.gain = gain
        if gain == 128:
            self.gain_bits = 1
        elif gain == 64:
            self.gain_bits = 3
        elif gain == 32:
            self.gain_bits = 2
        else:
            raise ValueError("Invalid gain value. Must be 128, 64, or 32.")
    
    def edge_callback(self, event):
        """Callback function triggered on GPIO edge event."""
        print(f'callback::{event}')
        self.edge_event_detected = True

    def monitor_gpio(self):
        """ monitor """
        print(f"Monitoring GPIO {self.data_line} for rising edge events...")

        while True:
            for event in self.data_request.read_edge_events(self.data_line):
                self.edge_callback(event)

    def read_raw(self) -> int:
        """
        Read raw data from the HX711 using edge events.

        :return: Raw 24-bit data value from the HX711.
        """
        self.edge_event_detected = False
        value = 0
        self.clock_request.set_value(self.clock_line, Value.INACTIVE)
        time.sleep(0.000001)
        for _ in range(24 + self.gain_bits):
            self.clock_request.set_value(self.clock_line, Value.ACTIVE)
            time.sleep(0.000001)
            if self.edge_event_detected:
                loc_value = self.data_request.get_value(self.data_line).value
                print(f'loc_value={loc_value}')
                value = (value << 1) | loc_value
                # value = (value << 1) | self.data_request.get_value(self.data_line).value
                print(f'value={value}')
            self.clock_request.set_value(self.clock_line, Value.INACTIVE)
            time.sleep(0.000001)

        # Convert 24-bit signed value
        value = value >> self.gain_bits
        print(f'gain_bits value={value}')
        if value & 0x800000:
            print(f'minus value={value}')
            value -= 0x1000000
        return value

    def read_weight(self) -> float:
        """
        Get the weight measurement in calibrated units.

        :return: Calibrated weight measurement.
        """
        return (self.read_raw() - self.offset) / self.scale

    def tare(self, num_samples: int = 10):
        """
        Tare the scale by setting the current reading as the offset.

        :param num_samples: Number of samples to average for tare value.
        """
        total = sum(self.read_raw() for _ in range(num_samples))
        print(f'total={total}')
        self.offset = total / num_samples
        print(f'offset={self.offset}')

    def set_scale(self, scale: float):
        """
        Set the calibration scale factor.

        :param scale: Calibration scale factor.
        """
        self.scale = scale

    def cleanup(self):
        """Release GPIO resources."""
        self.data_request.release()
        self.clock_request.release()


class TensileScale:
    """
    Scale using a tensile sensor and HX711 load cell amplifier.
    """
    def __init__(self, chip_name: str, data_line: int, clock_line: int, gain: int = 128):
        """
        Initialize the TensileScale.

        :param chip_name: The GPIO chip name (e.g., "gpiochip0").
        :param data_line: Line number for the HX711 data pin.
        :param clock_line: Line number for the HX711 clock pin.
        :param gain: Gain setting for the HX711 (default is 128).
        """
        self.hx711 = HX711(chip_name, data_line, clock_line, gain)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

        thread = threading.Thread(target=self.hx711.monitor_gpio, daemon=True)
        thread.start()

    def calibrate(self, known_weight: float):
        """
        Calibrate the scale using a known weight.

        :param known_weight: The weight in grams used for calibration.
        """
        logging.info("Starting calibration...")
        self.hx711.tare()
        raw_value = self.hx711.read_raw()
        print(f'calibrate::raw_value={raw_value}')
        scale_factor = raw_value / known_weight
        print(f'calibrate::scale_factor={scale_factor}')
        self.hx711.set_scale(scale_factor)
        logging.info("Calibration completed. Scale factor: %.5f", scale_factor)

    def get_weight(self, num_samples: int = 10) -> Optional[float]:
        """
        Get the current weight measurement.

        :param num_samples: Number of samples to average for weight measurement.
        :return: The weight in grams, or None if an error occurs.
        """
        try:
            weight = sum(self.hx711.read_weight() for _ in range(num_samples)) / num_samples
            logging.info("Weight measurement: %.2f grams", weight)
            return weight
        except Exception as e:
            logging.error("Error reading weight: %s", e)
            return None

    def tare(self):
        """Tare the scale to zero."""
        logging.info("Taring the scale...")
        self.hx711.tare()
        logging.info("Scale tared.")

    def cleanup(self):
        """Release GPIO resources."""
        logging.info("Cleaning up GPIO resources...")
        self.hx711.cleanup()
        logging.info("Cleanup complete.")

if __name__ == "__main__":
    scale = TensileScale(chip_name="/dev/gpiochip0", data_line=226, clock_line=227, gain=64)

    try:
        scale.calibrate(known_weight=2000.0)  # Calibrate with a 2000g weight
        # scale.calibrate(known_weight=0.001)  # Calibrate with a 500g weight
        logging.info('Sleep!')
        time.sleep(5)
        weight = scale.get_weight()
        if weight:
            print(f"Measured weight: {weight:.2f} grams")
        else:
            print('ZERO')
    finally:
        scale.cleanup()

