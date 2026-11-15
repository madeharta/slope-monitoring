import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent))
from scripts import gnss_auto_spp as mod

START = dt.datetime(2026, 11, 15, 3, 0, tzinfo=dt.timezone.utc)
END = START + dt.timedelta(hours=1)

class TestSPP(unittest.TestCase):
    def test_timezone_required(self):
        with self.assertRaisesRegex(ValueError, 'TIMEZONE_REQUIRED'):
            mod.parse_time('2026-11-15T03:00:00')

    def test_no_rows(self):
        with self.assertRaisesRegex(ValueError, 'RAWX_ROW_COUNT_INVALID'):
            mod.validate_rows([], 'BASE-01', START, END)

    def test_wrong_device(self):
        rows = [{'device_id':'ROVER-B1-01','time':START,'raw_payload_base64':'anything'}]
        with self.assertRaisesRegex(ValueError, 'RAWX_WRONG_DEVICE'):
            mod.validate_rows(rows, 'BASE-01', START, END)

    def test_future_rawx(self):
        rows = [{'device_id':'BASE-01','time':END,'raw_payload_base64':'anything'}]
        with self.assertRaisesRegex(ValueError, 'RAWX_TIMESTAMP_OUT_OF_WINDOW'):
            mod.validate_rows(rows, 'BASE-01', START, END)

    def test_valid_fixture_base(self):
        fixture = ROOT / 'tests' / 'fixtures' / 'gnss_BASE-01_20261115_1045.csv'
        if not fixture.exists():
            self.skipTest('uploaded RAWX fixture not installed')
        rows = mod.load_fixture(fixture)
        self.assertEqual(len(mod.validate_rows(rows,'BASE-01', START, END)),20)

    def test_output_requires_compatible_solution_times(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'solution.pos'
            p.write_text('2026/11/14 23:00:00.0 2.3 117.3 10 5 13\n')
            with self.assertRaisesRegex(ValueError, 'SPP_SOLUTIONS_OUTSIDE_RAWX_WINDOW'):
                mod.ensure_solution_window(p, START, END)

    def test_fail_closed_missing_binary(self):
        import argparse, tempfile
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(csv=Path(d)/'fixture.csv',dsn=None,expected_db=None,expected_role=None,
                since=START.isoformat(),until=END.isoformat(),base='BASE-01',convbin='missing',rnx2rtkp='missing',
                nav_cache=Path(d),state=Path(d)/'state.json',no_download=True,apply_local=False)
            with patch.object(mod,'load_fixture',return_value=[{'device_id':'BASE-01','time':START,
                'raw_payload_base64':'bad'}]*10):
                with self.assertRaises(ValueError):
                    mod.run(args)

if __name__ == '__main__':
    unittest.main()
