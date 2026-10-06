import logging


def get_pylogger(name: str = __name__) -> logging.Logger:
    """Plain logger (trimmed by Folivox: lightning's rank_zero_only wrapper removed)."""
    return logging.getLogger(name)
