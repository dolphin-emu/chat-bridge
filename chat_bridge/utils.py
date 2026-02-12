"""Utility functions and classes."""

import logging
import threading
import time


class DaemonThread(threading.Thread):
    daemon = True

    def __init__(self, *args, **kwargs):
        super(DaemonThread, self).__init__(*args, **kwargs)
        self.daemon_target = kwargs.get("target")
        self.args = kwargs.get("args", ())
        self.kwargs = kwargs.get("kwargs", {})
        if self.daemon_target is None:
            self.daemon_target = self.run_daemonized

    def run(self):
        while True:
            try:
                self.daemon_target(*self.args, **self.kwargs)
            except Exception:
                logging.exception("Daemon thread %r failed", self)
                time.sleep(1)


class ObjectLike:
    """Transforms a dict-like structure into an object-like structure."""

    def __init__(self, dictlike):
        self.reset(dictlike)

    def reset(self, dictlike):
        self.dictlike = dictlike

    def items(self):
        for k, v in self.dictlike.items():
            if isinstance(v, dict):
                yield (k, ObjectLike(v))
            else:
                yield (k, v)

    def __getattr__(self, name):
        val = self.dictlike.get(name)
        if isinstance(val, dict):
            return ObjectLike(val)
        else:
            return val

    def __contains__(self, name):
        return name in self.dictlike

    def __str__(self):
        return str(self.dictlike)

    def __repr__(self):
        return repr(self.dictlike)
