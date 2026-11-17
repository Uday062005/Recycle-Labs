"""Python replica of the Aspen flowsheet (crusher -> SCREEN1 with oversize recycle -> SCREEN2 -> sink-float split).

Aspen's CRUSH block gives a fixed product size distribution (set from the gap), SCREEN1/SCREEN2 apply the Plitt curve at the interval midpoint,
and DENSEP applies the split computed by tank.py. The recycle loop therefore has a closed form (the crusher product does not depend on what enters it).
scripts/validate_emulator.py compares every output with the Aspen rows in data/results_v2_lhs.csv (and results_wide.csv when present).

emulate(...) returns one dict per call (flows in kg/h, purities as fractions, recoveries in %), using the same column names as the sweep CSV.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crusher_v2 as cr  # noqa: E402
import tank_v2 as tk  # noqa: E402

EDGES = [0, 2, 5, 8, 12, 20, 40, 80]
MID = [(a + b) / 2.0 for a, b in zip(EDGES, EDGES[1:])]
FEED_PSD = [0.0, 0.0, 0.0, 0.0, 0.05, 0.45, 0.50]       # fixed feed size distribution (12-20 / 20-40 / 40-80 mm)
SHARPNESS = 8.0                                         # Plitt sharpness of both screens (ASSUMPTION, as in the Aspen case)


def plitt(d: float, cut: float, m: float = SHARPNESS) -> float:
    return 1.0 - math.exp(-math.log(2.0) * (d / cut) ** m)


def emulate(pet_pct: float, hdpe_pct: float, pp_pct: float, gap: float, s1: float, s2: float, tau: float, spread: float = 0.5,
            feed: float = 300.0) -> dict:
    share = {"PET": pet_pct / 100.0, "HDPE": hdpe_pct / 100.0, "PP": pp_pct / 100.0}
    p = cr.psd(gap)
    e1_i = [plitt(d, s1) for d in MID]
    e2_i = [plitt(d, s2) for d in MID]
    e1 = sum(a * b for a, b in zip(p, e1_i))                         # share of crusher product that is oversize
    thr = feed / (1.0 - e1)                                          # crusher throughput (fresh feed + recycle)
    oversize = thr - feed
    under = [a * (1.0 - b) / (1.0 - e1) for a, b in zip(p, e1_i)]    # SCREEN1 undersize PSD (flow = feed)
    cf = sum(a * b for a, b in zip(under, e2_i))                     # share of undersize that is coarse
    coarse = feed * cf
    fines = feed - coarse
    q = [a * b / cf for a, b in zip(under, e2_i)]                    # COARSE PSD
    over_psd = [a * b / e1 for a, b in zip(p, e1_i)]
    mix = [(feed * a + oversize * b) / thr for a, b in zip(FEED_PSD, over_psd)]
    f80 = cr.percentile_mm(mix, 0.8)
    power = cr.power_kw(thr, f80, p, {c: 100.0 * v for c, v in share.items()})
    coarse_c = {c: feed * share[c] * cf for c in share}
    split = tk.overall_split(q, comp=coarse_c, residence_s=tau, spread=spread)
    dense_c = {c: coarse_c[c] * split[c] for c in share}
    light_c = {c: coarse_c[c] - dense_c[c] for c in share}
    feed_c = {c: feed * share[c] for c in share}
    met = tk.separation_metrics(dense_c, light_c, feed_c)
    dense, light = sum(dense_c.values()), sum(light_c.values())
    return {
        "oversize_flow": oversize, "recycle_ratio": oversize / feed, "under1_flow": feed, "coarse_flow": coarse, "fines_flow": fines,
        "dense_flow": dense, "light_flow": light, "split_PET_dense": split["PET"], "split_HDPE_dense": split["HDPE"], "split_PP_dense": split["PP"],
        **{f"dense_{c}_flow": dense_c[c] for c in share}, **{f"light_{c}_flow": light_c[c] for c in share},
        **met, "yield_pct": 100.0 * (dense + light) / feed, "fines_loss_pct": 100.0 * fines / feed,
        "d50_coarse_mm": cr.percentile_mm(q, 0.5), "crusher_throughput_kg_h": thr, "crusher_F80_mm": f80, "crusher_P80_mm": cr.percentile_mm(p, 0.8),
        "crusher_power_kW": power, "crusher_kWh_per_tonne_feed": power / (feed / 1000.0),
    }


# ---------------------------------------------------------------- vectorised model (same equations, many points at once)
import numpy as np  # noqa: E402

_ERF = np.vectorize(math.erf, otypes=[float])


def _pct(P: "np.ndarray", q: float) -> "np.ndarray":
    """Size below which a fraction q of the mass lies, linear inside the interval (same rule as crusher.percentile_mm), for rows of P."""
    tot = P.sum(axis=1)
    tgt = q * tot
    cum = np.cumsum(P, axis=1)
    mask = (P > 0) & (cum >= tgt[:, None])
    idx = np.where(mask.any(axis=1), mask.argmax(axis=1), len(EDGES) - 2)
    rows = np.arange(len(P))
    lo = np.array(EDGES[:-1], float)[idx]
    hi = np.array(EDGES[1:], float)[idx]
    prev = cum[rows, idx] - P[rows, idx]
    return np.where(mask.any(axis=1), lo + (hi - lo) * (tgt - prev) / np.maximum(P[rows, idx], 1e-300), float(EDGES[-1]))


class PhysicsModel:
    """The Python replica of the Aspen flowsheet, vectorised. predict() has the same arguments and result keys as surrogate.Surrogate.predict, but there is
    no regression error: it reproduces the Aspen results to about 1e-4 (scripts/validate_model.py). Valid inside surrogate.BOUNDS (the simulated ranges)."""

    def __init__(self):
        cfg = tk.CONFIG
        self.cfg = cfg
        d_m = [d / 1000.0 for d in tk.midpoints_mm(cfg)]
        self.vt, self.nrz = {}, {}
        for polymer, rho in cfg["densities"].items():
            vre = [tk.terminal_velocity(rho, d, cfg["sphericity"], cfg["temp_C"]) for d in d_m]
            self.vt[polymer] = np.array([v for v, _ in vre])
            self.nrz[polymer] = np.array([tk.richardson_zaki_n(re) for _, re in vre])

    def predict(self, pet, gap, s1, s2, tau, sigma=0.5, feed: float = 300.0) -> dict:
        pet, gap, s1, s2, tau, sigma = np.broadcast_arrays(*[np.atleast_1d(np.asarray(v, float)) for v in (pet, gap, s1, s2, tau, sigma)])
        n = pet.size
        cfg = self.cfg
        # crusher product (Rosin-Rammler, truncated at the 80 mm feed top size)
        e = np.array(EDGES, float)
        f = lambda x: 1.0 - np.exp(-((np.minimum(x, 80.0)[None, :] / gap[:, None]) ** cr.CONFIG["rr_n"]))  # noqa: E731
        cum = np.minimum(1.0, f(e) / f(np.array([80.0]))[:, :1])
        cum[:, 0] = 0.0
        p = np.diff(cum, axis=1)
        mid = np.array(MID)[None, :]
        e1_i = 1.0 - np.exp(-math.log(2.0) * (mid / s1[:, None]) ** SHARPNESS)
        e2_i = 1.0 - np.exp(-math.log(2.0) * (mid / s2[:, None]) ** SHARPNESS)
        e1 = np.maximum((p * e1_i).sum(axis=1), 1e-12)
        thr = feed / (1.0 - e1)
        oversize = thr - feed
        under = p * (1.0 - e1_i) / (1.0 - e1)[:, None]
        cf = (under * e2_i).sum(axis=1)
        coarse = feed * cf
        fines = feed - coarse
        q = under * e2_i / cf[:, None]
        over_psd = p * e1_i / e1[:, None]
        mix = (feed * np.array(FEED_PSD)[None, :] + oversize[:, None] * over_psd) / thr[:, None]
        f80, p80 = _pct(mix, 0.8), _pct(p, 0.8)
        wi = cr.WI_EFF
        spec = np.maximum(0.0, 10.0 * wi * (1.0 / np.sqrt(p80 * 1000.0) - 1.0 / np.sqrt(f80 * 1000.0))) * 1000.0 / cr.SHORT_TON_KG
        power = spec * thr / 1000.0
        # composition on the line used by the sweeps, and the solids volume fraction of the tank slurry
        hdpe = 40.0 - (pet - 30.0) * 2.0 / 3.0
        share = {"PET": pet / 100.0, "HDPE": hdpe / 100.0, "PP": (100.0 - pet - hdpe) / 100.0}
        rho_s = 1.0 / sum(share[c] / cfg["densities"][c] for c in share)
        vs = cfg["solids_mass_frac"] / rho_s
        vw = (1.0 - cfg["solids_mass_frac"]) / tk.water_density(cfg["temp_C"])
        phi = vs / (vs + vw)
        vcrit = (cfg["depth_m"] / tau)[:, None]
        split = {}
        for c in share:
            vh = self.vt[c][None, :] * (1.0 - phi)[:, None] ** self.nrz[c][None, :]
            z = (vh - vcrit) / vcrit
            part = 0.5 * (1.0 + _ERF(z / sigma[:, None] / math.sqrt(2.0)))
            split[c] = np.clip((q * np.clip(part, 0.0, 1.0)).sum(axis=1), 0.0, 1.0)
        coarse_c = {c: feed * share[c] * cf for c in share}
        dense_c = {c: coarse_c[c] * split[c] for c in share}
        light_c = {c: coarse_c[c] - dense_c[c] for c in share}
        dense, light = sum(dense_c.values()), sum(light_c.values())
        feed_pet = feed * share["PET"]
        pepp_feed = feed * (share["HDPE"] + share["PP"])
        return {
            "oversize_flow": oversize, "recycle_ratio": oversize / feed, "fines_flow": fines, "fines_loss_pct": 100.0 * fines / feed,
            "dense_flow": dense, "light_flow": light, "yield_pct": 100.0 * (dense + light) / feed,
            "split_PET_dense": split["PET"], "split_HDPE_dense": split["HDPE"], "split_PP_dense": split["PP"],
            "PET_purity_dense": dense_c["PET"] / dense, "PE_PP_purity_light": (light_c["HDPE"] + light_c["PP"]) / light,
            "PET_recovery_pct": 100.0 * dense_c["PET"] / feed_pet, "PEPP_recovery_pct": 100.0 * (light_c["HDPE"] + light_c["PP"]) / pepp_feed,
            "PET_loss_to_light_pct": 100.0 * light_c["PET"] / feed_pet, "PEPP_loss_to_dense_pct": 100.0 * (dense_c["HDPE"] + dense_c["PP"]) / pepp_feed,
            "d50_coarse_mm": _pct(q, 0.5), "crusher_F80_mm": f80, "crusher_P80_mm": p80,
            "crusher_throughput_kg_h": thr, "crusher_power_kW": power, "crusher_kWh_per_tonne_feed": power / (feed / 1000.0),
        }
