"""Render stand-ins for the render-process tests: imported by name inside a spawned child."""

import os
import sys


def ok(book, opts, events):
    events.stage("load", "Loading")
    events.plan(10, 0, 1, 1)
    return opts.output


def fail(book, opts, events):
    raise RuntimeError("no voice")


def crash(book, opts, events):
    events.stage("load", "Loading")
    print("Could not load symbol cudnnGetLibConfig. Error code 127", file=sys.stderr, flush=True)
    os._exit(3)


def slow(book, opts, events):
    import time

    from folivox.pipeline import Cancelled

    events.stage("load", "Loading")
    for _ in range(600):
        if events.cancelled():
            raise Cancelled()
        time.sleep(0.1)
