"""v2 cost model: capex, opex, revenue per product stream, simple payback, budget filter, location factors. PRELIMINARY (+-30 % class at best).

Every constant carries a note (COSTS) with its source or the word ASSUMPTION and an accuracy remark; all are also listed in assumptions.md.
Results are returned as optimistic / base / pessimistic scenarios (ranges), never a single number.
Currency: USD. Payback = installed capex / annual net cash (simple, undiscounted, no tax, no depreciation, no financing).
Product quality (purity) does not change the price in this model; price ranges stand in for that.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sizing_v2 as sz  # noqa: E402
import surrogate_v2 as S  # noqa: E402
import tank_v2 as tk  # noqa: E402

# name: (low, base, high, note)
COSTS = {
    "crusher_ref_usd_30kW": (10000, 20000, 60000, "ASSUMPTION. Listings: new 30 kW plastic crusher EUR 8,499 (machineseeker); used 18.5 kW AUD 22,000 and used 90 kW AUD 58,000 (Australian dealers); Chinese supplier granulators USD 8,000-60,000. Vendor spread is wider than +-30 %."),
    "screen_ref_usd_1m2": (3000, 6000, 12000, "ASSUMPTION, no source found (small vibrating screen incl. motor)."),
    "tank_ref_usd_1m3": (2500, 5000, 10000, "ASSUMPTION, no source found (sink-float tank with sump pump)."),
    "scale_exponent": (0.6, 0.6, 0.6, "ASSUMPTION: generic six-tenths rule (Peters & Timmerhaus); real exponents vary 0.4-0.9."),
    "auxiliary_factor": (0.5, 1.0, 2.0, "ASSUMPTION: conveyors, pumps, dewatering, dryer, electrics as a fraction of main equipment cost. Real washing/drying lines can cost several times the granulator."),
    "installation_factor": (1.3, 1.5, 1.8, "ASSUMPTION: installed cost / delivered equipment cost (installation, piping, foundations)."),
    "maintenance_frac_capex": (0.03, 0.05, 0.07, "ASSUMPTION: annual maintenance as a fraction of installed capex (typically 2-6 %)."),
    "electricity_usd_kWh": (0.07, 0.10, 0.15, "ASSUMPTION, location dependent; editable."),
    "aux_power_frac": (0.2, 0.4, 0.6, "ASSUMPTION: screens, pumps, conveyors as a fraction of crusher power."),
    "water_usd_m3": (0.5, 1.0, 2.0, "ASSUMPTION, location dependent."),
    "product_moisture_frac": (0.05, 0.10, 0.15, "ASSUMPTION: water leaving with the wet product = make-up water (recirculating tank)."),
    "operators": (1, 2, 3, "ASSUMPTION: operators per shift."),
    "wage_usd_h": (4.0, 8.0, 15.0, "ASSUMPTION, location dependent; editable."),
    "price_dense_usd_t": (300, 400, 600, "ASSUMPTION: unwashed, colour-mixed PET-rich flake, priced at roughly half of the clean rPET flake references: USD 1,170-1,235/t US (Platts, 2025), 770-850/t Asia (OPIS/Platts). Purity does not change this price."),
    "price_light_usd_t": (300, 400, 550, "ASSUMPTION: unwashed mixed PE/PP flake, a little above US mixed-colour HDPE bale prices (about USD 330-375/t) and well below recycled HDPE pellets (USD 800-1,150/t) (2025, various sources); no PP flake price found."),
    "price_fines_usd_t": (0, 0, 0, "ASSUMPTION: fines are waste (no sale)."),
    "price_scrap_usd_t": (150, 250, 350, "ASSUMPTION, no source: purchase price (or opportunity value) of the mixed scrap feed."),
}
CAPEX_RANGE = (0.7, 1.0, 1.3)   # accuracy class of a preliminary estimate (CLAUDE_V2.md: +-30 %)
OPEX_RANGE = (0.8, 1.0, 1.2)    # ASSUMPTION
SCEN = ("optimistic", "base", "pessimistic")
LOCATION_DEFAULT = {"capex_factor": 1.0, "labour_factor": 1.0, "electricity_factor": 1.0, "water_factor": 1.0}   # editable; no regional data used


def _c(name: str, level: int) -> float:
    """level 0/1/2 = low/base/high value of constant `name`."""
    return COSTS[name][level]


def equipment_cost(crusher_kw: float, screen_areas: list[float], tank_m3: float, lvl: int = 1) -> dict:
    n = _c("scale_exponent", lvl)
    crusher = _c("crusher_ref_usd_30kW", lvl) * (crusher_kw / 30.0) ** n
    screens = [_c("screen_ref_usd_1m2", lvl) * a ** n for a in screen_areas]
    tank = _c("tank_ref_usd_1m3", lvl) * tank_m3 ** n
    main = crusher + sum(screens) + tank
    return {"crusher": crusher, "screens": screens, "tank": tank, "main_equipment": main, "auxiliary": main * _c("auxiliary_factor", lvl)}


def installed_capex(eq: dict, lvl: int, k_capex: float, location: dict) -> float:
    return (eq["main_equipment"] + eq["auxiliary"]) * _c("installation_factor", lvl) * k_capex * location["capex_factor"]


def budget_check(budget_usd: float | None, capex: dict) -> dict:
    """capex = {'optimistic':..., 'base':..., 'pessimistic':...}"""
    if budget_usd is None:
        return {"status": "no budget given"}
    lo, ba, hi = capex["optimistic"], capex["base"], capex["pessimistic"]
    if budget_usd >= hi:
        s = "within budget (also at the pessimistic estimate)"
    elif budget_usd >= ba:
        s = "within budget at the base estimate; may exceed it at the pessimistic estimate"
    elif budget_usd >= lo:
        s = "OVER BUDGET at the base estimate; within budget only at the optimistic estimate"
    else:
        s = "OVER BUDGET (even at the optimistic estimate)"
    return {"status": s, "budget_usd": budget_usd, "shortfall_base_usd": max(0.0, ba - budget_usd), "capex_range_usd": [lo, ba, hi]}


def payback(capex: float, net_per_year: float) -> float | None:
    return capex / net_per_year if net_per_year > 0 else None


def estimate(pet: float, variables: dict, feed_rate_kg_h: float = 300.0, hours_per_year: float = 2000.0, budget_usd: float | None = None,
             spread: float = 0.5, location: dict | None = None, model: S.Surrogate | None = None) -> dict:
    """Plant proposal numbers for one set of decision variables. Flows and power are scaled linearly with the feed rate (verified in V5)."""
    if not 100.0 <= feed_rate_kg_h <= 500.0:
        raise ValueError("feed rate outside the modelled 100-500 kg/h")
    if hours_per_year <= 0 or hours_per_year > 8760:
        raise ValueError("operating hours must be in (0, 8760]")
    loc = {**LOCATION_DEFAULT, **(location or {})}
    model = model or S.Surrogate.load()
    v = variables
    p = {k: float(a[0]) for k, a in model.predict(pet, v["crusher_gap_mm"], v["screen1_cut_mm"], v["screen2_cut_mm"], v["residence_time_s"], spread, 300.0).items()}
    sc = feed_rate_kg_h / 300.0
    thr, power = p["crusher_throughput_kg_h"] * sc, p["crusher_power_kW"] * sc
    fines, dense, light = p["fines_flow"] * sc, p["dense_flow"] * sc, p["light_flow"] * sc
    comp = S.composition_from_pet(pet)
    rho_s = 1.0 / sum((comp[c] / 100.0) / tk.CONFIG["densities"][c] for c in comp)
    crusher = sz.size_crusher(power, thr, power / (thr / 1000.0), v["crusher_gap_mm"])
    scr1 = sz.size_screen(thr, v["screen1_cut_mm"])
    scr2 = sz.size_screen(feed_rate_kg_h, v["screen2_cut_mm"])
    tank = sz.size_tank(feed_rate_kg_h - fines, v["residence_time_s"], rho_s)
    t_dense, t_light, t_fines, t_feed = (sz.annual(x, hours_per_year) for x in (dense, light, fines, feed_rate_kg_h))
    t_prod = t_dense + t_light
    kwh = (power * (1 + _c("aux_power_frac", 1))) * hours_per_year
    out = {"inputs": {"pet_pct": pet, "feed_rate_kg_h": feed_rate_kg_h, "hours_per_year": hours_per_year, "spread": spread, "variables": v, "location": loc},
           "flows_kg_h": {"dense": dense, "light": light, "fines": fines, "crusher_throughput": thr},
           "predicted": {k: p[k] for k in ("PET_purity_dense", "PE_PP_purity_light", "PET_recovery_pct", "PEPP_recovery_pct", "yield_pct", "fines_loss_pct",
                                           "recycle_ratio", "d50_coarse_mm", "crusher_kWh_per_tonne_feed")},
           "sizing": {"crusher": crusher, "screen1": scr1, "screen2": scr2, "tank": tank}, "scenarios": {}}
    capex_all = {}
    for i, name in enumerate(SCEN):                       # 0 = optimistic (low cost, high price), 1 = base, 2 = pessimistic
        lvl_cost, lvl_price = 1, 2 - i                    # cost constants stay at base (capex +-30 %, opex +-20 % applied below); prices high -> low
        lvl_scrap = i                                     # scrap price low -> high
        eq = equipment_cost(crusher["motor_kW"], [scr1["area_m2"], scr2["area_m2"]], tank["volume_m3"], lvl_cost)
        capex = installed_capex(eq, lvl_cost, CAPEX_RANGE[i], loc)
        k = OPEX_RANGE[i]
        elec = kwh * _c("electricity_usd_kWh", lvl_cost) * loc["electricity_factor"] * k
        water = t_prod * _c("product_moisture_frac", lvl_cost) / (1 - _c("product_moisture_frac", lvl_cost)) * _c("water_usd_m3", lvl_cost) * loc["water_factor"] * k
        labour = _c("operators", lvl_cost) * _c("wage_usd_h", lvl_cost) * hours_per_year * loc["labour_factor"] * k
        maint = capex * _c("maintenance_frac_capex", lvl_cost) * k
        scrap = t_feed * _c("price_scrap_usd_t", lvl_scrap)
        opex = elec + water + labour + maint
        rev = {"dense": t_dense * _c("price_dense_usd_t", lvl_price), "light": t_light * _c("price_light_usd_t", lvl_price), "fines": t_fines * _c("price_fines_usd_t", lvl_price)}
        revenue = sum(rev.values())
        net = revenue - opex - scrap
        capex_all[name] = capex
        out["scenarios"][name] = {"capex_usd": capex, "equipment_usd": eq, "opex_usd_per_year": {"electricity": elec, "water": water, "labour": labour, "maintenance": maint, "total": opex},
                                  "scrap_purchase_usd_per_year": scrap, "revenue_usd_per_year": {**rev, "total": revenue}, "net_usd_per_year": net,
                                  "payback_years": payback(capex, net)}
    out["budget"] = budget_check(budget_usd, capex_all)
    out["notes"] = ["PRELIMINARY estimate: capex accuracy class about +-30 % at best; vendor price spread for granulators is wider.",
                    "Payback is dominated by the assumed price gap between products and scrap; the pessimistic scenario can show no payback. Replace the prices with real quotes.",
                    "Not modelled: washing, drying, colour/metal sorting, contamination losses, selling costs, working capital, tax, financing.",
                    "Prices, scrap cost, utilities, labour are ASSUMPTIONS (see COSTS notes). Purity does not change the price.",
                    "Equipment is at its practical minimum size at this scale (min screen area, min tank volume), so costs are floor-driven.",
                    "Purity and recovery depend on assumed tank parameters (residence time, spread)."]
    return out


# ---------------------------------------------------------------- vectorised economics (used by the optimiser)
def economics_vec(pred: dict, v: "np.ndarray", pet: float, feed_rate_kg_h: float, hours_per_year: float, scenario: int = 1,
                  location: dict | None = None) -> dict:
    """capex, net cash and payback for many candidate settings at once. `pred` = surrogate.predict(..., feed=300) arrays,
    `v` = (n, 4) array of [gap, SCREEN1 cut, SCREEN2 cut, residence time]. scenario 0/1/2 = optimistic/base/pessimistic.
    Same formulas as estimate() (the tests check that the two agree). Uses the current COSTS values, so price overrides apply."""
    import numpy as np
    loc = {**LOCATION_DEFAULT, **(location or {})}
    sc = feed_rate_kg_h / 300.0
    thr, power = pred["crusher_throughput_kg_h"] * sc, pred["crusher_power_kW"] * sc
    fines, dense, light = pred["fines_flow"] * sc, pred["dense_flow"] * sc, pred["light_flow"] * sc
    motors = np.array(sz.MOTORS_KW, float)
    need = power * sz.SIZING["motor_service_factor"]
    motor = motors[np.minimum(np.searchsorted(motors, need, side="left"), len(motors) - 1)]
    pts = np.array(sz.SCREEN_TABLE)                                   # (aperture, t/h/m2)
    unit_cap = lambda ap: np.exp(np.interp(np.log(ap), np.log(pts[:, 0]), np.log(pts[:, 1])))  # noqa: E731
    q = lambda ap: unit_cap(ap) * sz.SIZING["bulk_density_kg_m3"] / sz.STD_BULK_DENSITY * sz.SIZING["screen_service_factor"]  # noqa: E731
    a1 = np.maximum(thr / 1000.0 / q(v[:, 1]), sz.SIZING["screen_min_area_m2"])
    a2 = np.maximum(feed_rate_kg_h / 1000.0 / q(v[:, 2]), sz.SIZING["screen_min_area_m2"])
    comp = S.composition_from_pet(pet)
    rho_s = 1.0 / sum((comp[c] / 100.0) / tk.CONFIG["densities"][c] for c in comp)
    ws = sz.SIZING["tank_solids_mass_frac"]
    rho_w = tk.water_density(tk.CONFIG["temp_C"])
    rho_slurry = 1.0 / (ws / rho_s + (1.0 - ws) / rho_w)
    tank = np.maximum((feed_rate_kg_h - fines) / ws / rho_slurry * v[:, 3] / 3600.0, sz.SIZING["tank_min_volume_m3"])
    n = _c("scale_exponent", 1)
    main = _c("crusher_ref_usd_30kW", 1) * (motor / 30.0) ** n + _c("screen_ref_usd_1m2", 1) * (a1 ** n + a2 ** n) + _c("tank_ref_usd_1m3", 1) * tank ** n
    capex = main * (1 + _c("auxiliary_factor", 1)) * _c("installation_factor", 1) * CAPEX_RANGE[scenario] * loc["capex_factor"]
    k = OPEX_RANGE[scenario]
    t = lambda kg_h: kg_h * hours_per_year / 1000.0  # noqa: E731
    elec = power * (1 + _c("aux_power_frac", 1)) * hours_per_year * _c("electricity_usd_kWh", 1) * loc["electricity_factor"] * k
    mo = _c("product_moisture_frac", 1)
    water = (t(dense) + t(light)) * mo / (1 - mo) * _c("water_usd_m3", 1) * loc["water_factor"] * k
    labour = _c("operators", 1) * _c("wage_usd_h", 1) * hours_per_year * loc["labour_factor"] * k
    maint = capex * _c("maintenance_frac_capex", 1) * k
    lvl_price, lvl_scrap = 2 - scenario, scenario
    revenue = t(dense) * _c("price_dense_usd_t", lvl_price) + t(light) * _c("price_light_usd_t", lvl_price) + t(fines) * _c("price_fines_usd_t", lvl_price)
    net = revenue - (elec + water + labour + maint) - t(np.full_like(dense, feed_rate_kg_h)) * _c("price_scrap_usd_t", lvl_scrap)
    with np.errstate(divide="ignore", invalid="ignore"):
        payback = np.where(net > 0, capex / net, np.inf)
    return {"capex_usd": capex, "net_usd_per_year": net, "payback_years": payback, "motor_kW": motor}
