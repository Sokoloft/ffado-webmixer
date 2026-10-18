# Exact FFADO model resolution

`device_registry.py` parses the source `ffado_configuration` to identify devices
with exact vendor/model IDs and FFADO's own MOTU/RME normalization rules.
`profiles/loader.py` selects an explicit model XML and reads the strict v2
capability contract in `profiles/capabilities.py`.

`interrogate.py` reads ConfigROM first and inventories **only source-declared,
model-mapped D-Bus paths**. For MOTU pre-mk3, it reads `/Mixer/Info/Model`
*before* probing the model-specific matrix and controls. It does not infer
hardware capabilities from matrix dimensions, D-Bus naming or label similarity.

`profiles/resolver.py` verifies the declared matrix/roles are present and maps
FFADO's actual dimensions/labels to the UI. A missing or unsupported matrix
returns no mixer rather than selecting the largest discovered matrix.

`mixer.py` handles live reads/writes, checks the resolved capabilities and
exposes the current model contract under `/api/describe.hardware_capabilities`.
`debug_backend.py` uses a synthetic backend and makes **no real D-Bus calls**;
fixtures are available only for models with declared mapped matrices.

See [CAPABILITIES.md](CAPABILITIES.md) for model coverage, statuses, source
attribution, and instructions for adding safely mapped controls.
