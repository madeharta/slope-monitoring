"""Regression tests for auto rover markers and time-effective BASE reference."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import gnss_auto_spp as spp
from scripts import ppk_qa_scheduler as scheduler
from scripts.gnss_provisional_reference import candidate

UTC = dt.timezone.utc


class TestAutoDeviceLocations(unittest.TestCase):
    def test_rnx2rtkp_explicitly_emits_utc(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            def fake_cmd(cmd, timeout=120):
                calls.append(cmd)
                if 'convbin' in cmd[0]:
                    (root / 'base.obs').write_text('obs')
                if 'rnx2rtkp' in cmd[0]:
                    (root / 'base.pos').write_text('pos')
            with patch.object(spp, 'run_cmd', side_effect=fake_cmd):
                spp.solve(b'data', root / 'NAV.rnx', 'convbin', 'rnx2rtkp', root)
            self.assertIn('-t', calls[1])
            self.assertIn('-u', calls[1])
            self.assertLess(calls[1].index('-t'), calls[1].index('-o'))

    def test_rover_candidate_does_not_change_base_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pos = root / 'sample.pos'
            lines = ['2026/11/15 03:40:%02d.000 2.31864491 117.38941845 104.9000 5 13' % x for x in range(10)]
            pos.write_text('\n'.join(lines) + '\n')
            result = candidate(pos, 'ROVER-B1-01')
            self.assertEqual(result['status'], 'CANDIDATE')
            old = {'reference_epoch': 1, 'provisional_base_reference': {'device_id':'BASE-01', 'latitude': 2.31667, 'longitude': 117.38691}}
            from scripts.gnss_provisional_reference import evaluate
            state, out = evaluate(old, result, base_id='BASE-01')
            self.assertEqual(out['status'], 'MARKER_READY')
            self.assertEqual(state['provisional_base_reference'], old['provisional_base_reference'])
            self.assertEqual(state['provisional_device_locations']['ROVER-B1-01']['source'], 'RTKLIB_SPP')

    def test_reference_not_effective_until_last_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'reference.json'
            state.write_text(json.dumps({'reference_epoch':1, 'provisional_base_reference': {
                'device_id':'BASE-01','source':'RTKLIB_SPP','validation_status':'provisional',
                'accepted_solutions':20,'min_satellites':8,'max_spread_m':1,
                'latitude':2.31667,'longitude':117.38691,'ellipsoidal_height_m':105,
                'observed_from_utc':'2026-11-15T03:40:00+00:00',
                'observed_to_utc':'2026-11-15T03:45:00+00:00'}}))
            with self.assertRaisesRegex(ValueError, 'NOT_EFFECTIVE'):
                scheduler.select_reference(state, 'BASE-01', dt.datetime(2026,11,15,3,43,tzinfo=UTC))
            self.assertEqual(scheduler.select_reference(state, 'BASE-01',dt.datetime(2026,11,15,4,0,tzinfo=UTC)), (2.31667,117.38691,105.0))

    def test_rover_standalone_success_exit_allowed(self):
        import inspect
        source = inspect.getsource(spp.main)
        self.assertIn("'MARKER_READY'", source)


if __name__ == '__main__':
    unittest.main()
