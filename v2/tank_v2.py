"""v2 sink-float tank model: settling velocity + residence time -> smooth partition curve -> DENSEP fractions.

Per polymer and per PSD interval (equivalent diameter = interval midpoint):
  1. Terminal velocity v_t in water at temperature T: Cd*Re^2 = (4/3) Ar with the Haider-Levenspiel drag law
     for non-spherical particles (sphericity psi). Sign: + sinks (PET), - rises (HDPE, PP).
  2. Hindered settling (solids loading): v_h = v_t * (1 - phi)^n, Richardson-Zaki exponent n(Re).
  3. Partition curve. A flake must travel the tank depth H within the residence time tau:  t_s = H / v_h  (signed, negative for floaters).
     P(DENSE) = Phi( (tau / t_s - 1) / sigma ),  Phi = standard normal CDF.
     tau/t_s = v_h / v_crit with v_crit = H/tau, so this is a smooth S-shaped function of t_s/tau: P = 0.5 at t_s = tau,
     -> 1 for fast sinkers, -> 0 for floaters; a slow floater is dragged down with a small, non-zero probability.
     sigma (spread) stands for turbulence, flake-shape spread and bubble effects: an ASSUMPTION (default/low/high in CONFIG).
     sigma -> 0 recovers the hard rule "reaches the bottom within tau".
  4. Overall split to DENSE per polymer = PSD-weighted mean of P over the 7 intervals (COARSE stream PSD from Aspen).
All numbers in CONFIG are recorded in assumptions_v2.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

G = 9.81

CONFIG = {
    "temp_C": 25.0,
    "sphericity": 0.6,           # ASSUMPTION (flat flakes)
    "depth_m": 1.0,              # tank depth H, ASSUMPTION (design placeholder)
    "residence_s": 20.0,         # residence time tau, ASSUMPTION (design placeholder; decision variable in V5)
    "spread": 0.5,               # sigma, ASSUMPTION (default); see spread_low / spread_high
    "spread_low": 0.25,
    "spread_high": 1.0,
    "solids_mass_frac": 0.05,    # solids mass fraction of the slurry in the tank, ASSUMPTION (for hindered settling)
    "floor": 0.0,                # optional minimum entrainment of HDPE/PP to DENSE (bubble attachment). 0 = none. ASSUMPTION if used.
    "densities": {"PET": 1380.0, "HDPE": 950.0, "PP": 905.0},   # kg/m3, same as Aspen VSPOLY
    "edges_mm": [0, 2, 5, 8, 12, 20, 40, 80],
}
FLOATERS = ("HDPE", "PP")


# ------------------------------------------------------------ water properties
def water_density(t_c: float) -> float:
    """Kell (1975), kg/m3, 0-100 C."""
    t = t_c
    return (999.83952 + 16.945176 * t - 7.9870401e-3 * t**2 - 46.170461e-6 * t**3
            + 105.56302e-9 * t**4 - 280.54253e-12 * t**5) / (1 + 16.879850e-3 * t)


def water_viscosity(t_c: float) -> float:
    """Vogel equation, Pa s: mu = 2.414e-5 * 10^(247.8 / (T - 140)), T in K."""
    return 2.414e-5 * 10 ** (247.8 / (t_c + 273.15 - 140.0))


# ------------------------------------------------------------ settling
def drag_coefficient(re: float, psi: float) -> float:
    """Haider & Levenspiel (1989) drag coefficient (equivalent-volume sphere)."""
    a = math.exp(2.3288 - 6.4581 * psi + 2.4486 * psi**2)
    b = 0.0964 + 0.5565 * psi
    c = math.exp(4.905 - 13.8944 * psi + 18.4222 * psi**2 - 10.2599 * psi**3)
    d = math.exp(1.4681 + 12.2584 * psi - 20.7322 * psi**2 + 15.8855 * psi**3)
    return 24.0 / re * (1.0 + a * re**b) + c / (1.0 + d / re)


def regime(re: float) -> str:
    return "Stokes" if re < 0.2 else ("intermediate" if re <= 1000.0 else "Newton")


def terminal_velocity(rho_p: float, d_m: float, psi: float, t_c: float = 25.0) -> tuple[float, float]:
    """(signed v_t m/s, particle Reynolds number) in free water at temperature t_c."""
    if d_m <= 0 or not 0 < psi <= 1:
        raise ValueError("need d > 0 and 0 < sphericity <= 1")
    rho_f, mu = water_density(t_c), water_viscosity(t_c)
    drho = rho_p - rho_f
    if drho == 0:
        return 0.0, 0.0
    target = 4.0 / 3.0 * G * d_m**3 * rho_f * abs(drho) / mu**2
    lo, hi = 1e-10, 1e7
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if drag_coefficient(mid, psi) * mid**2 < target:
            lo = mid
        else:
            hi = mid
    re = math.sqrt(lo * hi)
    return math.copysign(re * mu / (rho_f * d_m), drho), re


def richardson_zaki_n(re: float) -> float:
    """Richardson-Zaki (1954) exponent (as in Coulson & Richardson, vol. 2)."""
    if re < 0.2:
        return 4.65
    if re < 1.0:
        return 4.35 * re**-0.03
    if re < 500.0:
        return 4.45 * re**-0.1
    return 2.39


def solids_volume_fraction(mass_frac_solids: float, comp: dict[str, float], cfg: dict) -> float:
    """Volume fraction of solids in the slurry from the solids mass fraction and the solids composition."""
    tot = sum(comp.values())
    rho_s = 1.0 / sum((m / tot) / cfg["densities"][c] for c, m in comp.items())
    rho_w = water_density(cfg["temp_C"])
    vs = mass_frac_solids / rho_s
    vw = (1.0 - mass_frac_solids) / rho_w
    return vs / (vs + vw)


# ------------------------------------------------------------ partition curve
def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def partition_to_dense(v_h: float, depth: float, tau: float, sigma: float, floor: float = 0.0, floater: bool = False) -> float:
    """P(DENSE) = Phi((tau/t_s - 1)/sigma), t_s = depth / v_h (signed). sigma -> 0: hard rule."""
    v_crit = depth / tau
    z = (v_h - v_crit) / v_crit            # = tau/t_s - 1
    if sigma <= 1e-12:
        p = 1.0 if z > 0 else (0.5 if z == 0 else 0.0)
    else:
        p = _phi(z / sigma)
    if floater:
        p = max(p, floor)
    return min(1.0, max(0.0, p))


@dataclass
class SizeRow:
    polymer: str
    d_mid_mm: float
    v_t: float          # free terminal velocity, m/s (signed)
    reynolds: float
    regime: str
    v_h: float          # hindered velocity, m/s (signed)
    t_s: float          # depth / v_h, s (signed)
    p_dense: float


def midpoints_mm(cfg: dict) -> list[float]:
    e = cfg["edges_mm"]
    return [(a + b) / 2.0 for a, b in zip(e, e[1:])]


def size_table(cfg: dict | None = None, comp: dict[str, float] | None = None, **over) -> list[SizeRow]:
    """Per polymer and size interval. `over` overrides CONFIG keys (e.g. residence_s=30, spread=0.25)."""
    cfg = {**(cfg or CONFIG), **over}
    comp = comp or {"PET": 0.45, "HDPE": 0.30, "PP": 0.25}
    phi = solids_volume_fraction(cfg["solids_mass_frac"], comp, cfg)
    rows = []
    for polymer, rho in cfg["densities"].items():
        for d_mm in midpoints_mm(cfg):
            v, re = terminal_velocity(rho, d_mm / 1000.0, cfg["sphericity"], cfg["temp_C"])
            vh = v * (1.0 - phi) ** richardson_zaki_n(re)
            p = partition_to_dense(vh, cfg["depth_m"], cfg["residence_s"], cfg["spread"], cfg["floor"], polymer in FLOATERS)
            rows.append(SizeRow(polymer, d_mm, v, re, regime(re), vh, cfg["depth_m"] / vh if vh else math.inf, p))
    return rows


def overall_split(psd: list[float], comp: dict[str, float] | None = None, cfg: dict | None = None, **over) -> dict[str, float]:
    """Fraction of each polymer going to DENSE: PSD-weighted mean of the partition probabilities (same PSD for all polymers)."""
    cfg = {**(cfg or CONFIG), **over}
    n = len(cfg["edges_mm"]) - 1
    if len(psd) != n:
        raise ValueError(f"PSD needs {n} fractions, got {len(psd)}")
    tot = sum(psd)
    if tot <= 0:
        raise ValueError("PSD sums to zero")
    w = [x / tot for x in psd]
    rows = size_table(cfg, comp)
    out = {}
    for polymer in cfg["densities"]:
        ps = [r.p_dense for r in rows if r.polymer == polymer]
        out[polymer] = min(1.0, max(0.0, sum(a * b for a, b in zip(w, ps))))
    return out


# ------------------------------------------------------------ both sides of the separation
def separation_metrics(dense: dict[str, float], light: dict[str, float], feed: dict[str, float]) -> dict[str, float]:
    """dense/light/feed: component flows {PET, HDPE, PP} (kg/h). Purities are fractions (0-1), the rest are percent."""
    d_tot, l_tot = sum(dense.values()), sum(light.values())
    pe_pp_feed = feed["HDPE"] + feed["PP"]
    return {
        "PET_purity_dense": dense["PET"] / d_tot if d_tot > 0 else float("nan"),
        "PE_PP_purity_light": (light["HDPE"] + light["PP"]) / l_tot if l_tot > 0 else float("nan"),
        "PET_recovery_pct": 100.0 * dense["PET"] / feed["PET"],
        "PEPP_recovery_pct": 100.0 * (light["HDPE"] + light["PP"]) / pe_pp_feed,
        "PET_loss_to_light_pct": 100.0 * light["PET"] / feed["PET"],
        "PEPP_loss_to_dense_pct": 100.0 * (dense["HDPE"] + dense["PP"]) / pe_pp_feed,
    }


if __name__ == "__main__":
    print(f"water {CONFIG['temp_C']} C: rho={water_density(CONFIG['temp_C']):.2f} mu={water_viscosity(CONFIG['temp_C'])*1e3:.4f} mPa s;"
          f" H={CONFIG['depth_m']} m tau={CONFIG['residence_s']} s v_crit={1000*CONFIG['depth_m']/CONFIG['residence_s']:.0f} mm/s sigma={CONFIG['spread']}")
    print(f"{'poly':<5}{'d mm':>6}{'v_t mm/s':>10}{'Re':>8} {'regime':<13}{'v_h mm/s':>9}{'P(DENSE)':>10}")
    for r in size_table():
        print(f"{r.polymer:<5}{r.d_mid_mm:>6.1f}{r.v_t*1000:>10.1f}{r.reynolds:>8.0f} {r.regime:<13}{r.v_h*1000:>9.1f}{r.p_dense:>10.4f}")
