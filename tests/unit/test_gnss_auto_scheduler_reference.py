import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from ppk_qa_scheduler import select_reference, config_for_reference

UTC = dt.timezone.utc


def good():
    return {'reference_epoch': 1, 'provisional_base_reference': {
        'device_id': 'BASE-01', 'source': 'RTKLIB_SPP', 'validation_status': 'provisional',
        'latitude': 2.31667944, 'longitude': 117.38691939,
        'ellipsoidal_height_m': 15.25, 'accepted_solutions': 20,
        'min_satellites': 8, 'max_spread_m': 0.8,
        'observed_from_utc': '2026-11-15T03:40:04+00:00'}}


class TestAutoReference(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.json'
        self.at = dt.datetime(2026, 11, 15, 4, tzinfo=UTC)

    def select(self, data):
        self.path.write_text(json.dumps(data))
        return select_reference(self.path, 'BASE-01', self.at)

    def test_select(self):
        self.assertEqual(self.select(good()), (2.31667944,117.38691939,15.25))

    def test_missing(self):
        with self.assertRaisesRegex(ValueError, 'MISSING'):
            select_reference(self.path, 'BASE-01', self.at)

    def test_pending_relocation(self):
        data=good(); data['pending_base_relocation']={'latitude':3}
        with self.assertRaisesRegex(ValueError, 'RELOCATION_PENDING'):
            self.select(data)

    def test_future_reference(self):
        data=good(); data['provisional_base_reference']['observed_from_utc']='2026-11-16T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'NOT_EFFECTIVE'):
            self.select(data)

    def test_nonfinite_reference(self):
        data=good(); data['provisional_base_reference']['ellipsoidal_height_m']=float('nan')
        with self.assertRaisesRegex(ValueError, 'OUT_OF_RANGE'):
            self.select(data)

    def test_wrong_device_and_quality(self):
        data=good(); data['provisional_base_reference']['device_id']='ROVER-B1-02'
        with self.assertRaisesRegex(ValueError, 'BASE_MISMATCH'):
            self.select(data)
        data=good(); data['provisional_base_reference']['min_satellites']=4
        with self.assertRaisesRegex(ValueError, 'QUALITY_REJECTED'):
            self.select(data)

    def test_config_rewrite(self):
        source=Path(self.temp.name)/'base.conf'; target=Path(self.temp.name)/'scoped.conf'
        source.write_text('pos1-posmode =kinematic\npos1-soltype =forward\nant2-postype =llh\nant2-pos1 = -6.8 # lat\nant2-pos2 = 107.5\nant2-pos3 = 880.5\n')
        config_for_reference(source,target,(2.31667944,117.38691939,15.25))
        result=target.read_text()
        self.assertIn('ant2-pos1 = 2.3166794400 # lat',result)
        self.assertIn('ant2-pos2 = 117.3869193900',result)
        self.assertIn('ant2-pos3 = 15.2500000000',result)
        self.assertIn('ant2-pos1 = -6.8',source.read_text())

    def test_duplicate_config_rejected(self):
        source=Path(self.temp.name)/'base.conf'; target=Path(self.temp.name)/'scoped.conf'
        source.write_text('ant2-pos1 = 1\nant2-pos1 = 2\nant2-pos2 = 3\nant2-pos3 = 4\n')
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            config_for_reference(source,target,(1,2,3))

if __name__=='__main__': unittest.main()
