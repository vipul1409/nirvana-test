"""
Generates deterministic telematics data for demo vehicles.

Data is controlled by demo_vehicles.json (written by the seed script).
Falls back to DEFAULT_VEHICLES (3 hardcoded vehicles) if no file exists.

Uses random.Random(vin) so every vehicle's data is reproducible.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

# Written by the seed script; read by the mock server at startup.
VEHICLES_FILE = "demo_vehicles.json"

# ---------------------------------------------------------------------------
# Default vehicles (used when VEHICLES_FILE does not exist)
# ---------------------------------------------------------------------------

DEFAULT_VEHICLES: list[dict] = [
    {"id": "samsara-v-001", "vin": "1HGBH41JXMN109186", "name": "Honda Civic #1",         "profile": "low_risk", "has_missing_data": False},
    {"id": "samsara-v-002", "vin": "3VWFE21C04M000001", "name": "Freightliner Cascadia #1","profile": "truck",    "has_missing_data": False},
    {"id": "samsara-v-003", "vin": "5YJSA1DG9DFP14105", "name": "Tesla Model 3 #1",        "profile": "ev",       "has_missing_data": False},
]

# Profiles cycle across generated vehicles: index % 3 → profile name.
_PROFILE_ORDER = ["low_risk", "truck", "ev"]
_PROFILE_NAMES = ["Honda Civic", "Freightliner Cascadia", "Tesla Model 3"]

_PROFILES: dict[str, dict] = {
    "low_risk": {
        "speed_mean": 42.0, "speed_std": 5.0,
        "hard_brakes_lam": 0.07, "hard_accel_lam": 0.05,
        "miles_mean": 18.0, "miles_std": 4.0,
        "idle_mean": 8, "idle_std": 3,
        "fuel_mean": 1.8, "fuel_std": 0.3,
        "fault_code_prob": 0.0,
    },
    "truck": {
        "speed_mean": 58.0, "speed_std": 8.0,
        "hard_brakes_lam": 0.27, "hard_accel_lam": 0.15,
        "miles_mean": 320.0, "miles_std": 60.0,
        "idle_mean": 30, "idle_std": 8,
        "fuel_mean": 120.0, "fuel_std": 20.0,
        "fault_code_prob": 0.011,
    },
    "ev": {
        "speed_mean": 51.0, "speed_std": 6.0,
        "hard_brakes_lam": 0.03, "hard_accel_lam": 0.04,
        "miles_mean": 28.0, "miles_std": 5.0,
        "idle_mean": 2, "idle_std": 1,
        "fuel_mean": 0.0, "fuel_std": 0.0,
        "fault_code_prob": 0.0,
    },
}

_FAULT_CODES = ["P0300", "P0420", "P0171", "U0100"]
_MISSING_MONTHS_COUNT = 3  # months with no data for missing-data vehicles


# ---------------------------------------------------------------------------
# VIN + vehicle generation
# ---------------------------------------------------------------------------

def generate_vin(index: int) -> str:
    """Generate a deterministic 17-char demo VIN for vehicle at position index."""
    return f"1DEMO{index:012d}"


def generate_vehicles(n: int, missing_count: int) -> list[dict]:
    """
    Generate n vehicle definitions. The last missing_count vehicles are
    flagged has_missing_data=True (some months will have no records).
    Profiles cycle: low_risk → truck → ev → low_risk → ...
    """
    if missing_count > n:
        raise ValueError(f"missing_count ({missing_count}) cannot exceed vehicles ({n})")

    vehicles = []
    for i in range(n):
        profile = _PROFILE_ORDER[i % len(_PROFILE_ORDER)]
        name = _PROFILE_NAMES[i % len(_PROFILE_NAMES)]
        vin = generate_vin(i + 1)
        vehicles.append({
            "id": f"samsara-v-{i + 1:04d}",
            "vin": vin,
            "name": f"{name} #{i + 1}",
            "profile": profile,
            "has_missing_data": i >= (n - missing_count),
        })
    return vehicles


# ---------------------------------------------------------------------------
# Telematics generation
# ---------------------------------------------------------------------------

def _poisson(rng: random.Random, lam: float) -> int:
    """Approximate Poisson sample for small lambda without numpy."""
    return sum(1 for _ in range(30) if rng.random() < lam / 30)


def _missing_months(vin: str) -> set[int]:
    """Deterministically pick which months (1–12) have no data for this VIN."""
    rng = random.Random(vin + "_missing")
    return set(rng.sample(range(1, 13), _MISSING_MONTHS_COUNT))


def generate_records(vin: str, profile_name: str, has_missing_data: bool) -> list[dict]:
    """
    Return daily records for 2024-01-01 → 2024-12-31.
    Vehicles with has_missing_data=True have _MISSING_MONTHS_COUNT months
    completely absent.
    """
    rng = random.Random(vin)
    p = _PROFILES[profile_name]
    skip_months = _missing_months(vin) if has_missing_data else set()

    records = []
    current = date(2024, 1, 1)
    end = date(2024, 12, 31)
    while current <= end:
        if current.month not in skip_months:
            fault_codes: list[str] = []
            if rng.random() < p["fault_code_prob"]:
                fault_codes = [rng.choice(_FAULT_CODES)]
            records.append({
                "vin": vin,
                "date": current.isoformat(),
                "speed_mph_avg": round(max(0.0, rng.gauss(p["speed_mean"], p["speed_std"])), 2),
                "hard_brakes": _poisson(rng, p["hard_brakes_lam"]),
                "hard_accelerations": _poisson(rng, p["hard_accel_lam"]),
                "miles_driven": round(max(0.0, rng.gauss(p["miles_mean"], p["miles_std"])), 2),
                "idle_minutes": max(0, int(rng.gauss(p["idle_mean"], p["idle_std"]))),
                "fuel_consumed_l": round(max(0.0, rng.gauss(p["fuel_mean"], p["fuel_std"])), 3),
                "fault_codes": fault_codes,
            })
        else:
            # Advance rng state consistently so non-missing vehicles stay
            # deterministic regardless of missing_count.
            rng.gauss(0, 1)
        current += timedelta(days=1)
    return records


def build_dataset(vehicles: list[dict]) -> dict[str, list[dict]]:
    """Build the {vin: [record, ...]} lookup used by mock routes."""
    return {
        v["vin"]: generate_records(v["vin"], v["profile"], v.get("has_missing_data", False))
        for v in vehicles
    }


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def load_vehicles() -> list[dict]:
    """Load vehicles from VEHICLES_FILE, falling back to DEFAULT_VEHICLES."""
    path = Path(VEHICLES_FILE)
    if path.exists():
        return json.loads(path.read_text())
    return DEFAULT_VEHICLES


def save_vehicles(vehicles: list[dict]) -> None:
    """Persist vehicles to VEHICLES_FILE."""
    Path(VEHICLES_FILE).write_text(json.dumps(vehicles, indent=2))


# ---------------------------------------------------------------------------
# Module-level singletons (loaded once when mock server starts)
# ---------------------------------------------------------------------------

VEHICLES: list[dict] = load_vehicles()
ALL_DATA: dict[str, list[dict]] = build_dataset(VEHICLES)
