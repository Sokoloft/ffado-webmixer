# Project documentation

Documentation lives in this folder so the repository root stays focused on the application source. The top-level [`README.md`](../README.md) remains in place for GitHub's project overview.

**Current project version:** 1.1.1 (development branch).

- [Changelog](CHANGELOG.md) — development history and release notes.

## Testing and verification guides

- [Adaptive bus selector: two columns for small mixers, extra columns for ProFire-style devices](TESTING_ADAPTIVE_BUS_GRID.md)
- [Priority 2: arbitrary input stereo pairs and safe routing (v1.1.1 development build)](TESTING_ARBITRARY_STEREO.md)
- [Testing source-defined device capabilities (v1.1.1 development build)](TESTING_CAPABILITIES.md)
- [v1.1.1 development build — Matrix gain precision testing](TESTING_GAIN_PRECISION.md)
- [Initial stereo pan display — Priority 3](TESTING_INITIAL_PAN.md)
- [v1.1.1 development build — inline matrix-cell rotary controls](TESTING_MATRIX_CELL_ROTARY.md)
- [Matrix → strip synchronization (v1.1.1 development build)](TESTING_MATRIX_STRIP_SYNC.md)
- [MOTU UltraLite (first generation) bus-routing update](TESTING_MOTU_ULTRALITE.md)
- [Three interfaces + KDE Plasma: v1.1.1 development build validation](TESTING_MULTIPLE_DEVICES_KDE.md)
- [Peak-metering test and diagnostic report (v1.1.1 development build)](TESTING_PEAK_METERS.md)
- [About QR view / v1.0.1 quick test](TESTING_QR.md)
- [Saffire PRO 26 — hardware testing and bug-report guide (ffado-webmixer 1.0.1)](TESTING_SAFFIRE_PRO26.md)
- [Testing the QjackCtl and About settings update](TESTING_SETTINGS.md)
- [v1.1.1 development build — Software mute/solo resilience and recovery](TESTING_SOFTWARE_MUTE_SOLO.md)
- [Regression: input stereo pairs must be independent per bus](TESTING_STEREO_BUS_VISIBILITY.md)
- [Stereo pairing validation (Priority 4)](TESTING_STEREO_PAIR_VALIDATION.md)
- [ffado-webmixer 1.1.1 development build — hardware and debug testing](TESTING_V1_1.md)
- [Priority 7 — mixer Volume vs. hardware Input Gain](TESTING_VOLUME_TERMINOLOGY.md)

## Other documentation

Device-family and profile implementation details stay near the code under [`ffado_webmixer/profiles/`](../ffado_webmixer/profiles/), and theme instructions stay with the theme assets.

For new testing guides, add them here and link them from this index instead of putting more Markdown files in the project root.
