CREATE TABLE IF NOT EXISTS ad_inventory (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    format VARCHAR(32) NOT NULL, -- 'outdoor_billboard' | 'indoor_screen' | 'digital_superboard'
    city VARCHAR(64) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    visibility_radius_m DOUBLE PRECISION NOT NULL CHECK (visibility_radius_m > 0),
    min_dwell_seconds INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS geo_pings (
    id BIGSERIAL PRIMARY KEY,
    device_hash VARCHAR(64) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    dwell_seconds INTEGER NOT NULL DEFAULT 0,
    age_group VARCHAR(16) NOT NULL, -- '18-24' | '25-34' | '35-44' | '45+'
    gender VARCHAR(8) NOT NULL,     -- 'M' | 'F'
    income_tier VARCHAR(16) NOT NULL, -- 'mass' | 'middle' | 'affluent'
    pinged_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_geo_pings_coords_time ON geo_pings (lat, lon, pinged_at);
CREATE INDEX IF NOT EXISTS idx_geo_pings_device_time ON geo_pings (device_hash, pinged_at);
