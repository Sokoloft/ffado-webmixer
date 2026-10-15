"""Conversion between UI control values and device-native ranges."""

def to_percent(raw, lo, hi):
    """Preserve the original integer 0..100 fader taper mapping."""
    return int(round(max(0.0, min(1.0, (raw - lo) / (hi - lo))) * 100)) if hi > lo else 0


def from_percent(value, lo, hi):
    """Preserve the original rounded hardware values."""
    return round(lo + max(0.0, min(100.0, float(value))) / 100 * (hi - lo))


def pan_to_ui(raw, lo, hi):
    return (raw - lo) / (hi - lo) * 2 - 1 if hi > lo else 0.0


def pan_from_ui(value, lo, hi):
    return round(lo + (max(-1.0, min(1.0, float(value))) + 1) / 2 * (hi - lo))
