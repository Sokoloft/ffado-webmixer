"""Bus master meters follow measured router destinations, not input estimates."""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer


@pytest.fixture
def metering(monkeypatch):
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('saffirepro40', Config(None))
    routes = {'Line/Out:07': 'Mixer/Out:01', '1394/Out:02': 'Mixer/Out:02',
              'Mixer/In:01': 'Anlg/In:01', 'Line/Out:01': 'Mute:00'}
    values = {'Line/Out:07': 256, '1394/Out:02': 4095, 'Mixer/In:01': 4095, 'Line/Out:01': 1024}
    calls = []
    clock = [10.]
    monkeypatch.setattr('ffado_webmixer.peak_metering.time.monotonic', lambda: clock[0])

    def router(_path, method, *args):
        calls.append((method, args))
        if method == 'hasPeakMetering':
            return True
        if method == 'getPeakValues':
            return list(values.items())
        if method == 'getSourceForDestination':
            return routes[args[0]]
        if method == 'getSourceNames':
            return ['Mixer/Out:01', 'Mixer/Out:02', 'Anlg/In:01', 'Mute:00']
        if method == 'getDestinationNames':
            return list(routes)
        if method == 'setConnectionState':
            source, destination, active = args
            routes[destination] = source if active else 'Mute:00'
            return True
        raise AssertionError(method)

    def forbidden(*args):
        raise AssertionError('Bus meters must not read or write gain controls')

    mixer.helper.router_call = router
    mixer.helper.get_cell = mixer.helper.set_cell = forbidden
    mixer.helper.get_value = mixer.helper.set_value = forbidden
    return mixer, routes, values, calls, clock


def test_real_bus_peaks_follow_router_assignments_not_output_ordinals(metering):
    mixer, _, _, calls, _ = metering
    mixer.config.settings['stereo_buses'] = [0]
    result = mixer.peak_snapshot()
    left, right = result['outputs']['bus/0'], result['outputs']['bus/1']
    assert left['source'] == 'Mixer/Out:01' and left['destination'] == 'Line/Out:07'
    assert left['level'] == .25 and left['raw'] == 256
    assert right['source'] == 'Mixer/Out:02' and right['destination'] == '1394/Out:02'
    assert right['near_full_scale']
    assert result['outputs']['line/1']['raw'] == 1024
    assert result['outputs']['line/7']['raw'] == 256
    assert 'bus/6' not in result['outputs']
    assert sum(method == 'getPeakValues' for method, _ in calls) == 1
    assert not any(method == 'setConnectionState' for method, _ in calls)


def test_bus_names_and_aliases_do_not_supply_meter_source_ids(metering):
    mixer, routes, _, _, _ = metering
    mixer.device['matrices'][0]['col_names'][0] = 'Mixer/Out:99'
    mixer.outputs['bus/0']['name'] = 'Headphones'
    routes['Line/Out:07'] = 'Mixer/Out:99'
    result = mixer.peak_snapshot()
    assert result['outputs']['bus/0']['source'] == 'Mixer/Out:99'
    assert 'bus/98' not in result['outputs']


def test_missing_bus_peaks_never_borrow_the_other_bus_or_loud_inputs(metering):
    mixer, _, values, _, _ = metering
    mixer.peak_snapshot()
    del values['1394/Out:02']
    result = mixer.peak_snapshot()
    assert 'bus/0' in result['outputs'] and 'bus/1' not in result['outputs']
    values['Line/Out:07'] = 0
    assert mixer.peak_snapshot()['outputs']['bus/0']['level'] == 0
    del values['Line/Out:07']
    assert not any(key.startswith('bus/') for key in mixer.peak_snapshot()['outputs'])


def test_route_cache_refreshes_for_external_edits_and_clears_failed_lookups(metering):
    mixer, routes, _, calls, clock = metering
    mixer.peak_snapshot()
    count = len(calls)
    mixer.peak_snapshot()
    assert len(calls) == count + 1, 'the next frame only reads peak values'
    routes['Line/Out:07'] = 'Mixer/Out:02'
    clock[0] += .6
    result = mixer.peak_snapshot()
    assert 'bus/0' not in result['outputs']
    assert result['outputs']['bus/1']['source'] == 'Mixer/Out:02'
    del routes['Line/Out:07']
    del routes['1394/Out:02']
    clock[0] += .6
    assert not any(key.startswith('bus/') for key in mixer.peak_snapshot()['outputs'])
    assert 'line/7' in mixer.peak_snapshot()['outputs'], 'physical meters survive route lookup failures'


def test_local_router_edits_invalidate_bus_mapping_immediately(metering):
    mixer, _, _, _, _ = metering
    assert 'bus/0' in mixer.peak_snapshot()['outputs']
    mixer.router_set('Line/Out:07', 'Mixer/Out:02')
    assert 'bus/0' not in mixer.peak_snapshot()['outputs']


def test_unknown_native_bus_labels_have_no_fabricated_meter(metering):
    mixer, _, _, _, _ = metering
    mixer.device['matrices'][0]['col_names'] = ['Bus 1', 'Bus 2']
    assert not any(key.startswith('bus/') for key in mixer.peak_snapshot()['outputs'])
