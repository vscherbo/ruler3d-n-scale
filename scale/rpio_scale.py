#!/usr/bin/env python3

""" Scale Tensile Hx711 by ChatGPT """

import logging
import time
from typing import Optional

import RPi.GPIO as GPIO  # For Raspberry Pi GPIO control


class HX711:
    """
    HX711 driver class for reading data from the load cell amplifier.
    """
    def __init__(self, data_pin: int, clock_pin: int, gain: int = 128):
        """
        Initialize the HX711.

        :param data_pin: GPIO pin connected to the data pin of the HX711.
        :param clock_pin: GPIO pin connected to the clock pin of the HX711.
        :param gain: Gain setting for the HX711 (128, 64, or 32).
        """
        self.data_pin = data_pin
        self.clock_pin = clock_pin
        self.gain = gain
        self.offset = 0
        self.scale = 1

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.data_pin, GPIO.IN)
        GPIO.setup(self.clock_pin, GPIO.OUT)

        self.set_gain(gain)

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

    def read_raw(self) -> int:
        """
        Read raw data from the HX711.

        :return: Raw 24-bit data value from the HX711.
        """
        while GPIO.input(self.data_pin):
            pass

        value = 0
        for _ in range(24 + self.gain_bits):
            GPIO.output(self.clock_pin, True)
            time.sleep(0.000001)
            value = (value << 1) | GPIO.input(self.data_pin)
            GPIO.output(self.clock_pin, False)
            time.sleep(0.000001)

        # Convert 24-bit signed value
        value = value >> self.gain_bits
        if value & 0x800000:
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
        self.offset = total / num_samples

    def set_scale(self, scale: float):
        """
        Set the calibration scale factor.

        :param scale: Calibration scale factor.
        """
        self.scale = scale

    def cleanup(self):
        """Clean up GPIO resources."""
        GPIO.cleanup()


class TensileScale:
    """
    Scale using a tensile sensor and HX711 load cell amplifier.
    """
    def __init__(self, data_pin: int, clock_pin: int, gain: int = 128):
        """
        Initialize the TensileScale.

        :param data_pin: GPIO pin connected to the HX711 data pin.
        :param clock_pin: GPIO pin connected to the HX711 clock pin.
        :param gain: Gain setting for the HX711 (default is 128).
        """
        self.hx711 = HX711(data_pin, clock_pin, gain)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    def calibrate(self, known_weight: float):
        """
        Calibrate the scale using a known weight.

        :param known_weight: The weight in grams used for calibration.
        """
        logging.info("Starting calibration...")
        self.hx711.tare()
        raw_value = self.hx711.read_raw()
        scale_factor = raw_value / known_weight
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
        """Clean up GPIO resources."""
        logging.info("Cleaning up GPIO resources...")
        self.hx711.cleanup()
        logging.info("Cleanup complete.")

# Example usage (uncomment for testing)
# if __name__ == "__main__":
#     scale = TensileScale(data_pin=5, clock_pin=6)
#     try:
#         scale.calibrate(known_weight=500.0)  # Calibrate with a 500g weight
#         weight = scale.get_weight()
#         print(f"Measured weight: {weight:.2f} grams")
#     finally:
#         scale.cleanup()
