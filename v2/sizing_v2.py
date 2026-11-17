"""v2 equipment sizing: crusher (motor and capacity), screens (area and aperture), sink-float tank (volume), annual scaling.

All inputs come from the surrogate / Aspen results (flows, power) and a SIZING dict whose every value is an ASSUMPTION or sourced in assumptions_v2.md.
At 100-500 kg/h the equipment sits at its practical minimum size (min_area, min_volume), so costs are floor-driven at this scale.
"""
from __future__ import annotations

import math

import tank_v2 as tk

SIZING = {
    "motor_service_factor": 1.25,     # installed motor = 1.25 x calculated power, ASSUMPTION (common sizing margin)
    "bulk_density_kg_m3": 350.0,      # shredded plastic flake bulk density, ASSUMPTION
    "screen_service_factor": 0.7,     # lumps efficiency, deck position, wet/dry and other corrections, ASSUMPTION
    "screen_min_area_m2": 0.5,        # smallest practical screen deck, ASSUMPTION
    "tank_min_volume_m3": 0.5,        # smallest practical sink-float tank (with pump sump), ASSUMPTION
    "tank_solids_mass_frac": tk.CONFIG["solids_mass_frac"],   # 5 %, same as the tank model
    "tank_depth_m": tk.CONFIG["depth_m"],
}
# IEC standard motor ratings, kW
MOTORS_KW = [0.75, 1.1, 1.5, 2.2, 3, 4, 5.5, 7.5, 11, 15, 18.5, 22, 30, 37, 45, 55, 75, 90, 110, 132, 160, 200, 250, 315]
# basic screen capacity, t/h per m2 of deck at a standard bulk density of 1600 kg/m3 (secondary source, see assumptions_v2.md)
SCREEN_TABLE = [(1.0, 6.53), (10.0, 32.67), (20.0, 46.93)]       # (aperture mm, t/h/m2)
STD_BULK_DENSITY = 1600.0


def select_motor(power_kw: float, service_factor: float | None = None) -> float:
    sf = SIZING["motor_service_factor"] if service_factor is None else service_factor
    need = power_kw * sf
    for m in MOTORS_KW:
        if m >= need:
            return float(m)
    raise ValueError(f"required motor {need:.0f} kW exceeds the catalogue ({MOTORS_KW[-1]} kW): split over several machines")


def size_crusher(power_kw: float, throughput_kg_h: float, specific_kwh_t: float, gap_mm: float) -> dict:
    """Motor size and the throughput it could carry at the same specific energy."""
    motor = select_motor(power_kw)
    capacity = motor / SIZING["motor_service_factor"] / specific_kwh_t * 1000.0     # kg/h at full (design) load
    return {"calculated_power_kW": power_kw, "motor_kW": motor, "service_factor": SIZING["motor_service_factor"],
            "throughput_kg_h": throughput_kg_h, "capacity_kg_h": capacity, "utilisation": throughput_kg_h / capacity, "gap_mm": gap_mm}


def screen_unit_capacity(aperture_mm: float) -> float:
    """Basic capacity t/h/m2 by log-log interpolation of SCREEN_TABLE (valid 1-20 mm)."""
    (a0, _), (a1, _) = SCREEN_TABLE[0], SCREEN_TABLE[-1]
    if not a0 <= aperture_mm <= a1:
        raise ValueError(f"aperture {aperture_mm} mm outside the table range {a0}-{a1} mm")
    for (x0, q0), (x1, q1) in zip(SCREEN_TABLE, SCREEN_TABLE[1:]):
        if x0 <= aperture_mm <= x1:
            return math.exp(math.log(q0) + (math.log(aperture_mm) - math.log(x0)) / (math.log(x1) - math.log(x0)) * (math.log(q1) - math.log(q0)))
    raise AssertionError


def size_screen(feed_kg_h: float, aperture_mm: float) -> dict:
    """Deck area for a feed in kg/h. Aperture = Plitt cut size (simplification, ASSUMPTION)."""
    q = screen_unit_capacity(aperture_mm)
    q_eff = q * SIZING["bulk_density_kg_m3"] / STD_BULK_DENSITY * SIZING["screen_service_factor"]
    area_calc = feed_kg_h / 1000.0 / q_eff
    return {"aperture_mm": aperture_mm, "feed_kg_h": feed_kg_h, "basic_capacity_t_h_m2": q, "effective_capacity_t_h_m2": q_eff,
            "area_calc_m2": area_calc, "area_m2": max(area_calc, SIZING["screen_min_area_m2"])}


def size_tank(solids_kg_h: float, residence_s: float, rho_solids: float = 1100.0, temp_c: float | None = None) -> dict:
    """Sink-float tank volume = slurry flow x residence time (min volume applies). rho_solids: mean flake density (kg/m3)."""
    ws = SIZING["tank_solids_mass_frac"]
    rho_w = tk.water_density(tk.CONFIG["temp_C"] if temp_c is None else temp_c)
    rho_slurry = 1.0 / (ws / rho_solids + (1.0 - ws) / rho_w)
    q_slurry = solids_kg_h / ws / rho_slurry                      # m3/h
    v_calc = q_slurry * residence_s / 3600.0
    v = max(v_calc, SIZING["tank_min_volume_m3"])
    return {"slurry_m3_h": q_slurry, "water_m3_h": q_slurry * (1 - ws) * rho_slurry / rho_w, "volume_calc_m3": v_calc, "volume_m3": v,
            "plan_area_m2": v / SIZING["tank_depth_m"], "depth_m": SIZING["tank_depth_m"], "residence_s": residence_s}


def annual(rate_kg_h: float, hours_per_year: float) -> float:
    """Tonnes per year for a rate in kg/h."""
    return rate_kg_h * hours_per_year / 1000.0
