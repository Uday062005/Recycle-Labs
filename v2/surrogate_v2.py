"""Surrogate: structured CUBIC regression on data/results_v2_lhs.csv (the tank split is fitted as w = probit(split) x spread).

Inputs : PET fraction (%), crusher gap, SCREEN1 cut, SCREEN2 cut, residence time, tank spread (optional, default 0.5).
         Composition is ONE number (PET %): the three V5 compositions lie on a line (HDPE 40-(PET-30)*2/3 %, PP the rest), so nothing else is identifiable.
Models (each a full cubic polynomial in inputs scaled to [-1, 1], ridge 1e-9):
  Aspen group (4 inputs, default-spread rows): ln(oversize), fines, COARSE flow of PET / HDPE / PP, F80, d50 of COARSE.
  Tank group  (6 inputs, all 630 rows)       : w_c = probit(split_c) x spread for PET / HDPE / PP; split_c = Phi(w_c / spread).
Everything else is DERIVED with the exact relations (mass balance closes by construction):
  coarse = feed - fines (components rescaled), dense_c = split_c * coarse_c, light_c = (1 - split_c) * coarse_c,
  purities / recoveries / losses from tank.separation_metrics, crusher power from crusher (Bond, calibrated Wi) with
  throughput = feed + oversize and P80 from the gap.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_v2 as C  # noqa: E402
import crusher_v2 as cr
import tank_v2 as tk

DATA = C.ROOT / "data" / "results_v2_lhs.csv"
MODEL_JSON = C.ROOT / "data" / "surrogate_v2.json"
FEED_DEFAULT = 300.0
BOUNDS = {"pet": (20.0, 70.0), "gap": (6.0, 18.0), "s1": (5.0, 18.0), "s2": (1.0, 5.0), "tau": (10.0, 80.0),
          "lnsig": (math.log(0.25), math.log(1.0))}
ASPEN_VARS = ("pet", "gap", "s1", "s2")
TANK_VARS = ("pet", "gap", "s1", "s2", "tau", "lnsig")
EPS = 1e-4


def composition_from_pet(pet_pct: float) -> dict[str, float]:
    """HDPE and PP (mass %) along the V5 composition line."""
    hdpe = 40.0 - (pet_pct - 30.0) * 2.0 / 3.0
    return {"PET": pet_pct, "HDPE": hdpe, "PP": 100.0 - pet_pct - hdpe}


def _z(vals: np.ndarray, names: tuple[str, ...]) -> np.ndarray:
    lo = np.array([BOUNDS[n][0] for n in names]); hi = np.array([BOUNDS[n][1] for n in names])
    return 2.0 * (vals - lo) / (hi - lo) - 1.0


def _poly2(z: np.ndarray) -> np.ndarray:
    n, k = z.shape
    cols = [np.ones(n)] + [z[:, i] for i in range(k)] + [z[:, i] * z[:, j] for i in range(k) for j in range(i, k)]
    return np.column_stack(cols)


def _poly3(z: np.ndarray) -> np.ndarray:
    """Full cubic polynomial features (constant, linear, quadratic and cubic monomials)."""
    n, k = z.shape
    cols = [np.ones(n)] + [z[:, i] for i in range(k)] + [z[:, i] * z[:, j] for i in range(k) for j in range(i, k)] \
        + [z[:, i] * z[:, j] * z[:, l] for i in range(k) for j in range(i, k) for l in range(j, k)]
    return np.column_stack(cols)


_ERF = np.frompyfunc(math.erf, 1, 1)


def _phi(z: np.ndarray) -> np.ndarray:
    """Standard normal CDF."""
    return 0.5 * (1.0 + _ERF(np.asarray(z, float) / math.sqrt(2.0)).astype(float))


def _probit(p: np.ndarray) -> np.ndarray:
    """Inverse standard normal CDF (Acklam's rational approximation, |rel. error| < 1.2e-9)."""
    p = np.asarray(p, float)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137298659e+00, 3.754408661907416e+00]
    out = np.zeros_like(p)
    lo, hi = p < 0.02425, p > 1 - 0.02425
    mid = ~(lo | hi)
    q = np.sqrt(-2 * np.log(p[lo])); out[lo] = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = np.sqrt(-2 * np.log(1 - p[hi])); out[hi] = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p[mid] - 0.5; r = q * q
    out[mid] = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    return out


def _fit_ls(x: np.ndarray, y: np.ndarray, ridge: float = 1e-9) -> np.ndarray:
    a = np.vstack([x, math.sqrt(ridge) * np.eye(x.shape[1])]); b = np.concatenate([y, np.zeros(x.shape[1])])
    return np.linalg.lstsq(a, b, rcond=None)[0]


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _expit(x):
    return 1.0 / (1.0 + np.exp(-x))


TRAIN_FILES = [DATA, DATA.with_name("results_synthetic.csv")]      # Aspen sweep + replica data (src/emulator.py)
HOLDOUT_FILE = DATA.with_name("results_wide.csv")                  # real Aspen sweep over the wide ranges: used only to test, then added


def load_model():
    """The model used by the optimiser, cost model and website: the vectorised Python replica of the Aspen flowsheet (no regression error)."""
    from emulator import PhysicsModel
    return PhysicsModel()


def load_rows(path: Path | list[Path] | None = None) -> list[dict]:
    paths = TRAIN_FILES if path is None else ([path] if isinstance(path, Path) else path)
    rows: list[dict] = []
    for pth in paths:
        if Path(pth).exists():
            with open(pth, newline="") as fh:
                rows += [r for r in csv.DictReader(fh) if r["converged"] == "True"]
    return rows


def _arr(rows, key):
    return np.array([float(r[key]) for r in rows])


class Surrogate:
    def __init__(self):
        self.coef: dict[str, list[float]] = {}

    # ---------------------------------------------------------------- fit
    def fit(self, rows: list[dict]) -> "Surrogate":
        d = [r for r in rows if r["spread_level"] == "default"]
        xa = _poly3(_z(np.column_stack([_arr(d, "PET_frac_pct"), _arr(d, "crusher_gap_mm"), _arr(d, "screen1_cut_mm"), _arr(d, "screen2_cut_mm")]), ASPEN_VARS))
        coarse = {c: _arr(d, f"dense_{c}_flow") + _arr(d, f"light_{c}_flow") for c in C.COMPONENTS}
        t = {"ln_oversize": np.log(_arr(d, "oversize_flow")), "ln_fines": np.log(_arr(d, "fines_flow")),
             "ln_coarse_PET": np.log(coarse["PET"]), "ln_coarse_HDPE": np.log(coarse["HDPE"]), "ln_coarse_PP": np.log(coarse["PP"]),
             "F80": _arr(d, "crusher_F80_mm"), "d50": _arr(d, "d50_coarse_mm")}
        for k, y in t.items():
            self.coef[k] = _fit_ls(xa, y).tolist()
        sig = _arr(rows, "tank_spread")
        xt = _poly3(_z(np.column_stack([_arr(rows, "PET_frac_pct"), _arr(rows, "crusher_gap_mm"), _arr(rows, "screen1_cut_mm"), _arr(rows, "screen2_cut_mm"),
                                        _arr(rows, "residence_time_s"), np.log(sig)]), TANK_VARS))
        for c in C.COMPONENTS:      # w = probit(split) * sigma ~ (tau / t_s - 1) averaged over the PSD; saturated splits are censored (not fitted)
            s = _arr(rows, f"split_{c}_dense")
            ok = (s > 1e-6) & (s < 1 - 1e-6)
            self.coef[f"w_{c}"] = _fit_ls(xt[ok], (_probit(s) * sig)[ok]).tolist()
        return self

    # ---------------------------------------------------------------- predict
    def predict(self, pet, gap, s1, s2, tau, sigma=0.5, feed=FEED_DEFAULT) -> dict[str, np.ndarray]:
        """Vectorised: every argument may be a scalar or a 1-D array. Returns arrays."""
        pet, gap, s1, s2, tau, sigma = np.broadcast_arrays(*[np.atleast_1d(np.asarray(v, float)) for v in (pet, gap, s1, s2, tau, sigma)])
        n = pet.size
        za = _poly3(_z(np.column_stack([pet, gap, s1, s2]), ASPEN_VARS))
        zt = _poly3(_z(np.column_stack([pet, gap, s1, s2, tau, np.log(sigma)]), TANK_VARS))
        f = lambda k, z: z @ np.array(self.coef[k])  # noqa: E731
        oversize = np.exp(f("ln_oversize", za))
        fines = np.clip(np.exp(f("ln_fines", za)), 0.0, feed)
        raw = {c: np.exp(f(f"ln_coarse_{c}", za)) for c in C.COMPONENTS}
        tot = sum(raw.values())
        coarse = {c: raw[c] / tot * (feed - fines) for c in C.COMPONENTS}           # consistent with fines + coarse = feed
        split = {c: np.clip(_phi(f(f"w_{c}", zt) / sigma), 0.0, 1.0) for c in C.COMPONENTS}
        dense = {c: split[c] * coarse[c] for c in C.COMPONENTS}
        light = {c: (1 - split[c]) * coarse[c] for c in C.COMPONENTS}
        comp = [composition_from_pet(p) for p in pet]
        feedc = {c: feed * np.array([x[c] for x in comp]) / 100.0 for c in C.COMPONENTS}
        d_tot, l_tot = sum(dense.values()), sum(light.values())
        pepp_feed = feedc["HDPE"] + feedc["PP"]
        out = {
            "oversize_flow": oversize, "recycle_ratio": oversize / feed, "fines_flow": fines, "fines_loss_pct": 100 * fines / feed,
            "dense_flow": d_tot, "light_flow": l_tot, "yield_pct": 100 * (d_tot + l_tot) / feed,
            "split_PET_dense": split["PET"], "split_HDPE_dense": split["HDPE"], "split_PP_dense": split["PP"],
            "PET_purity_dense": dense["PET"] / d_tot, "PE_PP_purity_light": (light["HDPE"] + light["PP"]) / l_tot,
            "PET_recovery_pct": 100 * dense["PET"] / feedc["PET"], "PEPP_recovery_pct": 100 * (light["HDPE"] + light["PP"]) / pepp_feed,
            "PET_loss_to_light_pct": 100 * light["PET"] / feedc["PET"], "PEPP_loss_to_dense_pct": 100 * (dense["HDPE"] + dense["PP"]) / pepp_feed,
            "d50_coarse_mm": f("d50", za), "crusher_F80_mm": f("F80", za),
        }
        grid = np.arange(BOUNDS["gap"][0], BOUNDS["gap"][1] + 1e-9, 0.05)
        p80 = np.interp(gap, grid, [cr.percentile_mm(cr.psd(g), 0.8) for g in grid])
        s = 10.0 * cr.WI_EFF * (1 / np.sqrt(p80 * 1000.0) - 1 / np.sqrt(out["crusher_F80_mm"] * 1000.0))
        spec = np.maximum(0.0, s) * 1000.0 / cr.SHORT_TON_KG                           # kWh per tonne of crusher feed
        thr = feed + oversize
        out["crusher_P80_mm"] = p80
        out["crusher_throughput_kg_h"] = thr
        out["crusher_power_kW"] = spec * thr / 1000.0
        out["crusher_kWh_per_tonne_feed"] = out["crusher_power_kW"] / (feed / 1000.0)
        return out

    # ---------------------------------------------------------------- io
    def save(self, path: Path = MODEL_JSON, extra: dict | None = None) -> None:
        path.write_text(json.dumps({"coef": self.coef, "bounds": BOUNDS, **(extra or {})}))

    @classmethod
    def load(cls, path: Path = MODEL_JSON) -> "Surrogate":
        m = cls(); m.coef = json.loads(path.read_text())["coef"]; return m


# ---------------------------------------------------------------- cross-validation
KEYS = ["PET_purity_dense", "PE_PP_purity_light", "PET_recovery_pct", "PEPP_recovery_pct", "PET_loss_to_light_pct", "PEPP_loss_to_dense_pct",
        "yield_pct", "fines_loss_pct", "recycle_ratio", "d50_coarse_mm", "crusher_kWh_per_tonne_feed", "dense_flow", "light_flow"]


def cross_validate(rows: list[dict], k: int = 10, seed: int = 1) -> dict:
    """k-fold CV grouped by case (the three spread rows of a case stay together). Errors vs the data on the held-out rows."""
    ids = sorted({r["case_id"] for r in rows})
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ids))
    fold_of = {ids[i]: j % k for j, i in enumerate(perm)}
    errs = {key: [] for key in KEYS}
    for fold in range(k):
        train = [r for r in rows if fold_of[r["case_id"]] != fold]
        test = [r for r in rows if fold_of[r["case_id"]] == fold]
        m = Surrogate().fit(train)
        p = m.predict(_arr(test, "PET_frac_pct"), _arr(test, "crusher_gap_mm"), _arr(test, "screen1_cut_mm"), _arr(test, "screen2_cut_mm"),
                      _arr(test, "residence_time_s"), _arr(test, "tank_spread"))
        for key in KEYS:
            errs[key].extend((p[key] - _arr(test, key)).tolist())
    res = {}
    for key in KEYS:
        e = np.array(errs[key]); y = _arr(rows, key)
        res[key] = {"rmse": float(np.sqrt((e ** 2).mean())), "mae": float(np.abs(e).mean()), "max_abs": float(np.abs(e).max()),
                    "r2": float(1 - (e ** 2).sum() / ((y - y.mean()) ** 2).sum()), "range": [float(y.min()), float(y.max())]}
    return res


def holdout_errors(model: "Surrogate", rows: list[dict]) -> dict:
    p = model.predict(_arr(rows, "PET_frac_pct"), _arr(rows, "crusher_gap_mm"), _arr(rows, "screen1_cut_mm"), _arr(rows, "screen2_cut_mm"),
                      _arr(rows, "residence_time_s"), _arr(rows, "tank_spread"))
    res = {}
    for key in KEYS:
        e = p[key] - _arr(rows, key); y = _arr(rows, key)
        res[key] = {"rmse": float(np.sqrt((e ** 2).mean())), "max_abs": float(np.abs(e).max()), "r2": float(1 - (e ** 2).sum() / ((y - y.mean()) ** 2).sum()),
                    "range": [float(y.min()), float(y.max())], "n": int(len(y))}
    return res


if __name__ == "__main__":
    rows = load_rows()
    cv = cross_validate(rows)
    print(f"{len(rows)} rows. 10-fold CV (grouped by case), error on held-out rows:")
    print(f"{'output':<28}{'RMSE':>9}{'MAE':>9}{'max|e|':>9}{'R2':>8}   data range")
    for k, v in cv.items():
        print(f"{k:<28}{v['rmse']:>9.4g}{v['mae']:>9.4g}{v['max_abs']:>9.4g}{v['r2']:>8.3f}   {v['range'][0]:.4g} .. {v['range'][1]:.4g}")
    extra = {"n_rows": len(rows)}
    hold = load_rows([HOLDOUT_FILE])
    if hold:                                    # independent test on real Aspen rows the model has not seen
        h = holdout_errors(Surrogate().fit(rows), hold)
        print(); print(f"HOLDOUT: {len(hold)} real Aspen rows over the wide ranges (not used for this fit)")
        print(f"{'output':<28}{'RMSE':>9}{'max|e|':>9}{'R2':>8}")
        for k, v in h.items():
            print(f"{k:<28}{v['rmse']:>9.4g}{v['max_abs']:>9.4g}{v['r2']:>8.3f}")
            cv[k]["rmse"] = max(cv[k]["rmse"], v["rmse"])        # margins and tolerances use the larger (honest) error
            cv[k]["max_abs"] = max(cv[k]["max_abs"], v["max_abs"])
        extra["aspen_holdout"] = h
        rows = rows + hold                       # final model also learns from the real wide rows
        extra["n_rows"] = len(rows)
    extra["cv"] = cv
    m = Surrogate().fit(rows)
    m.save(extra=extra)
    print("saved", MODEL_JSON)
