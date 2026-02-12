"""Events module, including all the supported event constructors and the global
event dispatcher."""

from . import utils

import functools
import logging


class EventTarget:
    def push_event(self, evt):
        logging.error("push_event not redefined in EventTarget subclass")

    def accept_event(self, evt):
        return False


class Dispatcher:
    def __init__(self, targets=None):
        self.targets = targets or []

    def register_target(self, target):
        self.targets.append(target)

    def dispatch(self, source, evt):
        transmitted = {"source": source}
        transmitted.update(evt)
        transmitted = utils.ObjectLike(transmitted)
        for tgt in self.targets:
            try:
                if tgt.accept_event(transmitted):
                    tgt.push_event(transmitted)
            except Exception:
                logging.exception("Failed to pass event to %r" % tgt)
                continue


dispatcher = Dispatcher()

# Event constructors. Events are dictionaries, with the following keys being
# mandatory:
#   - type: The event type (string).
#   - source: The event source (string).


def event(type):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            evt = f(*args, **kwargs)
            evt["type"] = type
            return evt

        wrapper.TYPE = type
        return wrapper

    return decorator


@event("internal_log")
def InternalLog(level: str, pathname: str, lineno: int, msg: str, args: str):
    return {
        "level": level,
        "pathname": pathname,
        "lineno": lineno,
        "msg": msg,
        "args": args,
    }


@event("config_reload")
def ConfigReload():
    return {}
