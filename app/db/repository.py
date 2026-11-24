"""Zero-ORM raw asyncpg PostgreSQL repository with bounding-box prefilter + exact Haversine SQL."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

BULK_INGEST_SQL = """
INSERT INTO geo_pings (device_hash, lat, lon, dwell_seconds, age_group, gender, income_tier, pinged_at)
SELECT * FROM UNNEST(
    $1::varchar[],
    $2::double precision[],
    $3::double precision[],
    $4::integer[],
    $5::varchar[],
    $6::varchar[],
    $7::varchar[],
    $8::timestamptz[]
)
"""

# Bounding-box degree approximation (~111.32 km/deg) prunes index before exact Haversine evaluation.
CAMPAIGN_SQL = """
WITH scoped_inventory AS (
    SELECT id, code, lat, lon, visibility_radius_m, min_dwell_seconds
    FROM ad_inventory
    WHERE code = ANY($1::varchar[])
),
contacts AS (
    SELECT
        p.device_hash,
        p.age_group,
        p.gender,
        p.income_tier,
        inv.code AS inventory_code
    FROM scoped_inventory inv
    INNER JOIN geo_pings p
        ON p.pinged_at BETWEEN $2 AND $3
       AND p.dwell_seconds >= inv.min_dwell_seconds
       AND p.lat BETWEEN inv.lat - (inv.visibility_radius_m / 111320.0)
                     AND inv.lat + (inv.visibility_radius_m / 111320.0)
       AND p.lon BETWEEN inv.lon - (inv.visibility_radius_m / (111320.0 * GREATEST(COS(RADIANS(inv.lat)), 0.1)))
                     AND inv.lon + (inv.visibility_radius_m / (111320.0 * GREATEST(COS(RADIANS(inv.lat)), 0.1)))
    WHERE (
        6371000.0 * 2.0 * ASIN(SQRT(
            POWER(SIN(RADIANS(p.lat - inv.lat) / 2.0), 2) +
            COS(RADIANS(inv.lat)) * COS(RADIANS(p.lat)) *
            POWER(SIN(RADIANS(p.lon - inv.lon) / 2.0), 2)
        ))
    ) <= inv.visibility_radius_m
),
dedup_devices AS (
    SELECT DISTINCT ON (device_hash)
        device_hash,
        age_group,
        gender,
        income_tier
    FROM contacts
),
totals AS (
    SELECT
        (SELECT COUNT(*)::bigint FROM contacts) AS ots,
        (SELECT COUNT(*)::bigint FROM dedup_devices) AS reach
),
age_breakdown AS (
    SELECT age_group, COUNT(*)::bigint AS cnt
    FROM dedup_devices
    GROUP BY age_group
)
SELECT
    t.ots,
    t.reach,
    CASE WHEN t.reach > 0 THEN ROUND(t.ots::numeric / t.reach, 2)::double precision ELSE 0.0 END AS frequency,
    COALESCE((SELECT json_object_agg(age_group, cnt) FROM age_breakdown), '{}'::json) AS age_counts
FROM totals t;
"""


class DmpRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def upsert_inventory(
        self,
        code: str,
        fmt: str,
        city: str,
        lat: float,
        lon: float,
        visibility_radius_m: float,
        min_dwell_seconds: int = 3,
    ) -> int:
        row = await self.pool.fetchrow(
            """
            INSERT INTO ad_inventory (code, format, city, lat, lon, visibility_radius_m, min_dwell_seconds)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (code) DO UPDATE SET
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                visibility_radius_m = EXCLUDED.visibility_radius_m,
                min_dwell_seconds = EXCLUDED.min_dwell_seconds
            RETURNING id
            """,
            code,
            fmt,
            city,
            lat,
            lon,
            visibility_radius_m,
            min_dwell_seconds,
        )
        return int(row["id"])

    async def bulk_ingest_pings(self, pings: list[dict[str, Any]]) -> int:
        if not pings:
            return 0
        await self.pool.execute(
            BULK_INGEST_SQL,
            [p["device_hash"] for p in pings],
            [float(p["lat"]) for p in pings],
            [float(p["lon"]) for p in pings],
            [int(p["dwell_seconds"]) for p in pings],
            [p["age_group"] for p in pings],
            [p["gender"] for p in pings],
            [p["income_tier"] for p in pings],
            [p["pinged_at"] for p in pings],
        )
        return len(pings)

    async def calculate_campaign(
        self,
        inventory_codes: list[str],
        since: datetime,
        until: datetime,
        target_population: int,
    ) -> dict[str, Any]:
        row = await self.pool.fetchrow(CAMPAIGN_SQL, inventory_codes, since, until)
        ots = int(row["ots"])
        reach = int(row["reach"])
        grp = (
            round((ots / target_population) * 100.0, 2)
            if target_population > 0
            else 0.0
        )
        return {
            "ots": ots,
            "reach": reach,
            "frequency": float(row["frequency"]),
            "grp": grp,
            "age_counts": row["age_counts"],
        }
