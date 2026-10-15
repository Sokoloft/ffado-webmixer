# Runtime FFADO discovery and XML interpretation

- `interrogate.py` inventories ConfigRom identity, scalar endpoints and live matrix paths/dimensions/names. It does not select or classify a mixer.
- `device_registry.py` maps FFADO ConfigRom identity to its configured mixer family.
- `profile_loader.py` loads the XML family/model profile and resolves the live matrix inventory into mixer roles and channel topology.
- `mixer.py` reads/writes only those live endpoints and applies profile ranges.
- `config.json` stores only application/user settings; hardware topology is not persisted.

Unknown families retain generic role inference; device-specific advanced controls are not invented.
