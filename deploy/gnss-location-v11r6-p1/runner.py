#!/usr/bin/env python3
"""Independent operational marker runner. No PPK, site or alarm writes."""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote

ROOT = Path('/opt/landslidemon/releases/gnss-location-c560bc0')
RUNTIME = ROOT / 'runtime'
STATE = Path('/var/lib/magris-gnss-location-v11r6-p1')
NAV = STATE / 'nav'
IMAGE = 'landslidemon-ppk-qa:gnss-8b7321e-psycopg'
NETWORK = 'landslidemon_db_internal'
DEVICES = ('BASE-01', 'ROVER-B1-01', 'ROVER-B1-02')
SOURCE = Path('/etc/landslidemon/secrets/ppk_qa_source_reader_password')
WRITER = Path('/opt/landslidemon/gnss-secrets/location_publisher_password')
UTC = dt.timezone.utc
SELECT = '''
WITH bounds AS (SELECT to_timestamp(floor(extract(epoch FROM now()-interval '2 minutes')/300)*300) cutoff),
w AS (SELECT device_id, to_timestamp(floor(extract(epoch FROM time)/300)*300) AS start,
 count(DISTINCT time) AS epochs FROM public.gnss_raw_samples, bounds
WHERE time >= cutoff-interval '24 hours' AND time < cutoff
AND device_id IN ('BASE-01','ROVER-B1-01','ROVER-B1-02') GROUP BY 1,2 HAVING count(DISTINCT time)>=8),
r AS (SELECT *,row_number() OVER(PARTITION BY device_id ORDER BY start DESC) rn FROM w)
SELECT device_id,start,start+interval '5 minutes',epochs FROM r WHERE rn<=3 ORDER BY device_id,start
'''
SELECT_CODE = '''import os,json,sys,psycopg
with psycopg.connect(os.environ['PPK_QA_SOURCE_DATABASE_URL'],connect_timeout=15) as c:
 c.execute('SET TRANSACTION READ ONLY')
 c.execute("SET LOCAL statement_timeout='60s'")
 assert c.execute('SELECT current_database(),current_user').fetchone()==('slope_iot','ppk_qa_source_reader')
 rows=c.execute(sys.argv[1]).fetchall()
 print(json.dumps([[d,s.isoformat(),e.isoformat(),n] for d,s,e,n in rows]))
'''
NAV_CODE = '''import sys
from datetime import datetime
from pathlib import Path
from scripts.ppk_qa_scheduler import nav_for
p,n,d=nav_for(datetime.fromisoformat(sys.argv[1]),datetime.fromisoformat(sys.argv[2]),Path('/nav'),True)
assert p.is_file() and n>0
print('NAV_READY')
'''
DB_CODE = '''import os,json,psycopg
with psycopg.connect(os.environ['MAGRIS_GNSS_LOCATION_WRITER_DSN'],connect_timeout=15) as c:
 c.execute('SET TRANSACTION READ ONLY')
 assert c.execute('SELECT current_database(),current_user').fetchone()==('slope_iot','gnss_location_publisher')
 print(json.dumps([c.execute('SELECT count(*) FROM public.'+t).fetchone()[0] for t in ('gnss_device_operational_locations','gnss_operational_location_epochs')]))
'''

def envfile(path, key, role, secret):
    if not secret.is_file() or secret.is_symlink() or secret.stat().st_mode & 0o077:
        raise RuntimeError('SECRET_PERMISSIONS')
    value=secret.read_text().strip()
    if len(value)<40 or any(x in value for x in ('\n','\r','\x00')):
        raise RuntimeError('SECRET_INVALID')
    with path.open('x') as f:
        f.write(f'{key}=postgresql://{role}:{quote(value,safe="")}@landslidemon-db:5432/slope_iot\n')
        if role=='ppk_qa_source_reader':
            f.write('PPK_QA_SOURCE_DB_NAME=slope_iot\nPPK_QA_SOURCE_DB_ROLE=ppk_qa_source_reader\n')
    return path

def docker(args, *, network, env=None, state=False, timeout=180):
    name=f'magris-gnss-location-job-{os.getpid()}'
    cmd=['docker','run','--rm','--pull','never','--name',name,'--network',network,
         '--mount',f'type=bind,src={RUNTIME},dst=/workspace,readonly',
         '--workdir','/workspace','--env','PYTHONPATH=/workspace']
    if env: cmd+=['--env-file',str(env)]
    if state: cmd+=['--mount',f'type=bind,src={STATE},dst=/state']
    cmd+=['--mount',f'type=bind,src={NAV},dst=/nav','--entrypoint','python',IMAGE,*args]
    try:
        return subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=30)
        raise

def output(result):
    if result.returncode: raise RuntimeError('JOB_FAILED')
    return json.loads(result.stdout.strip().splitlines()[-1])

def windows_to_process(rows, state):
    """Do not replay already accepted or pending observation windows."""
    selected=[]
    for device,start,end,count in rows:
        if device not in DEVICES or count<8: raise ValueError('WINDOW_INVALID')
        a,b=dt.datetime.fromisoformat(start),dt.datetime.fromisoformat(end)
        if a.tzinfo is None or b-a!=dt.timedelta(minutes=5): raise ValueError('WINDOW_INVALID')
        prior=state.get('provisional_device_locations',{}).get(device,{})
        pending=state.get('pending_device_relocations',{}).get(device,{}).get('observations',[])
        stamps=[x['observed_to_utc'] for x in [prior,*pending] if x.get('observed_to_utc')]
        # Accepted solution timestamps are inside their five-minute window.
        # Skip the entire prior window, even if delayed rows later arrive in it.
        if stamps and a<=max(dt.datetime.fromisoformat(t.replace('Z','+00:00')) for t in stamps):
            continue
        selected.append((device,start,end,count))
    return sorted(selected,key=lambda row:(DEVICES.index(row[0]),dt.datetime.fromisoformat(row[1])))

def cycle(src, writer):
    path=STATE/'locations.json'
    if not path.is_file():
        if output(docker(['-c',DB_CODE],network=NETWORK,env=writer)) != [0,0]:
            raise RuntimeError('STATE_MISSING_WITH_PUBLISHED_DATA')
    data=json.loads(path.read_text()) if path.is_file() else {}
    rows=output(docker(['-c',SELECT_CODE,SELECT],network=NETWORK,env=src))
    for device,start,end,count in windows_to_process(rows,data):
        nav=docker(['-c',NAV_CODE,start,end],network='bridge',timeout=240)
        if nav.returncode or nav.stdout.strip().splitlines()[-1:]!=['NAV_READY']:
            print(f'{device} {start} NAV_HOLD',flush=True); continue
        result=docker(['scripts/gnss_auto_spp.py','--base',device,'--reference-base','BASE-01',
                       '--since',start,'--until',end,'--state','/state/locations.json','--nav-cache','/nav',
                       '--no-download','--apply-local'],network=NETWORK,env=src,state=True)
        if result.returncode:
            print(f'{device} {start} SPP_HOLD',flush=True); continue
        rec=output(result)
        allowed={'REFERENCE_INITIALIZED_PROVISIONAL','REFERENCE_UNCHANGED','REFERENCE_RELOCATED_AUTOMATICALLY','MARKER_READY','STALE_OBSERVATION_IGNORED','RELOCATION_CONFIRMING'}
        if rec.get('device_id')!=device or rec.get('quality_gate_passed') is not True or rec.get('status') not in allowed:
            raise RuntimeError('SPP_CONTRACT')
        print(f'{device} {start} {rec["status"]}',flush=True)
    data=json.loads(path.read_text()) if path.is_file() else {}
    if not data.get('provisional_device_locations'):
        print('GNSS_CYCLE=WAITING_INPUT_OR_NAV',flush=True); return
    rec=output(docker(['scripts/publish_gnss_locations.py','--state','/state/locations.json','--apply'],network=NETWORK,env=writer,state=True))
    if rec.get('mode')!='APPLIED' or not rec.get('validated_device_ids'):
        raise RuntimeError('PUBLISH_CONTRACT')
    updated=rec.get('device_ids',[])
    if any(d not in DEVICES for d in updated): raise RuntimeError('PUBLISH_CONTRACT')
    print('GNSS_PUBLISHED_NEW='+','.join(updated),flush=True)
    print('GNSS_CYCLE=COMPLETE',flush=True)

def main():
    os.umask(0o077)
    if os.environ.get('MAGRIS_GNSS_LOCATION_ENABLE')!='true': raise RuntimeError('DISABLED')
    if os.environ.get('OPERATIONAL_ALARMS_ENABLED')!='false': raise RuntimeError('ALARMS_GUARD')
    if not RUNTIME.is_dir(): raise RuntimeError('RUNTIME_MISSING')
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    NAV.mkdir(mode=0o700,exist_ok=True)
    if any(p.is_symlink() or p.stat().st_mode & 0o077 for p in (STATE,NAV)):
        raise RuntimeError('STATE_PERMISSIONS')
    with (STATE/'cycle.lock').open('ab') as lock:
        try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('GNSS_CYCLE=ALREADY_RUNNING',flush=True); return
        with tempfile.TemporaryDirectory(prefix='magris-location-',dir='/run') as tmp:
            src=envfile(Path(tmp)/'source.env','PPK_QA_SOURCE_DATABASE_URL','ppk_qa_source_reader',SOURCE)
            writer=envfile(Path(tmp)/'writer.env','MAGRIS_GNSS_LOCATION_WRITER_DSN','gnss_location_publisher',WRITER)
            cycle(src,writer)

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('GNSS_CYCLE=BLOCKED '+type(exc).__name__,flush=True)
        raise SystemExit(2)
