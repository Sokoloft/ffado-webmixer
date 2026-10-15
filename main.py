import argparse
import sys
import threading
from pathlib import Path

from ffado_webmixer.config import Config
from ffado_webmixer.server import create_app, run_server


APP_NAME = "ffado-webmixer"
APP_VERSION = 1.0

ROOT = Path(__file__).parent
CONFIG_DIR = Path.home() / ".config" / "ffado-webmixer"
CONFIG_FILE = CONFIG_DIR / "config.json"


def parse_args():
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="ffado-mixer replacement with web functionality",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION}",
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with a simulated mixer instead of FFADO hardware (nothing is saved)",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run web server without client front end",
    )

    return parser.parse_args()


def create_backend(demo, config):
    if demo:
        from ffado_webmixer.demo import DemoMixer

        return DemoMixer()

    try:
        # Imported here so --demo works on a machine without FFADO or dbus.
        from ffado_webmixer.mixer import Mixer

        return Mixer(config)
    except Exception as exc:
        sys.exit(
            f"Could not connect to the FFADO mixer: {exc}\n"
            "No hardware handy? Try running with --demo"
        )


def main():
    args = parse_args()
    if not args.demo:
        (CONFIG_DIR / "themes").mkdir(parents=True, exist_ok=True)

    # Demo mode keeps its settings in memory only, so it never touches the real config.json.
    config = Config(None if args.demo else CONFIG_FILE)
    config.load(migrate_from=ROOT / "config.json" if (ROOT / "config.json").exists() else ROOT / "states" / "ffado.json")

    backend = create_backend(args.demo, config)

    description = backend.describe()
    device = description.get("device")

    window_title = (
        f"{APP_NAME}: {device}"
        if device
        else APP_NAME
    )

    app = create_app(
        backend=backend,
        description=description,
        config=config,
        about={
            "name": APP_NAME,
            "version": APP_VERSION,
            "mode": "Demo (simulated mixer)" if args.demo else "FFADO hardware",
        },
    )

    if args.headless:
        run_server(app)
        return

    server_thread = threading.Thread(
        target=run_server,
        args=(app,),
        daemon=True,
    )
    server_thread.start()

    from ffado_webmixer.client import run_window
    run_window(
        window_title,
        config.settings.get("theme", "dark"),
        skip_loading_screen=config.settings.get("skip_loading_screen", False),
        config=config,
    )


if __name__ == "__main__":
    main()
