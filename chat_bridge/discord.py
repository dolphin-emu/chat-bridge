"""Discord client module that sends notifications to a Discord channel."""

from . import events, utils
from .config import cfg

from pypeul import Tags

from discord import Client, Intents, TextChannel, MessageType

import asyncio
import logging
import queue


class Bot(Client):
    def __init__(self, cfg, intents):
        super(Bot, self).__init__(intents=intents)
        self.cfg = cfg

    async def on_message(self, message):
        if message.author == self.user:
            return

        channel = message.channel
        if channel.id != self.cfg.channel:
            return

        if message.type != MessageType.default and message.type != MessageType.reply:
            return

        if message.author.id in self.cfg.ignore_users:
            return

        evt = events.DiscordMessage(message)
        events.dispatcher.dispatch("discord", evt)

    def format_irc_message(self, msg):
        """
        Turns an IRC message into formatted text for Discord.
        """
        chunklist = Tags.parse(msg)

        ret = ""
        for chunk in chunklist.children:
            text = chunk.text
            # Escape all backslashes first.
            text = text.replace("\\", "\\\\")
            # Escape the < character to prevent Discord from parsing it.
            for char in ("<",):
                text = text.replace(char, "\\" + char)

            if "reset" in chunk.tags:
                ret += text
                continue

            if "bold" in chunk.tags:
                text = "**" + text + "**"
            if "monospace" in chunk.tags:
                text = "`" + text + "`"
            if "italics" in chunk.tags:
                text = "*" + text + "*"
            if "strikethrough" in chunk.tags:
                text = "~~" + text + "~~"
            if "underline" in chunk.tags:
                text = "__" + text + "__"

            ret += text

        return ret

    def relay_irc_message(self, who, what, action):
        if not action:
            message_format = "**<%s>** %s"
        else:
            message_format = "＊ **%s** %s"

        text = message_format % (who, self.format_irc_message(what))

        channel = self.get_channel(self.cfg.channel)
        f = asyncio.run_coroutine_threadsafe(channel.send(text), self.loop)
        f.result()


class EventTarget(events.EventTarget):
    def __init__(self, bot):
        self.bot = bot
        self.queue = queue.Queue()

    def push_event(self, evt):
        self.queue.put(evt)

    def accept_event(self, evt):
        accepted_types = [events.IRCMessage.TYPE]
        return evt.type in accepted_types

    def run(self):
        while True:
            evt = self.queue.get()
            if evt.type == events.IRCMessage.TYPE:
                self.bot.relay_irc_message(evt.who, evt.what, evt.action)
            else:
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
    intents.message_content = True

    bot = Bot(cfg.discord, intents)
    utils.DaemonThread(target=bot.run, kwargs={"token": cfg.discord.token}).start()

    evt_target = EventTarget(bot)
    events.dispatcher.register_target(evt_target)
    utils.DaemonThread(target=evt_target.run).start()
