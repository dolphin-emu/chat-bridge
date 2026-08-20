"""Discord client module for relaying messages between Discord and IRC."""

from . import events, utils
from .config import cfg

from pypeul import Tags

from discord import (
    Client,
    Intents,
    TextChannel,
    MessageType,
    NotFound,
    AuditLogAction,
    Forbidden,
    HTTPException,
)

from datetime import datetime, timedelta, timezone

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

        if not payload.message.edited_at:
            return

        now = datetime.now(timezone.utc)
        if now - payload.message.edited_at > timedelta(seconds=10):
            return

        evt = events.DiscordMessageEdit(payload.message, self.user)
        events.dispatcher.dispatch("discord", evt)

    async def on_raw_message_delete(self, payload):
        if payload.channel_id != self.cfg.channel:
            return

        channel = self.get_channel(payload.channel_id)
        if not channel:
            logging.error(
                "Channel %s not found in on_raw_message_delete", payload.channel_id
            )
            return

        message = payload.cached_message
        if not message:
            try:
                message = await channel.fetch_message(payload.message_id)
            except (NotFound, HTTPException):
                logging.error(
                    "Message %s not found in on_raw_message_delete", payload.message_id
                )
                return

        deleter = None

        if payload.guild_id:
            guild = self.get_guild(payload.guild_id)
            if guild:
                try:
                    async for entry in guild.audit_logs(
                        limit=5, action=AuditLogAction.message_delete
                    ):
                        if (
                            message
                            and entry.target.id == message.author.id
                            and entry.extra.channel.id == payload.channel_id
                        ):
                            deleter = entry.user
                            break
                except (Forbidden, HTTPException):
                    logging.error("Failed to fetch audit logs in on_raw_message_delete")
                    return
            else:
                logging.error(
                    "Guild %s not found in on_raw_message_delete", payload.guild_id
                )
                return
        else:
            logging.error("Guild not specified in on_raw_message_delete")

        if deleter is None and message:
            deleter = message.author

        evt = events.DiscordMessageDelete(
            deleter,
            message,
            self.user,
        )
        events.dispatcher.dispatch("discord", evt)

    async def on_raw_reaction_add(self, payload):
        if payload.channel_id != self.cfg.channel:
            return

        channel = self.get_channel(payload.channel_id)
        if not channel:
            logging.error(
                "Channel %s not found in on_raw_reaction_add", payload.channel_id
            )
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except NotFound:
            logging.error(
                "Message %s not found in on_raw_reaction_add", payload.message_id
            )
            return

        user = payload.member
        if not user:
            try:
                user = await self.fetch_user(payload.user_id)
            except NotFound:
                logging.error(
                    "User %s not found in on_raw_reaction_add", payload.user_id
                )
                return

        evt = events.DiscordReactionAdd(message, payload.emoji, user, self.user)
        events.dispatcher.dispatch("discord", evt)

    def format_irc_message(self, msg):
        """
        Turns an IRC message into formatted text for Discord.
        """
        chunklist = Tags.parse(msg)

        ret = ""
        active_styles = []
        style_map = {
            "bold": "**",
            "italics": "*",
            "underline": "__",
            "strikethrough": "~~",
            "monospace": "`",
        }

        for chunk in chunklist.children:
            text = chunk.text.replace("\\", "\\\\").replace("<", "\\<")

            if "reset" in chunk.tags:
                target_styles = set()
            else:
                target_styles = {tag for tag in chunk.tags if tag in style_map}

            # Find common prefix of styles to keep
            keep_count = 0
            for style in active_styles:
                if style not in target_styles:
                    break
                keep_count += 1

            # Close unwanted styles
            while len(active_styles) > keep_count:
                ret += style_map[active_styles.pop()]

            # Open new styles (sort new styles to ensure correct nesting order)
            new_styles = sorted(
                (s for s in target_styles if s not in active_styles),
                key=lambda s: (s == "monospace", s),
            )

            for style in new_styles:
                ret += style_map[style]
                active_styles.append(style)

            ret += text

        # Close any remaining active styles
        while active_styles:
            ret += style_map[active_styles.pop()]

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

    bot = Bot(cfg.discord, intents)
    utils.DaemonThread(target=bot.run, kwargs={"token": cfg.discord.token}).start()

    evt_target = EventTarget(bot)
    events.dispatcher.register_target(evt_target)
    utils.DaemonThread(target=evt_target.run).start()
