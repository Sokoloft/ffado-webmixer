## 1.2.0 — Fader spacing and MOTU volume display (2026-10-22)

- Remove the 20px bottom reserve left by the former unlink button, keeping channel and master labels close to the bottom of their cards on desktop and mobile.
- Shorten the input trim caption to **Gain** on mapped pre-mark3 MOTU devices.
- Display MOTU channel, bus, Main and Phones volume from 0 dB to −84 dB with a separate −∞ position below the quietest finite setting. Preserve all 129 FFADO native positions instead of rounding them to integer percentages.
- Keep native hardware writes and matrix capabilities unchanged. The manufacturer documents the −84..0 dB range, but not a raw-position conversion table; intermediate display values use endpoint interpolation and still require physical calibration.

## 1.2.0 — Access control and reliability (2026-10-22)

- Remove the settings tab scroll container and wrap tabs on narrow windows. Keep hidden settings panels from forcing horizontal overflow.
- Add an optional saved listener port to GUI and CLI Remote Access setup. Blank input uses 5000; validate ports from 1 to 65535 and use the running port for the desktop, readiness checks, and About/QR links. Port changes require restart; existing credential files retain the default.
- Default to a localhost listener until Remote Access is enabled. Configure a username and password in the new settings tab or with `--enable-remote-access` (hidden password prompts); both save a private Argon2id credential file in `~/.config/ffado-webmixer/auth.json`. Saved settings control LAN listening, with an explicit `--host` override. `--disable-remote-access` disables it for the next launch. This replaces `FFADO_WEBMIXER_TOKEN`; remote clients use their configured credentials with HTTP Basic authentication.
- Reject cross-origin browser writes and non-JSON API submissions. Local desktop access remains automatic.
- Pin the selected GUID, backend and settings for each HTTP request so another browser changing the preferred mixer cannot redirect in-flight reads, writes or event broadcasts.
- Apply paired native pan changes in one hardware transaction, restoring both original values after partial failures and reporting any incomplete rollback.
- Limit paired-edit rollback snapshots to the affected input channels, avoiding whole-bus D-Bus reads while retaining the same value conversions and transaction lock.
- Serialize channel/output renames with preference saves, restore prior names after failed persistence, and return JSON validation errors for malformed mixer changes.
- Validate mute-recovery journal structure and numeric values before applying them. Preserve malformed files and show the existing recovery warning with safe discard, rather than preventing startup.
- Route SIGTERM through normal server shutdown and software-mute restoration. Run cleanup once, tolerate repeated termination signals during restoration, and retain recovery records for levels that could not be restored.
- Remove peak-stream subscribers even when their response closes before iteration starts, so metering stops after the last viewer disconnects.
- Retry shared peak streaming after temporary transport failures with exponential delays capped at 30 seconds and HTTP polling between attempts. Cancel retries for hidden/stopped views, reject stale polling results after reconnection, and stop metering when access is denied.
- Revoke existing remote event and meter streams when credentials change or remote access is disabled. Wake idle streams, release their subscriptions, and reject streams authenticated before the change even if they subscribe afterward.
- Read application theme and accent preferences from the global configuration for every device and the default favicon, matching the desktop splash while preserving explicit icon previews.
- Validate saved configuration before applying it; retain malformed files in unique `.bad` backups and preserve legacy migrations.
- Request a complete browser refresh of mixer state after event overflow or reconnection, including bus layouts and routing.
- Extract routing and output controls from the mixer backend, and live synchronization from the main frontend script.
- Use one package version for distribution metadata and the CLI: `1.2.0`.

## 1.1.1-dev — Editable fader values and unity reset (2026-10-22)

- Display tiny positive and negative dB levels rounded to zero as `0.0 dB`, never `+0.0 dB` or `-0.0 dB`.
- Allow Enter-to-commit manual fader levels (e.g. `+3.1 dB`) and Escape-to-cancel for channel and master faders; validate limits before sending existing FFADO 0..100 transport values.
- Double-click a calibrated DICE/RME fader handle or track to reset to 0.0 dB (unity), not silence. Preserve legacy percentage devices without guessing a dB calibration.
- Added `tests/fader_value_edit_ui_test.cjs` and `docs/TESTING.md#mixer-routing-and-stereo-links`. No audio routing or backend gain arithmetic changes.

## 1.1.1-dev — Concurrent theme-icon cache fix (2026-10-22)

- Fixed a pywebview icon-cache race when switching themes or accents quickly. Concurrent worker threads previously reused a temporary SVG filename based on the process ID, resulting in intermittent `FileNotFoundError` during `os.replace()`.
- Each icon write now uses its own securely allocated temporary file and an atomic replacement; stray temporary files are cleaned up if a write fails.
- Added deterministic concurrent-write and failed-write cleanup regressions. No changes to hardware controls, theme palettes or browser favicon responses.

## 1.1.1-dev — Stereo-bus fader from silence (2026-10-22)

- Fixed linked-bus faders silently ignoring changes when both bus coefficients were −∞.
- An explicit mono fader raise now connects that mono input to the selected stereo bus pair at the requested level. A linked input pair activates only its assigned Left/Right diagonal paths; linking alone never alters routing.
- Restores each channel's previous pan ratio after a fader-down-to-−∞ and fader-up gesture in the same running session. Recognizes FFADO's 0–16 native silence sentinel, and invalidates memory on external matrix edits.
- Groups linked input fader changes into a verified, serialized write with best-effort rollback on failure; preserves unrelated matrix routes.
- Added Saffire PRO 40/40.1 and ProFire 2626/610 simulated tests. See [TESTING.md#mixer-routing-and-stereo-links](TESTING.md#mixer-routing-and-stereo-links).

## 1.1.1-dev — Explicit stereo FireWire playback routing (2026-10-22)

- Used the Focusrite Saffire PRO 40 manual's DAW playback → mixer → output routing architecture to distinguish FireWire playback sources from independent mixer bus outputs and physical monitor destinations.
- Added an optional **Stereo FireWire playback** helper to the DICE Mixer Matrix. It discovers the current FFADO `1394/In` source assignments and correct mixer input columns; never assumes FireWire playback 1/2 appear on physical mixer faders 1/2.
- After explicit confirmation, it connects Left input to Left bus and Right input to Right bus at 0 dB and silences only their two crossed connections. All unrelated crosspoints and the Crossbar Router remain unchanged.
- Verified reads/writes, serialized hardware operations, and rollback for failures. Linking faders or buses alone still changes no audio routes. Added backend and browser interaction regressions. See [TESTING.md#mixer-routing-and-stereo-links](TESTING.md#mixer-routing-and-stereo-links).

## 1.1.1-dev — Dynamic theme icons (2026-10-22)

- Derive the browser favicon and Qt pywebview window icon from the color tokens
  already used by the themed loading-screen logo, including custom themes and
  six-digit accent overrides.
- Set the native icon on startup and update it via a queued Qt GUI-thread slot
  when themes or accents change in the pywebview client. Update browser
  favicons immediately; no Qt dependencies for browser-only operation.
- When the matching per-user KDE launcher is installed, synchronize its SVG
  artwork with the current theme (Plasma may cache it until relaunch).
- Added theme-asset, launcher, native bridge and browser interaction tests.

## 1.1.1-dev — Compact Crossbar Router destination names (2026-10-22)

- Replaced raw group headings such as `1394/Out`, `ADAT/Out`, `Line/Out`, `Loop` and `Mixer/In` with **Firewire**, **ADAT**, **Line Out**, **Loop** and **Mixer Inputs**.
- Display destination rows with the same vocabulary: `1394/Out:01` → **Firewire 1**, `Line/Out:01` → **Line Out 1**, `Loop:01` → **Loop 1**. Mixer input rows continue to show both destination identity and live source (for example **In 9 ← Disconnected**).
- Preserved the original FFADO destination IDs for D-Bus routing, meter mapping, readback, and selector option values. Added an end-to-end JavaScript regression test and a hardware checklist: [TESTING.md#mixer-routing-and-stereo-links](TESTING.md#mixer-routing-and-stereo-links).

## 1.1.1-dev — Persisted intro preference and themed splash (2026-10-22)

- Fixed **Skip loading screen** saving only to the selected device JSON, while the
  desktop window checked the global `~/.config/ffado-webmixer/config.json`.
  The preference now persists globally and is consistent when switching devices.
- Import a previously saved per-device startup preference once, without
  replacing an explicit global preference or re-enabling an option after the
  user disables it. The existing device-specific mixer layouts and controls
  remain separate.
- Persist the active theme and accent override for use by the desktop intro.
  Its first-frame background matches the selected theme, and its logo,
  progress bar and activity indicator use theme CSS variables.
- Report failed Skip setting saves and restore the previous checkbox state.
  Added persistence, migration, themed-window, and visual-style checks.
  See [TESTING.md#multiple-devices-and-desktop-integration](TESTING.md#multiple-devices-and-desktop-integration).

## 1.1.1-dev — Consistent routing source labels in matrix and Crossbar Router (2026-10-22)

- Matrix snapshot returns a separate `input_labels` array using the current DICE
  Crossbar Router source for each mixer input, including **Disconnected** when
  FFADO reports its `Mute:00` routing sentinel. Original matrix `inputs` and
  numeric coefficient coordinates are unchanged.
- Matrix reads refresh actual router source selections, so a matrix Refresh
  picks up external `ffado-mixer` changes even without opening Crossbar Router.
  A temporary router read failure does not block matrix volume reads.
- Crossbar Router rows display both the stable destination and selected source
  (e.g. `In 9 ← Disconnected`); dropdown labels use compact Analog/Firewire/etc.
  names but retain raw FFADO option values.
- A routing event now also refreshes an open matrix tab. Added Python and
  JavaScript regression coverage. See [TESTING.md#mixer-routing-and-stereo-links](TESTING.md#mixer-routing-and-stereo-links).

## 1.1.1-dev — Crossbar Router / fader source-label synchronization (2026-10-22)

- Fixed DICE channel-strip hardware source labels remaining stuck at matrix
  discovery values after selecting a new source for `Mixer/In` in In/Out →
  Crossbar Router. The server now associates matrix input columns with the
  exact router destinations and updates their display source from verified
  router readback (or a fresh Crossbar Router snapshot).
- Automatically refresh the active strips after a successful router selection
  and send the existing routing event to other browser clients. Stereo pairs
  show the updated ordered Left+Right labels, with existing custom strip names
  preserved. Disconnected mixer inputs show `Disconnected`.
- Does not rename physical matrix channels, touch mixer coefficients, or treat
  a `Line/Out` route as a mixer input. Refreshes external ffado-mixer changes
  when the Crossbar Router snapshot is requested, without per-fader D-Bus
  polling. See [TESTING.md#mixer-routing-and-stereo-links](TESTING.md#mixer-routing-and-stereo-links).

## 1.1.1-dev — Saffire PRO 40 inputs 3–8 label correction (2026-10-22)

- Recognize both `Mic/Lin/Inst` (inputs 1–2) and `Mic/Lin/In` (inputs 3–8) as
  analog input labels. Previously the formatter omitted the latter form, so
  inputs 3–8 retained their long hardware names.
- Apply the same compact naming to stereo pairs without repeating `Analog`
  (for example `Mic/Lin/In:03+04` → `Analog 3+4`), while leaving underlying
  FFADO IDs, customized names, and other device functionality untouched.
- Added regression cases for all eight inputs, including the alternate
  `Mic/Line/In` spelling. See [`TESTING.md#layout-editing-and-settings-persistence`](TESTING.md#layout-editing-and-settings-persistence).

## 1.1.1-dev — Complete Saffire input labels / stereo 1394 display (2026-10-21)

- Recognize `Mic/Lin/Inst` and `Mic/Line/Inst` as compact **Analog** input labels.
  For example, `Mic/Lin/Inst:03+04` now appears as `Analog 3+4`.
- Show native `1394/In` ports as **Firewire**, e.g. `1394/In:01` → `Firewire 1`.
  A native stereo pair or two individually named 1394 ports displays
  `Firewire 1+2`, with **no repeated “Firewire” prefix**. Reversed and
  nonadjacent pair order remains intact.
- Shortening occurs in the shared presentation-only label function across
  channel strips, stereo pair names, bus names and In/Out matrix headings.
  Custom names, FFADO routing identifiers, saved IDs and API payloads remain
  unchanged. See [`TESTING.md#layout-editing-and-settings-persistence`](TESTING.md#layout-editing-and-settings-persistence).

## 1.1.1-dev — Saffire PRO 40 stereo-pan and concise hardware labels (2026-10-21)

- Fixed stereo input balance when the Right input had no active diagonal to
  the linked Right bus. An **explicit** user pan adjustment can now complete
  that one missing diagonal from the existing leg's level; it never activates
  an arbitrary cross-route. Simply linking/unlinking still does not touch the
  FFADO matrix. If both diagonals are disconnected, neither is enabled.
- DICE/RME input pairs require the corresponding stereo output bus link for
  balance; a missing link is explained instead of attempting unsupported
  native pan writes. Selecting/starting from a linked Right output bus now
  normalizes to its Left bus.
- Pan drags preview locally and commit once on release; mouse wheel and
  keyboard interactions are coalesced. Avoids flooding the slow FireWire
  D-Bus mixer with intermediate writes.
- Shortened recognized FFADO hardware labels in strips, bus selector, and
  matrix headers (for example `Mixer/Out:01` → `Bus 1`, `Anlg/In:02` →
  `Analog 2`). Original labels, D-Bus paths, channel IDs, and user-defined
  names remain unchanged.
- Added PRO 40 simulated hardware tests, UI interaction tests, and a live
  test checklist: [`TESTING.md#mixer-routing-and-stereo-links`](TESTING.md#mixer-routing-and-stereo-links).
  Hardware validation remains pending; start at low monitoring volume.

## 1.1.1-dev — Shared live peak stream / smoother meters (2026-10-21)

- Compared the uploaded `ffado-web-mixer-main` project's one-reader / WebSocket
  100 ms architecture with our request-then-wait HTTP meter polling. Replaced
  normal browser polling with a **shared, per-GUID, 100 ms FFADO sampler** and
  dependency-free Flask Server-Sent Events at `/api/peak-stream`.
- Coalesced frames for slow viewers (one-slot latest-frame queues), stopped
  sampling when no page watches a device, and stopped browser streams in hidden
  tabs. Existing `/api/peaks` remains as a diagnostic and transport fallback.
- Cached repeated meter DOM lookups, used a short CSS full-track transition for
  smoother movement, and preserved precise FFADO destination mapping, distinct
  stereo lanes, color scale, peak/clip holds, and the Crossbar Router meters.
- Added server fanout/device-safety tests and EventSource/fallback regression
  tests. See [`TESTING.md#metering-performance-and-readback`](TESTING.md#metering-performance-and-readback).
  Hardware performance verification is still pending.

## 1.1.1-dev — Saffire PRO 40 / ProFire stereo mute correction (2026-10-21)

- Fixed a linked **output bus** muting only its Left matrix row; a stereo input
  pair on a linked bus now suppresses and restores all four affected DICE EAP
  crosspoints rather than just the visible left bus.
- Grouped software mute writes under one serialized operation with FFADO
  readback and best-effort rollback; crash-safe per-device gain journals remain
  in use and preexisting Solo/user mute states are preserved.
- Corrected FFADO's `0..16` native silence-sentinel readback so some devices do
  not misinterpret a muted cell as an external gain change and discard the
  original level. Matrix silence alone is no longer mistaken for a user mute.
- Stereo strips now report partial mute states and refresh from hardware after
  a write. Output/master Mute surfaces rejected writes rather than silently
  continuing. Incoming mute events refresh the actual state.
- Added tests using exact Saffire PRO 40/40.1 and ProFire 2626/610 profile
  simulations, including partial failure rollback, stereo pairs on stereo
  buses, Solo coexistence and initially disconnected routes. See
  [`TESTING.md#mixer-routing-and-stereo-links`](TESTING.md#mixer-routing-and-stereo-links).
- This is limited to the FFADO matrix; direct Crossbar Router paths can bypass
  the mixer. Physical interface validation is pending.

## 1.1.1-dev — Meter color bands anchored to full scale (2026-10-21)

- Fixed the **channel-strip peak color scale**: previously the green/yellow/red
  gradient was stretched across the *current* meter fill, making even
  mid-level peaks appear yellow or red. Now a fixed 100%-height gradient is
  clipped from the bottom according to FFADO's real normalized peak value.
- Standardized warning colors near the physical end of each meter:
  green below roughly 90% of the displayed FFADO scale, yellow in the upper
  band, and red very near full scale (97%+). Applied the same fixed-scale
  treatment to horizontal **Crossbar Router** meters.
- Preserved FFADO's underlying 12-bit peak conversion, destination/channel
  mapping, stereo lane separation, peak-hold markers, near-full-scale warning
  hold, and unsupported-device behavior. This is a rendering-only change, not
  a modification to D-Bus metering, pan law, or routing.
- Added Node regression coverage for full-scale clipping at multiple levels,
  Python source checks, and an optional Chromium pixel regression covering
  both vertical and horizontal meter colors. See
  [`TESTING.md#metering-performance-and-readback`](TESTING.md#metering-performance-and-readback).
  Physical FireWire hardware verification remains pending.

## 1.1.1-dev — Fix MOTU Phones destination discovery (2026-10-21)

- Fixed the missing **Phones destination** dropdown in In/Out → Bus → outputs:
  MOTU model profiles declared `/Mixer/Control/Phones_src` as
  `phones_source_path`, but the runtime D-Bus inventory did not probe that
  attribute. Now the exact model-approved path is enumerated before resolving
  the selector; it appears only when FFADO exports a real Discrete control.
- Added discovery-level tests, including valid/invalid interfaces, unmapped
  families, and independent bus destinations. Existing General Settings layout
  and backend readback protection are unchanged. Hardware confirmation pending.

## 1.1.1-dev — MOTU Phones destination and General Settings layout

- In/Out → Bus → outputs now includes a **Phones destination** dropdown when an exact
  MOTU `/Mixer/Control/Phones_src` Discrete control is advertised by FFADO.
  Hardware reads and writes are verified; this is distinct from each mix bus's
  `/Mixer/MixN/Mix_dest` and does not rewrite levels or matrix crosspoints.
- Only source-mapped pre-Mk3 MOTU model profiles expose the control, and only
  when the endpoint exists. Model-specific available destinations are reused.
- General Settings now displays Skip loading screen and Hide minimized strips
  in the left column, with Enable QJackCtl support in the upper-right column.
  Options have centered checkboxes and centered, wrapping explanatory text;
  on phones, they stack into one column.

# Changelog

## 1.1.1 — development branch (2026-10-19)

- **Fixed missing Saffire PRO 26 and other DICE channel-strip meters**: `/api/state` uses zero-padded strip IDs (`ch/00`–`ch/09`), while `/api/peaks.channels` uses unpadded decimal JSON keys (`"0"`–`"9"`). The front end now normalizes the index before reading the actual FFADO peak value; formerly only strip indices 10+ could match correctly. This affects every model using the common DICE EAP peak renderer.
- Added CSS hiding for unsupported/unmapped `.peak-meter` controls, source-accurate tests for all 16 supported DICE meter profiles, and end-to-end regression coverage that renders actual backend-style JSON through the JavaScript meter display. No routing changes or invented meter readings. Physical devices still require testing. See [`TESTING.md#metering-performance-and-readback`](TESTING.md#metering-performance-and-readback).

- Reserved a toolbar-to-bus-picker clearance in the sidebar across desktop, tablet and phone sizes. Adaptive bus-column selection now subtracts the real top/bottom padding from the available height instead of allowing the bus grid to crowd the routing/settings controls in a maximized 1440p window. Short landscape windows retain a smaller but positive gap, with vertical scrolling when necessary.
- Added [`TESTING.md#layout-editing-and-settings-persistence`](TESTING.md#layout-editing-and-settings-persistence) and expanded the adaptive bus-grid regression test for constrained height and touch viewports. No changes to FFADO mixer controls or device settings.
- Made the sidebar **bus selector responsive to bus count and available height**: small mixers remain at up to two columns, while large devices can expand leftward into 4, 6, or more bus columns within the current sidebar width/viewport cap. Outputs remain independent and limited to two columns.
- Grouped each supported stereo bus pair with its link/unlink button, so buttons never drift onto a different row or lose their visual association when the panel widens. The user-resized sidebar and narrow/small-screen scrolling remain supported.
- No changes to hardware routing, device profiles, stereo-link semantics, saved settings or version number. Added adaptive bus-grid regression tests and [`TESTING.md#layout-editing-and-settings-persistence`](TESTING.md#layout-editing-and-settings-persistence).
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
- Stopped stale asynchronous poll replies from showing peaks after a device change/restart. Expanded dependency-free Node.js UI regression tests and updated `TESTING.md#metering-performance-and-readback`. Actual ProFire verification remains necessary.

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
- Added `TESTING.md#mixer-routing-and-stereo-links`, Python concurrency/validation/
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
  See `TESTING.md#mixer-routing-and-stereo-links` for screenshots-based validation.

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

See `TESTING.md#offline-smoke-tests` for a safe testing checklist and diagnostic instructions.


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
  TESTING.md#mixer-routing-and-stereo-links / PROFILE_CAPABILITIES.md.

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
- New diagnostic guide: `TESTING.md#metering-performance-and-readback`.

## Native gain precision and matrix editor (this update)

- Added `ffado_webmixer/gain.py`: FFADO 2^14-unity native-to-dB conversions, silent sentinel, model-gated DICE/RME limits and explicit value validation.
- Preserved fractional resolution for DICE/RME main faders, rather than rounding to whole 0–100 percent steps.
- The matrix snapshot now includes `db_values` (null for silence), a model-specific gain scale, and the existing percentage `values` for legacy clients.
- `/api/matrix` accepts `db` (including null for silence) in addition to the existing `value`. Writes return native readback level and native coefficient; software-muted writes are identified as deferred.
- Completed matrix editing: 0.1 dB number entry/keyboard/knob, FFADO-style presets from +6 to −55 and −∞, unity and silence actions, and double-click-to-preview unity followed by Apply.
- The UI displays **hardware readback**, not the assumed requested gain. Hardware's finite integer coefficients determine actual attainable precision.
- Original MOTU UltraLite output routing remains unchanged; unsupported dB controls are not exposed.
- Added `TESTING.md#mixer-routing-and-stereo-links` and converter/matrix regression tests.

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
- Added `TESTING.md#mixer-routing-and-stereo-links` and hardware-free failure-injection
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
- Added `TESTING.md#multiple-devices-and-desktop-integration` for the tester with three ProFire
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
