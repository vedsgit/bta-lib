#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
# Copyright 2020 Daniel Rodriguez
# Use of this source code is governed by the MIT License
###############################################################################
import argparse
import logging
from logging import info as loginfo, error as logerror, debug as logdebug
import os.path
import sys

import pandas as pd
import talib  # noqa: F401

# append module root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import btalib  # noqa: E402 F401

csv = '../data/2006-day-001.txt'
df = pd.read_csv(
    csv, parse_dates=True, index_col='date', skiprows=1,
    names=['date', 'open', 'high', 'low', 'close', 'volume', 'openinterest'],
)

RESULTS = {}


def run_indicators(main=False, **kwargs):
    pargs = parse_args(None if main else [], main=main)

    loginfo('')
    loginfo('[+] From main        : {}'.format(main))
    if pargs.list_names:
        loginfo(', '.join(kwargs))
        return 0  # success

    for name, testdata in kwargs.items():
        if name != (pargs.name or name):
            continue
        RESULTS[name] = run_indicator(pargs, name, testdata, main=main)

    all_good = all(RESULTS.values())

    loginfo('[+]' + '-' * 74)
    logging.info('[+] Global Result: {}'.format(all_good))
    if not all_good:
        sys.exit(1)


def run_indicator(pargs, name, testdata, main=False):
    loginfo('[+]' + '-' * 74)
    loginfo('[+] Running test for : {}'.format(name))
    loginfo('[+] Testdata is      : {}'.format(testdata))

    # If a string has been passed, check and return the result
    if isinstance(testdata, str):
        rother = RESULTS.get(testdata, False)
        loginfo('[+] Test completed with : {}'.format(testdata))
        loginfo('[+] Test result         : {}'.format(rother))
        return rother

    elif callable(testdata):
        loginfo('[+] Calling tesdata')
        try:
            ret = testdata(main=main)
        except AssertionError as e:
            ret = False
            _, _, tb = sys.exc_info()
            tb_info = traceback.extract_tb(tb)
            filename, line, func, text = tb_info[-1]
            logging.error('[-] Assertiont Message "{}"'.format(e))
            logging.error('[-] File {} / Line {} / Text {}'.format(
                filename, line, text,
            ))

        loginfo('[+] Test completed with : {}'.format(ret))
        return ret

    # bta-lib indicator calculation
    # The indicator is either the given test name or specified in test data
    btind = getattr(btalib, testdata.get('btind', name))

    # The inputs are either specified in the testdata or the default from ind
    inputs = [df[x] for x in testdata.get('inputs', btind.inputs)]

    btkwargs = testdata.get('btkwargs', {})
    if pargs.bt_overargs:
        btkwargs = eval('dict(' + pargs.bt_overargs + ')')
    elif pargs.bt_kwargs:
        btkwargs.update(eval('dict(' + pargs.bt_kwargs + ')'))

    btresult = btind(*inputs, **btkwargs)
    btouts = list(btresult.outputs)
    for a, b in testdata.get('swapouts', {}).items():
        btouts[a], btouts[b] = btouts[b], btouts[a]

    checkminperiods = testdata.get('minperiods', [])
    if checkminperiods:
        eqperiods = btresult._minperiods == checkminperiods
    else:
        eqperiods = -1

    # Now, determine the actual indicators. The name is the name from the
    # bta-lib indicator. Find the corresponding ta indicator
    # Either specified or capitalize the given name
    taind_name = testdata.get('taind', name.upper())
    try:
        taind = getattr(talib, taind_name)
    except AttributeError:
        for taind_name in btind.alias:
            try:
                taind = getattr(talib, taind_name)
            except AttributeError:
                pass
            else:
                break
        else:
            logerror('[-] No ta-lib indicator found for: {}'.format(name))
            return False

    takwargs = testdata.get('takwargs', {})
    if pargs.ta_overargs:
        takwargs = eval('dict(' + pargs.ta_overargs + ')')
    elif pargs.ta_kwargs:
        takwargs.update(eval('dict(' + pargs.ta_kwargs + ')'))

    touts = taind(*inputs, **takwargs)
    if isinstance(touts, pd.Series):  # check if single output
        touts = (touts,)  # consistent single-multiple result presentation

    # Result checking
    logseries = []
    equal = True  # innocent until proven guilty
    for tseries, btout in zip(touts, btouts):
        btseries = btout.series

        # Rounding to x decimals
        decimals = pargs.decimals
        if decimals is None:  # no command line argument was given
            decimals = testdata.get('decimals', None)

        if decimals is not None and decimals >= 0:
            tseries = tseries.round(decimals=decimals)
            btseries = btseries.round(decimals=decimals)

        # Keep record of entire series for verbosity
        logseries.append([tseries, btseries, btseries.eq(tseries)])

        # Minperiod test check settings
        test_minperiod = pargs.minperiod
        if test_minperiod is None:  # nothing in command line
            test_minperiod = testdata.get('minperiod', 0)
        if not test_minperiod:
            minperiod = btresult._minperiod  # global minperiod
        elif test_minperiod > 0:
            minperiod = btout._minperiod  # per output minperiod
        else:  # < 0
            minperiod = 0  # no minperiod at all

        if minperiod:  # check requested from non starting point
            tseries = tseries[minperiod:]
            btseries = btseries[minperiod:]

        equality = btseries.eq(tseries)  # calculate equality of series
        allequal = equality.all()
        if not allequal:  # make a nancheck
            na_bt, na_ta = btseries.isna(), tseries.isna()
            equality = na_bt.eq(na_ta)  # calculate equality of series
            allequal = equality.all()

        equal = equal and allequal  # check if result still equal True

    logging.info('[+] Result: {}'.format(equal))

    if pargs.verbose:  # if verbosity is requested
        # General Information
        logdebug('-' * 78)
        logdebug('Result         : {}'.format(equal))
        logdebug('Chk Minperiods : {} {}'.format(
            eqperiods,
            '(-1 if no check done)',
        ))
        logdebug('Decimals       : {}'.format(decimals))
        logdebug('-' * 78)
        logdebug('Indicator      : {}'.format(btind.__name__))
        logdebug('Inputs         : {}'.format(btind.inputs))
        logdebug('Outputs        : {}'.format(btind.outputs))
        logdebug('Def Params     : {}'.format(btind.params))
        logdebug('Params         : {}'.format(dict(btresult.params)))
        logdebug('-' * 78)
        logdebug('Period Check   : {} {}'.format(
            test_minperiod,
            ('(0: after max minperiod / 1: per line / -1: ignore)'),
        ))
        logdebug('Minperiods     : {}'.format(btresult._minperiods))
        logdebug('Minperiod      : {}'.format(btresult._minperiod))
        logdebug('-' * 78)

        # Generate logging dataframe
        pdct = {'count': range(1, len(df.index) + 1)}  # visual period check
        for tseries, btseries, eqseries in logseries:
            name = btseries._name

            pdct['ta__' + name] = tseries
            pdct['bta_' + name] = btseries
            pdct['eq__' + name] = eqseries

        logdf = pd.DataFrame(pdct)
        logdebug(logdf.to_string())

    return equal


def parse_args(pargs, main=False):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=(
            'Test Argument Parser'
        )
    )

    parser.add_argument('--name', default='',
                        help='Select specific test name')

    parser.add_argument('--list-names', action='store_true',
                        help='List all test names and exit')

    parser.add_argument('--decimals', '-d', type=int,
                        help='Force rounding to x decimals')

    parser.add_argument('--minperiod', '-mp', type=int,
                        help='Minperiod chk: -1: No, 0: per-ind, 1: per-line')

    parser.add_argument('--bt-kwargs', '-btk', default='', metavar='kwargs',
                        help='kwargs in key=value format (update)')

    parser.add_argument('--bt-overargs', '-btok', default='', metavar='kwargs',
                        help='kwargs in key=value format (override)')

    parser.add_argument('--ta-kwargs', '-tak', default='', metavar='kwargs',
                        help='kwargs in key=value format (update)')

    parser.add_argument('--ta-overargs', '-taok', default='', metavar='kwargs',
                        help='kwargs in key=value format (override)')

    pgroup = parser.add_argument_group('Verbosity Options')
    pgroup.add_argument('--stderr', action='store_true',
                        help='Log to stderr, else to stdout')
    pgroup = pgroup.add_mutually_exclusive_group()
    pgroup.add_argument('--quiet', '-q', action='store_true',
                        help='Silent (errors will be reported)')
    pgroup.add_argument('--verbose', '-v', action='store_true',
                        help='Increase verbosity level')

    pargs = parser.parse_args(pargs)
    logconfig(pargs, main=main)  # config logging
    return pargs


def logconfig(pargs, main=False):
    if pargs.quiet:
        verbose_level = logging.ERROR
    else:
        verbose_level = logging.INFO - pargs.verbose * 10  # -> DEBUG

    logger = logging.getLogger()
    for h in logger.handlers:  # Remove all loggers from root
        logger.removeHandler(h)

    # when not main, log always to stderr to let nosetests capture the output
    if not main:
        stream = sys.stderr
    else:
        stream = sys.stderr if pargs.stderr else sys.stdout  # choose stream

    logging.basicConfig(
        stream=stream,
        format="%(message)s",  # format="%(levelname)s: %(message)s",
        level=verbose_level,
    )
