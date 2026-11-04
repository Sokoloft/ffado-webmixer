"""Source-defined D-Bus metering for DICE EAP devices.

FFADO references:
  src/dice/dice_eap.cpp, PeakSpace::read(): 12-bit field at bits 16..27
  support/mixer-qt4/ffado/widgets/crossbarrouter.py, VuMeter.paintEvent():
      uses sqrt(raw / 4096) for the visual amplitude.

The DICE EAP specification does not establish a calibrated dBFS measurement
for these 12-bit values.  We therefore expose a *normalized FFADO meter level*,
not verified ADC/DAC clipping measurements. No hardware writes occur here.
"""
import math
import re
import time

# Only a genuine Mixer/In router destination named in FFADO's matrix row
# is associated with the corresponding mixer input strip. Never fabricate
# destination identifiers from the strip's ordinal number.
MIXER_INPUT = re.compile(r'^Mixer/In:\d{2,3}$')
MIXER_OUTPUT = re.compile(r'^Mixer/Out:\d{2,3}$')
BUS_ROUTE_REFRESH_SECONDS = 0.5


def meter_config(profile, matrix):
    """Validate the exact model's declared meter conversion and mapping."""
    feature = profile.get('capabilities', {}).get('features', {}).get('peak_metering', {})
    if feature.get('state') not in ('mapped', 'optional'):
        return None
    if (feature.get('format') != 'dice_eap_peak12' or
            feature.get('channel_map') != 'matrix_input_router_destination' or
            feature.get('path') != '/EAP/Router' or
            not matrix.get('transposed')):
        return None
    return {'format': 'dice_eap_peak12', 'full_scale': 4096, 'maximum': 4095,
            'unit': 'dB relative to FFADO EAP full scale (estimated)',
            'calibrated_dbfs': False, 'clip_code': 4095}


def channel_destinations(device, matrix, config):
    """Map each actual DICE matrix input row to its FFADO router destination."""
    if not config:
        return {}
    actual = next((m for m in device.get('matrices', [])
                   if m.get('path') == matrix.get('path')), None)
    if actual is None:
        return {}
    result = {}
    for index, label in enumerate(actual.get('row_names', [])):
        router_destination = str(label).split('\n', 1)[0].strip()
        if MIXER_INPUT.fullmatch(router_destination):
            result[str(index)] = router_destination
    return result


def normalize_peak(raw, config):
    """Convert DICE EAP raw peak to FFADO-equivalent visual amplitude.

    FFADO uses sqrt(raw/4096), not raw/4095, for its meter display.
    Expressing that visual amplitude in dB gives 10*log10(raw/4096).
    """
    raw = float(raw)
    if not math.isfinite(raw) or raw < 0 or raw > config['maximum']:
        return None
    scaled = raw / config['full_scale']
    amplitude = math.sqrt(scaled)
    return {'raw': raw, 'level': amplitude,
            'db': round(20 * math.log10(amplitude), 2) if amplitude > 0 else None,
            'near_full_scale': raw >= config['clip_code']}


def output_peak_samples(mixer, destinations):
    """Map source-declared outputs to real FFADO router destination peaks.

    ``destinations`` is the normalized getPeakValues() frame already used by
    input and routing meters. No additional hardware reads or calculations
    from mixer gains are needed. Missing output peaks remain unavailable.
    """
    if mixer.matrix['mode'] != 'dice_db':
        return {}
    result = {}
    for out_id, output in mixer.outputs.items():
        destination = output.get('meter_destination')
        if destination in destinations:
            result[out_id] = {'destination': destination, **destinations[destination]}
    return result


def bus_peak_samples(mixer, destinations):
    """Use a bus's actual routed destination peak, never sum input readings.

    DICE meters router destinations. Associate native matrix output sources
    with their currently routed destinations; unconnected/unmetered buses
    remain unavailable. Share routing metadata between peak frames to avoid
    a full routing read on every 20 Hz meter tick.
    """
    if mixer.matrix.get('mode') != 'dice_db' or not mixer.matrix.get('transposed'):
        return {}
    matrix = next((item for item in mixer.device.get('matrices', [])
                   if item.get('path') == mixer.matrix['path']), {})
    sources = {str(label).split('\n', 1)[0].strip(): f'bus/{index}'
               for index, label in enumerate(matrix.get('col_names', []))
               if MIXER_OUTPUT.fullmatch(str(label).split('\n', 1)[0].strip())
               and f'bus/{index}' in mixer.outputs}
    if not sources:
        return {}
    measured = [name for name in destinations if not MIXER_OUTPUT.fullmatch(name)]
    now = time.monotonic()
    routes = getattr(mixer, '_bus_meter_routes', {})
    if (now - getattr(mixer, '_bus_meter_routes_at', -float('inf')) >= BUS_ROUTE_REFRESH_SECONDS or
            any(name not in routes for name in measured)):
        routes = {}
        for name in measured:
            try:
                routes[name] = str(mixer.helper.router_call(mixer.router_path, 'getSourceForDestination', name))
            except Exception:
                routes[name] = None  # A failed lookup must never reuse a stale route.
        mixer._bus_meter_routes = routes
        mixer._bus_meter_routes_at = now
    result = {}
    for destination in sorted(measured):
        source = routes.get(destination)
        out_id = sources.get(source)
        if out_id is not None and out_id not in result:
            result[out_id] = {'source': source, 'destination': destination, **destinations[destination]}
    return result
