#!/usr/bin/env pytho3

""" Scale giga-02 """

import logging
from time import sleep

import RPi.GPIO as GPIO

# Настраиваем логгер
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)-8s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

class WeightSensor:
    """
    Класс для управления тензодатчиками с использованием интерфейса HX711.

    Параметры:
        dout_pin (int): Номер пина данных (DOUT).
        pd_sck_pin (int): Номер пина тактирования (PD_SCK).
        gain (int): Коэффициент усиления. Возможные значения: 128 или 64.
        reference_unit (float): Калибровочный коэффициент для перевода сырых значений в граммы.

    Методы:
        power_down(): Выключение питания датчика.
        power_up(): Включение питания датчика.
        read(): Чтение сырого значения с датчика.
        get_weight(): Преобразование сырого значения в вес (граммы).
        tare(): Установка нуля (обнуление показаний).
    """

    def __init__(self, dout_pin, pd_sck_pin, gain=128, reference_unit=200):
        self.dout_pin = dout_pin
        self.pd_sck_pin = pd_sck_pin
        self.gain = gain
        self.reference_unit = reference_unit

        try:
            # Настройка GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pd_sck_pin, GPIO.OUT)
            GPIO.setup(self.dout_pin, GPIO.IN)

            # Включаем питание датчика
            self.power_up()
            logger.info("Тензодатчик успешно инициализирован.")
        except Exception as e:
            logger.error(f"Произошла ошибка при инициализации тензодатчика: {e}")
            raise

    def power_down(self):
        """Выключает питание датчика."""
        try:
            GPIO.output(self.pd_sck_pin, False)
            GPIO.cleanup([self.pd_sck_pin, self.dout_pin])
            logger.debug("Питание датчика отключено.")
        except Exception as e:
            logger.warning(f"Произошла ошибка при отключении питания датчика: {e}")

    def power_up(self):
        """Включает питание датчика."""
        try:
            GPIO.output(self.pd_sck_pin, True)
            logger.debug("Питание датчика включено.")
        except Exception as e:
            logger.warning(f"Произошла ошибка при включении питания датчика: {e}")

    def read(self):
        """Читает сырое значение с датчика."""
        reading = 0

        try:
            for _ in range(24):
                GPIO.output(self.pd_sck_pin, True)
                reading <<= 1
                GPIO.output(self.pd_sck_pin, False)

                if GPIO.input(self.dout_pin):
                    reading |= 0x01

            GPIO.output(self.pd_sck_pin, True)
            GPIO.output(self.pd_sck_pin, False)

            reading ^= 0x800000

            return reading if reading > 0x7fffff else reading - 0xffffff
        except Exception as e:
            logger.error(f"Произошла ошибка при чтении данных с датчика: {e}")
            raise

    def get_weight(self):
        """Преобразует сырое значение в вес (граммы)."""
        try:
            raw_value = self.read()
            weight = raw_value / self.reference_unit
            logger.debug(f"Вес: {weight:.2f} г")
            return weight
        except Exception as e:
            logger.error(f"Произошла ошибка при вычислении веса: {e}")
            raise

    def tare(self):
        """Обнуляет показания датчика."""
        try:
            self.reference_unit = self.read() / 1000
            logger.debug("Показания датчика обнулены.")
        except Exception as e:
            logger.error(f"Произошла ошибка при обнулении показаний датчика: {e}")
            raise
