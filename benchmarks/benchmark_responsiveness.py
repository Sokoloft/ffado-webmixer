"""Reproducible offline FFADO read/fader/peak microbenchmarks.

These use debug devices and a simulated D-Bus round-trip, NOT physical
FireWire measurements or real browser rendering. No physical mixer is touched.
Run: python benchmarks/benchmark_responsiveness.py --rpc-ms 1 --iterations 8
"""
import argparse
import contextlib
import io
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.services.peak_stream import PeakStreamHub


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 3)


def exercise_mixer(model, *, stereo, iterations, delay):
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(model, Config(None))
    original_get = mixer.helper.get_cell
    original_set = mixer.helper.set_cell
    rpc_calls = {'get': 0, 'set': 0}

    def get_cell(*args):
        rpc_calls['get'] += 1
        if delay: time.sleep(delay)
        return original_get(*args)

    def set_cell(*args):
        rpc_calls['set'] += 1
        if delay: time.sleep(delay)
        return original_set(*args)

    mixer.helper.get_cell = get_cell
    mixer.helper.set_cell = set_cell
    measures = []
    count = []
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(iterations):
            before = rpc_calls['get']
            started = time.perf_counter()
            state = mixer.read_mix(0, stereo_bus=stereo)
            measures.append((time.perf_counter() - started) * 1000)
            count.append(rpc_calls['get'] - before)
        rpc_calls['get'] = rpc_calls['set'] = 0
        fader_timings = []
        for i in range(iterations):
            # The same per-strip write path used by /api/set, without Flask or HTTP.
            started = time.perf_counter()
            mixer.write(0, 'ch/00', 'fader', 50 + i % 10)
            fader_timings.append((time.perf_counter() - started) * 1000)
    return {
        'model': model, 'stereo_bus': stereo, 'channels': len(state),
        'state_reads_per_refresh': count,
        'state_ms_mean': round(statistics.mean(measures), 3),
        'state_ms_p95': percentile(measures, .95),
        'fader_write_ms_mean': round(statistics.mean(fader_timings), 3),
        'fader_write_ms_p95': percentile(fader_timings, .95),
        'fader_get_calls_total': rpc_calls['get'],
        'fader_set_calls_total': rpc_calls['set'],
    }


def exercise_meter(*, iterations, delay):
    # Run the actual profile-driven meter conversion and SSE fanout against
    # the debug DICE FFADO router, not a fake random peak generator.
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('profire2626', Config(None))
    router_call = mixer.helper.router_call
    rpc_counts = {'hasPeakMetering': 0, 'getPeakValues': 0}

    def counted_router(*args):
        if args[1] in rpc_counts:
            rpc_counts[args[1]] += 1
        if delay: time.sleep(delay)
        return router_call(*args)

    mixer.helper.router_call = counted_router
    original_snapshot = mixer.peak_snapshot
    def timestamped_snapshot():
        with contextlib.redirect_stdout(io.StringIO()):
            frame = original_snapshot()
        frame['generated_at'] = time.monotonic()
        return frame
    mixer.peak_snapshot = timestamped_snapshot

    hub = PeakStreamHub(interval=0.1)
    sampler, first = hub.subscribe(mixer)
    _, second = hub.subscribe(mixer)
    times, latencies = [], []
    identical = True
    try:
        for _ in range(iterations):
            payload = json.loads(first.get(timeout=3))
            received = time.monotonic()
            peer = json.loads(second.get(timeout=3))
            identical &= payload == peer
            if not payload['available']:
                raise RuntimeError('Debug DICE FFADO peak sampler unavailable')
            times.append(received)
            latencies.append((received - payload['generated_at']) * 1000)
    finally:
        hub.unsubscribe(sampler, first)
        hub.unsubscribe(sampler, second)
        if sampler.thread is not None:
            sampler.thread.join(timeout=1)
    return {
        'samples': iterations, 'ffado_get_peak_values_calls': rpc_counts['getPeakValues'],
        'ffado_has_peak_metering_calls': rpc_counts['hasPeakMetering'],
        'two_viewers_received_same_frames': identical,
        'observed_interval_ms_mean': round(statistics.mean([(b-a)*1000 for a,b in zip(times,times[1:])]), 3),
        'sample_to_consumer_ms_p95': percentile(latencies, .95),
        'single_latest_frame_queue': first.maxsize == second.maxsize == 1,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rpc-ms', type=float, default=1.0,
                   help='Simulated latency per FFADO matrix get/set call (milliseconds)')
    p.add_argument('--iterations', type=int, default=8)
    args = p.parse_args()
    if args.rpc_ms < 0 or args.iterations < 3:
        p.error('rpc-ms must be >=0 and iterations >=3')
    delay = args.rpc_ms / 1000
    result = {
        'mode': 'offline debug devices; simulated D-Bus call delay; no physical interface/HTTP/DOM',
        'rpc_ms': args.rpc_ms, 'iterations': args.iterations,
        'mixers': [exercise_mixer('profire2626', stereo=True, iterations=args.iterations, delay=delay),
                   exercise_mixer('motuultralite', stereo=False, iterations=args.iterations, delay=delay)],
        'peak_sse_sampler': exercise_meter(iterations=args.iterations, delay=delay),
    }
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
