from django.utils.module_loading import import_string

from ..conf import identity_conf

_engine = None


def get_engine():
    """The configured engine, created once per process (models are loaded lazily on first use)."""
    global _engine
    if _engine is None:
        _engine = import_string(identity_conf.ENGINE)()
    return _engine


def reset_engine():
    global _engine
    _engine = None
