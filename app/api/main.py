"""FastAPI async service for OOH/Indoor geo-audience measurement (DMP)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.db.repository import DmpRepository
from app.services.geo_math import GeoPing, InventoryPoint, calculate_campaign_metrics

DSN = os.getenv(
    "DATABASE_URL", "postgresql://paygate:paygate@localhost:5432/geo_dmp_development"
)


class PingIn(BaseModel):
    device_hash: str = Field(min_length=4, max_length=64)
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    dwell_seconds: int = Field(ge=0, le=86_400)
    age_group: Literal["18-24", "25-34", "35-44", "45+"]
    gender: Literal["M", "F"]
    income_tier: Literal["mass", "middle", "affluent"]
    pinged_at: datetime


class BatchIngestRequest(BaseModel):
    pings: list[PingIn] = Field(min_length=1, max_length=10_000)


class CampaignQueryRequest(BaseModel):
    inventory_codes: list[str] = Field(min_length=1)
    since: datetime
    until: datetime
    target_population: int = Field(gt=0)


class InMemoryEstimateRequest(BaseModel):
    inventories: list[dict]
    pings: list[PingIn]
    target_population: int = Field(gt=0)
    baseline_age_share: dict[str, float] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    yield
    await app.state.pool.close()


app = FastAPI(title="Geo DMP Engine", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    async with app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok", "engine": "asyncpg"}


@app.post("/v1/ingest/pings", status_code=201)
async def ingest_pings(req: BatchIngestRequest) -> dict[str, int]:
    repo = DmpRepository(app.state.pool)
    count = await repo.bulk_ingest_pings([p.model_dump() for p in req.pings])
    return {"ingested": count}


@app.post("/v1/campaigns/calculate")
async def calculate_campaign(req: CampaignQueryRequest) -> dict:
    if req.until <= req.since:
        raise HTTPException(status_code=422, detail="until must be after since")
    repo = DmpRepository(app.state.pool)
    return await repo.calculate_campaign(
        inventory_codes=req.inventory_codes,
        since=req.since,
        until=req.until,
        target_population=req.target_population,
    )


@app.post("/v1/campaigns/simulate")
async def simulate_campaign(req: InMemoryEstimateRequest) -> dict:
    invs = [
        InventoryPoint(
            code=str(i["code"]),
            lat=float(i["lat"]),
            lon=float(i["lon"]),
            visibility_radius_m=float(i["visibility_radius_m"]),
            min_dwell_seconds=int(i.get("min_dwell_seconds", 3)),
        )
        for i in req.inventories
    ]
    pings = [
        GeoPing(
            device_hash=p.device_hash,
            lat=p.lat,
            lon=p.lon,
            dwell_seconds=p.dwell_seconds,
            age_group=p.age_group,
            gender=p.gender,
            income_tier=p.income_tier,
        )
        for p in req.pings
    ]
    report = calculate_campaign_metrics(
        invs, pings, req.target_population, req.baseline_age_share
    )
    return report.__dict__
