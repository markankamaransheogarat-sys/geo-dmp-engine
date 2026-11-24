"""Control-example verification and PostgreSQL asyncpg integration tests for Geo DMP Engine."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
import pytest

from app.api.main import app
from app.db.repository import DmpRepository
from app.services.geo_math import (
    GeoPing,
    InventoryPoint,
    calculate_campaign_metrics,
    haversine_meters,
)


def test_haversine_known_distance():
    # Red Square -> Bolshoi Theatre (~500-650m)
    dist = haversine_meters(55.7539, 37.6208, 55.7601, 37.6186)
    assert 650.0 <= dist <= 750.0


def test_campaign_metrics_on_control_dataset():
    inv = [
        InventoryPoint(
            code="MSK_BILLBOARD_01",
            lat=55.7558,
            lon=37.6173,
            visibility_radius_m=150.0,
            min_dwell_seconds=5,
        ),
    ]
    pings = [
        # Valid contact 1 (device A, ~0m)
        GeoPing(
            device_hash="dev_A",
            lat=55.7558,
            lon=37.6173,
            dwell_seconds=10,
            age_group="25-34",
            gender="M",
            income_tier="affluent",
        ),
        # Repeat contact 2 for device A (~30m away) -> OTS=2, Reach still=1
        GeoPing(
            device_hash="dev_A",
            lat=55.7560,
            lon=37.6175,
            dwell_seconds=6,
            age_group="25-34",
            gender="M",
            income_tier="affluent",
        ),
        # Valid contact 3 (device B, ~50m away)
        GeoPing(
            device_hash="dev_B",
            lat=55.7562,
            lon=37.6173,
            dwell_seconds=8,
            age_group="35-44",
            gender="F",
            income_tier="middle",
        ),
        # Filtered out: dwell too short (2s < 5s)
        GeoPing(
            device_hash="dev_C",
            lat=55.7558,
            lon=37.6173,
            dwell_seconds=2,
            age_group="18-24",
            gender="F",
            income_tier="mass",
        ),
        # Filtered out: outside 150m visibility radius (~1.1km away)
        GeoPing(
            device_hash="dev_D",
            lat=55.7658,
            lon=37.6173,
            dwell_seconds=30,
            age_group="45+",
            gender="M",
            income_tier="mass",
        ),
    ]

    report = calculate_campaign_metrics(
        inventories=inv,
        pings=pings,
        target_population=10_000,
        baseline_age_share={"25-34": 25.0, "35-44": 25.0},
    )

    assert report.ots == 3
    assert report.reach == 2
    assert report.frequency == 1.5
    assert report.grp == 0.03
    assert report.age_distribution_pct == {"25-34": 50.0, "35-44": 50.0}
    assert report.affinity_index == {"25-34": 200.0, "35-44": 200.0}


@pytest.mark.asyncio
async def test_postgres_asyncpg_ingest_and_campaign_sql():
    dsn = os.getenv(
        "TEST_DATABASE_URL", "postgresql://paygate:paygate@localhost:5432/geo_dmp_test"
    )
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3)
    try:
        schema_sql = Path("app/db/schema.sql").read_text(encoding="utf-8")
        async with pool.acquire() as conn:
            await conn.execute(schema_sql)
            await conn.execute(
                "TRUNCATE TABLE geo_pings, ad_inventory RESTART IDENTITY;"
            )

        repo = DmpRepository(pool)
        await repo.upsert_inventory(
            "KRD_SCR_01",
            "indoor_screen",
            "Krasnodar",
            45.0355,
            38.9753,
            120.0,
            min_dwell_seconds=4,
        )

        now = datetime.now(timezone.utc)
        await repo.bulk_ingest_pings(
            [
                {
                    "device_hash": "d1",
                    "lat": 45.0355,
                    "lon": 38.9753,
                    "dwell_seconds": 12,
                    "age_group": "25-34",
                    "gender": "M",
                    "income_tier": "middle",
                    "pinged_at": now,
                },
                {
                    "device_hash": "d1",
                    "lat": 45.0356,
                    "lon": 38.9754,
                    "dwell_seconds": 7,
                    "age_group": "25-34",
                    "gender": "M",
                    "income_tier": "middle",
                    "pinged_at": now + timedelta(minutes=5),
                },
                {
                    "device_hash": "d2",
                    "lat": 45.0358,
                    "lon": 38.9753,
                    "dwell_seconds": 6,
                    "age_group": "35-44",
                    "gender": "F",
                    "income_tier": "affluent",
                    "pinged_at": now + timedelta(minutes=10),
                },
                {
                    "device_hash": "d3_far",
                    "lat": 45.0500,
                    "lon": 38.9753,
                    "dwell_seconds": 20,
                    "age_group": "18-24",
                    "gender": "M",
                    "income_tier": "mass",
                    "pinged_at": now,
                },
            ]
        )

        app.state.pool = pool
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/campaigns/calculate",
                json={
                    "inventory_codes": ["KRD_SCR_01"],
                    "since": (now - timedelta(minutes=5)).isoformat(),
                    "until": (now + timedelta(minutes=30)).isoformat(),
                    "target_population": 1000,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ots"] == 3
            assert data["reach"] == 2
            assert data["frequency"] == 1.5
            assert data["grp"] == 0.3
    finally:
        await pool.close()
