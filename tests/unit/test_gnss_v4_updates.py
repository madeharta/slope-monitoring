import datetime as dt
import unittest
from unittest.mock import patch
from scripts.gnss_provisional_reference import evaluate


def observation(device, minute, lat=2.31667553, lon=117.3869197):
    t = dt.datetime(2026,11,15,3,0,tzinfo=dt.timezone.utc)+dt.timedelta(minutes=minute)
    return dict(device_id=device, status='CANDIDATE', latitude=lat, longitude=lon,
                ellipsoidal_height_m=105, source='RTKLIB_SPP', validation_status='provisional',
                accepted_solutions=200, min_satellites=8, max_spread_m=1,
                observed_from_utc=(t-dt.timedelta(minutes=5)).isoformat(), observed_to_utc=t.isoformat())

class TestLocationUpdates(unittest.TestCase):
    def test_rover_marker_updates_and_reference_does_not(self):
        state, _ = evaluate({},observation('BASE-01',0))
        base=state['provisional_base_reference'].copy()
        state,_ =evaluate(state,observation('ROVER-B1-02',20,2.31777,117.38761))
        state,result=evaluate(state,observation('ROVER-B1-02',40,2.318,117.388))
        self.assertEqual(result['status'],'MARKER_READY')
        self.assertEqual(state['provisional_device_locations']['ROVER-B1-02']['latitude'],2.318)
        self.assertEqual(state['provisional_base_reference'],base)
    def test_out_of_order_position_never_overwrites(self):
        state,_=evaluate({},observation('ROVER-B1-02',40))
        state,result=evaluate(state,observation('ROVER-B1-02',20,4,120))
        self.assertEqual(result['status'],'STALE_OBSERVATION_IGNORED')
        self.assertAlmostEqual(state['provisional_device_locations']['ROVER-B1-02']['latitude'],2.31667553)
    def test_base_same_location_no_rebaseline(self):
        state,_=evaluate({},observation('BASE-01',0))
        state,result=evaluate(state,observation('BASE-01',40,2.31668,117.38692))
        self.assertEqual(result['status'],'REFERENCE_UNCHANGED')
        self.assertEqual(state['reference_epoch'],1)
    def test_auto_relocation_needs_three_spaced_windows(self):
        state,_=evaluate({},observation('BASE-01',0))
        for i,t in enumerate((40,80,120),1):
            state,out=evaluate(state,observation('BASE-01',t,3.3166755,117.3869197))
            self.assertEqual(state['reference_epoch'],2 if i==3 else 1)
        self.assertEqual(out['status'],'REFERENCE_RELOCATED_AUTOMATICALLY')
        self.assertEqual(len(state['reference_history']),2)
        self.assertEqual(state['displacement_baseline_status'],'REQUIRES_NEW_EPOCH_BASELINE_QA')
        self.assertNotIn('pending_base_relocation',state)
    def test_repeated_window_does_not_confirm_relocation(self):
        state,_=evaluate({},observation('BASE-01',0))
        for i in range(4):
            state,_=evaluate(state,observation('BASE-01',40,3.3166755,117.3869197))
        self.assertEqual(state['reference_epoch'],1)
    def test_inconsistent_relocation_resets_confirmation(self):
        state,_=evaluate({},observation('BASE-01',0))
        state,_=evaluate(state,observation('BASE-01',40,3.3166755,117.3869197))
        state,out=evaluate(state,observation('BASE-01',80,4.3166755,117.3869197))
        self.assertEqual(out['confirmation_windows'],1)
        self.assertEqual(state['reference_epoch'],1)
    def test_unstable_solution_does_not_update_marker(self):
        state,_=evaluate({},observation('ROVER-B1-01',0))
        bad=observation('ROVER-B1-01',40,6,110)
        bad['status']='HOLD_UNSTABLE_SPP'
        state,_=evaluate(state,bad)
        self.assertAlmostEqual(state['provisional_device_locations']['ROVER-B1-01']['latitude'],2.31667553)

if __name__=='__main__':unittest.main()
