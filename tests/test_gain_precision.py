"""Source-aligned, hardware-free gain precision tests.

FFADO's matrixmixer.py uses 16384 for unity, <=16 as its silent
sentinel, and -60..+6 dB as the Qt matrix editor range.
"""
import contextlib
import io
import math
import unittest
from pathlib import Path

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.gain import (UNITY, scale, raw_to_db, db_to_raw,
                                 raw_to_ui, ui_to_raw)


class NativeGainConversions(unittest.TestCase):
    def test_unity_is_exact(self):
        for family in ('dice_db','rme_db'):
            with self.subTest(family=family):
                self.assertEqual(db_to_raw(0, family), UNITY)
                self.assertAlmostEqual(raw_to_db(UNITY, family), 0, places=9)
                self.assertAlmostEqual(raw_to_ui(UNITY, family), 60/66*100, places=4)

    def test_silence_is_not_negative_sixty_db(self):
        for family in ('dice_db','rme_db'):
            self.assertEqual(db_to_raw(None, family), 0)
            self.assertEqual(db_to_raw(-60, family), 0)
            self.assertIsNone(raw_to_db(16, family))
            self.assertIsNone(raw_to_db(0, family))
            self.assertIsNone(raw_to_db(ui_to_raw(0, family), family))

    def test_tenth_db_steps_preserved_to_native_resolution(self):
        for family in ('dice_db','rme_db'):
            for db in (-50.0,-30.7,-20,-12.3,-6.1,-0.1,0,0.1,3.2,6):
                with self.subTest(family=family, db=db):
                    actual=raw_to_db(db_to_raw(db,family),family)
                    self.assertAlmostEqual(actual,db,delta=0.04)
                    pct=raw_to_ui(db_to_raw(db,family),family)
                    self.assertAlmostEqual(pct, (db + 60)*100/66, delta=0.09)

    def test_legacy_percentage_protocol_accepts_fraction(self):
        for family in ('dice_db','rme_db'):
            for pct in (22.5, 50.25, 91.12345):
                with self.subTest(family=family,pct=pct):
                    self.assertAlmostEqual(raw_to_ui(ui_to_raw(pct,family),family),pct,delta=0.09)

    def test_native_limits_and_input_validation(self):
        self.assertEqual(scale('dice_db')['native_max'],65535)
        self.assertEqual(scale('rme_db')['native_max'],32768)
        self.assertEqual(scale('dice_db')['step_db'],0.1)
        self.assertIsNone(scale('linear'))
        for bad in (-61,6.01,float('nan'),float('inf')):
            with self.assertRaises(ValueError): db_to_raw(bad,'dice_db')
        for bad in (-1,101,float('nan')):
            with self.assertRaises(ValueError): ui_to_raw(bad,'dice_db')
        with self.assertRaises(ValueError): raw_to_db(32769,'rme_db')

    def test_native_values_above_ui_limit_are_not_misreported(self):
        # DICE can encode 65535 despite FFADO's gain editor limiting +6.
        self.assertGreater(raw_to_db(65535,'dice_db'),12)
        self.assertEqual(raw_to_ui(65535,'dice_db'),100)


class MatrixDbWrites(unittest.TestCase):
    def mixer(self,name='profire2626'):
        with contextlib.redirect_stdout(io.StringIO()):
            return make_debug_mixer(name, Config(None))

    def test_snapshot_contains_real_db_and_preserves_legacy_values(self):
        mixer=self.mixer()
        with contextlib.redirect_stdout(io.StringIO()):
            data=mixer.matrix_snapshot()
        self.assertEqual(data['gain_scale']['unity'],UNITY)
        self.assertEqual(data['mode'],'dice_db')
        self.assertAlmostEqual(data['db_values'][0][0],0,places=3)
        self.assertAlmostEqual(data['values'][0][0],90.90909,places=4)

    def test_matrix_exact_db_write_uses_native_coefficient_and_readback(self):
        mixer=self.mixer()
        output=3; input_=2
        with contextlib.redirect_stdout(io.StringIO()) as tracing:
            result=mixer.matrix_set(input_,output,db=-11.7,use_db=True)
        self.assertEqual(mixer.helper.cells[(mixer.roles['fader'][0],input_,output)],db_to_raw(-11.7,'dice_db'))
        self.assertAlmostEqual(result['db'],-11.7,delta=0.04)
        self.assertFalse(result['deferred'])
        self.assertEqual(result['native'],db_to_raw(-11.7,'dice_db'))
        self.assertIn('MatrixMixer.setValue',tracing.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            snapshot=mixer.matrix_snapshot()
        self.assertAlmostEqual(snapshot['db_values'][input_][output],-11.7,delta=0.04)

    def test_matrix_silence_and_legacy_percentage(self):
        mixer=self.mixer()
        with contextlib.redirect_stdout(io.StringIO()):
            silent=mixer.matrix_set(0,0,db=None,use_db=True)
            self.assertEqual(silent['native'],0)
            self.assertIsNone(silent['db'])
            legacy=mixer.matrix_set(0,0,50.125)
            self.assertAlmostEqual(legacy['value'],50.125,delta=0.09)

    def test_matrix_gain_edits_while_software_muted_preserve_hardware_silence(self):
        mixer=self.mixer()
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.write(0,'ch/00','mute',True)
            result=mixer.matrix_set(0,0,db=-7.3,use_db=True)
            self.assertEqual(mixer._get_cell(mixer.roles['fader'][0],0,0),0)
            self.assertAlmostEqual(result['db'],-7.3,delta=0.04)
            self.assertTrue(result['deferred'])
            mixer.write(0,'ch/00','mute',False)
            self.assertAlmostEqual(raw_to_db(mixer._get_cell(mixer.roles['fader'][0],0,0),'dice_db'),-7.3,delta=0.04)

    def test_matrix_rejects_invalid_db_without_hardware_write(self):
        mixer=self.mixer()
        before=dict(mixer.helper.cells)
        for invalid in (6.1, -60.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                mixer.matrix_set(0,0,db=invalid,use_db=True)
        self.assertEqual(mixer.helper.cells,before)

    def test_motu_refuses_db_mode_and_keeps_legacy_matrix_control(self):
        mixer=self.mixer('motuultralite')
        with self.assertRaises(ValueError): mixer.matrix_set(0,0,db=0,use_db=True)
        with contextlib.redirect_stdout(io.StringIO()):
            data=mixer.matrix_snapshot()
        self.assertNotIn('db_values',data)
        self.assertNotIn('gain_scale',data)
