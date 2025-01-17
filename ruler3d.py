#!/usr/bin/env python3

import time
import gpiod
import threading

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


INS_R3D = "INSERT INTO shp.ruler3d (shp_id, box, length, width, height) VALUES (%s, %s, %s, %s, %s);"


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

    @property
    def lines(self):
        """ Converts keys of self.line_def to tuple """
        return tuple(self.line_def.keys())

    @property
    def chip_name(self):
        """ Returns chip_name from config """
        return self.config['GPIO']['chip_name']

    def event_handler(self, line_offset, event):
        # logging.debug(f"Edge detected on line {line_offset}, Event: {event.event_type}")
        if event.event_type == event.Type.RISING_EDGE:
            self.timestamp_rising[line_offset] = event.timestamp_ns
            try:
                if len(self.dist3[line_offset]) == 2:
                    self.dist3[line_offset] = []
            except KeyError:
                self.dist3[line_offset] = []
                pass

        elif event.event_type == event.Type.FALLING_EDGE:
            try:
                ts_delta = event.timestamp_ns - self.timestamp_rising[line_offset]
            except KeyError:
                logging.warning(f'NO rising. Skip: {self.dist3}')
            else:
                # if delta 38 ms then NO answer received!
                # dist_cm = round(ts_delta/1000/58.8, 1)
                dist_cm = round(ts_delta / 1000 / 57.72, 1)
                logging.debug(f'   {line_offset}, dist(cm)={dist_cm}')
                self.dist3[line_offset].append(dist_cm)
                if len(self.dist3[line_offset]) == 2:
                    dist_avg = round((self.dist3[line_offset][0] + self.dist3[line_offset][1]) /
                                     2.0, 1)
                    self.dist3[line_offset] = []
                    size: float = round(self.line_def[line_offset]['base'] - dist_avg, 1)
                    self.size[self.line_def[line_offset]['name']] = size
                    logging.debug(f'{self.line_def[line_offset]["name"]}, dist_avg={dist_avg}, \
                            size={size}')
                    self.timestamp_rising[line_offset] = {}
                    if len(self.size) == 3:
                        self.pg_write()
                        self.size = {}

    def pg_write(self):
        """ save results to PG database"""
        logging.debug(self.size)
        ins_sql = self.curs.mogrify(INS_R3D, (112233, 1, self.size['length'], self.size['width'],
                                              self.size['height']))
        if not self.do_query(ins_sql, reconnect=True):
            # save to file
            dt_str = time.strftime("%Y-%m-%d-%H-%M-%S")
            with open(f'failed_inserts_{dt_str}.sql', 'a') as file:
                file.write(ins_sql.decode("utf-8") + '\n')
            logging.error("Ошибка при вставке данных в базу данных. Данные сохранены в файл.")


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
