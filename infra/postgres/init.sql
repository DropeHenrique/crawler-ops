-- Simula o RDS (PostgreSQL) da plataforma de captura.
CREATE DATABASE airflow;

\connect crawlerops

CREATE TABLE capture_runs (
    id             BIGSERIAL PRIMARY KEY,
    job_id         TEXT        NOT NULL,
    batch_id       TEXT        NOT NULL,
    source         TEXT        NOT NULL,
    target_url     TEXT        NOT NULL,
    status         TEXT        NOT NULL CHECK (status IN ('success', 'failed')),
    terminal       BOOLEAN     NOT NULL,
    error_type     TEXT,
    error_message  TEXT,
    attempt        INT         NOT NULL DEFAULT 1,
    items_count    INT         NOT NULL DEFAULT 0,
    invalid_items  INT         NOT NULL DEFAULT 0,
    duration_ms    INT         NOT NULL,
    http_status    INT,
    s3_raw_key     TEXT,
    s3_data_key    TEXT,
    worker_id      TEXT,
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX capture_runs_source_finished_idx ON capture_runs (source, finished_at DESC);
CREATE INDEX capture_runs_batch_idx ON capture_runs (batch_id);

CREATE TABLE incidents (
    id                BIGSERIAL PRIMARY KEY,
    fingerprint       TEXT        NOT NULL,
    source            TEXT        NOT NULL,
    rule              TEXT        NOT NULL,
    severity          TEXT        NOT NULL CHECK (severity IN ('P1', 'P2', 'P3')),
    status            TEXT        NOT NULL CHECK (status IN ('open', 'acknowledged', 'resolved')),
    title             TEXT        NOT NULL,
    details           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    auto_resolve      BOOLEAN     NOT NULL DEFAULT TRUE,
    occurrences       INT         NOT NULL DEFAULT 1,
    opened_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at   TIMESTAMPTZ,
    resolved_at       TIMESTAMPTZ,
    response_due_at   TIMESTAMPTZ NOT NULL,
    resolution_due_at TIMESTAMPTZ NOT NULL,
    resolved_by       TEXT,
    resolution_notes  TEXT
);

-- Garante no máximo um incidente ativo por fingerprint (deduplicação de alertas).
CREATE UNIQUE INDEX incidents_active_fingerprint_idx
    ON incidents (fingerprint) WHERE status <> 'resolved';

CREATE TABLE incident_events (
    id          BIGSERIAL PRIMARY KEY,
    incident_id BIGINT      NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    kind        TEXT        NOT NULL,
    message     TEXT        NOT NULL,
    author      TEXT        NOT NULL DEFAULT 'system',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX incident_events_incident_idx ON incident_events (incident_id, created_at);
