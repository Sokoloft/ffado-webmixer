import argparse
import os
import sys
import threading
from pathlib import Path

from ffado_webmixer.config import Config
from ffado_webmixer import __version__


APP_NAME = "ffado-webmixer"
APP_VERSION = __version__

# Source checkouts retain a root main.py; installed distributions do not.
ROOT = Path(__file__).resolve().parents[2] if (Path(__file__).resolve().parents[2] / 'main.py').is_file() else Path(__file__).resolve().parent
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
        "--debug", metavar="PROFILE",
        help="Requires an explicit offline profile (e.g. --debug profire2626, --debug Motu-Ultralite, or --debug list); never connects to D-Bus",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run web server without client front end",
    )

    parser.add_argument(
        '--host', choices=('127.0.0.1', 'localhost', '0.0.0.0'), default='127.0.0.1',
        help='Listen locally by default; 0.0.0.0 enables LAN access and requires FFADO_WEBMIXER_TOKEN',
    )

    desktop = parser.add_mutually_exclusive_group()
    desktop.add_argument('--install-desktop', action='store_true', help='Install a per-user .desktop launcher and themed icon')
    desktop.add_argument('--remove-desktop', action='store_true', help='Remove the FFADO Webmixer per-user launcher')
    desktop.add_argument('--check-desktop', action='store_true', help='Check the per-user desktop launcher')

    return parser.parse_args()


def create_backends(args, config):
    if args.debug:
        from ffado_webmixer.debug_backend import make_debug_mixer, fixture_names, resolve_debug_profile
        if args.debug.lower() == 'list':
            print('Available offline profiles:')
            for name in fixture_names(): print('  '+name)
            sys.exit(0)
        # Debug uses in-memory preferences and a logging D-Bus double.
        try:
            return [make_debug_mixer(resolve_debug_profile(args.debug), config)]
        except ValueError as exc:
            sys.exit(str(exc))
    if args.demo:
        from ffado_webmixer.demo import DemoMixer
        mixer = DemoMixer()
        mixer.guid = 'de00000000000000'  # synthetic 64-bit identity; no hardware D-Bus
        mixer.profile = {}
        mixer.nickname_path = None
        return [mixer]
    try:
        from ffado_webmixer.mixer import Mixer, load_device_info
        from ffado_webmixer.profiles.loader import load_profile
        data = load_device_info()
        from ffado_webmixer.helper import FfadoHelper
        helper = FfadoHelper()
        result=[]
        excluded=[]
        for device in data['devices']:
            profile=load_profile(device)
            if not profile or not profile.get('mixer_matrix'):
                excluded.append(device.get('model_name') or device['guid'])
                continue
            try:
                result.append(Mixer(config, device=device, helper=helper))
            except Exception as exc:
                # A broken/unavailable unit must not prevent other connected
                # verified devices from being controlled. Show the diagnostic
                # but retain only successfully initialized mixers.
                excluded.append(f'{device["guid"]} ({type(exc).__name__}: {exc})')
        if excluded:
            print('No verified gain profile for:', ', '.join(excluded))
        if not result:
            raise RuntimeError('No matching source-defined mixer profiles for connected devices')
        return result
    except Exception as exc:
        sys.exit(f'Unable to load known FFADO hardware: {exc}\nTry --debug profire2626 for offline UI testing')


def main():
    args = parse_args()
    if getattr(args, 'check_desktop', False) or getattr(args, 'remove_desktop', False) or getattr(args, 'install_desktop', False):
        from ffado_webmixer.desktop_integration import is_installed, install, remove
        if getattr(args, 'check_desktop', False):
            print('Desktop launcher installed' if is_installed() else 'Desktop launcher not installed')
            return
        if getattr(args, 'remove_desktop', False):
            try:
                print('Desktop launcher removed' if remove() else 'No desktop launcher to remove')
            except (OSError, PermissionError) as exc:
                sys.exit(str(exc))
            return
        settings = Config(CONFIG_FILE)
        settings.load()
        try:
            desktop, icon = install(settings.settings)
            with settings._save_lock:
                settings.settings['desktop_integration_prompted'] = True
                settings.save()
        except OSError as exc:
            sys.exit(str(exc))
        print(f'Desktop launcher: {desktop}\nTheme icon: {icon}')
        return
    # Validate debug selection before requiring Flask/Qt or opening a D-Bus bus.
    if args.debug and args.debug.lower() != "list":
        from ffado_webmixer.debug_backend import resolve_debug_profile
        try:
            resolve_debug_profile(args.debug)
        except ValueError as exc:
            sys.exit(str(exc))
    if args.debug and args.debug.lower() == "list":
        from ffado_webmixer.debug_backend import fixture_names
        print("Available offline profiles:")
        for name in fixture_names():
            print("  " + name)
        return
    from ffado_webmixer.access import AccessPolicy
    try:
        access_policy = AccessPolicy(getattr(args, 'host', '127.0.0.1'),
                                     os.environ.get('FFADO_WEBMIXER_TOKEN'))
    except ValueError as exc:
        sys.exit(str(exc))
    from ffado_webmixer.server import create_app, prepare_server
    if not (args.demo or args.debug):
        (CONFIG_DIR / "themes").mkdir(parents=True, exist_ok=True)

    # Demo mode keeps its settings in memory only, so it never touches the real config.json.
    config = Config(None if args.demo or args.debug else CONFIG_FILE)
    config.load(migrate_from=ROOT / "config.json" if (ROOT / "config.json").exists() else ROOT / "states" / "ffado.json")

    from ffado_webmixer.device_manager import DeviceManager, SelectedBackend, SelectedConfig
    manager = DeviceManager(create_backends(args, config), config, debug=bool(args.debug))
    # Graceful termination restores software-suppressed matrix coefficients.
    # A power loss or crash leaves a journal and requires explicit recovery.
    if not (args.debug or args.demo):
        import atexit
        def restore_soft_mutes_on_exit():
            for unit in manager.devices.values():
                if hasattr(unit, 'shutdown_soft_mutes'):
                    try: unit.shutdown_soft_mutes()
                    except Exception as exc:
                        print(f'FFADO software mute cleanup failed on {unit.guid}: {exc}')
        atexit.register(restore_soft_mutes_on_exit)
    backend = SelectedBackend(manager)
    selected_config = SelectedConfig(manager)
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
        config=selected_config,
        device_manager=manager,
        access_policy=access_policy,
        about={
            "name": APP_NAME,
            "version": APP_VERSION,
            "mode": "Debug (no D-Bus)" if args.debug else "Demo (simulated mixer)" if args.demo else "FFADO hardware",
        },
    )

    # Bind in this thread: a busy port must fail before opening the Qt window,
    # not disappear in a daemon thread while the splash spins indefinitely.
    try:
        http_server = prepare_server(app)
    except RuntimeError as exc:
        sys.exit(str(exc))

    if args.headless:
        try:
            http_server.serve_forever()
        finally:
            http_server.server_close()
        return

    server_thread = threading.Thread(
        target=http_server.serve_forever,
        daemon=True,
    )
    server_thread.start()

    from ffado_webmixer.client import run_window, wait_until_ready
    try:
        wait_until_ready(server_thread=server_thread)
    except RuntimeError as exc:
        http_server.shutdown()
        http_server.server_close()
        sys.exit(str(exc))

    try:
        run_window(
            window_title,
            config.settings.get("theme", "dark"),
            skip_loading_screen=config.settings.get("skip_loading_screen", False),
            config=config,
        )
    finally:
        http_server.shutdown()
        http_server.server_close()


if __name__ == "__main__":
    main()
