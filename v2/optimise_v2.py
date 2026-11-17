"""Optimiser: search the surrogate (and, for the money objectives, the sizing and cost model), then (separately) confirm in Aspen.

Objectives: energy (default, J = crusher kWh per tonne of fresh feed + W_TAU * residence_time), payback, profit (annual net cash) or recovery. Energy shown below as the original form:
Minimise  J = crusher kWh per tonne of fresh feed + W_TAU * residence_time   (the tau term is only a tie-breaker)
over   crusher gap, SCREEN1 cut, SCREEN2 cut, residence time  (the tank spread is an assumption, NOT a decision variable)
subject to the customer requirements:
    d50 of the COARSE stream inside [d50_min, d50_max]  (product size range)
    PET purity in DENSE >= PET_purity_min,  PE/PP purity in LIGHT >= PE_PP_purity_min
    PET recovery >= PET_recovery_min (%),   PE/PP recovery >= PEPP_recovery_min (%)
Constraints are tightened by `safety` x the cross-validation RMSE of the surrogate for that output (default 1), so the optimum is not sitting on a
surrogate error. Returns status "infeasible" (never a fake answer) when no point satisfies all constraints.
Search: random Latin-hypercube points (vectorised surrogate) -> best feasible -> shrinking-step random local search.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import surrogate_v2 as S  # noqa: E402

W_TAU = 0.05            # kWh/t per second of residence time: tie-breaker, ASSUMPTION (placeholder for tank cost)
DECISION = ("gap", "s1", "s2", "tau")
LIMITS = {"d50_min": ("d50_coarse_mm", ">="), "d50_max": ("d50_coarse_mm", "<="), "PET_purity_min": ("PET_purity_dense", ">="),
          "PE_PP_purity_min": ("PE_PP_purity_light", ">="), "PET_recovery_min": ("PET_recovery_pct", ">="), "PEPP_recovery_min": ("PEPP_recovery_pct", ">=")}
SCALE = {"d50_coarse_mm": 1.0, "PET_purity_dense": 0.01, "PE_PP_purity_light": 0.01, "PET_recovery_pct": 1.0, "PEPP_recovery_pct": 1.0}   # violation scale (units)


def _load_cv() -> dict:
    return json.loads(S.MODEL_JSON.read_text()).get("cv", {})


def _eval(model: S.Surrogate, x: np.ndarray, pet: float, sigma: float, feed: float) -> dict:
    return model.predict(pet, x[:, 0], x[:, 1], x[:, 2], x[:, 3], sigma, feed)


def _violation(pred: dict, cons: dict, margin: dict) -> np.ndarray:
    """Largest normalised violation per point (<= 0 means feasible)."""
    v = None
    for name, val in cons.items():
        key, sense = LIMITS[name]
        m = margin.get(key, 0.0)
        g = (val + m - pred[key]) if sense == ">=" else (pred[key] - (val - m))
        g = g / SCALE[key]
        v = g if v is None else np.maximum(v, g)
    return v if v is not None else np.full(pred["recycle_ratio"].shape, -1.0)


OBJECTIVES = ("energy", "payback", "profit", "recovery")


def _objective(pred: dict, x: np.ndarray) -> np.ndarray:
    return pred["crusher_kWh_per_tonne_feed"] + W_TAU * x[:, 3]


def optimise(pet: float, constraints: dict, spread: float = 0.5, feed: float = S.FEED_DEFAULT, safety: float = 1.0,
             n_samples: int = 60000, seed: int = 7, model: S.Surrogate | None = None,
             objective: str = "energy", plant_feed_kg_h: float | None = None, hours_per_year: float = 2000.0,
             budget: float | None = None, target: str = "pet", location: dict | None = None, scenario: int = 1) -> dict:
    """objective: 'energy' (lowest crusher kWh/t, the original), 'payback' (shortest simple payback), 'profit' (highest annual net cash),
    'recovery' (highest recovery of the preferred product). The money objectives use the real feed rate (`plant_feed_kg_h`), operating hours,
    prices (current cost.COSTS) and equipment sizes (motor steps, screen area, tank volume), so the best settings can change with them.
    `budget` (USD) is a constraint on the installed capex of the chosen scenario (0 optimistic, 1 base, 2 pessimistic)."""
    import cost_v2 as cs
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}")
    plant_feed = feed if plant_feed_kg_h is None else float(plant_feed_kg_h)
    lo_p, hi_p = S.BOUNDS["pet"]
    if not lo_p <= pet <= hi_p:
        raise ValueError(f"PET fraction {pet} % is outside the modelled range {lo_p}-{hi_p} %")
    if not np.exp(S.BOUNDS["lnsig"][0]) - 1e-12 <= spread <= np.exp(S.BOUNDS["lnsig"][1]) + 1e-12:
        raise ValueError("tank spread outside 0.25-1.0")
    bad = [k for k in constraints if k not in LIMITS]
    if bad:
        raise ValueError(f"unknown constraints {bad}; allowed {sorted(LIMITS)}")
    model = model or S.Surrogate.load()
    cv = _load_cv()
    margin = {LIMITS[n][0]: safety * cv.get(LIMITS[n][0], {}).get("rmse", 0.0) for n in constraints}
    rec_key = "PET_recovery_pct" if target == "pet" else "PEPP_recovery_pct"
    need_econ = objective in ("payback", "profit") or budget is not None
    b = [S.BOUNDS[k] for k in DECISION]

    def evaluate(x):
        p = _eval(model, x, pet, spread, feed)
        v = _violation(p, constraints, margin)
        e = cs.economics_vec(p, x, pet, plant_feed, hours_per_year, scenario, location) if need_econ else None
        if budget is not None:
            v = np.maximum(v, (e["capex_usd"] - budget) / (0.01 * max(budget, 1.0)))     # 1 unit = 1 % over budget
        if objective == "energy":
            o = _objective(p, x)
        elif objective == "recovery":
            o = -p[rec_key] + 1e-3 * _objective(p, x)
        elif objective == "profit":
            o = -e["net_usd_per_year"] - 0.01 * p[rec_key]               # tie-break: equal money -> higher recovery of the preferred product
        else:   # payback: any positive cash flow beats none; with no payback, the larger (less negative) net cash ranks first
            o = np.where(np.isfinite(e["payback_years"]), e["payback_years"], 1e6 - e["net_usd_per_year"] / 1e3) - 1e-4 * p[rec_key]
        return p, v, o, e

    rng = np.random.default_rng(seed)
    u = np.column_stack([rng.permutation((np.arange(n_samples) + rng.random(n_samples)) / n_samples) for _ in DECISION])
    x = np.column_stack([b[j][0] + u[:, j] * (b[j][1] - b[j][0]) for j in range(4)])
    viol = np.empty(n_samples); obj = np.empty(n_samples)
    for i in range(0, n_samples, 20000):
        _, viol[i:i + 20000], obj[i:i + 20000], _ = evaluate(x[i:i + 20000])
    feas = viol <= 0
    if not feas.any():
        j = int(np.argmin(viol))
        return {"status": "infeasible", "message": "no setting inside the variable ranges satisfies all constraints (with the surrogate safety margin)",
                "closest_point": dict(zip(DECISION, x[j].round(3).tolist())), "closest_worst_violation_normalised": float(viol[j]),
                "constraints": constraints, "safety": safety, "pet": pet, "spread": spread, "objective_name": objective}
    k = int(np.argmin(np.where(feas, obj, np.inf)))
    best_x, best_j = x[k].copy(), float(obj[k])
    span = np.array([bb[1] - bb[0] for bb in b])
    lo = np.array([bb[0] for bb in b]); hi = np.array([bb[1] for bb in b])
    for step in (0.10, 0.05, 0.02, 0.01, 0.005, 0.002):
        improved = True
        while improved:
            improved = False
            cand = np.clip(best_x + rng.normal(0, step, (800, 4)) * span, lo, hi)
            _, v, o, _ = evaluate(cand)
            ok = (v <= 0) & (o < best_j - 1e-9)
            if ok.any():
                kk = int(np.argmin(np.where(ok, o, np.inf)))
                best_x, best_j, improved = cand[kk].copy(), float(o[kk]), True
    p1, _, _, e1 = evaluate(best_x[None, :])
    pred = {k_: float(v_[0]) for k_, v_ in p1.items()}
    out = {"status": "ok", "pet": pet, "composition": S.composition_from_pet(pet), "spread": spread, "feed": feed,
           "variables": {"crusher_gap_mm": round(float(best_x[0]), 3), "screen1_cut_mm": round(float(best_x[1]), 3),
                         "screen2_cut_mm": round(float(best_x[2]), 3), "residence_time_s": round(float(best_x[3]), 3)},
           "objective": best_j, "objective_name": objective, "predicted": pred, "constraints": constraints, "safety": safety,
           "n_feasible_of_random": int(feas.sum()), "n_random": n_samples}
    if e1 is not None:
        out["economics_scenario"] = {"capex_usd": float(e1["capex_usd"][0]), "net_usd_per_year": float(e1["net_usd_per_year"][0]),
                                     "payback_years": None if not np.isfinite(e1["payback_years"][0]) else float(e1["payback_years"][0])}
    return out


# ------------------------------------------------------------------ Aspen confirmation (needs Aspen closed everywhere else)
def confirm_in_aspen(solution: dict) -> dict:
    """Run the optimum once in Aspen (two-pass, as in the sweep). Returns the Aspen default-spread row."""
    import aspen_io_v2 as io
    import config_v2 as C
    import sweep_v2 as sw
    pet = solution["pet"]
    sw.COMPOSITIONS["OPT"] = S.composition_from_pet(pet)
    v = solution["variables"]
    case = {"case_id": "OPT-001", "composition_tag": "OPT", "design": "optimum", "feed_rate": solution["feed"], "crusher_gap_mm": v["crusher_gap_mm"],
            "screen1_cut_mm": v["screen1_cut_mm"], "screen2_cut_mm": v["screen2_cut_mm"], "residence_time_s": v["residence_time_s"]}
    from tank_v2 import CONFIG as TK
    TK_SPREAD = TK["spread"]
    TK["spread"] = solution["spread"]
    try:
        with io.open_case(sw.CASE_FILE) as s:
            rows, why = sw.run_case(s, case, False, [])
    finally:
        TK["spread"] = TK_SPREAD
    if not rows:
        return {"status": "aspen_failed", "reason": why}
    row = next(r for r in rows if r["spread_level"] == "default")     # default row = Aspen run at the requested spread
    return {"status": "ok", "row": row}
