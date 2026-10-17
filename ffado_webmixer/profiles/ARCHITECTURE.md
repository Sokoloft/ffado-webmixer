# Runtime FFADO discovery and XML interpretation

- `interrogate.py` inventories ConfigRom identity, scalar endpoints and live matrix paths/dimensions/names. It does not select or classify a mixer.
- `device_registry.py` maps FFADO ConfigRom identity to its configured mixer family.
- `profile_loader.py` loads the XML family/model profile and resolves the live matrix inventory into mixer roles and channel topology.
- `mixer.py` reads/writes only those live endpoints and applies profile ranges.
- `config.json` stores only application/user settings; hardware topology is not persisted.

Unknown families retain generic role inference; device-specific advanced controls are not invented.

## Native matrix orientation (source-derived)

- DICE EAP (`src/dice/dice_eap.cpp`, `support/mixer-qt4/ffado/mixer/generic_dice_eap.py`): `/EAP/MatrixMixer` rows are mixer **inputs**, columns are mixer **outputs**. `Mixer._coordinates` transposes to the webmixer's output-bus/strip convention. Its gain coefficient is linear (`0` silent, `16384` unity); convert to FFADO's -60..+6 dB UI scale rather than using 0..1 or 0..100 raw values.
- MOTU: `/Mixer/fader` is an ordinary output-row/input-column fader matrix.
- RME: FFADO uses `/Mixer/InputFaders` and `/Mixer/PlaybackFaders` with `Columns_are_inputs`; additional submixes must be implemented from verified source mappings.
- EAP `/EAP/Router` is **not** a gain matrix. It implements `org.ffado.Control.Element.CrossbarRouter` with named sources/destinations. It is rendered in a separate routing tab.
- Saffire PRO 26 `/EAP/Monitoring/LineOut/Volume1..6` are discrete monitor levels in the native range -40..0, and `/EAP/Monitoring/LineOut/Mute1..6` are Boolean (`selected`/`select`, not `getValue`/`setValue`). These are individual line outputs, **not** a global master volume.
- Other unidentified matrices are deliberately not classified as writable faders. Real hardware verification remains necessary.
