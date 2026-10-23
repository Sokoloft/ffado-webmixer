"""Opens QjackCtl's Graph and Patchbay windows through QjackCtl's D-Bus interface.

QjackCtl listens for signals on the system bus (path "/", interface "org.rncbc.qjackctl"). It only does so if
"Setup > Misc > Other > Enable D-Bus interface" is switched on in QjackCtl.

The window opens on the computer running ffado-webmixer, whichever device pressed the button.
"""
import subprocess
import threading

DBUS_PATH = "/"
DBUS_INTERFACE = "org.rncbc.qjackctl"

# The only things the web page may ask for.
WINDOWS = ("graph", "patchbay")

_lock = threading.Lock()


class QjackCtlError(Exception):
    """QjackCtl can't be reached right now (not running, no D-Bus, ...). The text is shown to the user."""


def is_running():
    try:
        result = subprocess.run(
            ["pgrep", "-x", "qjackctl"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return True               # no pgrep to ask; just try sending the signal

    return result.returncode == 0


def open_window(window):
    """Ask QjackCtl to show its "graph" or "patchbay" window."""
    if window not in WINDOWS:
        raise ValueError(f"unknown QjackCtl window '{window}'")

    if not is_running():
        raise QjackCtlError("QjackCtl isn't running.")

    try:
        import dbus
        import dbus.lowlevel
    except ImportError:
        raise QjackCtlError("D-Bus isn't available (is python-dbus installed?).")

    try:
        with _lock:
            bus = dbus.SystemBus()
            bus.send_message(dbus.lowlevel.SignalMessage(DBUS_PATH, DBUS_INTERFACE, window))
            bus.flush()           # make sure it is on its way before we return
    except dbus.exceptions.DBusException as exc:
        raise QjackCtlError(f"Couldn't reach the system D-Bus: {exc}")
