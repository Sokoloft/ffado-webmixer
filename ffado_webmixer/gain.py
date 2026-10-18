"""FFADO matrix gain conversions, preserving native fixed-point precision.

Source: libffado/support/mixer-qt4/ffado/widgets/matrixmixer.py.
FFADO uses 16384 (2^14) for unity. Values <=16 are displayed as
silence (the Qt UI uses -60 dB for its lower sentinel). The Qt gain
editor limits adjustments to -60..+6 dB, even when the native coefficient
field can represent a larger value.
"""
import math

UNITY = 16384
FLOOR_DB = -60.0
MAX_DB = 6.0
NATIVE_LIMITS = {"dice_db": 65535, "rme_db": 32768}


def has_db_scale(mode):
    return mode in NATIVE_LIMITS


def scale(mode):
    if not has_db_scale(mode):
        return None
    return {"mode": mode, "min_db": FLOOR_DB, "max_db": MAX_DB,
            "step_db": 0.1, "unity": UNITY,
            "native_max": NATIVE_LIMITS[mode]}


def raw_to_db(raw, mode):
    if not has_db_scale(mode):
        raise ValueError("The device profile does not declare a dB gain scale")
    raw = float(raw)
    if not math.isfinite(raw) or raw < 0 or raw > NATIVE_LIMITS[mode]:
        raise ValueError("Invalid native mixer gain from FFADO")
    # FFADO treats raw <= 16 as its silent/minimum value.
    return None if raw <= 16 else 20.0 * math.log10(raw / UNITY)


def db_to_raw(db, mode):
    if not has_db_scale(mode):
        raise ValueError("The device profile does not declare a dB gain scale")
    if db is None:
        return 0
    db = float(db)
    if not math.isfinite(db) or db < FLOOR_DB or db > MAX_DB:
        raise ValueError(f"Mixer gain must be between {FLOOR_DB:g} and +{MAX_DB:g} dB, or null for silence")
    # An explicit -60 dB entry means FFADO's -inf sentinel.
    if db <= FLOOR_DB:
        return 0
    return min(NATIVE_LIMITS[mode], round(UNITY * 10.0 ** (db / 20.0)))


def raw_to_ui(raw, mode):
    db = raw_to_db(raw, mode)
    if db is None:
        return 0.0
    # The regular strip maintains its existing 0..100 UI protocol;
    # avoid rounding it to integer steps, which caused ~0.66 dB errors.
    return round(max(0.0, min(100.0, (db - FLOOR_DB) * 100.0 / (MAX_DB - FLOOR_DB))), 5)


def ui_to_raw(ui, mode):
    ui = float(ui)
    if not math.isfinite(ui) or not 0 <= ui <= 100:
        raise ValueError("Mixer fader must be between 0 and 100")
    return db_to_raw(None if ui == 0 else FLOOR_DB + ui * (MAX_DB - FLOOR_DB) / 100.0, mode)


def db_label(db):
    return "−∞ dB" if db is None else f"{db:+.1f} dB" if db > 0 else f"{db:.1f} dB"
