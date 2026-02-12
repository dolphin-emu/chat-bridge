"""IRC client module that sends events to an IRC channel with nice,
human-readable formatting. Also receives events from registered users."""

from . import events, utils
from .config import cfg

from pypeul import IRC, Tags

import logging
import queue


class Bot(IRC):
    def __init__(self, cfg):
        super(Bot, self).__init__()
        self.cfg = cfg

    def start(self):
        self.connect(self.cfg.server, self.cfg.port, self.cfg.ssl)
        self.ident(
            self.cfg.nick,
            sasl_username=self.cfg.sasl_username,
            sasl_password=self.cfg.sasl_password,
        )
        self.set_reconnect(lambda n: 10 * n)
        self.run()

    def on_ready(self):
        self.join(self.cfg.channel)


class EventTarget(events.EventTarget):
    def __init__(self, bot):
        self.bot = bot
        self.queue = queue.Queue()

    def push_event(self, evt):
        self.queue.put(evt)

    def accept_event(self, evt):
        accepted_types = []
        return evt.type in accepted_types

    def run(self):
        while True:
            evt = self.queue.get()
            logging.error("Got unknown event for irc: %r" % evt.type)


def start():
    """Starts the IRC client."""
    if not cfg.irc:
        logging.warning("Skipping IRC module: no configuration provided")
        return

    server = cfg.irc.server
    port = cfg.irc.port
    ssl = cfg.irc.ssl
    nick = cfg.irc.nick
    channels = cfg.irc.channels

    logging.info(
        "Starting IRC client: server=%r port=%d ssl=%s nick=%r sasl=%s channels=%r",
        server,
        port,
        ssl,
        nick,
        cfg.irc.sasl_username is not None and cfg.irc.sasl_password is not None,
        channels,
    )

    bot = Bot(cfg.irc)
    utils.DaemonThread(target=bot.start).start()

    evt_target = EventTarget(bot)
    events.dispatcher.register_target(evt_target)
    utils.DaemonThread(target=evt_target.run).start()
