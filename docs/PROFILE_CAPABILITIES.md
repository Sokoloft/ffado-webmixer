# Source-derived FFADO capability contract (v2)

This catalogue is derived from the supplied `ffado-master` source archive,
principally `configuration`, `src/motu/`, `src/dice/`, `src/rme/`,
`src/fireworks/`, and `support/mixer-qt4/ffado/mixer/`.

**Identification is not mixer support.** The catalogue contains one model
profile for each unique identity in FFADO's `configuration` file (including
models whose FFADO definition has no Qt mixer module), plus five explicit MOTU
pre-mk3 internal model overlays. These declarations intentionally distinguish
what FFADO implements from what ffado-webmixer knows how to control.

## Capability schema

Each `<device>` has an exact `<match vendor_id="..." configuration_model_id="..."/>`
(or a MOTU `<device model_id="...">` internal overlay) and a complete
`<capabilities schema="2">` feature catalogue.

Every feature has one of four states:

| State | Meaning in ffado-webmixer |
| --- | --- |
| `mapped` | Source defines a path and application has a verified interpretation. The path and D-Bus interface must **also** exist at runtime before use. |
| `optional` | Source defines a probeable feature, such as router peak metering. The app may query its availability; no capability is assumed. |
| `source_only` | FFADO implements or refers to this control, but the app has **not** implemented the correct value handling / UI. Never writes it. |
| `unmapped` | No safe application mapping has been established. **Not** a claim the device lacks that hardware feature. |

Profile-level status:

- `mapped`: at least a usable mixer matrix is implemented in ffado-webmixer.
- `identity_only`: exact identity known, but **no writable mixer layout** is enabled.
- `requires_internal_model`: ConfigROM distinguishes only a generation. Read the
  specific FFADO Info/Model property **before** choosing an internal overlay.

A source-mapped *name* is not equivalent to an established value range or
interface: for example AudioFire's `/Mixer/MonitorGain` is `source_only` until
its scaling/axes are translated and tested.

## Runtime sequence

1. Query connected devices' **ConfigROM identity** from FFADO D-Bus.
2. Match its normalized vendor/model identity against FFADO's `configuration`.
3. Load **one exact model XML**, never match a model based on D-Bus matrix size,
   control name, or "looks like DICE" heuristics.
4. For pre-mk3 MOTU only, read `/Mixer/Info/Model` first and select a supported
   model's *internal* overlay. Unknown internal values are not writable.
5. Enumerate only explicitly mapped paths; read FFADO's actual matrix dimensions
   and labels, which may depend on firmware, routing and sample rate.
6. Match every writable role to its **declared D-Bus path**, and validate
   its D-Bus interface. A missing control remains unavailable. Never synthesize
   fader values or substitute a different matrix.

Device capability declarations are returned by the existing `/api/describe`
endpoint under `hardware_capabilities` for diagnosis. The UI remains unchanged
in this update.

## Model-specific examples

- **ProFire 2626 / 610**: DICE `/EAP/MatrixMixer` and `/EAP/Router` have
  source-defined meanings. Peak metering is optional and must be checked via
  FFADO's `hasPeakMetering`. The ProFire 2626 volume-knob settings are
  `source_only` (not falsely rendered as gain controls).
- **Saffire Pro 14 / 24 / 26 / 40**: DICE EAP as above. The model's declared
  monitor output count is **4 / 6 / 6 / 10** respectively. Only the documented
  line-volume and line-mute controls are enabled; GlobalDim and GlobalMute
  remain `source_only` until properly implemented.
- **MOTU pre-mk3**: ConfigROM is *not* a unique model. The app first reads
  `/Mixer/Info/Model`, then selects a supported overlay such as UltraLite,
  Traveler, 8pre, 828mkII, or 896HD. On the original UltraLite, ADAT and
  AES/EBU channels/destinations are explicitly absent and filtered. Output
  assignments use `/Mixer/Mix{n}/Mix_dest`, **not** a matrix gain control.
- **MOTU mk3**: The FFADO Qt `motu_mark3.py` does not provide a verified
  `/Mixer/fader` implementation; the device is identity-only for now.
- **RME Fireface 400 / 800**: FFADO Qt mixer uses `InputFaders` with input
  columns and output rows. `PlaybackFaders` / `OutputFaders` and input invert
  controls are recorded as `source_only` until the additional UI is mapped.
  Other RME configuration model IDs are identity-only pending verification.
- **Echo AudioFire**: FFADO exposes `MonitorGain`, `MonitorMute`,
  `MonitorSolo`, and `MonitorPan`, but webmixer has not yet translated their
  axes and gain range. They are explicitly `source_only`.
- **BeBoB and other scalar mixers**: Where FFADO's Qt source defines
  `Feature_Volume` or `Selector` controls, the profiles record those as
  `source_only`. No generic MatrixMixer is fabricated for these devices.
- **Driver-only FFADO entries**: Every remaining FFADO configuration identity
  gets an explicit `driver_only` XML whose features are `unmapped`. These
  devices may stream audio through FFADO without having a matching mixer UI.

## Editing a profile

1. Find the **exact model** in the FFADO `configuration` file.
2. Find the relevant C++ implementation and Qt mixer code for that model.
3. Add/change a feature's `state` and `source` reference. Mark `mapped` only
   after adding the corresponding, typed Python API interpretation.
4. For a mapped matrix, ensure its declared path, orientation and coefficient
   mode match the exact profile's `common.xml` matrix hint.
5. Run the offline test suite. With the original FFADO source available:

   ```bash
   FFADO_SOURCE_DIR=/path/to/ffado-master python -m unittest discover -s tests -v
   ```

   Tests verify every model declares all feature keys, source file references
   resolve, model IDs match the FFADO source configuration, and unsupported
   matrices aren't guessed. They do **not** validate physical audio behavior.

Do not promote `source_only` or `unmapped` features to `mapped` merely because
an endpoint with the same name exists on an unrelated model.

## DICE EAP source-mapped peak meters

Models declaring `peak_metering` as `optional` specify:

```xml
format="dice_eap_peak12" channel_map="matrix_input_router_destination"
```

The router must exist at `/EAP/Router` and return true to `hasPeakMetering()`.
FFADO's matrix row label **must itself name** the router destination
(e.g. `Mixer/In:01`) for a channel strip to show a meter. Source-mapped DICE
line outputs use their corresponding `Line/Out:NN` hardware peaks from the
same `getPeakValues()` frame, with separate Left/Right lanes when linked.
Output metering adds no routing or matrix-gain reads and does not estimate
levels from input peaks. Missing hardware output peaks leave that meter
unavailable. Other destinations remain visible in In/Out → Crossbar router.

This feature does not reinterpret FireWire device model IDs, guess meter
counts, or synthesize meter readings for unmatched control paths. The peak
scale is normalized relative to FFADO's visual meter (`sqrt(value/4096)`);
calibrated dBFS cannot be asserted from the provided source alone.
MOTU meter configuration registers are not live peak-reading endpoints.
