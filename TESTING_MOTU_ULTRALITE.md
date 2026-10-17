# MOTU UltraLite (first generation) bus-routing update

This update replaces MOTU's In/Out gain matrix with a **bus-to-output assignment grid**.
FFADO implements one `/Mixer/MixN/Mix_dest` Discrete control per mix bus (N=1..4).
**A mix bus selects one destination; it is not a full crossbar router.**
Multiple buses may choose the same destination. Changing an assignment can
immediately change what the speakers and headphones receive.

## Supported UltraLite destinations

Disabled, Phones, Analog 1–2, 3–4, 5–6, 7–8, MainOut (FFADO ID 6), and S/PDIF.
The original UltraLite has **no ADAT or AES/EBU ports**; those destinations and
mixer input strips are hidden when `/Mixer/Info/Model` reports `3`.
For other MOTU models, the existing FFADO model-specific routing rules apply.

## How to test (start at low listening volume)

1. Back up existing hardware routing, either by recording current choices in
   `ffado-mixer` or making screenshots before testing.
2. Start `ffado-dbus-server` and `ffado-webmixer` as before.
3. Click the routing button near Settings. Only **Bus → outputs** should be
   visible for the original UltraLite; **Mixer matrix** must not be offered.
4. Confirm the initial selected cell for each bus agrees with `ffado-mixer`'s
   Mix 1–4 destination selectors.
5. Change ONE bus destination to an available output you can monitor safely.
   Confirm the respective Mix_dest selector in `ffado-mixer` reflects it.
6. Confirm that the input faders on the selected mix bus do **not** move.
7. Confirm that no ADAT or AES/EBU entries appear in the UltraLite routing grid
   or its input strips; S/PDIF remains available.
8. Restore the original route after testing.

If a change fails or its readback differs, the dialog reports an error instead
of claiming success. This release has **offline** FFADO method tests but has
not been verified with a connected UltraLite.

## Relevant code

- `ffado_webmixer/profiles/resolver.py`: binds MOTU `Mix_dest` by source-defined
  D-Bus path rather than ambiguous control labels.
- `ffado_webmixer/mixer.py`: reads/writes bus destinations independently of
  input gain matrix cells, with a post-write readback check.
- `ffado_webmixer/profiles/motu/motu_ultralite.xml`: per-model optical/AES
  filtering and MainOut destination mapping.
- `ffado_webmixer/assets/static/routing.js`: the new routing assignment grid.

**FFADO source reference**:
`support/mixer-qt4/ffado/mixer/motu.py` in the uploaded FFADO source,
`initValues_g2()` and Mix_dest selectors; `src/motu/motu_controls.cpp`
`MixDest::setValue()`.
