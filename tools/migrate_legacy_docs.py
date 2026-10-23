#!/usr/bin/env python3
"""Remove obsolete root-level documentation after applying the docs/ patch.

Only exact, unmodified files from the 1.1.0-dev baseline are deleted. A locally
edited file is left in place so that the user's changes cannot be lost.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_HASHES = {'TESTING_ARBITRARY_STEREO.md': '83089cd7bdee48f8cad5c1d7f7b4deff2050942254c4a61eb02e8c8b957767bf', 'TESTING_CAPABILITIES.md': '1ccb2cbffce651fe2f2f829c8f6a0828c4aca82a145492d2826192dd356ac2a6', 'TESTING_GAIN_PRECISION.md': 'cfdd6328389c8c4db060db0f4011ca20baa57b50b7c702b27700e3b752ebe94e', 'TESTING_INITIAL_PAN.md': '63fa5719c53119819f94e5a35e657a2a19d712568ca1cbfc80c181b20b36e268', 'TESTING_MATRIX_CELL_ROTARY.md': 'ba496074971224eca784dfc152951287420284777439579a0cbcb9dc46c6e130', 'TESTING_MATRIX_STRIP_SYNC.md': '6c2e0a8d00ce0988c7377b86a6fb212005651af110af9eb42a79c54f0f3a7344', 'TESTING_MOTU_ULTRALITE.md': 'bf12598ac4a8a8d0e9d245ffa33a15989547dc29c8cfad846903c9fc511ccf26', 'TESTING_MULTIPLE_DEVICES_KDE.md': '8878d935e58bbbef6b6b5268fce70a5b1ed843fadb95b532353b9c7306973bd3', 'TESTING_PEAK_METERS.md': '2ddc2239ab02e3bd1dbe965e079a3e53508bd5db5e753088d92bad1aa1d06424', 'TESTING_QR.md': '7857f821dee3ef3c84714e1f0f28358313e5138c49764ae4049410c118af5edf', 'TESTING_SAFFIRE_PRO26.md': '60aff5b2308d7493b63422500003eed9aa048f2e754eda9e2adc4b149870fb40', 'TESTING_SETTINGS.md': 'f549b8adf5e89e809f6fe69ab0ab254621fb134d8b86bc32cc2108abc85490da', 'TESTING_SOFTWARE_MUTE_SOLO.md': '558091eddf4b65d122f7385323cb060b6f393dab96a184329b0b0685baf1c47b', 'TESTING_STEREO_BUS_VISIBILITY.md': 'f1b8d10fefd94da3f35bca0f56a1fe94974b18f3f37641a9f590ec72aad3d266', 'TESTING_STEREO_PAIR_VALIDATION.md': 'd601203d31307c540d13a2401f8e5ef3263393b3f669a342419cf5986b0c62df', 'TESTING_V1_1.md': '444f7b38a636e23168b9e65b23dc56769dcf8aec0dbf5653b4e0ca8f164bc4a4', 'TESTING_VOLUME_TERMINOLOGY.md': '4321f36790e732c081353930c4d6bdb55cd5f3453dc21df4bd623c0afcc020a9', 'CHANGELOG_1_1_0_DEV.md': 'c5ea2c0e0f78d623db6af224f87d7a9759b2ecf26e2c82cf6034937307b34ad2'}


def main():
    if not (ROOT / 'docs' / 'CHANGELOG.md').is_file():
        raise SystemExit('Please extract the updated docs/ folder before running this script.')
    removed = 0
    for name, baseline_hash in BASELINE_HASHES.items():
        old = ROOT / name
        new = ROOT / 'docs' / ('CHANGELOG.md' if name.startswith('CHANGELOG_') else name)
        if not old.is_file():
            continue
        if not new.is_file():
            print(f'Keeping {name}: destination missing')
            continue
        current_hash = hashlib.sha256(old.read_bytes()).hexdigest()
        if current_hash != baseline_hash:
            print(f'Keeping {name}: locally changed (move or merge it manually)')
            continue
        old.unlink()
        removed += 1
    print(f'Removed {removed} obsolete root-level Markdown file(s).')


if __name__ == '__main__':
    main()
