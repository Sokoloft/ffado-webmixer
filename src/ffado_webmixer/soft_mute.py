"""Crash-safe journal of matrix coefficients suppressed by software mute/solo.

A journal is scoped to a physical FireWire GUID and the exact source-declared
mixer matrix path. Recovery is always opt-in after an interrupted session.
"""
import json
import math
import os
from pathlib import Path


class MuteJournal:
    def __init__(self, config_path, guid, matrix_path, *, enabled=True):
        self.guid = guid
        self.matrix_path = matrix_path
        self.path = None
        if enabled and config_path is not None:
            base = Path(config_path)
            self.path = base.with_name(base.stem + '.mute-recovery.json')

    def load(self):
        if self.path is None or not self.path.exists():
            return {}
        invalid = f'Invalid software mute recovery data in {self.path}'
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (ValueError, RecursionError) as exc:
            raise ValueError(invalid) from exc
        if not isinstance(data, dict):
            raise ValueError(invalid)
        if (type(data.get('schema')) is not int or data['schema'] != 1 or
                data.get('guid') != self.guid or
                data.get('matrix_path') != self.matrix_path):
            raise ValueError(f'Recovery journal identity does not match this device: {self.path}')
        levels = data.get('levels')
        if not isinstance(levels, list):
            raise ValueError(invalid)
        values = {}
        for item in levels:
            if not isinstance(item, dict):
                raise ValueError(invalid)
            mix, column, raw = item.get('mix'), item.get('column'), item.get('raw')
            # Do not coerce coordinates: truncating a float or accepting a
            # boolean could restore a gain to a different channel or bus.
            if (type(mix) is not int or type(column) is not int or
                    mix < 0 or column < 0 or type(raw) not in (int, float)):
                raise ValueError(invalid)
            try:
                raw = float(raw)
            except OverflowError as exc:
                raise ValueError(invalid) from exc
            key = (mix, column)
            if key in values or not math.isfinite(raw) or raw < 0:
                raise ValueError(invalid)
            values[key] = raw
        return values

    def write(self, values):
        if self.path is None:
            return
        if not values:
            self.path.unlink(missing_ok=True)
            return
        data = {'schema': 1, 'guid': self.guid, 'matrix_path': self.matrix_path,
                'levels': [{'mix': mix, 'column': col, 'raw': float(raw)}
                           for (mix, col), raw in sorted(values.items())]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + '.tmp')
        try:
            with temp.open('w', encoding='utf-8') as stream:
                json.dump(data, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(self.path)
        finally:
            temp.unlink(missing_ok=True)
