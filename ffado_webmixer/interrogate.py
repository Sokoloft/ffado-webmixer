"""Inventory connected FFADO device identities and available D-Bus endpoints.

No hardware interpretation or persistence is performed here. Profile resolution
and topology construction belong to profile_loader.py.
"""
import json
import re
import xml.etree.ElementTree as ET

import dbus

BUS_NAME = "org.ffado.Control"
DEVICE_MANAGER = "/org/ffado/Control/DeviceManager"
NS = "org.ffado.Control.Element."
GUID_RE = re.compile(r"^[0-9a-f]{16}$")        # FireWire device GUIDs
VALUE_KINDS = ("Continuous", "Discrete", "Boolean", "Text", "Enum", "AttributeEnum")

# ---------- low-level DBus access ----------
def iface(bus, path, kind):
    """Interface proxy for one element; `kind` is e.g. 'MatrixMixer'."""
    obj = bus.get_object(BUS_NAME, path)
    return dbus.Interface(obj, kind if kind.startswith("org.") else NS + kind)


def introspect(bus, path):
    """(interface names, child node names) as reported by DBus introspection."""
    text = iface(bus, path, "org.freedesktop.DBus.Introspectable").Introspect()
    root = ET.fromstring(str(text))
    return ({i.attrib["name"] for i in root.findall("interface")},
            [n.attrib["name"] for n in root.findall("node")])


def container_children(bus, path):
    """Child element names of an FFADO container (names may contain '/')."""
    container = iface(bus, path, "Container")
    return [str(container.getElementName(dbus.Int32(i)))
            for i in range(int(container.getNbElements()))]


def try_call(bus, path, kind, method, *args, default=None):
    try:
        value = getattr(iface(bus, path, kind), method)(*args)
    except dbus.exceptions.DBusException:
        return default
    return value if value is not None else default


# ---------- discovery ----------
def get_device_paths(bus):
    """Paths of every FFADO device under the device manager."""
    try:
        names = container_children(bus, DEVICE_MANAGER)
    except dbus.exceptions.DBusException:
        names = introspect(bus, DEVICE_MANAGER)[1]          # fall back to introspection
    return [f"{DEVICE_MANAGER}/{n}" for n in names if GUID_RE.match(n)]


def current_guids(bus=None):
    bus = bus or dbus.SessionBus()
    return [p.rsplit("/", 1)[1] for p in get_device_paths(bus)]


def walk(bus, path):
    """Yield (path, kinds) for an element and everything below it."""
    interfaces, _ = introspect(bus, path)
    kinds = {i[len(NS):] for i in interfaces if i.startswith(NS)}
    yield path, kinds
    if "Container" in kinds:
        for name in container_children(bus, path):
            yield from walk(bus, f"{path}/{name}")


def interrogate_device(bus, device_path):
    """Discover the mixer layout and capabilities for one FFADO device."""
    matrices, controls, routers = [], [], []
    for path, kinds in walk(bus, device_path):
        if "MatrixMixer" in kinds:
            matrices.append({
                "path": path,
                "name": path.rsplit("/", 1)[1],
                "rows": int(try_call(bus, path, "MatrixMixer", "getRowCount", default=0)),
                "cols": int(try_call(bus, path, "MatrixMixer", "getColCount", default=0)),
            })
            m = matrices[-1]
            m["row_names"] = [str(try_call(bus, path, "MatrixMixer", "getRowName", dbus.Int32(i), default="")) for i in range(m["rows"])]
            m["col_names"] = [str(try_call(bus, path, "MatrixMixer", "getColName", dbus.Int32(i), default="")) for i in range(m["cols"])]
        elif "CrossbarRouter" in kinds:
            routers.append({"path": path})
        elif "Container" not in kinds:
            kind = next((k for k in VALUE_KINDS if k in kinds), None)
            if kind:
                entry = {"path": path, "kind": kind,
                         "label": str(try_call(bus, path, "Element", "getLabel", default="")),
                         "name": str(try_call(bus, path, "Element", "getName", default=""))}
                if kind in ("Enum", "AttributeEnum"):
                    count = int(try_call(bus, path, kind, "count", default=0))
                    entry["options"] = [str(try_call(bus, path, kind, "getEnumLabel", dbus.Int32(i), default=""))
                                        for i in range(count)]
                if kind == "Continuous":
                    entry["min"] = try_call(bus, path, kind, "getMinimum")
                    entry["max"] = try_call(bus, path, kind, "getMaximum")
                controls.append(entry)

    rom = f"{device_path}/ConfigRom"
    result = {
        "device": device_path,
        "guid": device_path.rsplit("/", 1)[1],
        "vendor_id": int(try_call(bus, rom, "ConfigRomX", "getVendorId", default=0)),
        "model_id": int(try_call(bus, rom, "ConfigRomX", "getModelId", default=0)),
        "unit_version": try_call(bus, rom, "ConfigRomX", "getUnitVersion"),
        "vendor_name": str(try_call(bus, rom, "ConfigRomX", "getVendorName", default="")),
        "model_name": str(try_call(bus, rom, "ConfigRomX", "getModelName", default="")),
        "mixer": None,
        "controls": controls,
    }
    # Runtime inventory only: no role classification or channel interpretation.
    # The profile layer decides how to turn this into a mixer.
    result["matrices"] = matrices
    result["routers"] = routers
    return result


def discover():
    """Interrogate FFADO and return what the app needs to know about the connected device(s)."""
    bus = dbus.SessionBus()
    device_paths = get_device_paths(bus)
    if not device_paths:
        raise RuntimeError("No FFADO devices found. Is ffado-dbus-server running?")

    devices = [interrogate_device(bus, p) for p in device_paths]
    if not any(d["matrices"] for d in devices):
        raise RuntimeError("FFADO devices found, but none expose a matrix mixer.")
    return {"devices": devices}


if __name__ == "__main__":
    print(json.dumps(discover(), indent=2))
