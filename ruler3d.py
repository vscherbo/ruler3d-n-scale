#!/usr/bin/env python3
"""
HC-SR04 
"""

import threading
import time
import logging

import gpiod
#from gpiod.line import Direction, Value, Edge, Bias

from HX711 import *

import log_app
import pg_app


class GPIOEventHandler:
    def __init__(self, chip_name, line_numbers, edge_type, callback):
        """
        Initialize the GPIOEventHandler.

        :param chip_name: The GPIO chip name (e.g., 'gpiochip0').
        :param line_numbers: A list of GPIO line numbers to monitor.
        :param edge_type: The edge type to detect ('rising', 'falling', 'both').
        :param callback: The callback function to execute on edge detection.
        """
        self.chip_name = chip_name
        self.line_numbers = line_numbers
        self.edge_type = edge_type
        self.callback = callback
        self.running = True

        # Open the GPIO chip
        self.chip = gpiod.Chip(chip_name)

        # Configure the GPIO lines
        self._configure_lines()

        # Start the event listener in a separate thread
        self.event_thread = threading.Thread(target=self._event_listener)
        self.event_thread.daemon = True
        self.event_thread.start()

    def _configure_lines(self):
        """Configure the GPIO lines for edge detection."""
        # Define edge event type

        if self.edge_type == 'rising':
            event_type = gpiod.line.Edge.RISING
        elif self.edge_type == 'falling':
            event_type = gpiod.line.Edge.FALLING
        elif self.edge_type == 'both':
            event_type = gpiod.line.Edge.BOTH
        else:
            raise ValueError("Invalid edge_type. Use 'rising', 'falling', or 'both'.")

        # Request lines with event detection
        self.request = gpiod.request_lines(self.chip_name, consumer="watch-lines-edge",
                                           config={
                                               self.line_numbers: gpiod.LineSettings(
                                                   direction=gpiod.line.Direction.INPUT,
                                                   bias=gpiod.line.Bias.PULL_DOWN,
                                                   edge_detection=event_type)
                                           }
                                           )

    def _event_listener(self):
        """Listen for GPIO edge events."""

        while self.running:
            # Block until an event occurs
            events = self.request.read_edge_events()

            if events:
                for event in events:
                    self.callback(event.line_offset, event)

    def start(self):
        """Start the event listener thread."""
        self.running = True

        if not self.event_thread.is_alive():
            self.event_thread = threading.Thread(target=self._event_listener)
            self.event_thread.daemon = True
            self.event_thread.start()

    def stop(self):
        self.running = False
        """Stop the event listener thread."""

        if hasattr(self, 'request'):
            self.request.release()
            logging.debug('self.request released')

    def __del__(self):
        """Clean up resources."""
        self.stop()  # Stop the thread if not stopped
        logging.debug('finalizer')


# DEBUG ONLY - same shp_id
INS_R3D = """INSERT INTO shp.ruler3d(shp_id, box, box_length, box_width, box_height, box_weight) VALUES(%s, %s, %s, %s, %s, %s)
ON CONFLICT (shp_id, box) DO UPDATE SET 
box_length = EXCLUDED.box_length,
box_width = EXCLUDED.box_width,
box_height = EXCLUDED.box_height,
box_weight = EXCLUDED.box_weight,
ins_ts = now();
"""

# INS_R3D = "INSERT INTO shp.ruler3d(shp_id, box, length, width, height) VALUES(%s, %s, %s, %s, %s);"


class Ruler3D(log_app.LogApp, pg_app.PGapp):
    def __init__(self, args):
        log_app.LogApp.__init__(self, args=args)
        # config_filename = args.conf
        self.get_config(inline_comment_prefixes=(';', '#'))

        pg_app.PGapp.__init__(self, self.config['PG']['pg_host'], self.config['PG']['pg_user'])

        if self.pg_connect():
            self.set_session(autocommit=True)

        self.timestamp_rising = {}
        self.dist3 = {}
        self.size = {}

        self.line_def = {
            int(self.config['length']['line']): {
                'base': float(self.config['length']['base']),
                'name': self.config['length']['name']},
            int(self.config['width']['line']): {
                'base': float(self.config['width']['base']),
                'name': self.config['width']['name']},
            int(self.config['height']['line']): {
                'base': float(self.config['height']['base']),
                'name': self.config['height']['name']}
        }
        self._shp_id = None
        self._box = None

        # self.hx711 = SimpleHX711(231, 232, 100, -24753)
        try:
            self.hx711 = SimpleHX711(int(self.config['hx711']['data_pin']),
                    int(self.config['hx711']['clock_pin']),
                    int(self.config['hx711']['ref_unit']),
                    int(self.config['hx711']['offset'])
                    )
        # except Exception as excp:  # GPIO busy
        except GpioException as excp:  # GPIO busy
            logging.error('Creating SimpleHX711 failed=%s', str(excp))
        except Exception as excp:
            logging.error('Creating SimpleHX711 exception=%s', str(excp))
            raise
        else:
            logging.debug('HX711 created')
            self.hx711.setUnit(Mass.Unit.G)
            self.hx711.zero()
            self._weight = None
            self._scale_offset = int(self.config['hx711']['offset'])

    @property
    def lines(self):
        """ Converts keys of self.line_def to tuple """

        return tuple(self.line_def.keys())

    @property
    def chip_name(self):
        """ Returns chip_name from config """

        return self.config['GPIO']['chip_name']

    @property
    def shp_id(self):
        return self._shp_id

    @shp_id.setter
    def shp_id(self, value):
        try:
            self._shp_id = int(value)
        except ValueError:
            self._shp_id = None

    @property
    def box(self):
        return self._box

    @box.setter
    def box(self, value):
        try:
            self._box = int(value)
        except ValueError:
            self._box = None

    @property
    def weight(self):
        return self._weight

    @weight.setter
    def weight(self, value):
        try:
            self._weight = round(float(value))
        except ValueError:
            self._weight = None

    def event_handler(self, line_offset, event):
        # logging.debug(f"Edge detected on line {line_offset}, Event: {event.event_type}")

        if event.event_type == event.Type.RISING_EDGE:
            self.timestamp_rising[line_offset] = event.timestamp_ns
            """ DEL
            try:
                if len(self.dist3[line_offset]) == 2:  # уже было 2 измерения, значит это новое и нужно очистить
                    self.dist3[line_offset] = []
            except KeyError:
                self.dist3[line_offset] = []
                pass
            """

        elif event.event_type == event.Type.FALLING_EDGE:
            try:
                ts_delta = event.timestamp_ns - self.timestamp_rising[line_offset]
            except KeyError:
                logging.warning(f'NO rising. Skip: {self.dist3}')
            else:
                # if delta 36-38 ms then NO answer received!
                # dist_cm = round(ts_delta/1000/58.8, 1)
                # PROD dist_cm = round(ts_delta / 1000 / 57.72, 1)
                dist_cm = round(ts_delta * 0.0172032 /1000, 1)
                logging.debug(f"   {self.line_def[line_offset]['name']}(line={line_offset}), dist(cm)={dist_cm}")
                # DEL self.dist3[line_offset] = dist_cm

                #size: float = round(self.line_def[line_offset]['base'] - self.dist3[line_offset], 1)  # размер = база - расстояние до объекта
                size: float = round(self.line_def[line_offset]['base'] - dist_cm, 1)  # размер = база - расстояние до объекта
                self.size[self.line_def[line_offset]['name']] = size
                logging.debug(f'>> {self.line_def[line_offset]["name"]}, dist_cm={dist_cm}, \
                        size={size}')
                # DEL self.dist3[line_offset] = []
                self.timestamp_rising[line_offset] = {}

                #if len(self.size) == 3:  # получены все 3 измерения, записываем в БД и обнуляем
                #    self.pg_write()
                #    self.size = {}

    def mk_ins_fname(self):            
        dt_str = time.strftime("%Y-%m-%d-%H-%M-%S")
        return f'failed_inserts_{self._shp_id}_{self._box}_{dt_str}.sql'

    def pg_write(self):
        """ save results to PG database"""
        logging.debug(self.size)
        #ins_sql = self.curs.mogrify(INS_R3D, (self.shp_id, self.box, self.size['length'], self.size['width'],
        #                                      self.size['height'], self.weight))
        ins_sql = self.curs.mogrify(INS_R3D, (self.shp_id, self.box, self.size.get('length'),
                                              self.size.get('width'),
                                              self.size.get('height'), self.weight))

        if not self.do_query(ins_sql, reconnect=True):
            # save to file
            loc_fname = self.mk_ins_fname()
            with open(loc_fname, 'a') as file:
                file.write(ins_sql.decode("utf-8") + '\n')
            logging.error(f"Ошибка при вставке данных в базу данных. Данные сохранены в файл {loc_fname}.")
        else:
            logging.info("Данные сохранены в базу данных.")


    def do_weigh(self):
        """ Do weigh """
        self.weight = self.hx711.weight(Options(10, ReadType.Median))

    def set_zero(self, samples=10):
        """ Set zero offset for a sacle """
        self._scale_offset = round(self.hx711.read(Options(int(samples))))
        self.config['hx711']['offset'] = str(self._scale_offset)
        self.hx711.setOffset(self._scale_offset)
        with open(self.conf_name, 'w', encoding='utf-8') as cfgfile:
            self.config.write(cfgfile)

    def calibrate(self, known_weight, samples=10, unit='g'):
        """ Calibrate a sacle """
        logging.debug(f'known_weight={known_weight}')
        raw = self.hx711.read(Options(int(samples)))
        logging.debug(f'raw={raw}')
        refUnitFloat = (raw - self._scale_offset) / known_weight
        #refUnit = round(refUnitFloat, 0)
        refUnit = round(refUnitFloat)
        logging.debug('refUnitFloat=%s', refUnitFloat)
        logging.debug('refUnit=%s', refUnit)
        logging.debug('round(refUnit)=%s', round(refUnit))

        if refUnit == 0:
            refUnit = 1

        self.hx711.setReferenceUnit(refUnit)
        #self.hx711.setOffset(self._scale_offset)
        self.config['hx711']['ref_unit'] = str(refUnit)
        with open(self.conf_name, 'w', encoding='utf-8') as cfgfile:
            self.config.write(cfgfile)



def emu_mode(ruler3d):
    """ Emulation """
    RISING_VALUE = gpiod.EdgeEvent.Type.RISING_EDGE.value
    FALLING_VALUE = gpiod.EdgeEvent.Type.FALLING_EDGE.value
    logging.error("GPIO chip not found, run in EMU mode")
    # run emulator mode

    for emu_line in RULER3D.lines:
        for cnt in [0, 1]:
            # gpiod._ext.EDGE_EVENT_TYPE_RISING,
            RULER3D.event_handler(emu_line,
                                  gpiod.EdgeEvent(event_type=RISING_VALUE,
                                                  timestamp_ns=time.time_ns(),
                                                  line_offset=emu_line,
                                                  global_seqno=0,
                                                  line_seqno=emu_line)
                                  )
            time.sleep(0.001)
            # gpiod._ext.EDGE_EVENT_TYPE_FALLING,
            RULER3D.event_handler(emu_line,
                                  gpiod.EdgeEvent(event_type=FALLING_VALUE,
                                                  line_offset=emu_line,
                                                  timestamp_ns=time.time_ns(),
                                                  global_seqno=0,
                                                  line_seqno=emu_line)
                                  )


def main():
    """ Just main
    """


# Example usage

if __name__ == "__main__":
    import logging
    import sys

    # log_app.PARSER.add_argument('--uuid', type=str, help='an order uuid to check status')
    ARGS = log_app.PARSER.parse_args()
    print(ARGS)
    RULER3D = Ruler3D(args=ARGS)

    if RULER3D:
        logging.debug(RULER3D.line_def)
        # logging.debug('type: lines tuple=%s', type(RULER3D.lines))
        # logging.debug('lines tuple=%s', RULER3D.lines)

        try:
            HANDLER = GPIOEventHandler(chip_name=RULER3D.chip_name, line_numbers=RULER3D.lines,
                                       edge_type="both",
                                       callback=RULER3D.event_handler)
        except FileNotFoundError:
            HANDLER = None
            emu_mode(RULER3D)
        except PermissionError:
            logging.error("Permission denied")
            sys.exit(1)
        else:
            try:
                while True:
                    pass  # Keep the program running
                    time.sleep(1)
                    # print('loop')
            except KeyboardInterrupt:
                print('\ncaught keyboard interrupt!')

                if HANDLER is not None:
                    HANDLER.stop()
                print("Program terminated")
