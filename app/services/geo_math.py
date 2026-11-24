"""Deterministic geospatial and OOH/Indoor media metric calculations."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

EARTH_RADIUS_M = 6_371_000.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in meters between two WGS84 coordinates."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class InventoryPoint:
    code: str
    lat: float
    lon: float
    visibility_radius_m: float
    min_dwell_seconds: int


@dataclass(frozen=True)
class GeoPing:
    device_hash: str
    lat: float
    lon: float
    dwell_seconds: int
    age_group: str
    gender: str
    income_tier: str


@dataclass(frozen=True)
class CampaignReport:
    ots: int
    reach: int
    frequency: float
    grp: float
    age_distribution_pct: dict[str, float]
    income_distribution_pct: dict[str, float]
    affinity_index: dict[str, float]


def calculate_campaign_metrics(
    inventories: Iterable[InventoryPoint],
    pings: Iterable[GeoPing],
    target_population: int,
    baseline_age_share: dict[str, float] | None = None,
) -> CampaignReport:
    """Compute OTS, unique Reach, Frequency, GRP, and socio-demographic affinity."""
    if target_population <= 0:
        raise ValueError("target_population must be positive")

    inv_list = list(inventories)
    matched_pings: list[GeoPing] = []

    for ping in pings:
        # A ping counts as a contact (OTS) if it falls inside at least one screen's visibility zone and dwell threshold.
        for inv in inv_list:
            if ping.dwell_seconds < inv.min_dwell_seconds:
                continue
            if (
                haversine_meters(inv.lat, inv.lon, ping.lat, ping.lon)
                <= inv.visibility_radius_m
            ):
                matched_pings.append(ping)
                break

    ots = len(matched_pings)
    if ots == 0:
        return CampaignReport(
            ots=0,
            reach=0,
            frequency=0.0,
            grp=0.0,
            age_distribution_pct={},
            income_distribution_pct={},
            affinity_index={},
        )

    # Deduplicate socio-demo profile by unique device_hash for Reach-based profiling
    unique_devices: dict[str, GeoPing] = {}
    for p in matched_pings:
        unique_devices.setdefault(p.device_hash, p)

    reach = len(unique_devices)
    frequency = round(ots / reach, 2)
    grp = round((ots / target_population) * 100.0, 2)

    age_counts = Counter(d.age_group for d in unique_devices.values())
    income_counts = Counter(d.income_tier for d in unique_devices.values())

    age_pct = {k: round((v / reach) * 100.0, 2) for k, v in sorted(age_counts.items())}
    income_pct = {
        k: round((v / reach) * 100.0, 2) for k, v in sorted(income_counts.items())
    }

    affinity: dict[str, float] = {}
    if baseline_age_share:
        for age, share in age_pct.items():
            base = baseline_age_share.get(age)
            if base and base > 0:
                affinity[age] = round((share / base) * 100.0, 1)

    return CampaignReport(
        ots=ots,
        reach=reach,
        frequency=frequency,
        grp=grp,
        age_distribution_pct=age_pct,
        income_distribution_pct=income_pct,
        affinity_index=affinity,
    )
