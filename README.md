# Geo DMP Engine

Outdoor & Indoor OOH Audience Measurement Platform (DMP) built on **Python, FastAPI, Zero-ORM `asyncpg`, PostgreSQL Geo-Spatial Raw SQL, and `pytest`**.

Inspired by `market-columnar-engine` and `deadhead-dispatcher`.

## What It Calculates
- **OTS (Opportunity To See)**, **Unique Reach**, **Frequency (`OTS / Reach`)**, **GRP**, and **Socio-Demographic Affinity Index**.
- **PostgreSQL Bounding-Box Prefilter + Exact Haversine SQL (`app/db/repository.py`)**: Prunes coordinate indexes before exact great-circle radius and dwell-time evaluation.
- **Zero-ORM `UNNEST` Batch Ingestion**: Single-roundtrip high-throughput ping ingestion via `asyncpg`.
- **Control-Example Verification (`tests/test_dmp_calculations.py`)**: Verifies mathematical accuracy against hand-computed reference datasets and live PostgreSQL queries.

## Run Tests
```bash
pytest -v
```
