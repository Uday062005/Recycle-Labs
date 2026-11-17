"""ReSort v2 website backend (Starlette). Read-only: serves the UI, the Aspen-based database summary and a proposal calculator.

No Aspen connection at request time, no upload endpoint, no database credentials. The proposal comes from the surrogate (surrogate),
the optimiser (optimise), the sizing model (sizing) and the cost model (cost), all fitted/validated on the v2 Aspen sweep.

Run (aspen-mcp venv has numpy, starlette, uvicorn):
    aspen-mcp\\.venv\\Scripts\\python.exe -m uvicorn server:app --app-dir website --port 8000
"""
from __future__ import annotations

import csv
import json
import math
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import cost_v2 as cs  # noqa: E402
import optimise_v2 as op  # noqa: E402
import sizing_v2 as sz  # noqa: E402
import surrogate_v2 as S  # noqa: E402
import tank_v2 as tk  # noqa: E402

DATA_CSVS = [S.DATA, S.DATA.with_name("results_wide.csv")]     # real Aspen sweeps (the second one is the wide-range sweep)
MODEL = S.load_model()
CV = json.loads(S.MODEL_JSON.read_text())["cv"]
SPREADS = {"low": tk.CONFIG["spread_low"], "default": tk.CONFIG["spread"], "high": tk.CONFIG["spread_high"]}
FEED_RANGE = (100.0, 500.0)
VAR_NAMES = {"crusher_gap_mm": "gap", "screen1_cut_mm": "s1", "screen2_cut_mm": "s2", "residence_time_s": "tau"}
PRICE_MAP = {"dense_usd_t": "price_dense_usd_t", "light_usd_t": "price_light_usd_t", "scrap_usd_t": "price_scrap_usd_t",
             "electricity_usd_kwh": "electricity_usd_kWh", "wage_usd_h": "wage_usd_h"}
SHOW = ["PET_purity_dense", "PE_PP_purity_light", "PET_recovery_pct", "PEPP_recovery_pct", "PET_loss_to_light_pct", "PEPP_loss_to_dense_pct",
        "yield_pct", "fines_loss_pct", "recycle_ratio", "d50_coarse_mm", "crusher_kWh_per_tonne_feed"]
LIMITS = [
    "PRELIMINARY proposal, not a guarantee and not an equipment quotation.",
    "Purity and recovery depend on assumed sink-float tank parameters (residence time, depth, turbulence spread, flake shape); see the spread sensitivity.",
    "Crusher energy is calibrated to one vendor claim (20-50 kWh/t); no measured plastic work index is available.",
    "Capex is a +-30 % class estimate at best; granulator prices vary 2-5x between vendors. Prices, scrap cost, utilities and wages are assumptions you can replace.",
    "Washing, drying, colour/metal sorting, contamination losses, selling costs, working capital, tax and financing are not modelled.",
    "PVC and PS are not modelled; in water they would sink with PET and cannot be separated from it by sink-float.",
    "Feed particle size distribution is fixed in the simulations; composition is described by the PET share (20-70 %) with HDPE:PP following the simulated mixes.",
]
_LOCK = threading.Lock()


class ValidationError(Exception):
    def __init__(self, errors: list[dict]):
        self.errors = errors


def _num(v, field: str, errs: list, lo=None, hi=None, optional=False, lo_open=False, msg: str | None = None):
    if v is None or v == "":
        if optional:
            return None
        errs.append({"field": field, "message": msg or f"{field} is required."})
        return None
    if isinstance(v, bool):
        errs.append({"field": field, "message": msg or f"{field} must be a number."})
        return None
    try:
        x = float(v)
        if not math.isfinite(x):
            raise ValueError
    except (TypeError, ValueError):
        errs.append({"field": field, "message": msg or f"{field} must be a number."})
        return None
    if (lo is not None and (x <= lo if lo_open else x < lo)) or (hi is not None and x > hi):
        errs.append({"field": field, "message": msg or f"{field} is outside the allowed range."})
        return None
    return x


def validate(req: dict) -> tuple[dict, list, list]:
    """Returns (clean inputs, errors, warnings). Errors are {field, message} with plain-language messages."""
    if not isinstance(req, dict):
        raise ValidationError([{"field": "body", "message": "Request must be a JSON object."}])
    errs: list[dict] = []
    warns: list[str] = []
    c: dict = {}
    c["feed"] = _num(req.get("feed_rate_kg_h"), "feed_rate_kg_h", errs, FEED_RANGE[0], FEED_RANGE[1],
                     msg=f"Feed rate must be a number between {FEED_RANGE[0]:.0f} and {FEED_RANGE[1]:.0f} kg/h (the range covered by the simulations).")
    hpd = _num(req.get("hours_per_day", 8), "hours_per_day", errs, 0, 24, lo_open=True, msg="Operating hours per day must be greater than 0 and at most 24.")
    dpy = _num(req.get("days_per_year", 250), "days_per_year", errs, 0, 366, lo_open=True, msg="Operating days per year must be greater than 0 and at most 366.")
    c["hours_per_year"] = hpd * dpy if hpd and dpy else None
    if c["hours_per_year"] and c["hours_per_year"] > 8760:
        errs.append({"field": "hours_per_day", "message": "Hours per day x days per year exceeds the 8,760 hours in a year."})
    comp = req.get("composition")
    if not isinstance(comp, dict):
        errs.append({"field": "composition", "message": "Composition (PET, HDPE, PP mass %) is required."})
    else:
        vals = {k: _num(comp.get(k), f"composition.{k}", errs, 0, 100, msg=f"{k} share must be a number between 0 and 100 %.") for k in ("PET", "HDPE", "PP")}
        if all(v is not None for v in vals.values()):
            tot = sum(vals.values())
            if abs(tot - 100.0) > 0.01:
                errs.append({"field": "composition", "message": f"Polymer shares must total 100 % (they total {tot:.2f} %)."})
            lo, hi = S.BOUNDS["pet"]
            if not lo <= vals["PET"] <= hi:
                errs.append({"field": "composition.PET", "message": f"PET share must be between {lo:.0f} % and {hi:.0f} % (the range covered by the simulations); you entered {vals['PET']:g} %."})
            else:
                line = S.composition_from_pet(vals["PET"])
                if abs(vals["HDPE"] - line["HDPE"]) > 5.0:
                    warns.append(f"The model describes the mix by its PET share only; at {vals['PET']:g} % PET it assumes about {line['HDPE']:.0f} % HDPE and {line['PP']:.0f} % PP. Your split differs, so treat the result as indicative.")
            c["pet"] = vals["PET"]
    top = _num(req.get("feed_top_size_mm"), "feed_top_size_mm", errs, 0, None, optional=True, lo_open=True, msg="Feed top particle size must be greater than 0 mm.")
    if top is not None:
        warns.append(f"Feed particle size is fixed in the simulations (top size 80 mm); your value of {top:g} mm was noted but not used.")
    d50lo = _num(req.get("product_d50_min_mm"), "product_d50_min_mm", errs, 0, None, lo_open=True, msg="Minimum product d50 (mm) is required and must be greater than 0.")
    d50hi = _num(req.get("product_d50_max_mm"), "product_d50_max_mm", errs, 0, None, lo_open=True, msg="Maximum product d50 (mm) is required and must be greater than 0.")
    if d50lo is not None and d50hi is not None and d50lo > d50hi:
        errs.append({"field": "product_d50_min_mm", "message": "Minimum product d50 must not exceed the maximum."})
    c["d50_min"], c["d50_max"] = d50lo, d50hi
    c["target"] = req.get("target", "pet")
    if c["target"] not in ("pet", "light"):
        errs.append({"field": "target", "message": "Preferred output must be 'pet' (PET-rich flakes) or 'light' (PP + HDPE-rich flakes)."})
    c["purity"] = _num(req.get("min_purity_pct"), "min_purity_pct", errs, 0, 100, optional=True, msg="Minimum purity must be between 0 and 100 %.")
    c["recovery"] = _num(req.get("min_recovery_pct"), "min_recovery_pct", errs, 0, 100, optional=True, msg="Minimum recovery must be between 0 and 100 %.")
    c["budget"] = _num(req.get("budget_usd"), "budget_usd", errs, 0, None, optional=True, msg="Budget must be 0 or more.")
    loc = req.get("location_factors") or {}
    c["location"] = {}
    for k, label in (("capex_factor", "Capex factor"), ("labour_factor", "Labour factor"), ("electricity_factor", "Electricity factor"), ("water_factor", "Water factor")):
        v = _num(loc.get(k), f"location_factors.{k}", errs, 0, 10, optional=True, lo_open=True, msg=f"{label} must be greater than 0 and at most 10.")
        if v is not None:
            c["location"][k] = v
    c["prices"] = {}
    for k in PRICE_MAP:
        v = _num((req.get("prices") or {}).get(k), f"prices.{k}", errs, 0, None, optional=True, msg=f"Price/cost '{k}' must be a number, 0 or more.")
        if v is not None:
            c["prices"][k] = v
    c["objective"] = req.get("objective", "payback")
    if c["objective"] not in op.OBJECTIVES:
        errs.append({"field": "objective", "message": "objective must be one of: payback (shortest payback), profit (highest annual net cash), recovery (highest recovery of the preferred product) or energy (lowest crusher energy)."})
    c["mode"] = req.get("mode", "optimise")
    if c["mode"] not in ("optimise", "evaluate"):
        errs.append({"field": "mode", "message": "mode must be 'optimise' or 'evaluate'."})
    c["spread"] = SPREADS["default"]
    if req.get("tank_spread") is not None:
        c["spread"] = _num(req["tank_spread"], "tank_spread", errs, SPREADS["low"], SPREADS["high"], msg=f"Tank spread must be between {SPREADS['low']} and {SPREADS['high']}.")
    c["variables"] = None
    if c["mode"] == "evaluate":
        v = req.get("variables")
        if not isinstance(v, dict):
            errs.append({"field": "variables", "message": "Evaluate mode needs the four settings (crusher_gap_mm, screen1_cut_mm, screen2_cut_mm, residence_time_s)."})
        else:
            c["variables"] = {}
            for name, short in VAR_NAMES.items():
                lo, hi = S.BOUNDS[short]
                x = _num(v.get(name), f"variables.{name}", errs, lo, hi, msg=f"{name} must be between {lo:g} and {hi:g} (the range covered by the simulations).")
                if x is not None:
                    c["variables"][name] = x
    if req.get("location_text"):
        warns.append("Location text is not used by the model; set the cost factors to reflect your location.")
    return c, errs, warns


@contextmanager
def price_overrides(prices: dict):
    """Temporarily replace cost constants by customer-supplied values (low = base = high). Locked: one request at a time."""
    with _LOCK:
        saved = dict(cs.COSTS)
        try:
            for k, v in prices.items():
                name = PRICE_MAP[k]
                cs.COSTS[name] = (v, v, v, cs.COSTS[name][3] + " [customer-supplied value]")
            yield
        finally:
            cs.COSTS.clear()
            cs.COSTS.update(saved)


def _pm(key: str, val: float) -> dict:
    """Value with +-2 x cross-validation RMSE, clipped to the physical range."""
    d = 2.0 * CV[key]["rmse"]
    lo, hi = val - d, val + d
    if key.endswith("_pct"):
        lo, hi = max(0.0, lo), min(100.0, hi)
    if "purity" in key:
        lo, hi = max(0.0, lo), min(1.0, hi)
    return {"value": val, "low": lo, "high": hi}


def achievable(pet: float, n: int = 30000) -> dict:
    """Best values reachable inside the modelled ranges (used to explain an infeasible request)."""
    rng = np.random.default_rng(3)
    b = [S.BOUNDS[k] for k in op.DECISION]
    x = np.column_stack([rng.uniform(*bb, n) for bb in b])
    p = op._eval(MODEL, x, pet, SPREADS["default"], 300.0)
    return {"max_PET_purity_pct": 100 * float(p["PET_purity_dense"].max()), "max_PE_PP_purity_pct": 100 * float(p["PE_PP_purity_light"].max()),
            "max_PET_recovery_pct": float(p["PET_recovery_pct"].max()), "max_PEPP_recovery_pct": float(p["PEPP_recovery_pct"].max()),
            "d50_range_mm": [float(p["d50_coarse_mm"].min()), float(p["d50_coarse_mm"].max())]}


LABELS = {"d50_min": "Minimum product d50", "d50_max": "Maximum product d50", "PET_purity_min": "PET purity", "PE_PP_purity_min": "PE/PP purity",
          "PET_recovery_min": "PET recovery", "PEPP_recovery_min": "PE/PP recovery"}
OBJ_TEXT = {"payback": "shortest payback", "profit": "highest annual profit", "recovery": "highest product recovery", "energy": "lowest crusher energy"}


def explain(c: dict, v: dict, met: dict, warns: list) -> list[str]:
    """Plain-language reasons for the returned settings: the active (binding) requirements and what does not move them."""
    if c["mode"] != "optimise":
        return ["These are the settings you entered; the numbers are predictions for them, not an optimum."]
    cv = op._load_cv()
    why = [f"Search goal: {OBJ_TEXT[c['objective']]}, with all your requirements met."]
    active = []
    for name, m in met.items():
        key, _sense = op.LIMITS[name]
        slack = abs(m["predicted"] - m["required"]) / op.SCALE[key]
        if slack <= 1.6 * cv.get(key, {}).get("rmse", 0.0) / op.SCALE[key] + 1e-3:
            active.append(LABELS[name])
    if active:
        why.append("These requirements are active (the settings sit exactly at their limit): " + ", ".join(active) + ".")
    else:
        why.append("None of your requirements is tight, so the goal alone decides the settings.")
    for name, short in VAR_NAMES.items():
        lo, hi = S.BOUNDS[short]
        if v[name] <= lo + 0.01 * (hi - lo) or v[name] >= hi - 0.01 * (hi - lo):
            why.append(f"{name.replace('_', ' ')} is at the edge of the simulated range ({lo:g}-{hi:g}): in this model a setting beyond it would help further, but it was not simulated.")
    why.append("Feed rate, operating hours and polymer mix change flows, equipment size, cost and payback below. They do not change the best settings per kilogram, because flows and power scale linearly with feed rate.")
    return why


def make_proposal(req: dict) -> dict:
    c, errs, warns = validate(req)
    if errs:
        raise ValidationError(errs)
    pet = c["pet"]
    cons: dict = {}
    if c["d50_min"] is not None:
        cons["d50_min"] = c["d50_min"]
    if c["d50_max"] is not None:
        cons["d50_max"] = c["d50_max"]
    pk, rk = ("PET_purity_min", "PET_recovery_min") if c["target"] == "pet" else ("PE_PP_purity_min", "PEPP_recovery_min")
    if c["purity"] is not None:
        cons[pk] = c["purity"] / 100.0
    if c["recovery"] is not None:
        cons[rk] = c["recovery"]
    out = {"status": "ok", "mode": c["mode"], "inputs": {k: c[k] for k in ("feed", "hours_per_year", "pet", "target", "budget", "spread", "objective")}, "constraints": cons, "warnings": warns, "limits": LIMITS}
    if c["mode"] == "optimise":
        with price_overrides(c["prices"]):       # the money objectives must see the customer's own prices
            sol = op.optimise(pet, cons, spread=c["spread"], feed=300.0, safety=1.0, model=MODEL, objective=c["objective"],
                              plant_feed_kg_h=c["feed"], hours_per_year=c["hours_per_year"], target=c["target"], location=c["location"])
        if sol["status"] != "ok":
            return {**out, "status": "infeasible", "message": "No setting inside the modelled ranges meets all of your requirements (with a safety margin equal to the surrogate's error).",
                    "closest_settings": sol["closest_point"], "achievable_at_this_composition": achievable(pet)}
        variables = sol["variables"]
        out["n_feasible_of_random"] = [sol["n_feasible_of_random"], sol["n_random"]]
        out["objective"] = c["objective"]
    else:
        variables = c["variables"]
    v = variables
    pred_all = {k: float(a[0]) for k, a in MODEL.predict(pet, v["crusher_gap_mm"], v["screen1_cut_mm"], v["screen2_cut_mm"], v["residence_time_s"], c["spread"], 300.0).items()}
    sens = {}
    for lvl, sg in SPREADS.items():
        pp = MODEL.predict(pet, v["crusher_gap_mm"], v["screen1_cut_mm"], v["screen2_cut_mm"], v["residence_time_s"], sg, 300.0)
        sens[lvl] = {k: float(pp[k][0]) for k in ("PET_purity_dense", "PE_PP_purity_light", "PET_recovery_pct", "PEPP_recovery_pct")} | {"spread": sg}
    met = {}
    for name, val in cons.items():
        key, sense = op.LIMITS[name]
        ok = pred_all[key] >= val if sense == ">=" else pred_all[key] <= val
        met[name] = {"required": val, "predicted": pred_all[key], "ok": bool(ok)}
    for name, short in VAR_NAMES.items():
        lo, hi = S.BOUNDS[short]
        if v[name] <= lo + 0.01 * (hi - lo) or v[name] >= hi - 0.01 * (hi - lo):
            warns.append(f"{name.replace('_', ' ')} = {v[name]:g} is at the edge of the simulated range ({lo:g}-{hi:g}); a better setting may exist outside it.")
    with price_overrides(c["prices"]):
        cost = cs.estimate(pet, v, c["feed"], c["hours_per_year"], c["budget"], c["spread"], c["location"], MODEL)
    out["why"] = explain(c, v, met, warns)
    out.update({"variables": v, "predicted": {k: _pm(k, pred_all[k]) for k in SHOW}, "spread_sensitivity": sens, "constraints_met": met,
                "cost": cost, "annual_t": {"feed": sz.annual(c["feed"], c["hours_per_year"]), "dense": sz.annual(cost["flows_kg_h"]["dense"], c["hours_per_year"]),
                                           "light": sz.annual(cost["flows_kg_h"]["light"], c["hours_per_year"]), "fines": sz.annual(cost["flows_kg_h"]["fines"], c["hours_per_year"])}})
    return out


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return float(o) if math.isfinite(float(o)) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ---------------------------------------------------------------- data for the plots (read only, from the Aspen sweep)
def _load_points() -> list[dict]:
    keep = ["PET_frac_pct", "crusher_gap_mm", "screen1_cut_mm", "screen2_cut_mm", "residence_time_s", "recycle_ratio", "fines_loss_pct", "yield_pct",
            "d50_coarse_mm", "crusher_kWh_per_tonne_feed", "PET_purity_dense", "PE_PP_purity_light", "PET_recovery_pct", "PEPP_recovery_pct"]
    rows = []
    for path in DATA_CSVS:
        if path.exists():
            with open(path, newline="") as fh:
                rows += [r for r in csv.DictReader(fh) if r["converged"] == "True" and r["spread_level"] == "default"]
    return [{k: float(r[k]) for k in keep} for r in rows]


POINTS = _load_points()


async def home(request):
    return FileResponse(HERE / "index.html")


async def health(request):
    return JSONResponse({"status": "ok"})


async def meta(request):
    return JSONResponse(_clean({
        "bounds": {"feed_kg_h": FEED_RANGE, "pet_pct": S.BOUNDS["pet"], "crusher_gap_mm": S.BOUNDS["gap"], "screen1_cut_mm": S.BOUNDS["s1"],
                   "screen2_cut_mm": S.BOUNDS["s2"], "residence_time_s": S.BOUNDS["tau"], "tank_spread": [SPREADS["low"], SPREADS["high"]]},
        "defaults": {"spread": SPREADS["default"], "hours_per_day": 8, "days_per_year": 250},
        "data": {"aspen_cases": len({(p["PET_frac_pct"], p["crusher_gap_mm"], p["screen1_cut_mm"]) for p in POINTS}), "rows_used": len(POINTS),
                 "max_balance_error_pct": 2.53e-7, "surrogate_cv": {k: {"rmse": v["rmse"], "r2": v["r2"], "max_abs": v["max_abs"]} for k, v in CV.items()}},
        "cost_constants": {k: {"low": v[0], "base": v[1], "high": v[2], "note": v[3]} for k, v in cs.COSTS.items()},
        "limits": LIMITS}))


async def dataset(request):
    return JSONResponse({"n": len(POINTS), "points": _clean(POINTS)})


async def proposal(request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"errors": [{"field": "body", "message": "Request body must be valid JSON."}]}, status_code=422)
    try:
        result = await run_in_threadpool(make_proposal, body)
    except ValidationError as exc:
        return JSONResponse({"errors": exc.errors}, status_code=422)
    return JSONResponse(_clean(result))


app = Starlette(routes=[
    Route("/", home), Route("/api/health", health), Route("/api/meta", meta), Route("/api/dataset", dataset, methods=["GET"]),
    Route("/api/proposal", proposal, methods=["POST"]), Mount("/assets", StaticFiles(directory=HERE / "static"), name="assets"),
])
