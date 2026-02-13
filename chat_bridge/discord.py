"""Discord client module for relaying messages between Discord and IRC."""

from . import events, utils
from .config import cfg

from pypeul import Tags

from discord import Client, Intents, TextChannel, MessageType

import asyncio
import logging
import queue
import re


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

        evt = events.DiscordMessage(message, self.user)
        events.dispatcher.dispatch("discord", evt)

    async def on_raw_message_edit(self, payload):
        if payload.message.channel.id != self.cfg.channel:
            return

        evt = events.DiscordMessageEdit(payload.message, self.user)
        events.dispatcher.dispatch("discord", evt)

    async def on_reaction_add(self, reaction, user):
        if reaction.message.channel.id != self.cfg.channel:
            return

        evt = events.DiscordReactionAdd(reaction, user, self.user)
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

        def replacement_callback(match):
            username = match.group(1)

            user = channel.guild.get_member_named(username)

            if not user:
                return username

            return "<@%s>" % user.id

        # Find all usernames in [] and add mentions wherever possible
        text = re.sub(r"\[(.*?)\]", replacement_callback, text)

        f = asyncio.run_coroutine_threadsafe(
            channel.send(text, suppress_embeds=True), self.loop
        )
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
    intents.reactions = True
    intents.members = True

    bot = Bot(cfg.discord, intents)
    utils.DaemonThread(target=bot.run, kwargs={"token": cfg.discord.token}).start()

    evt_target = EventTarget(bot)
    events.dispatcher.register_target(evt_target)
    utils.DaemonThread(target=evt_target.run).start()
