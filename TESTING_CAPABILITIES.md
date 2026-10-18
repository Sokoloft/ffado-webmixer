# Testing source-defined device capabilities (v1.1.0-dev)

## Offline checks (without FFADO or hardware)

From the project root:

```bash
python -m unittest discover -s tests -v
python main.py --debug list
python main.py --debug profire2626 --headless
python main.py --debug Motu-Ultralite --headless
```

`--debug` never opens FFADO D-Bus, and logs the calls it **would** make.
To verify the provenance paths directly against a checkout of FFADO:

```bash
FFADO_SOURCE_DIR=/path/to/ffado-master python -m unittest discover -s tests -v
```

Do not treat offline test success as proof that a physical unit accepts writes.

## On real devices

1. Start FFADO as usual and launch webmixer. Confirm it identifies the exact
   device under `/api/describe` (including `profile` and `hardware_capabilities`).
2. Check that each exposed gain, mute, solo and output destination exists in
   FFADO's own mixer and responds to a **small, low-volume test adjustment**.
3. Verify sample-rate changes, because DICE EAP matrix dimensions and router
   entries can change; the app must not show controls for the wrong device.
4. On an original MOTU UltraLite, confirm there are no AES/EBU or ADAT options,
   and that changing the output-assignment grid does **not** modify input gain.
5. On a Saffire Pro 26, confirm its six line monitor outputs and mute controls;
   no unsupported seventh through tenth line controls should be generated.
6. Attach `/api/describe`, `/api/state`, `/api/router` (if supported), a
   screenshot and the console error to any bug report. Include FFADO version,
   model name, vendor/model IDs and FireWire GUID, but remove private network
   addresses if sharing the report publicly.
7. For an unsupported device, report its precise identity, the FFADO Qt mixer
   controls which work, and a D-Bus introspection snapshot. Do **not** manually
   modify the XML or run unknown write commands just to diagnose a failure.

Source-only and unmapped features are intentionally not enabled. They represent
follow-up device implementations, not an assertion that the interface lacks
those physical functions.
