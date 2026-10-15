"""Backward-compatible imports for existing callers; implementations live in profiles/."""
from .profiles.loader import load_profile
from .profiles.resolver import (
    resolve_mixer, resolve_controls, visible_columns, destination_options,
    bus_name, CHANNEL_WORDS, match_outputs, match_channel_controls,
)
