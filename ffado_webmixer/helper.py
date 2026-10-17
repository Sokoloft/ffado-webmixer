"""Reads and writes FFADO values over DBus. The only module that changes device state."""
import threading
from contextlib import contextmanager

import dbus

BUS_NAME = "org.ffado.Control"
NS = "org.ffado.Control.Element."

# DBus type each kind of single-value element expects.
SETTERS = {"Discrete": dbus.Int32, "Continuous": dbus.Double, "Boolean": dbus.Boolean,
           "Text": dbus.String, "Enum": dbus.Int32, "AttributeEnum": dbus.Int32}


def _native(value):
    """dbus-python types -> plain Python."""
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    return value


class FfadoHelper:
    def __init__(self):
        self._bus = dbus.SessionBus()
        self._lock = threading.RLock()      # Flask serves requests from several threads
        self._proxies = {}

    @contextmanager
    def transaction(self):
        """Serialize a multi-operation hardware transaction on this helper."""
        with self._lock:
            yield

    def _call(self, path, kind, method, *args):
        """Retry once if FFADO's D-Bus service invalidated a cached proxy."""
        for attempt in range(2):
            try:
                return getattr(self._iface(path, kind), method)(*args)
            except dbus.exceptions.DBusException as exc:
                name = exc.get_dbus_name()
                if attempt or name not in (
                    'org.freedesktop.DBus.Error.ServiceUnknown',
                    'org.freedesktop.DBus.Error.NameHasNoOwner',
                    'org.freedesktop.DBus.Error.UnknownObject',
                    'org.freedesktop.DBus.Error.UnknownMethod',
                    'org.freedesktop.DBus.Error.NoReply',
                    'org.freedesktop.DBus.Error.Disconnected',
                ):
                    raise
                self._proxies.clear()
                self._bus = dbus.SessionBus()

    def _iface(self, path, kind):
        key = (path, kind)
        if key not in self._proxies:
            obj = self._bus.get_object(BUS_NAME, path)
            self._proxies[key] = dbus.Interface(obj, NS + kind)
        return self._proxies[key]

    # ---- FFADO EAP CrossbarRouter (exact methods from control-interface.xml) ----
    def router_call(self, path, method, *args):
        with self._lock:
            return self._call(path, "CrossbarRouter", method, *args)

    # ---- matrix mixer cells (fader / mute / pan / solo ...) ----
    def get_cell(self, path, row, col):
        with self._lock:
            return _native(self._call(path, "MatrixMixer", "getValue", dbus.Int32(row), dbus.Int32(col)))

    def set_cell(self, path, row, col, value):
        with self._lock:
            self._call(path, "MatrixMixer", "setValue", dbus.Int32(row), dbus.Int32(col), dbus.Double(value))

    # ---- single-value elements (Discrete / Continuous / Text / Boolean) ----
    def get_value(self, path, kind):
        with self._lock:
            return _native(self._call(path, kind, "getValue"))

    def set_value(self, path, kind, value):
        with self._lock:
            self._call(path, kind, "setValue", SETTERS[kind](value))

    # ---- enums (clock source, sample rate select ...) ----
    def get_selected(self, path, kind="Enum"):
        with self._lock:
            return _native(self._call(path, kind, "selected"))

    def select(self, path, index, kind="Enum"):
        with self._lock:
            self._call(path, kind, "select", dbus.Boolean(index) if kind == "Boolean" else dbus.Int32(index))
