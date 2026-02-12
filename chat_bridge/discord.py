"""Discord client module that sends notifications to a Discord channel."""

from . import events, utils
from .config import cfg

from pypeul import Tags

from discord import Client, Intents

import asyncio
import logging
import queue


class Bot(Client):
    def __init__(self, cfg, intents):
        super(Bot, self).__init__(intents=intents)
        self.cfg = cfg


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
            logging.error("Got unknown event for discord: %r" % evt.type)


def start():
    """Starts the Discord client."""
    if not cfg.discord:
        logging.warning("Skipping Discord module: no configuration provided")
        return

    logging.info("Starting Discord client")

    intents = Intents.default()
    intents.guilds = True
    intents.guild_messages = True

    bot = Bot(cfg.discord, intents)
    utils.DaemonThread(target=bot.run, kwargs={"token": cfg.discord.token}).start()

    evt_target = EventTarget(bot)
    events.dispatcher.register_target(evt_target)
    utils.DaemonThread(target=evt_target.run).start()
