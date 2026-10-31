"""Weather Underground PWS current observations; credentials never logged."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import httpx

URL = 'https://api.weather.com/v2/pws/observations/current'
FIELDS = ('temp','dewpt','heatIndex','windChill','windSpeed','windGust','pressure','precipRate','precipTotal','elev')

class WUError(Exception):
    pass

def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    return v if math.isfinite(v) else None

def normalize(body: dict, station_id: str) -> dict:
    observations = body.get('observations')
    if not isinstance(observations,list) or not observations or not isinstance(observations[0],dict):
        raise WUError('No current observation returned')
    raw = observations[0]
    if raw.get('stationID','').upper() != station_id.upper():
        raise WUError('Unexpected station ID')
    try:
        dt = datetime.fromisoformat(raw['obsTimeUtc'].replace('Z','+00:00'))
        if dt.tzinfo is None:
            raise ValueError('missing UTC zone')
        observed = dt.astimezone(timezone.utc)
    except (KeyError, ValueError, AttributeError) as exc:
        raise WUError('Invalid observation timestamp') from exc
    if observed > datetime.now(timezone.utc).replace(microsecond=0):
        # Accommodate modest clock drift but not future dated payloads.
        from datetime import timedelta
        if observed - datetime.now(timezone.utc) > timedelta(minutes=5):
            raise WUError('Observation timestamp in future')
    metric = raw.get('metric')
    if not isinstance(metric,dict):
        raise WUError('Missing metric measurements')
    values = {key: numeric(metric.get(key)) for key in FIELDS}
    values.update({
        'humidity': numeric(raw.get('humidity')),
        'winddir': numeric(raw.get('winddir')),
        'solarRadiation': numeric(raw.get('solarRadiation')),
        'uv': numeric(raw.get('uv')),
    })
    lat, lon = numeric(raw.get('lat')), numeric(raw.get('lon'))
    if lat is not None and not (-90 <= lat <= 90): raise WUError('Invalid latitude')
    if lon is not None and not (-180 <= lon <= 180): raise WUError('Invalid longitude')
    qc = raw.get('qcStatus')
    if qc is not None and qc not in (-1,0,1): raise WUError('Invalid QC status')
    return {'station_id':station_id,'observed_at':observed,'lat':lat,'lon':lon,
            'qc_status':qc,'values':values}

async def fetch_current(station_id: str, api_key: str) -> dict:
    if not api_key: raise WUError('WU API key not configured')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0),follow_redirects=False) as client:
            response = await client.get(URL,params={'stationId':station_id,'format':'json','units':'m',
                                                      'numericPrecision':'decimal','apiKey':api_key})
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Do not leak exception string: request URLs may embed API key.
        raise WUError('WU API request failed (details intentionally hidden)') from None
    return normalize(body,station_id)
