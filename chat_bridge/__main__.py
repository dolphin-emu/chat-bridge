"""Main module for Dolphin Chat Bridge.

Initializes and registers the required components then starts the main event
loop of the process.
"""

from . import (
    config,
    discord,
    events,
    ircclient,
)

import argparse
import datetime
import functools
import logging
import logging.handlers
import platform
import signal
import time


class EventLoggingHandler(logging.Handler):
    """Emits internal_log events to the internal event dispatcher when a log
    message is received."""

    def emit(self, record):
        evt = events.InternalLog(
            record.levelname,
            record.pathname,
            record.lineno,
            record.msg,
            str(record.args),
        )
        events.dispatcher.dispatch("logging", evt)


def setup_logging(program, verbose=False, local=True, file=False, syslog=True):
    """Sets up the default Python logger.

    Always log to syslog, optionaly log to stdout.

    Args:
      program: Name of the program logging informations.
      verbose: If true, log more messages (DEBUG instead of INFO).
      local: If true, log to stdout as well as syslog.
      file: If true, log to a file.
      syslog: If true, log to syslog.
    """
    loggers = []
    if syslog and platform.system() == "Linux":
        loggers.append(logging.handlers.SysLogHandler("/dev/log"))
    loggers.append(EventLoggingHandler())
    if local:
        loggers.append(logging.StreamHandler())
    for logger in loggers:
        logger.setFormatter(
            logging.Formatter(program + ": [%(levelname)s] %(message)s")
        )
        logging.getLogger("").addHandler(logger)
    if file:
        now = datetime.datetime.now()
        log_filename = f"{program}-{now.strftime('%Y%m%d-%H%M%S')}.log"
        file_handler = logging.FileHandler(log_filename)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s " + program + ": [%(levelname)s] %(message)s"
            )
        )
        logging.getLogger("").addHandler(file_handler)
    logging.getLogger("").setLevel(logging.DEBUG if verbose else logging.INFO)


def reload_config(path, *, sighup=False):
    with open(path) as fp:
        config.load(fp)
    if sighup:
        logging.info("SIGHUP received, reloaded config")
        events.dispatcher.dispatch("sighup", events.ConfigReload())


def main():
    # Parse command line flags.
    parser = argparse.ArgumentParser(
        description="Dolphin Chat Bridge event dispatching server."
    )
    parser.add_argument(
        "--verbose", help="Increases logging level.", action="store_true", default=False
    )
    parser.add_argument(
        "--no_local_logging",
        help="Disable stderr logging.",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--no-syslog-logging",
        help="Disable syslog logging.",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--config",
        help="Path to configuration file.",
        required=True,
    )
    parser.add_argument(
        "--log-to-file",
        help="Log to a file with a timestamped name.",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()

    # Initialize logging.
    setup_logging(
        "chat-bridge",
        args.verbose,
        not args.no_local_logging,
        args.log_to_file,
        not args.no_syslog_logging,
    )

    logging.info("Starting Dolphin Chat Bridge.")

    # Load configuration from disk.
    reload_config(args.config)
    signal.signal(
        signal.SIGHUP, lambda *a, **kw: reload_config(args.config, sighup=True)
    )

    logging.info("Configuration loaded, starting modules initialization.")

    # Start the modules.
    for mod in [
        discord,
        ircclient,
    ]:
        mod.start()

    logging.info("Modules started, waiting for events.")

    # Loop to wait for signals/exceptions.
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
