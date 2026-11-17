"""v2 crusher model: gap -> 7-interval product PSD (written into the Aspen CRUSH spec) and Bond power (Python).

PSD: Rosin-Rammler cumulative passing  F(x) = 1 - exp(-(x / x63)^n),  x63 = A * gap,
truncated at the feed top size (nothing leaves coarser than it entered) and re-normalised, then binned on the
Aspen PSD mesh (0, 2, 5, 8, 12, 20, 40, 80 mm).
  n = 1.45 : fitted to the cumulative PSD that was in the v1 Aspen spec (see assumptions_v2.md).
  A = 1.0  : ASSUMPTION (characteristic product size equals the gap/screen aperture).

Power: Bond  W = 10 Wi (1/sqrt(P80) - 1/sqrt(F80))  [kWh/short ton, sizes in micrometres],
converted to kWh per metric tonne (x 1/0.907185) and multiplied by the crusher throughput (fresh feed + recycle).
Wi (per polymer, mass-weighted for the mixture) is an EFFECTIVE value calibrated to a vendor specific energy of
35 kWh/t at a reference duty. It is NOT a material property (Bond's law is made for brittle minerals; no
published Wi for PET/HDPE/PP was found). Aspen limits BWI to 99.99, so Aspen's own power is informational only.
"""
from __future__ import annotations

import math

SHORT_TON_KG = 907.185

CONFIG = {
    "edges_mm": [0, 2, 5, 8, 12, 20, 40, 80],
    "rr_n": 1.45,           # Rosin-Rammler spread, fitted to the v1 Aspen PSD spec
    "rr_a": 1.0,            # x63 / gap, ASSUMPTION
    "fines_mm": 2.0,        # size below which material counts as fines (SCREEN2 cut in the base case)
    # calibration of the effective work index (ASSUMPTION, see assumptions_v2.md)
    "target_kwh_per_t": 35.0,   # mid-point of the vendor claim range 20-50 kWh/t (CMG: 20-25 efficient, >50 conventional)
    "target_low": 20.0,
    "target_high": 50.0,
    "ref_f80_mm": 45.0,         # reference crusher feed F80 (base case recycle mix is 45.35 mm)
    "ref_gap_mm": 10.0,         # reference gap
    "ref_top_mm": 80.0,         # reference feed top size
}


def _cum_rr(x: float, gap: float, top: float, cfg: dict) -> float:
    x63 = cfg["rr_a"] * gap
    f = lambda v: 1.0 - math.exp(-((v / x63) ** cfg["rr_n"]))  # noqa: E731
    return min(1.0, f(min(x, top)) / f(top))


def psd(gap_mm: float, top_mm: float = 80.0, cfg: dict | None = None) -> list[float]:
    """7 mass fractions on the Aspen mesh; sum is exactly 1 (last bin takes the rounding remainder)."""
    cfg = cfg or CONFIG
    if gap_mm <= 0 or top_mm <= 0:
        raise ValueError("gap and top size must be > 0")
    e = cfg["edges_mm"]
    cum = [_cum_rr(x, gap_mm, top_mm, cfg) for x in e]
    cum[0] = 0.0
    fr = [max(0.0, round(cum[i + 1] - cum[i], 8)) for i in range(len(e) - 1)]
    k = max(range(len(fr)), key=fr.__getitem__)       # rounding remainder goes to the largest bin (never negative)
    fr[k] = round(fr[k] + (1.0 - sum(fr)), 8)
    return fr


def percentile_mm(fractions: list[float], p: float, cfg: dict | None = None) -> float:
    """Size (mm) below which a fraction p of the mass lies; linear interpolation on the mesh (same as Aspen's D80)."""
    e = (cfg or CONFIG)["edges_mm"]
    total, cum = sum(fractions), 0.0
    for lo, hi, f in zip(e, e[1:], fractions):
        if f > 0 and cum + f >= p * total:
            return lo + (hi - lo) * (p * total - cum) / f
        cum += f
    return float(e[-1])


def fines_fraction(fractions: list[float], cfg: dict | None = None) -> float:
    """Mass fraction below cfg['fines_mm'] (must be a mesh edge)."""
    cfg = cfg or CONFIG
    e = cfg["edges_mm"]
    k = e.index(cfg["fines_mm"])
    return sum(fractions[:k])


def specific_energy_kwh_t(f80_mm: float, p80_mm: float, wi: float) -> float:
    """Bond specific energy, kWh per metric tonne. Zero if there is no size reduction."""
    w = 10.0 * wi * (1.0 / math.sqrt(p80_mm * 1000.0) - 1.0 / math.sqrt(f80_mm * 1000.0))  # kWh/short ton
    return max(0.0, w) * 1000.0 / SHORT_TON_KG


def calibrate_wi(target_kwh_t: float, cfg: dict | None = None) -> float:
    """Effective Wi (kWh/short ton) that gives `target_kwh_t` at the reference duty."""
    cfg = cfg or CONFIG
    p80 = percentile_mm(psd(cfg["ref_gap_mm"], cfg["ref_top_mm"], cfg), 0.8, cfg)
    unit = specific_energy_kwh_t(cfg["ref_f80_mm"], p80, 1.0)
    return target_kwh_t / unit


# per-polymer effective Wi. No polymer-specific data exists, so all three share the calibrated value (ASSUMPTION).
WI_EFF = calibrate_wi(CONFIG["target_kwh_per_t"])
WI_POLYMER = {"PET": WI_EFF, "HDPE": WI_EFF, "PP": WI_EFF}


def mixture_wi(mass_fractions: dict[str, float], wi: dict[str, float] | None = None) -> float:
    wi = wi or WI_POLYMER
    tot = sum(mass_fractions.values())
    return sum(wi[c] * m for c, m in mass_fractions.items()) / tot


def power_kw(throughput_kg_h: float, f80_mm: float, product_psd: list[float],
             mass_fractions: dict[str, float], wi: dict[str, float] | None = None) -> float:
    """Crusher power (kW) = specific energy (kWh/t) x throughput (t/h). Throughput includes the recycle."""
    p80 = percentile_mm(product_psd, 0.8)
    s = specific_energy_kwh_t(f80_mm, p80, mixture_wi(mass_fractions, wi))
    return s * throughput_kg_h / 1000.0


if __name__ == "__main__":
    print(f"calibrated effective Wi = {WI_EFF:.1f} kWh/short ton (target {CONFIG['target_kwh_per_t']} kWh/t at "
          f"F80 {CONFIG['ref_f80_mm']} mm, gap {CONFIG['ref_gap_mm']} mm)")
    for lo_hi, t in (("low", CONFIG["target_low"]), ("high", CONFIG["target_high"])):
        print(f"  {lo_hi}: Wi = {calibrate_wi(t):.1f} for {t} kWh/t")
    print(f"{'gap':>5} {'P80':>6} {'fines<2':>8} {'kWh/t':>7}   PSD")
    for g in (4, 6, 8, 10, 12, 14, 16):
        p = psd(g)
        print(f"{g:>5} {percentile_mm(p, .8):>6.2f} {100*fines_fraction(p):>7.1f}% "
              f"{specific_energy_kwh_t(45.35, percentile_mm(p, .8), WI_EFF):>7.1f}   {[round(x, 3) for x in p]}")
