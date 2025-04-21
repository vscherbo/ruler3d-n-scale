#!/usr/bin/env python3
""" A PG listener to update Ozon stocks
"""

import ctypes
import argparse
import logging
import os
import select
import signal
# from sys import exc_info, exit
import sys
from time import sleep
import ast

import gpiod
import psycopg2
import psycopg2.extensions
from gpiod.line import Direction, Value

#from HX711 import *

import log_app
from ruler3d import Ruler3D, GPIOEventHandler

PG_CHANNELS = ('do_ruler3d',)
PG_TIMEOUT = 5
MARK_DISPLAY = 3600
R3D_MAX_FREQ = 30

TRG_TIME = 0.001
#TRG_LINES = [73, 228, 229]  # to conf file
"""
GPIO=73, Phys=7
GPIO=228, Phys=5
GPIO=229, Phys=3
"""
SAMPLE_WAIT = 0.1

SIGNALS_TO_NAMES_DICT = dict((getattr(signal, n), n) for n in dir(signal)
                             if n.startswith('SIG') and '_' not in n)

# Load the shared library
gpio_lib = ctypes.CDLL("./gpio_pulse.so")

# Define function argument types
gpio_lib.generate_pulse.argtypes = [ctypes.c_char_p, ctypes.c_int]

####################################################################################################
def do_start_ruler3d(notify):
    """ Run ??? """
    logging.debug("     Inside do_start_ruler3d")
    try:
        (str_shp_id, str_box) = notify.payload.split('^')
    except ValueError:
        logging.warning('wrong payload=%s', notify.payload)
    else:
        logging.debug('str_shp_d=%s, str_box=%s', str_shp_id, str_box)

        RULER3D.shp_id = str_shp_id
        RULER3D.box = str_box

        RULER3D.do_weigh()
        #loc_weight = HX711.weight(Options(10, ReadType.Median))
        #logging.info(f'loc_weight={loc_weight}')
        #RULER3D.weight = loc_weight

        call_pulse()
        sleep(2)
        RULER3D.pg_write()


#############################################################################
def call_pulse():
    """ sends 10 uS pulse signals to activate sensors
    """
    # Pass a bytes string (C-compatible)
    #RULER3D.chip_name.encode('utf-8')
    #chip_name = b"/dev/gpiochip0"  # Convert to bytes (b"string")
    chip_name = RULER3D.chip_name.encode('utf-8')
    RULER3D.size = {}

    for gpio_line in TRG_LINES:
        gpio_lib.generate_pulse(chip_name, gpio_line)
        sleep(SAMPLE_WAIT)

#############################################################################
def do_listen(arg_conn, a_pg_timeout):
    """ Do listen """
    sel_res = select.select([arg_conn], [], [], a_pg_timeout)

    if sel_res == ([], [], []):
        pass
    else:
        arg_conn.poll()

        while arg_conn.notifies:
            notify = arg_conn.notifies.pop(0)
            logging.info("=========================================")
            logging.info("Got NOTIFY: %s %s %s", notify.pid, notify.channel, notify.payload)

            if 'do_ruler3d' == notify.channel:
                do_start_ruler3d(notify)
            else:
                logging.warning("unexpected notify.channel=%s", notify.channel)
            arg_conn.commit()
# End of do_listen


def main(arg_conn):
    """ Just main """
    # main loop

    mark_counter = 0
    loc_rc = 1
    do_while = 1

    def signal_handler(*arg_signal):
        """ A handler of signals
        Ctrl+C """
        logging.info('Got signal: %s',
                     SIGNALS_TO_NAMES_DICT.get(arg_signal[0], f"Unnamed signal: {arg_signal[0]}"))
        nonlocal do_while
        nonlocal loc_rc
        do_while = 0
        loc_rc = 0

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while do_while == 1:
        try:
            do_listen(arg_conn, PG_TIMEOUT)
            mark_counter += PG_TIMEOUT

            if mark_counter >= MARK_DISPLAY:
                mark_counter = 0
                logging.info("Heartbeat mark")
        except psycopg2.Error as exc:
            do_while = 0
            logging.info("Try to re-connect... exc=%s", str(exc))
        except BaseException as exc:
            logging.warning("Other exception=%s", str(exc))
            raise

    logging.info("Exiting")

    return loc_rc


if __name__ == '__main__':
    args = log_app.PARSER.parse_args()

    ### ruler3d with config parsing!
    RULER3D = Ruler3D(args=args)
    if RULER3D:
        logging.debug(RULER3D.line_def)

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
    ### end of ruler3d

    #TRG_L = RULER3D.config['GPIO']['trg_lines']
    #TRG_LINES = RULER3D.config['GPIO']['trg_lines']
    #TRG_LINES = [int(item) for item in RULER3D.config['GPIO']['trg_lines']]
    TRG_LINES = ast.literal_eval(RULER3D.config['GPIO']['trg_lines'])
    logging.debug('conf.trg_lines=%s', TRG_LINES)
    logging.debug('type(trg_lines)=%s', type(TRG_LINES))
    logging.debug('type(trg_lines[0])=%s', type(TRG_LINES[0]))

    #HX711 = SimpleHX711(231, 232, 100, -24753)
    #if HX711:
    #    logging.debug('HX711 created')
    #    HX711.zero()

    # password - .pgpass
    DSN = f"dbname={RULER3D.config['PG']['pg_user']} host={RULER3D.config['PG']['pg_host']} user={RULER3D.config['PG']['pg_user']}"

    numeric_level = getattr(logging, args.log_level, None)

    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {numeric_level}')

    """
    LOG_FORMAT = '%(asctime)-15s | %(levelname)-7s | %(filename)-25s:%(lineno)4s - %(funcName)25s()\
            | %(message)s'
    (prg_name, prg_ext) = os.path.splitext(os.path.basename(__file__))
    logging.basicConfig(filename=prg_name+'.log', format=LOG_FORMAT, level=numeric_level)  # INFO)
    """

    logging.info("Started")
    DO_CONNECT = 1


    while DO_CONNECT == 1:
        # sel_res = ([], [], [])
        try:
            conn = psycopg2.connect(DSN)
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            curs = conn.cursor()

            for pg_channel in PG_CHANNELS:
                curs.execute("LISTEN " + pg_channel + ";")
                logging.info("Waiting for notifications on channel %s", pg_channel)
        except psycopg2.Error as err:
            logging.error("Connection failed, ERROR=%s", err)
            logging.warning(" Exception on connect=%s. Sleep for %s", str(err), str(PG_TIMEOUT))
            sleep(PG_TIMEOUT)
        else:
            DO_CONNECT = main(conn)  # 0 if Ctrl+C

    sys.exit(DO_CONNECT)
