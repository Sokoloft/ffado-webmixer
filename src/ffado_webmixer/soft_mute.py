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
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (data.get('schema') != 1 or data.get('guid') != self.guid or
                data.get('matrix_path') != self.matrix_path):
            raise ValueError(f'Recovery journal identity does not match this device: {self.path}')
        values = {}
        for item in data['levels']:
            key = (int(item['mix']), int(item['column']))
            raw = float(item['raw'])
            if (key in values or key[0] < 0 or key[1] < 0 or
                    not math.isfinite(raw) or raw < 0):
                raise ValueError(f'Invalid software mute recovery data in {self.path}')
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
