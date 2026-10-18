"""Offline test of source-defined DICE peak fields and mappings."""
import contextlib
import io
import math
import re
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.peak_metering import meter_config, channel_destinations, normalize_peak
from ffado_webmixer.profiles.capabilities import parse_capabilities


class PeakProfilesTest(unittest.TestCase):
    def fixture(self, name):
        with contextlib.redirect_stdout(io.StringIO()):
            return make_debug_mixer(name, Config(None))

    def test_calibration_matches_ffado_code_and_never_claims_dbfs(self):
        p=self.fixture('profire2626')
        config=p.meter_spec
        self.assertEqual(config['full_scale'],4096)
        self.assertEqual(config['maximum'],4095)
        self.assertFalse(config['calibrated_dbfs'])
        self.assertAlmostEqual(normalize_peak(1024,config)['level'],0.5)
        self.assertAlmostEqual(normalize_peak(1024,config)['db'], -6.02,places=2)
        self.assertEqual(normalize_peak(0,config)['level'], 0)
        self.assertIsNone(normalize_peak(0,config)['db'])
        self.assertFalse(normalize_peak(4094,config)['near_full_scale'])
        self.assertTrue(normalize_peak(4095,config)['near_full_scale'])
        for raw in (-1, 4096, math.nan, math.inf, -math.inf):
            self.assertIsNone(normalize_peak(raw,config))

    def test_only_declared_hardware_destinations_match_columns(self):
        p=self.fixture('saffirepro26')
        self.assertEqual(p.meter_channels['0'],'Mixer/In:01')
        self.assertEqual(p.meter_channels['17'],'Mixer/In:18')
        mat=next(x for x in p.device['matrices'] if x['path']==p.matrix['path'])
        mat['row_names'][2]='OtherDestination:03\n(Analog/In:03)'
        mat['row_names'][4]='Mixer/In:99 (bogus suffix)'
        mat['row_names'][5]='Mixer/Out:06'
        actual=channel_destinations(p.device,p.matrix,p.meter_spec)
        self.assertNotIn('2',actual)
        self.assertNotIn('4',actual)
        self.assertNotIn('5',actual)
        self.assertEqual(actual['1'],'Mixer/In:02')
        p.device['matrices'] = []
        self.assertEqual(channel_destinations(p.device,p.matrix,p.meter_spec),{})

    def test_router_peak_read_uses_explicit_destination_not_index(self):
        p=self.fixture('profire2626')
        calls=[]
        old=p.helper.router_call
        def wrapped(path,method,*args):
            calls.append(method)
            if method == 'getPeakValues':
                return [('Line/Out:01',2048),('Mixer/In:04',4095),
                        ('Mixer/In:02',1024),('Mixer/In:01',0),
                        ('Mixer/In:03', float('nan'))]
            return old(path,method,*args)
        p.helper.router_call=wrapped
        with contextlib.redirect_stdout(io.StringIO()):
            result=p.peak_snapshot()
            again=p.peak_snapshot()
        self.assertTrue(result['available'])
        self.assertEqual(result['guid'],p.guid)
        self.assertEqual(result['channels']['1']['destination'],'Mixer/In:02')
        self.assertAlmostEqual(result['channels']['1']['db'],-6.02,places=2)
        self.assertNotIn('2',result['channels'])
        self.assertTrue(result['channels']['3']['near_full_scale'])
        self.assertEqual(result['channels']['0']['level'],0)
        self.assertEqual(result['destination_levels']['Line/Out:01']['raw'],2048)
        self.assertEqual(calls.count('hasPeakMetering'),1)
        self.assertEqual(calls.count('getPeakValues'),2)
        self.assertTrue(again['available'])

    def test_no_backend_meter_for_unmapped_motu(self):
        p=self.fixture('motuultralite')
        self.assertIsNone(p.meter_spec)
        def failure(*args,**kwargs): raise AssertionError('Must not probe a router')
        p.helper.router_call=failure
        self.assertEqual(p.peak_snapshot()['channels'],{})
        self.assertFalse(p.peak_snapshot()['available'])

    def test_false_ffado_peak_capability_makes_no_read(self):
        p=self.fixture('profire2626')
        calls=[]
        def call(path,method,*args):
            calls.append(method)
            return False if method=='hasPeakMetering' else None
        p.helper.router_call=call
        self.assertFalse(p.peak_snapshot()['available'])
        self.assertFalse(p.peak_snapshot()['available'])
        self.assertEqual(calls,['hasPeakMetering'])

    def test_every_optional_peak_model_declares_source_format_and_mapping(self):
        root=Path(__file__).parents[1]/'ffado_webmixer'/'profiles'
        n=0
        for path in root.glob('*/*.xml'):
            if path.name in ('reference.xml','common.xml'):continue
            node=ET.parse(path).getroot()
            if node.tag != 'device' or node.find('capabilities') is None:continue
            caps=parse_capabilities(node)['features']['peak_metering']
            if caps['state'] not in ('mapped','optional'):
                continue
            n+=1
            self.assertEqual(caps['path'],'/EAP/Router',str(path))
            self.assertEqual(caps.get('format'),'dice_eap_peak12',str(path))
            self.assertEqual(caps.get('channel_map'),'matrix_input_router_destination',str(path))
        self.assertGreaterEqual(n,15)


if __name__=='__main__':unittest.main()
