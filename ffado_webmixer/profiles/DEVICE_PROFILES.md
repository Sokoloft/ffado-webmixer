# FFADO device profiles

The `profiles/` tree represents the exact supported FFADO configuration
identities plus explicitly documented internal MOTU model variants. Every
model profile has a complete `<capabilities schema="2">` declaration.

Profiles use explicit `mapped`, `optional`, `source_only`, and `unmapped`
feature states. **`unmapped` does not mean absent hardware.** If the device is
recognized but does not have a verified gain matrix, ffado-webmixer excludes
it from the writable mixer list rather than guessing a D-Bus matrix.

For an implementation and feature matrix, see [CAPABILITIES.md](CAPABILITIES.md).
The `reference.xml` files remain archival material, not executable profiles.
