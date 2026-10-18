# FFADO WebMixer 1.1.0-dev (experimental)

## Design changes

- Bundles FFADO's `configuration` device registry from the supplied source.
- Matches ConfigROM vendor/model and FFADO unit-version rules to a specific
  device XML. No matrix size/name heuristics can enable a control.
- Enumerates only the D-Bus controls declared by that model's family profile.
- Starts one independently addressable Mixer per supported FireWire GUID.
- Stores per-device fader names/layouts/stereo pair settings and local nicknames
  in `~/.config/ffado-webmixer/devices/<guid>.json`.
- Includes stale-device request rejection to avoid routing a queued fader write
  to a different unit after browser device switching.

## Mixer controls

- Adjacent odd-left/even-right stereo input link buttons replace drag-to-link.
- Optional adjacent stereo output-bus linking and gain-derived balance on
  supported DICE/RME gain matrices.
- DICE/RME mixer gain displays a decibel scale around FFADO unity=16384.
- Layered software matrix mute/solo restores earlier levels without overwriting
  user mute states, when there is no native mute matrix.
- DICE EAP peak readings are obtained from the router's destination meters;
  only strips with actually matching destination IDs show a meter.
- Gain matrix editor includes a rotary/numeric dB control and quick presets.
- DICE route disconnection accepts FFADO's native `Mute:00` readback.
- Existing MOTU bus destination grid, original UltraLite ADAT/AES filters,
  and Saffire monitoring-volume controls are preserved.

## Offline development

- `--debug profire2626`, `--debug saffirepro26`, or `--debug motuultralite`
  replaces all FFADO D-Bus access with in-memory fixtures and console traces.
- `--debug list` prints the included source-derived fixture names.
- QjackCtl D-Bus integration is disabled in debug mode.

## Packaging

- Adds `packaging/ffado-webmixer.desktop` and a Qt6 window-identity hint to
  help KDE Plasma distinguish this app from the original FFADO mixer.

## Limitations and validation

- An identity entry in FFADO's registry is **not** a guarantee of an implemented
  gain profile. Unsupported matrices are not writable.
- Synthetic debug matrix sizes do not claim to reflect every hardware variant.
- Software mute/solo affects the gain matrix, not direct crossbar bypass routes.
- Peak meters are per router destination and may not correspond to input ADCs.
- KDE taskbar identity and physical hardware interaction require live tests.
- Automated tests do not establish successful writes to an actual interface.

See `TESTING_V1_1.md` for a safe testing checklist and diagnostic instructions.


## Source-derived per-model capabilities (phase 1)

- Added capability schema v2: each unique FFADO configuration identity has an
  explicit model XML with mapped, optional, source-only or unmapped features.
- Added driver-only identity profiles; no fake mixer layout is created for
  FFADO devices without verified mixer-control implementations.
- Enforced exact model feature mapping in the resolver, control selection,
  live D-Bus inventory and debug-profile catalogue.
- Pre-mk3 MOTU detection reads Info/Model **before** probing gain or output
  controls. Unknown internal model IDs never use a generic MOTU mix profile.
- Source-backed count-specific Saffire monitoring profiles (4/6/10 outputs).
- Recorded FireWorks/BeBoB source-only controls for future backend work.
- Exposed capability metadata under /api/describe.hardware_capabilities.
- Debug fixtures now use synthetic identities based on their selected model
  rather than a shared unrelated placeholder GUID.
- Added profile provenance checks and regression tests, and
  TESTING_CAPABILITIES.md / profiles/CAPABILITIES.md.

Profiles classified identity-only or source-only are **not** suddenly supported
mixers; the feature map intentionally refuses unimplemented D-Bus writes.

## MOTU startup regression fix

- Corrected MOTU metadata profile paths from `Info/Model` and
  `Info/SampleRate` to their actual FFADO locations,
  `/Mixer/Info/Model` and `/Mixer/Info/SampleRate`.
- Preserve the *verified* internal model ID obtained from D-Bus during
  discovery for the subsequent Mixer initialization. If metadata
  introspection is temporarily unavailable, the verified ID is retained.
- This does not loosen the model allowlist: unknown/unreadable internal
  models still cannot inherit MOTU mixer controls.
- Added an offline discovery-to-Mixer UltraLite startup regression suite.

### Peak metering (DICE EAP)

- Source-derived DICE EAP 12-bit peak format and explicit model-declared input
  mapping; meter availability verified via FFADO's `hasPeakMetering()`.
- Correct FFADO 4096 full-scale reference and square-root visual amplitude.
  Normalized readings deliberately are **not** claimed as calibrated dBFS.
- Display actual FFADO router-destination peaks in the In/Out crossbar, and
  only attach strip meters for destinations named by the actual matrix rows.
- Added 1.6-second peak hold, 4-second near-full-scale warning hold, click to
  clear, stereo-pair peak aggregation, no overlapping polling requests, and
  safe behavior on unsupported devices or device changes.
- New diagnostic guide: `TESTING_PEAK_METERS.md`.

## Native gain precision and matrix editor (this update)

- Added `ffado_webmixer/gain.py`: FFADO 2^14-unity native-to-dB conversions, silent sentinel, model-gated DICE/RME limits and explicit value validation.
- Preserved fractional resolution for DICE/RME main faders, rather than rounding to whole 0–100 percent steps.
- The matrix snapshot now includes `db_values` (null for silence), a model-specific gain scale, and the existing percentage `values` for legacy clients.
- `/api/matrix` accepts `db` (including null for silence) in addition to the existing `value`. Writes return native readback level and native coefficient; software-muted writes are identified as deferred.
- Completed matrix editing: 0.1 dB number entry/keyboard/knob, FFADO-style presets from +6 to −55 and −∞, unity and silence actions, and double-click-to-preview unity followed by Apply.
- The UI displays **hardware readback**, not the assumed requested gain. Hardware's finite integer coefficients determine actual attainable precision.
- Original MOTU UltraLite output routing remains unchanged; unsupported dB controls are not exposed.
- Added `TESTING_GAIN_PRECISION.md` and converter/matrix regression tests.

## Software mute/solo reliability (phase 4)

- Added a durable, per-GUID recovery journal for software-suppressed matrix
  coefficients. Saves source-defined matrix coordinates and original levels
  before muting and clears entries only after verified restoration.
- Restores software-mute and solo gain levels on a normal clean exit on a
  best-effort basis. Interrupted sessions require an explicit, volume-warning
  confirmation in the UI, not unsafe automatic startup gain changes.
- Added `GET/POST /api/mute-recovery` for inspection, restore and discard.
  Restoration refuses to overwrite any nonzero hardware level changed outside
  the application; failures leave the remaining journal intact.
- Handles unexpected external matrix changes, failed/missing D-Bus readback,
  and partial solo writes with best-effort rollback and retained recovery data.
- Fader, matrix dB, stereo-bus gain and balance edits share the same suppressed
  coefficient journal, preserving gain changes made during mute.
- Hardened the existing emulated Main/Phones/output mutes: no more removing a
  saved output level before verifying the hardware restoration.
- Debug profiles continue to use in-memory simulated D-Bus and do not create
  persistent recovery journals.
- Added `TESTING_SOFTWARE_MUTE_SOLO.md` and hardware-free failure-injection
  tests. Direct crossbar bypass signals are unaffected by software mute/solo.

## Three-device and KDE integration validation (phase 5)

- Reject duplicate or malformed FFADO GUIDs instead of silently allowing one
  detected unit to replace another in the device map. This catches incorrect
  device discovery before any writes occur.
- Distinguish otherwise identical model/nickname tab labels with a stable GUID
  suffix; optional device aliases continue to use separate GUID-keyed files.
- Correct shared nested default settings between devices; serialize saves per
  configuration so concurrent web requests cannot collide over one `.tmp` file.
- Scope server-sent events to the selected device's stream and add selected-GUID
  checks to browser mixer/metadata/layout, routing and peak-meter reads. A stale
  tab cannot silently show values from another unit after a browser-session
  switch; existing writes continue to reject mismatched GUIDs (HTTP 409).
- When one known device fails to initialize, report its GUID and error but
  keep other supported devices available instead of aborting the whole mixer.
- Keep debug/demo synthetic identities conformant to the required 16-hex GUID
  format, without touching the FFADO D-Bus service.
- KDE/Wayland desktop integration: set Qt's desktop identity before showing
  the window where supported; include an optional unprivileged desktop-entry
  installer for source checkouts, with check and removal commands. Launcher,
  SVG icon, and Qt application ID all use `ffado-webmixer`.
- New three-unit tests cover route isolation, browser-session switching,
  rejected stale writes/reads, GUID collision rejection, config persistence
  across discovery-order changes, scoped events, and optional launcher setup.
- Added `TESTING_MULTIPLE_DEVICES_KDE.md` for the tester with three ProFire
  units and a repeatable KDE Plasma checklist.

**Limits:** All validation in this phase is hardware-free. Live multi-interface
JACK/FFADO operation, actual QPA application-ID behavior under KDE Plasma, and
power-off/hotplug behavior must still be tested on the tester's machine.
The app currently enumerates devices on startup, not live after unplugging.
