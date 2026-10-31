-- Isolated external weather observations; does not mutate existing Open-Meteo measurements.
CREATE TABLE IF NOT EXISTS public.wu_weather_observations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    station_id text NOT NULL CHECK (station_id ~ '^[A-Za-z0-9_-]{3,40}$'),
    observed_at timestamptz NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    lat double precision CHECK (lat BETWEEN -90 AND 90),
    lon double precision CHECK (lon BETWEEN -180 AND 180),
    qc_status smallint CHECK (qc_status IN (-1,0,1)),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT uq_wu_station_observed UNIQUE(station_id, observed_at)
);
CREATE INDEX IF NOT EXISTS ix_wu_station_time ON public.wu_weather_observations(station_id, observed_at DESC);
