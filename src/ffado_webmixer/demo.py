"""Demo mode (--demo): a simulated mixer with six channels and four buses. Needs no hardware."""

NAMES = ["Kick", "Snare", "Vox", "Bass", "Guitar", "Keys"]
DESTINATIONS = ["Disabled", "Phones", "Analog 1-2", "Analog 3-4", "Analog 5-6", "Analog 7-8", "MainOut", "SPDIF"]


class DemoMixer:
    def __init__(self):
        # fader/pan/mute/solo are per mix; gain and polarity belong to the channel
        self.mixes = [
            {f"ch/{i + 1:02d}": {"fader": 75 - 5 * i + 2 * m, "pan": 0.0, "mute": i == 2, "solo": False}
             for i in range(len(NAMES))} for m in range(4)
        ]
        self.chan = {f"ch/{i + 1:02d}": {"gain": 10 * i % 54, "invert": False} for i in range(len(NAMES))}
        self.dest = {f"bus/{i}": v for i, v in enumerate((6, 0, 2, 0))}
        self.out = {"main": {"name": "Main", "level": 80, "mute": False},
                    "phones": {"name": "Phones", "level": 60, "mute": False},
                    **{f"bus/{m}": {"name": f"Bus {m + 1}", "level": 70, "mute": False} for m in range(4)}}

    def describe(self):
        return {"device": "Demo mixer",
                "mixes": [{"id": m, "name": f"Bus {m + 1}"} for m in range(4)],
                "outputs": [{"id": k, "name": v["name"], "mix": int(k[4:]) if k.startswith("bus/") else None,
                             "controllable": True, "destination": k.startswith("bus/")} for k, v in self.out.items()],
                "fader": {"writable": True},
                "features": {"pan": {"writable": True}, "solo": {"writable": True},
                             "gain": {"writable": True, "min": 0, "max": 53},
                             "invert": {"writable": True}}}

    def read_mix(self, mix, *, channels=None):
        selected = set(channels) if channels is not None else None
        return {sid: {"name": NAMES[i], "input": f"Input {i + 1}", **self.mixes[mix][sid], **self.chan[sid]}
                for i, sid in enumerate(self.chan) if selected is None or sid in selected}

    def write(self, mix, strip, control, value):
        if strip not in self.chan:
            raise ValueError(f"unknown channel {strip}")
        if control in ("gain", "invert"):
            self.chan[strip][control] = value
        elif control in ("fader", "pan", "mute", "solo"):
            self.mixes[mix][strip][control] = value
        else:
            raise ValueError(f"unknown control {control}")

    def read_output(self, out_id):
        return dict(self.out[out_id])

    def write_output(self, out_id, control, value):
        key = {"fader": "level", "mute": "mute"}[control]
        self.out[out_id][key] = value

    def read_destination(self, out_id):
        if out_id not in self.dest:
            raise ValueError(f"'{out_id}' has no destination setting")
        stands_for = {"Phones": "phones", "MainOut": "main"}
        return {"value": self.dest[out_id],
                "options": [dict({"value": i, "name": n}, **({"output": stands_for[n]} if n in stands_for else {}))
                            for i, n in enumerate(DESTINATIONS)]}

    def write_destination(self, out_id, value):
        if out_id not in self.dest or not 0 <= int(value) < len(DESTINATIONS):
            raise ValueError("unknown bus or destination")
        self.dest[out_id] = int(value)
