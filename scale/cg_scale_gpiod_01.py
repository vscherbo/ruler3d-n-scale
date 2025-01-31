#!/usr/bin/env python3

import logging
import time
from typing import Optional

import gpiod  # Modern GPIO library for Raspberry Pi
from gpiod.line import Bias, Direction, Value
# from gpiod.line import Direction, Value


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
        self.data_line_num = data_line
        self.clock_line_num = clock_line

        cfg_clock = {clock_line: gpiod.LineSettings(
                        direction=Direction.OUTPUT, output_value=Value.INACTIVE)
                     }
        self.clock_line = gpiod.request_lines(
                    chip_name,
                    consumer="hx711-sck",
                    config=cfg_clock
            )

        cfg_data = {data_line: gpiod.LineSettings(
                        direction=Direction.INPUT, bias=Bias.PULL_DOWN)
                        # direction=Direction.INPUT)
                    }
        self.data_line = gpiod.request_lines(
                    chip_name,
                    consumer="hx711-dt",
                    config=cfg_data
            )

        # self.chip = gpiod.Chip(chip_name)
        # self.data_line = self.chip.get_line(data_line)
        # self.clock_line = self.chip.get_line(clock_line)
        # self.data_line.request(consumer="hx711", type=gpiod.LINE_REQ_DIR_IN)
        # self.clock_line.request(consumer="hx711", type=gpiod.LINE_REQ_DIR_OUT)

        # self.data_line = gpiod.request_line(chip_name, data_line, gpiod.LINE_REQ_DIR_IN)
        # self.clock_line = gpiod.request_line(clock_line, gpiod.LINE_REQ_DIR_OUT)

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

        logging.debug('wait INPUT')
        # val = self.data_line.get_value(self.data_line_num).value
        # logging.debug('1st. val=%s', val)

        while self.data_line.get_value(self.data_line_num):
            pass

        value = 0
        # logging.debug('start measuring loop FOR')

        for _ in range(24 + self.gain_bits):
            self.clock_line.set_value(value=Value.INACTIVE, line=self.clock_line_num)
            time.sleep(0.000001)
            self.clock_line.set_value(self.clock_line_num, Value.ACTIVE)
            time.sleep(0.000001)
            val1 = self.data_line.get_value(self.data_line_num).value
            # logging.debug('   loop val1=%s', val1)
            # logging.debug('   loop value << 1=%s', value << 1)
            value = (value << 1) | val1
            # logging.debug('   value=%s', value)
            # value = (value << 1) | self.data_line.get_value(self.data_line_num).value
            self.clock_line.set_value(value=Value.INACTIVE, line=self.clock_line_num)
            time.sleep(0.000001)

        # Convert 24-bit signed value
        # logging.debug('before convert value=%s', value)
        value = value >> self.gain_bits
        # logging.debug('after convert value=%s', value)

        val0x8 = value & 0x800000
        logging.debug('val0x8=%s', val0x8)

        if value & 0x800000:
            value -= 0x1000000
            logging.debug('if True value=%s', value)

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
        """Release GPIO resources."""
        self.data_line.release()
        self.clock_line.release()


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
        log_format = '%(asctime)-15s | %(levelname)-7s | %(filename)-25s:%(lineno)4s - \
                %(funcName)25s() | %(message)s'

        # logging.basicConfig(level=logging.INFO,
        # format='%(asctime)s - %(levelname)s - %(message)s')
        logging.basicConfig(level=logging.DEBUG, format=log_format)

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
        """Release GPIO resources."""
        logging.info("Cleaning up GPIO resources...")
        self.hx711.cleanup()
        logging.info("Cleanup complete.")


# Example usage (uncomment for testing)

if __name__ == "__main__":
    import time
    # scale = TensileScale(chip_name="/dev/gpiochip0", data_line=72, clock_line=74)
    # scale = TensileScale(chip_name="/dev/gpiochip0", data_line=72, clock_line=233)
    scale = TensileScale(chip_name="/dev/gpiochip0", data_line=227, clock_line=226, gain=32)
    try:
        # scale.calibrate(known_weight=532.0)  # Calibrate with a 500g weight
        # scale.calibrate(known_weight=0.001)  # Calibrate with a 500g weight
        # logging.info('Sleep!')
        # time.sleep(5)
        weight = scale.get_weight()
        print(f"Measured weight: {weight:.2f} grams")
    finally:
        scale.cleanup()
