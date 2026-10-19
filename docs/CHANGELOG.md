# Changelog

## 1.1.1 — development branch (2026-10-19)

- Updated the application's displayed version to **1.1.1** (still under active development; not a stable release announcement).
- Moved root-level testing guides into [`docs/`](./README.md) and consolidated the previous `CHANGELOG_1_1_0_DEV.md` history into this version-independent changelog.
- Kept the repository root `README.md` for GitHub discoverability and updated documentation references to their new paths.
- Application behavior, FFADO hardware controls, and user configuration formats are unchanged.

---

## 1.1.0-dev — previous development work (history)

## Channel-strip peak-meter refinement (Priority 6, October 2026)

- Channel strips now render **individual real FFADO router-destination levels** beside the fader. Mono has one lane; a linked stereo strip has **independent Left and Right lanes** in click order (including arbitrary 2+5 or 8+3 pairs). This replaces the misleading maximum-of-two meter in linked strips.
- Each lane has independent 1.6-second peak hold and 4-second near-full-scale warning, including optional click-to-clear; one loud channel never makes its partner appear loud. Missing metered channels stay hidden instead of receiving copied or synthetic values.
- Refined accessible labels and tooltips identifying actual router destination names and readings, with no claim of calibrated dBFS or post-fader measurement. Enlarged the visual meter for legibility without changing fader range or matrix coefficients.
- Preserved the existing exact FFADO DICE EAP matrix-row-to-router-destination mapping, 12-bit normalization, GUID scoping, and unsupported-device behavior. No D-Bus writes or unverified pre/post metering have been added.
- Stopped stale asynchronous poll replies from showing peaks after a device change/restart. Expanded dependency-free Node.js UI regression tests and updated `TESTING_PEAK_METERS.md`. Actual ProFire verification remains necessary.

## Matrix-cell rotary controls (2026-10-19)

- Added a compact knob and always-visible hardware level to every writable mixer-matrix crosspoint, following the ProFire mixer UI feedback. Works with native DICE/RME dB matrices and percentage-backed matrices.
- Pointer/touch drag previews locally and commits only on release; wheel and keyboard edits coalesce into one write after 320 ms of idle time. Fine dB step is 0.1 dB, Shift makes it 1 dB. Home/M mutes; End reaches maximum; 0 selects unity. Double-click keeps the original stage-unity-then-Apply behavior.
- Hardware writes still target **one explicit input/output coefficient** and use the existing `/api/matrix` verified readback, including deferred software-mute handling. No new routing links or pan-law calculations are introduced.
- Knobs disable during pending writes; failed writes restore the prior value and trigger a fresh hardware read. A stale matrix GET no longer replaces the cell being edited or a write's readback. The selected cell and keyboard focus are preserved across matrix refreshes.
- The numeric dB entry, slider, precise editor knob, and gain presets remain available when a crosspoint is selected. Added a dependency-free Node.js UI regression and a tester guide; Node is only required to run that optional test, not the app.

## Hardened stereo pair validation (Priority 4, October 2026)

- Validate input channel IDs, operation payloads, and bus number before
  modifying pair metadata. Malformed bus URLs can no longer silently fall
  back to Bus 1; channels already paired on the same bus receive an explicit
  conflict message identifying their existing partner.
- Serialize server-side pair validation and commits across browser clients.
  Concurrent requests cannot assign the same channel to two different pairs.
- Roll back in-memory pair/layout metadata when config persistence fails.
  Invalid or rejected requests do not broadcast changes or write any FFADO
  mixer matrix coefficients.
- Ignore malformed, self-linked, or overlapping legacy/saved pair entries,
  preserving the first valid Left→Right pair and bus-level overrides.
- Disable the fader chain-link controls during a pending link/unlink request;
  check unlink HTTP status, refresh after failures, and protect against clicks
  on a bus that is still loading or stale after switching.
- Preserve unrestricted input pairing (2→5, 8→3), independent per-bus pairs,
  initial pan readback, chain-link SVG buttons, and routing-safe behavior.
- Added `TESTING_STEREO_PAIR_VALIDATION.md`, Python concurrency/validation/
  persistence regression tests, and browser-free UI error/race tests.
  Live FireWire hardware confirmation remains pending.

## Initial stereo pan display (Priority 3, October 2026)

- A linked input pair now displays its Left/Right balance directly from the
  current DICE/RME matrix **immediately** after linking, switching buses, or
  returning from the matrix editor; moving the pan slider is no longer needed.
- Corrected an inverse-formula mismatch: paired inputs are written with a
  peak-normalized diagonal attenuation, but were initially read with the
  sum-normalized mono-bus balance formula. The readback now matches the
  existing write rule at -100, -50, center, +50 and +100.
- The first clicked input determines Left and the second Right, including
  nonadjacent (2+5) and reverse-numbered (8+3) pairs. Pairings remain
  independent for each output bus.
- When **both** diagonal routes are disconnected, PAN shows an em dash and
  is disabled rather than incorrectly reporting a centered balance. When
  only one diagonal route is active, its hard-L/R setting is shown with a
  warning that moving balance cannot reconnect the other input.
- A `*` and tooltip identify **partial balance** when the matrix has
  custom cross-routes. A single pan number cannot capture the full 2x2
  stereo routing, so none of those crosspoints are rewritten or hidden.
- Added ProFire debug hardware-state and JavaScript value-display regression
  tests. No change to pan-law writes or routing; physical ProFire validation
  is still required.

## Bus-specific input pairs and chain-link controls (October 2026)

- Fixed a cross-bus visibility bug: linking or unlinking input channels on Bus 2
  no longer changes Bus 1's stereo pair state or saved strip layout.
- Changed stereo metadata persistence from one global list to independent
  `stereo_by_mix` entries. Existing global `stereo` settings remain the initial
  fallback until each bus is customized, preserving previous saved pairs.
- Hidden Right-channel entries keep their original position, pin and minimized
  state rather than being deleted from the layout when paired. Unlink repairs
  missing legacy entries **on the selected bus only**.
- Stereo link events carry their bus index; other bus views do not refresh.
  Unfinished first-click selections are cleared when changing buses.
- Replaced Unicode chains buttons with a theme-colored SVG chain-link icon on
  both paired and unpaired faders.
- Scoped temporary DICE/RME input balance references to the active bus.
- Added ProFire debug tests for the exact Bus 1/Bus 2 reproduction, different
  pairings per bus, migration across restarts, hardware routing preservation,
  per-bus control mirroring and UI event handling. Live FFADO validation pending.

## Arbitrary ordered stereo pairing and routing-safe balance (Priority 2)

- Every unpaired input strip has a lower-right link button. First click
  assigns Left, second assigns Right, even for nonadjacent or reverse-numbered
  channels (for example 2→5 or 7→3). Selecting the same button cancels.
- Pairing/unpairing saves UI metadata **without writing** input gain, pan,
  or matrix routing. The selected Left channel retains its position.
- Linked-input pan on a stereo DICE/RME output pair changes only existing
  diagonal L→L / R→R gains; user-defined crosspoints are never synthesized.
  The balance readback follows the selected input order.
- Temporary balance references restore previously active diagonal channels
  when returning from a full-left or full-right gesture; external hardware
  changes and direct matrix edits invalidate stale references.
- A completely disconnected input cannot be sent to both output legs by
  merely moving its linked-bus fader.
- Added offline ProFire matrix regression tests and pairing interaction tests.
  Live validation on the tester's hardware is still required.

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

## ProFire matrix → strip synchronization (October 2026)

- The linked DICE/RME output-bus fader and balance now come from the same
  serialized native matrix readback. No stale separately-read pan or level.
- Stereo-linked input strips show the louder leg and mark unequal paired
  inputs as `MAX`, with per-input values in a tooltip.
- The combined balance of linked inputs on linked output buses uses their
  actual native matrix coefficients, rather than averaging their pan controls.
- Matrix edits still trigger a direct strip refresh and SSE refresh on other
  app pages; the new state readback reflects external matrix values on reload.
- Hardware routing and write-side pan laws are unchanged in this step.
  See `TESTING_MATRIX_STRIP_SYNC.md` for screenshots-based validation.

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

## User-facing volume terminology (priority 7)

- Rename mixer matrix crosspoint ARIA labels, precise dB editor, rotary knob, slider, and preset accessibility text from **Gain** to **Volume**. Channel-strip and master fader tooltips now identify digital mixer/output volume.
- Distinguish the separate, capability-mapped **Input Gain**/trim control from digital mixer volume. It remains a gain control because it does not represent a mixer crosspoint.
- Update routing guidance, software-mute recovery wording, and the README to use user-facing volume terminology consistently. No change to D-Bus/API identifiers, coefficient conversion, volume/pan algorithms, saved configuration, or hardware writes.
- Add UI-terminology regression tests (including the hardware gain exception and percent-mode rotary matrices).
