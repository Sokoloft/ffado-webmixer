"""Source-checkout compatibility launcher; the PyPI entry point uses the package."""
# For source-checkout installs: pip install -r requirements.txt (also requires host FFADO/D-Bus).
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from ffado_webmixer.main import main

if __name__ == "__main__":
    main()
