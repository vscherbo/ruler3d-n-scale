#!/usr/bin/env python3
""" A PG listener to update Ozon stocks
"""

import argparse
import logging
import os
import select
import signal
# from sys import exc_info, exit
import sys
from time import sleep

import gpiod
import psycopg2
import psycopg2.extensions
from gpiod.line import Direction, Value

import log_app
from ruler3d import Ruler3D, GPIOEventHandler

PG_CHANNELS = ('do_ruler3d',)
PG_TIMEOUT = 5
MARK_DISPLAY = 3600
R3D_MAX_FREQ = 30

TRG_LINES = [73, 228, 229]  # to conf file
SAMPLE_WAIT = 0.1

SIGNALS_TO_NAMES_DICT = dict((getattr(signal, n), n) for n in dir(signal)
                             if n.startswith('SIG') and '_' not in n)


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
        # loc_home = os.path.expanduser('~')
        start_ruler3d(str_shp_id, str_box)


#############################################################################
def start_ruler3d(arg_shp_id, arg_box):
    """ sends 3 signals to activate sensor
    """
    # logging.debug('arg_shp_id=%s, arg_box=%s', arg_shp_id, arg_box)
    # logging.debug('RULER3D.lines=%s', RULER3D.lines)
    RULER3D.shp_id = arg_shp_id
    RULER3D.box = arg_box


    with gpiod.request_lines(
        RULER3D.chip_name,  # "/dev/gpiochip0",
        consumer="ruler3d-trigger",
        config={
            tuple(TRG_LINES): gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.ACTIVE
            )
        },
    ) as request:
        for line in TRG_LINES:
            request.set_value(line, Value.INACTIVE)
            sleep(SAMPLE_WAIT)
            logging.debug('  UP %s', line)
            request.set_value(line, Value.ACTIVE)
            sleep(0.001)
            request.set_value(line, Value.INACTIVE)
            logging.debug('FINISH %s', line)
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

    #self.config['PG']['pg_host'], self.config['PG']['pg_user']
    # password='PASS'-.pgpass
    #DSN = f'dbname={args.db} host={args.host} user={args.user}'
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
