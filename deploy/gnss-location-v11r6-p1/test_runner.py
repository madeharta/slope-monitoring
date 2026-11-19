import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile, json
import subprocess
import runner

class RunnerTest(unittest.TestCase):
    def row(self, device, hour, minute):
        import datetime as d
        a=d.datetime(2026,11,19,hour,minute,tzinfo=d.timezone.utc)
        return [device,a.isoformat(),(a+d.timedelta(minutes=5)).isoformat(),20]
    def test_delayed_rover_and_order(self):
        a=self.row('ROVER-B1-02',11,45); b=self.row('BASE-01',13,50); c=self.row('ROVER-B1-02',11,40)
        self.assertEqual(runner.windows_to_process([a,b,c],{}),[tuple(b),tuple(c),tuple(a)])
    def test_accepted_window_not_replayed(self):
        a=self.row('BASE-01',13,45); b=self.row('BASE-01',13,50)
        s={'provisional_device_locations':{'BASE-01':{'observed_to_utc':'2026-11-19T13:49:51+00:00'}}}
        self.assertEqual(runner.windows_to_process([a,b],s),[tuple(b)])
    def test_pending_window_not_replayed(self):
        a=self.row('ROVER-B1-02',11,40); b=self.row('ROVER-B1-02',11,45)
        s={'pending_device_relocations':{'ROVER-B1-02':{'observations':[{'observed_to_utc':'2026-11-19T11:44:51+00:00'}]}}}
        self.assertEqual(runner.windows_to_process([a,b],s),[tuple(b)])
    def test_missing_state_with_db_rows_blocks(self):
        with tempfile.TemporaryDirectory() as p, patch.object(runner,'STATE',Path(p)), patch.object(runner,'docker',return_value=subprocess.CompletedProcess([],0,'[1,1]','')):
            with self.assertRaisesRegex(RuntimeError,'STATE_MISSING'): runner.cycle('src','writer')
    def test_network_credentials_separated_and_publish(self):
        with tempfile.TemporaryDirectory() as p, patch.object(runner,'STATE',Path(p)):
            calls=[]
            def fake(args,**kw):
                calls.append((args,kw)); result=''
                if args[0]=='-c' and args[1]==runner.DB_CODE: result='[0,0]'
                elif args[0]=='-c' and args[1]==runner.SELECT_CODE: result=json.dumps([self.row('ROVER-B1-02',11,45)])
                elif args[0]=='-c' and args[1]==runner.NAV_CODE: result='NAV_READY'
                elif args[0].endswith('gnss_auto_spp.py'):
                    (Path(p)/'locations.json').write_text(json.dumps({'provisional_device_locations':{'ROVER-B1-02':{}}}))
                    result=json.dumps({'device_id':'ROVER-B1-02','quality_gate_passed':True,'status':'MARKER_READY'})
                elif args[0].endswith('publish_gnss_locations.py'): result=json.dumps({'mode':'APPLIED','validated_device_ids':['ROVER-B1-02'],'device_ids':['ROVER-B1-02']})
                else: self.fail('unexpected job')
                return subprocess.CompletedProcess([],0,result,'')
            with patch.object(runner,'docker',side_effect=fake): runner.cycle('src','writer')
            self.assertEqual(calls[2][1]['network'],'bridge'); self.assertNotIn('env',calls[2][1]); self.assertEqual(calls[3][1]['env'],'src'); self.assertIn('--no-download',calls[3][0]); self.assertEqual(calls[4][1]['env'],'writer')
    def test_hold_no_publish_without_state(self):
        with tempfile.TemporaryDirectory() as p, patch.object(runner,'STATE',Path(p)), patch.object(runner,'docker',side_effect=[subprocess.CompletedProcess([],0,'[0,0]',''),subprocess.CompletedProcess([],0,json.dumps([self.row('BASE-01',13,50)]),''),subprocess.CompletedProcess([],1,'','')]) as mock:
            runner.cycle('src','writer'); self.assertEqual(mock.call_count,3)
if __name__=='__main__': unittest.main()
