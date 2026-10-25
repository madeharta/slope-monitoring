from datetime import datetime, timezone, timedelta
import pytest
from services.weather_service.wu_client import normalize, WUError

def sample():
    return {'observations':[{'stationID':'IBANDU103','obsTimeUtc':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),
            'lat':-6.876,'lon':107.664,'humidity':87,'winddir':91,'qcStatus':1,
            'metric':{'temp':21.1,'dewpt':18.9,'windSpeed':0,'windGust':1.6,
                      'pressure':1015.21,'precipRate':0,'precipTotal':0.51}}]}

def test_normalize_metric():
    n=normalize(sample(),'IBANDU103')
    assert n['values']['temp']==21.1
    assert n['values']['precipTotal']==0.51
    assert n['observed_at'].tzinfo is not None
    assert n['values']['humidity']==87

def test_empty():
    with pytest.raises(WUError):normalize({'observations':[]},'IBANDU103')

def test_bad_station():
    p=sample();p['observations'][0]['stationID']='OTHER'
    with pytest.raises(WUError):normalize(p,'IBANDU103')

def test_no_key():
    from services.weather_service.wu_client import fetch_current
    import asyncio
    with pytest.raises(WUError):asyncio.run(fetch_current('IBANDU103',''))
