import unittest
from datetime import datetime, timedelta, timezone
from scripts.publish_gnss_locations import parse_marker, UPSERT

class TestLocationPublish(unittest.TestCase):
    def marker(self, **override):
        result = {'latitude': 2.3, 'longitude': 117.3, 'source':'RTKLIB_SPP',
                  'observed_to_utc': (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),
                  'accepted_solutions':20, 'min_satellites':8, 'max_spread_m':0.8,
                  'ellipsoidal_height_m':105}
        result.update(override)
        return result
    def test_accept(self):
        self.assertEqual(parse_marker('BASE-01',self.marker())[0],'BASE-01')
    def test_reject_zero(self):
        with self.assertRaises(ValueError): parse_marker('BASE-01', self.marker(latitude=0, longitude=0))
    def test_reject_future(self):
        with self.assertRaises(ValueError): parse_marker('BASE-01', self.marker(observed_to_utc=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
    def test_reject_insufficient(self):
        with self.assertRaises(ValueError): parse_marker('BASE-01',self.marker(accepted_solutions=2))
    def test_reject_bad_source(self):
        with self.assertRaises(ValueError): parse_marker('BASE-01',self.marker(source='UNKNOWN'))
    def test_reject_bad_spread(self):
        with self.assertRaises(ValueError): parse_marker('BASE-01',self.marker(max_spread_m=1000))
    def test_monotonic_upsert(self):
        self.assertIn('observed_at < EXCLUDED.observed_at',UPSERT)
