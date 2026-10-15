# FFADO family profiles — best-effort support

The 23 family directories contain source-derived `common.xml` profiles and
`reference.xml` archives extracted from the supplied FFADO mixer Python/Qt
sources. MOTU also has an UltraLite model override.

At runtime, FFADO D-Bus is authoritative: `interrogate.py` enumerates the actual
matrix mixers and controls. `profile_loader.py` selects profiles by explicit
hardware IDs where available, otherwise by multiple unique observed D-Bus
control paths. Generic paths alone cannot identify a family. If identification
is ambiguous, generic enumeration is used instead.

The backend supports its existing matrix controls, including fader/pan when a
profile supplies a numeric range, and binary mute/solo controls when FFADO
reports those matrices. Unspecified numeric ranges remain read-only. Other
source-derived controls are preserved as discovery metadata, **not** executed
as speculative commands. FFADO families without matrix mixers are not yet
supported by the web mixer interface.

These profiles are not a claim of full functionality for every device. Users
can submit D-Bus discovery logs and bug reports to expand individual profiles.

## FFADO-native device selection

`device_registry.py` reads `/usr/share/libffado/configuration` and merges
`~/.ffado/configuration` overrides by vendor/model ID, following FFADO's
`DeviceList` behavior. `interrogate.py` captures ConfigRom `unit_version` and
other identity fields. `profile_loader.py` uses FFADO's configured `mixer`
name to select `profiles/<mixer-name-lowercase>/common.xml`, then loads
model-specific XML as before. MOTU uses unitVersion >= 0x15 for `Motu_Mark3`,
otherwise `Motu`; RME uses unitVersion as its configuration model ID.

When a configuration entry has no mixer, or the selected family lacks a
profile, generic D-Bus discovery remains the fallback. Profile data never
creates hardware controls that the D-Bus server does not expose.

The runtime device configuration is not bundled: install libffado normally.
`testdata/configuration` is a snapshot used only by automated tests.
