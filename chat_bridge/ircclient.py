"""IRC client module for relaying messages between Discord and IRC."""

from . import events, utils
from .config import cfg

from discord import MessageReferenceType

from pypeul import IRC, Tags

import logging
import re
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

    def sanitize_name(self, name):
        # Insert a zero-width space to prevent accidental pings on IRC.
        return name[0] + "\ufeff" + name[1:]

    def sanitize_irc_names(self, text, nicks):
        """Sanitizes all occurrences of IRC nicks to prevent accidental pings.

        The algorithm used to detect nicks is based on Textual's "full word matches":
        https://github.com/Codeux-Software/Textual/blob/243a6e2c06ad92a2ad590e071d902ec3c9b389d8/Sources/App/Classes/Views/Channel%20View/TVCLogRenderer.m#L378
        """

        # Sort by length to ensure "OatmealDome" is matched before "Oatmeal", for example
        sorted_nicks = sorted([n for n in nicks if n], key=len, reverse=True)

        if not sorted_nicks:
            return text

        # Compile a regex with two capturing groups: "[nick]" and "nick"
        nicks_pattern = "|".join(map(re.escape, sorted_nicks))
        full_pattern = re.compile(
            f"\\[({nicks_pattern})\\]|({nicks_pattern})", re.IGNORECASE
        )

        def replacement_callback(match):
            # If the match is in group 1, return the nick without [] to passthrough the ping.
            if match.group(1):
                return match.group(1)

            found_str = match.group(2)
            start, end = match.span(2)

            # If match starts with alphanumeric char, prev char must not be alphanumeric
            if found_str[0].isalnum():
                if start > 0 and text[start - 1].isalnum():
                    return found_str

            # If match ends with alphanumeric char, next char must not be alphanumeric
            if found_str[-1].isalnum():
                if end < len(text) and text[end].isalnum():
                    return found_str

            # Match found, replace
            return self.sanitize_name(found_str)

        return full_pattern.sub(replacement_callback, text)

    def extract_sender_from_discord_message(
        self, message, bot_user, parent_message=None
    ):
        # If this message was not sent by ourselves, just return the sender's name.
        if message.author.id != bot_user.id:
            return self.sanitize_name(message.author.name)

        # Extract the original sender on IRC from the message content.
        match = re.match(r"^\*\*<(.*)>\*\* ", message.content)
        if match:
            nick = match.group(1)

            # Check if the parent message mentions the bot. If so, ping the user on IRC.
            if parent_message and bot_user.mentioned_in(parent_message):
                return nick

            # Otherwise, return the nick sanitized to avoid a ping.
            return self.sanitize_name(nick)

        return "???"

    def relay_discord_message(self, msg, bot_user, edited=False):
        preamble_items = []

        if edited:
            preamble_items.append("edited previous message")

        if msg.reference is not None:
            if msg.reference.resolved is not None:
                if msg.reference.type == MessageReferenceType.reply:
                    preamble_items.append(
                        "in reply to %s"
                        % self.extract_sender_from_discord_message(
                            msg.reference.resolved, bot_user, msg
                        )
                    )
                elif msg.reference.type == MessageReferenceType.forward:
                    preamble_items.append(
                        "forwarded message from %s"
                        % self.extract_sender_from_discord_message(
                            msg.reference.resolved, bot_user
                        )
                    )
            else:
                preamble_items.append("unresolved reference")

        if len(preamble_items) > 0:
            preamble = "(" + ", ".join(preamble_items) + ") "
        else:
            preamble = ""

        if msg.content:
            text = msg.content

            irc_nicks = (u.nick for u in self.users_in(self.cfg.channel))
            text = self.sanitize_irc_names(text, irc_nicks)

            for user in msg.mentions:
                text = text.replace(
                    "<@%s>" % user.id, "@%s" % self.sanitize_name(user.name)
                )

            for role in msg.role_mentions:
                text = text.replace(
                    "<@&%s>" % role.id, "@%s" % self.sanitize_name(role.name)
                )

            for channel in msg.channel_mentions:
                text = text.replace(
                    "<#%s>" % channel.id, "#%s" % self.sanitize_name(channel.name)
                )

            def emoji_replacement_callback(match):
                return '[custom emoji "%s"]' % Tags.Bold(match.group(1))

            # Replace all custom emoji with their names
            text = re.sub(r"<:(\w+):\d+>", emoji_replacement_callback, text)
        else:
            text = ""

        irc_message = "%s%s %s%s" % (
            Tags.Bold(self.sanitize_name(msg.author.name)),
            Tags.Bold(":"),
            preamble,
            text,
        )
        self.message(self.cfg.channel, irc_message)

        if msg.poll:
            self.message(
                self.cfg.channel,
                "Poll - user started a poll, unable to render or vote on IRC",
            )

        for embed in msg.embeds:
            if embed.type == "rich":
                self.message(
                    self.cfg.channel,
                    "Embedded content - rich embed, unable to render on IRC",
                )
            elif embed.type == "poll_result":
                self.message(
                    self.cfg.channel,
                    "Embedded content - poll result, unable to render on IRC",
                )

        for attachment in msg.attachments:
            self.message(self.cfg.channel, "Attachment - %s" % attachment.url)

        for sticker in msg.stickers:
            self.message(self.cfg.channel, 'Sticker - "%s"' % sticker.name)

    def relay_discord_message_delete(self, deleter, message, bot_user):
        deleter_name = self.sanitize_name(deleter.name)
        author_name = self.extract_sender_from_discord_message(message, bot_user)

        if deleter.id == message.author.id:
            text = "%s deleted their message" % Tags.Bold(deleter_name)
        else:
            text = "%s deleted a message by %s" % (
                Tags.Bold(deleter_name),
                Tags.Bold(author_name),
            )

        self.message(self.cfg.channel, text)

    def relay_discord_reaction_add(self, message, emoji, user, bot_user):
        if emoji.is_custom_emoji():
            emoji_text = "custom emoji %s" % emoji.name
        else:
            emoji_text = emoji.name

        text = "%s reacted with %s to a message by %s" % (
            Tags.Bold(self.sanitize_name(user.name)),
            emoji_text,
            Tags.Bold(self.extract_sender_from_discord_message(message, bot_user)),
        )
        self.message(self.cfg.channel, text)

    def on_channel_message(self, who, channel, msg):
        if who.nick in self.cfg.ignore_users:
            return

        evt = events.IRCMessage(str(who), msg)
        events.dispatcher.dispatch("ircclient", evt)

    def on_action(self, who, target, msg):
        if who.nick in self.cfg.ignore_users:
            return

        evt = events.IRCMessage(str(who), msg, action=True)
        events.dispatcher.dispatch("ircclient", evt)


class EventTarget(events.EventTarget):
    def __init__(self, bot):
        self.bot = bot
        self.queue = queue.Queue()

    def push_event(self, evt):
        self.queue.put(evt)

    def accept_event(self, evt):
        accepted_types = [
            events.DiscordMessage.TYPE,
            events.DiscordMessageEdit.TYPE,
            events.DiscordMessageDelete.TYPE,
            events.DiscordReactionAdd.TYPE,
        ]
        return evt.type in accepted_types

    def run(self):
        while True:
            evt = self.queue.get()
            if evt.type == events.DiscordMessage.TYPE:
                self.bot.relay_discord_message(evt.msg, evt.bot_user)
            elif evt.type == events.DiscordMessageEdit.TYPE:
                self.bot.relay_discord_message(evt.msg, evt.bot_user, edited=True)
            elif evt.type == events.DiscordMessageDelete.TYPE:
                self.bot.relay_discord_message_delete(
                    evt.deleter,
                    evt.message,
                    evt.bot_user,
                )
            elif evt.type == events.DiscordReactionAdd.TYPE:
                self.bot.relay_discord_reaction_add(
                    evt.message, evt.emoji, evt.user, evt.bot_user
                )
            else:
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
    channel = cfg.irc.channel

    logging.info(
        "Starting IRC client: server=%r port=%d ssl=%s nick=%r sasl=%s channel=%r",
        server,
        port,
        ssl,
        nick,
        cfg.irc.sasl_username is not None and cfg.irc.sasl_password is not None,
        channel,
    )

    bot = Bot(cfg.irc)
    utils.DaemonThread(target=bot.start).start()

    evt_target = EventTarget(bot)
    events.dispatcher.register_target(evt_target)
    utils.DaemonThread(target=evt_target.run).start()
