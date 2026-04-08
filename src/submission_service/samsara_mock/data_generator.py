"""
Generates deterministic telematics data for the 3 demo vehicles.
Uses random.Random(vin) so data is reproducible across restarts.
This module is the single source of truth — seed.py and mock routes both import from here.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Vehicle definitions
# ---------------------------------------------------------------------------

VEHICLES: list[dict] = [
    {
        "id": "samsara-v-001",
        "vin": "1HGBH41JXMN109186",
        "name": "Honda Civic #1",
        "profile": "low_risk",
    },
    {
        "id": "samsara-v-002",
        "vin": "3VWFE21C04M000001",
        "name": "Freightliner Cascadia #1",
        "profile": "truck",
    },
    {
        "id": "samsara-v-003",
        "vin": "5YJSA1DG9DFP14105",
        "name": "Tesla Model 3 #1",
        "profile": "ev",
    },
]

# ---------------------------------------------------------------------------
# Behavior profiles
# ---------------------------------------------------------------------------

_PROFILES: dict[str, dict] = {
    "low_risk": {
        "speed_mean": 42.0,
        "speed_std": 5.0,
        "hard_brakes_lam": 0.07,       # Poisson lambda (events/day)
        "hard_accel_lam": 0.05,
        "miles_mean": 18.0,
        "miles_std": 4.0,
        "idle_mean": 8,
        "idle_std": 3,
        "fuel_mean": 1.8,
        "fuel_std": 0.3,
        "fault_code_prob": 0.0,
        "is_ev": False,
    },
    "truck": {
        "speed_mean": 58.0,
        "speed_std": 8.0,
        "hard_brakes_lam": 0.27,
        "hard_accel_lam": 0.15,
        "miles_mean": 320.0,
        "miles_std": 60.0,
        "idle_mean": 30,
        "idle_std": 8,
        "fuel_mean": 120.0,
        "fuel_std": 20.0,
        "fault_code_prob": 0.011,      # ~4 fault codes per year
        "is_ev": False,
    },
    "ev": {
        "speed_mean": 51.0,
        "speed_std": 6.0,
        "hard_brakes_lam": 0.03,
        "hard_accel_lam": 0.04,
        "miles_mean": 28.0,
        "miles_std": 5.0,
        "idle_mean": 2,
        "idle_std": 1,
        "fuel_mean": 0.0,
        "fuel_std": 0.0,
        "fault_code_prob": 0.0,
        "is_ev": True,
    },
}

_FAULT_CODES = ["P0300", "P0420", "P0171", "U0100"]


def _poisson(rng: random.Random, lam: float) -> int:
    """Approximate Poisson sample for small lambda without numpy."""
    return sum(1 for _ in range(30) if rng.random() < lam / 30)


def _generate_year(vin: str, profile_name: str) -> list[dict]:
    """Return 365 daily records for 2024 in deterministic order."""
    rng = random.Random(vin)
    p = _PROFILES[profile_name]
    records = []
    current = date(2024, 1, 1)
    end = date(2024, 12, 31)
    while current <= end:
        fault_codes: list[str] = []
        if rng.random() < p["fault_code_prob"]:
            fault_codes = [rng.choice(_FAULT_CODES)]
        records.append(
            {
                "vin": vin,
                "date": current.isoformat(),
                "speed_mph_avg": round(
                    max(0.0, rng.gauss(p["speed_mean"], p["speed_std"])), 2
                ),
                "hard_brakes": _poisson(rng, p["hard_brakes_lam"]),
                "hard_accelerations": _poisson(rng, p["hard_accel_lam"]),
                "miles_driven": round(
                    max(0.0, rng.gauss(p["miles_mean"], p["miles_std"])), 2
                ),
                "idle_minutes": max(
                    0, int(rng.gauss(p["idle_mean"], p["idle_std"]))
                ),
                "fuel_consumed_l": round(
                    max(0.0, rng.gauss(p["fuel_mean"], p["fuel_std"])), 3
                ),
                "fault_codes": fault_codes,
            }
        )
        current += timedelta(days=1)
    return records


def generate_all() -> dict[str, list[dict]]:
    """Returns {vin: [daily_record, ...]} for all 3 vehicles."""
    result: dict[str, list[dict]] = {}
    for v in VEHICLES:
        result[v["vin"]] = _generate_year(v["vin"], v["profile"])
    return result


# Module-level singleton — computed once at import time
ALL_DATA: dict[str, list[dict]] = generate_all()
