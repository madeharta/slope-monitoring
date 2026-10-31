CREATE TABLE IF NOT EXISTS public.blast_trigger_timeout_events (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    expired_at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL CHECK (reason = 'TIMEOUT_EXPIRED'),
    UNIQUE (device_id, started_at)
);
CREATE INDEX IF NOT EXISTS blast_trigger_timeout_events_expired_idx
    ON public.blast_trigger_timeout_events (expired_at DESC);
