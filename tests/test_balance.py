"""Tests for balance.py and ensemble.py (T1-T11 plus a few small guards).

Expected values are fixed. Never edit an expected value to make a test pass.
Tolerances: 0.1 m3 for volumes, 0.001 mm for depths.
"""
import ast
import inspect
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import balance as b  # noqa: E402
import ensemble as en  # noqa: E402

VOL_TOL = 0.1
MM_TOL = 0.001

A = b.load_assumptions()
RICE, MUSTARD = b.crops_from_assumptions(A)
CROPS = [RICE, MUSTARD]
EA, EC = b.efficiencies(A)
DAYS = b.week_dates(A)


def gfs_control():
    """GFS unsuffixed (control) series for the assumed week: (et0, rain), via ensemble.py."""
    s = en.load_model("GFS", DAYS).control
    return list(s.et0), list(s.rain)


# ---- guards on the inputs themselves --------------------------------------
def test_assumptions_labels_and_areas():
    assert all(a.label in b.LABELS for a in A.values())
    assert A["soil_store"].label == b.NOT_SCORED and A["bund_store"].label == b.NOT_SCORED
    assert A["ET0"].label == "Estimated" and A["rain"].label == "Estimated"
    assert A["rice_Kc_mid"].label == "Estimated"
    assert RICE.area_ha + MUSTARD.area_ha == float(A["command_area_ha"].value) == 500
    assert len(DAYS) == 7 and DAYS[0] == date(2026, 11, 10) and DAYS[-1] == date(2026, 11, 16)
    assert (EA, EC) == (0.70, 0.75)


def test_stage_boundaries():
    assert b.stage_by_day(30, RICE) == "initial" and b.stage_by_day(31, RICE) == "development"
    assert b.stage_by_day(60, RICE) == "development" and b.stage_by_day(61, RICE) == "mid-season"
    assert b.stage_by_day(140, RICE) == "mid-season" and b.stage_by_day(141, RICE) == "late-season"
    assert b.stage_by_day(180, RICE) == "late-season" and b.stage_by_day(181, RICE) == "after season"
    assert b.kc_by_day(181, RICE) == RICE.kc_end


# ---- T1 hand line ----------------------------------------------------------
def test_T1_hand_line():
    et0, rain = gfs_control()
    assert et0[0] == 3.53 and rain[0] == 0.1  # 10 Nov values in the file

    assert RICE.day_number(date(2026, 11, 10)) == 133
    assert MUSTARD.day_number(date(2026, 11, 10)) == 22
    assert RICE.kc_on(date(2026, 11, 10)) == pytest.approx(1.20, abs=1e-9)
    assert MUSTARD.kc_on(date(2026, 11, 10)) == pytest.approx(0.41, abs=1e-9)

    r = b.crop_day(RICE, date(2026, 11, 10), et0[0], rain[0])
    assert r.etc_mm == pytest.approx(4.236, abs=MM_TOL)
    assert r.nir_mm == pytest.approx(4.136, abs=MM_TOL)
    m = b.crop_day(MUSTARD, date(2026, 11, 10), et0[0], rain[0])
    assert m.etc_mm == pytest.approx(1.4473, abs=MM_TOL)
    assert m.nir_mm == pytest.approx(1.3473, abs=MM_TOL)

    assert r.volume_m3 + m.volume_m3 == pytest.approx(17_891.3, abs=VOL_TOL)


# ---- T2 --------------------------------------------------------------------
def test_T2_etc_is_kc_times_et0():
    assert b.etc_mm(1.0, 5.0) == pytest.approx(5.0, abs=MM_TOL)


# ---- T3 --------------------------------------------------------------------
def test_T3_control_week_no_rain():
    et0, _ = gfs_control()
    field = b.week_field_volume_m3(DAYS, et0, [0.0] * 7, CROPS)
    assert field == pytest.approx(122_460.2, abs=VOL_TOL)
    head = b.head_volume_m3(field, EA, EC)
    assert head == pytest.approx(233_257.5, abs=VOL_TOL)


# ---- T4 --------------------------------------------------------------------
def test_T4_rain_exceeds_etc():
    one_ha = b.Crop("test", 1.0, date(2026, 1, 1), 100, 0, 0, 0, 0.5, 0.5, 0.5)
    r = b.crop_day(one_ha, date(2026, 1, 1), et0=2.0, rain=5.0)
    assert r.kc == 0.5
    assert r.etc_mm == pytest.approx(1.0, abs=MM_TOL)
    assert r.pe_mm == pytest.approx(1.0, abs=MM_TOL)
    assert r.nir_mm == pytest.approx(0.0, abs=MM_TOL)
    assert r.volume_m3 == pytest.approx(0.0, abs=VOL_TOL)


def test_negative_rain_is_set_to_zero():
    et0 = 3.0
    neg = b.crop_day(RICE, DAYS[0], et0, -2.0)
    zero = b.crop_day(RICE, DAYS[0], et0, 0.0)
    assert neg.pe_mm == 0.0 and neg.nir_mm == zero.nir_mm


# ---- T5 --------------------------------------------------------------------
def test_T5_percentile():
    v = [1, 2, 3, 4, 10]
    assert b.percentile(v, 10) == pytest.approx(1.4, abs=MM_TOL)
    assert b.percentile(v, 50) == pytest.approx(3.0, abs=MM_TOL)
    assert b.percentile(v, 90) == pytest.approx(7.6, abs=MM_TOL)
    assert b.percentile([5, 1, 3], 50) == 3  # input order does not matter


# ---- T11 -------------------------------------------------------------------
def test_T11_missing_ec_head_volume_not_scored():
    field = 100_000.0
    out = b.head_volume_m3(field, 0.70, None)
    assert out == b.NOT_SCORED and isinstance(out, str)  # no number emitted
    assert b.head_volume_m3(field, None, 0.75) == b.NOT_SCORED
    # rejected values
    for bad in (0, -0.5, 1.5, float("nan"), "abc", ""):
        assert b.head_volume_m3(field, 0.70, bad) == b.NOT_SCORED

    # missing in the assumptions table itself
    a2 = dict(A)
    del a2["Ec"]
    assert b.efficiencies(a2) == (0.70, None)
    ea, ec = b.efficiencies(a2)
    assert b.head_volume_m3(field, ea, ec) == b.NOT_SCORED

    # accepted pair still produces a number
    assert b.head_volume_m3(field, 0.70, 0.75) == pytest.approx(field / 0.525, abs=VOL_TOL)


# ===========================================================================
# Stage B: ensemble.py  (T6-T10 + ECMWF z60 sensitivity)
# ===========================================================================
@pytest.fixture(scope="module")
def models():
    return {n: en.load_model(n, DAYS) for n in ("GFS", "ECMWF", "ICON")}


def _approx_band(band, p10, p50, p90):
    assert band.p10 == pytest.approx(p10, abs=VOL_TOL)
    assert band.p50 == pytest.approx(p50, abs=VOL_TOL)
    assert band.p90 == pytest.approx(p90, abs=VOL_TOL)


# ---- T6 GFS members: percentile of the command volume, not of the parts ---
def test_T6_gfs_parts_vs_command_percentile(models):
    gfs = models["GFS"]
    rice_p50 = en.crop_nir_band(gfs, RICE).p50
    must_p50 = en.crop_nir_band(gfs, MUSTARD).p50
    assert rice_p50 == pytest.approx(25.032, abs=MM_TOL)
    assert must_p50 == pytest.approx(9.2099, abs=MM_TOL)

    from_parts = b.field_volume_m3(rice_p50, RICE.area_ha) + b.field_volume_m3(must_p50, MUSTARD.area_ha)
    command_p50 = en.field_volume_band(gfs, CROPS).p50
    assert from_parts == pytest.approx(109_337.9, abs=VOL_TOL)
    assert command_p50 == pytest.approx(109_507.15, abs=VOL_TOL)
    assert abs(command_p50 - from_parts) > 100  # they must differ


# ---- T7 bands --------------------------------------------------------------
def test_T7_bands(models):
    _approx_band(en.field_volume_band(models["GFS"], CROPS), 98_623.27, 109_507.15, 114_046.78)
    _approx_band(en.field_volume_band(models["ECMWF"], CROPS), 63_705.72, 76_630.95, 93_613.32)
    _approx_band(en.field_volume_band(models["ICON"], CROPS), 61_290.98, 78_616.90, 86_620.26)
    assert en.control_field_volume_m3(models["GFS"], CROPS) == pytest.approx(109_460.2, abs=VOL_TOL)


def test_T7_ecmwf_negative_rain_clip_matters():
    """Rain clipped at 0 gives P10 63,705.72; leaving negatives in would give 63,805.72."""
    raw = en.load_model("ECMWF", DAYS, clip_negative_rain=False)
    assert any(r < 0 for s in raw.members.values() for r in s.rain)  # negatives do exist

    def unclipped_volume(s):  # Pe = min(rain, ETc) with the raw (possibly negative) rain
        tot = 0.0
        for c in CROPS:
            for d, e, r in zip(raw.dates, s.et0, s.rain):
                etc = b.etc_mm(c.kc_on(d), e)
                tot += b.field_volume_m3(etc - min(r, etc), c.area_ha)
        return tot

    assert b.percentile([unclipped_volume(s) for s in raw.members.values()], 10) == \
        pytest.approx(63_805.72, abs=VOL_TOL)
    clipped = en.load_model("ECMWF", DAYS)
    assert all(r >= 0 for s in clipped.members.values() for r in s.rain + clipped.control.rain)


def test_ecmwf_z60_sensitivity_only():
    z60 = en.load_model("ECMWF_z60", DAYS)
    assert len(z60.members) == 50
    _approx_band(en.field_volume_band(z60, CROPS), 65_178.55, 78_469.15, 95_862.70)
    assert "ECMWF_z60" not in en.MODEL_FILES and "ECMWF_z60" in en.SENSITIVITY_FILES


# ---- T8 break-even depth = P50 / 5000 -------------------------------------
def test_T8_breakeven_depth(models):
    area = float(A["command_area_ha"].value)
    assert area * 10 == 5000
    expected = {"GFS": 21.90143, "ECMWF": 15.32619, "ICON": 15.72338}
    for name, exp in expected.items():
        p50 = en.field_volume_band(models[name], CROPS).p50
        assert b.breakeven_depth_mm(p50, area) == pytest.approx(p50 / 5000)
        assert b.breakeven_depth_mm(p50, area) == pytest.approx(exp, abs=MM_TOL)


# ---- T9 member counts; unsuffixed series excluded --------------------------
def test_T9_member_counts_and_control_excluded(models):
    assert {n: len(m.members) for n, m in models.items()} == {"GFS": 30, "ECMWF": 50, "ICON": 39}
    for name, m in models.items():
        assert all(k.startswith("member") and k[6:].isdigit() for k in m.members), name
        assert len(en.member_field_volumes_m3(m, CROPS)) == len(m.members)
        # the control series is held apart and is not one of the members
        assert all(s != m.control for s in m.members.values()), name


def test_T9_reader_drops_unsuffixed_series_on_synthetic_file(tmp_path):
    t = [d.isoformat() for d in DAYS]
    n = len(t)
    daily = {
        "time": t,
        "precipitation_sum": [9.0] * n, "et0_fao_evapotranspiration": [9.0] * n,           # control
        "precipitation_sum_member01": [-1.0] * n, "et0_fao_evapotranspiration_member01": [3.0] * n,
        "precipitation_sum_member02": [0.0] * n, "et0_fao_evapotranspiration_member02": [4.0] * n,
    }
    p = tmp_path / "ecmwf_ens.json"
    p.write_text(json.dumps({"daily": daily}))
    # the same loader path as production, pointed at a temp dir
    m = en.load_model("ECMWF", DAYS, data_dir=tmp_path)
    assert list(m.members) == ["member01", "member02"]
    assert m.control.et0 == (9.0,) * n and m.control.rain == (9.0,) * n
    assert m.members["member01"].rain == (0.0,) * n  # negative rain set to 0
    # a member list that mixes in the control would give 3 volumes
    assert len(en.member_field_volumes_m3(m, CROPS)) == 2


# ---- T10 nothing mixes or averages data across models ----------------------
_FORBIDDEN_CALLS = {"mean", "fmean", "average", "median", "nanmean", "nanmedian", "harmonic_mean",
                    "geometric_mean", "avg"}


APP_PATH = ROOT / "app.py"
# app.py must never aggregate: no sums/means/percentiles of its own, no group-bys.
_APP_FORBIDDEN_CALLS = _FORBIDDEN_CALLS | {
    "sum", "fsum", "percentile", "quantile", "groupby", "agg", "aggregate", "pivot_table",
    "rolling", "ewm", "cumsum", "interpolate", "concat", "merge",
}
_NETWORK_MODULES = {"requests", "urllib", "urllib3", "http", "httpx", "socket", "aiohttp", "ftplib"}


def _tree_of(module_or_path):
    if isinstance(module_or_path, Path):
        return ast.parse(module_or_path.read_text(encoding="utf-8"))
    return ast.parse(inspect.getsource(module_or_path))


def _called_names(module_or_path):
    names = set()
    for node in ast.walk(_tree_of(module_or_path)):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return names


def _imported_roots(module_or_path):
    tree = _tree_of(module_or_path)
    roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    roots |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    return roots


def test_T10_no_cross_model_mixing():
    # (a) no averaging/medians anywhere in the calculation modules; app.py is stricter still
    for mod in (b, en):
        assert not (_called_names(mod) & _FORBIDDEN_CALLS), mod.__name__
    assert not (_called_names(APP_PATH) & _APP_FORBIDDEN_CALLS), sorted(_called_names(APP_PATH) & _APP_FORBIDDEN_CALLS)
    # (b) no statistics/numpy imports that would make cross-model averaging easy
    for mod in (b, en, APP_PATH):
        assert not (_imported_roots(mod) & {"numpy", "statistics", "scipy"}), str(mod)
    # (c) every public function takes at most one model object, and none takes a list of models
    for fn_name, fn in inspect.getmembers(en, inspect.isfunction):
        if fn.__module__ != "ensemble" or fn_name.startswith("_"):
            continue
        ann = [str(p.annotation) for p in inspect.signature(fn).parameters.values()]
        assert sum("ModelEnsemble" in a for a in ann) <= 1, fn_name
        assert not any("Sequence[ModelEnsemble]" in a or "list[ModelEnsemble]" in a for a in ann), fn_name


def test_no_network_imports_and_no_direct_data_reads():
    for mod in (b, en, APP_PATH):
        assert not (_imported_roots(mod) & _NETWORK_MODULES), str(mod)
    # app.py gets weather only through ensemble.py: it must not open or parse JSON itself
    assert not (_called_names(APP_PATH) & {"open", "read_text", "loads", "load"})
    assert "json" not in _imported_roots(APP_PATH)


def test_T10_each_model_band_is_independent_of_the_others(models):
    # band of a model loaded alone equals its band when the other models are loaded too,
    # and no model's band equals any other model's band
    for name in ("GFS", "ECMWF", "ICON"):
        alone = en.field_volume_band(en.load_model(name, DAYS), CROPS)
        assert alone == en.field_volume_band(models[name], CROPS)
    bands = {n: en.field_volume_band(m, CROPS) for n, m in models.items()}
    assert len({(x.p10, x.p50, x.p90) for x in bands.values()}) == 3


# ===========================================================================
# Stage C: roster comparison and alert rules (balance.py)
# ===========================================================================
def test_roster_status_boundaries():
    assert b.roster_status(99.9, 100, 200) == b.BELOW_P10 == "below P10"
    assert b.roster_status(100, 100, 200) == b.INSIDE == "inside"
    assert b.roster_status(200, 100, 200) == b.INSIDE
    assert b.roster_status(200.1, 100, 200) == b.ABOVE_P90 == "above P90"


def test_roster_alert_is_one_sided():
    assert b.roster_alert_fires(b.BELOW_P10) is True
    assert b.roster_alert_fires(b.INSIDE) is False
    assert b.roster_alert_fires(b.ABOVE_P90) is False  # a roster above the band is NOT an alert


def test_default_roster_20mm_vs_bands(models):
    vol = b.field_volume_m3(20.0, 500)
    got = {n: b.roster_status(vol, *(lambda x: (x.p10, x.p90))(en.field_volume_band(m, CROPS)))
           for n, m in models.items()}
    assert got == {"GFS": b.INSIDE, "ECMWF": b.ABOVE_P90, "ICON": b.ABOVE_P90}


def test_missing_inputs_always_lists_soil_store():
    keys = [k for k, _ in b.missing_inputs(A)]
    assert "soil_store" in keys and "bund_store" in keys and "head volume" not in keys
    a2 = dict(A)
    del a2["soil_store"]
    assert "soil_store" in [k for k, _ in b.missing_inputs(a2)]   # still listed when the row is absent
    del a2["Ec"]
    got = dict(b.missing_inputs(a2))
    assert "Ec" in got and got["head volume"].startswith(b.NOT_SCORED)


def test_stage_shift_warnings_default_week():
    w = {(x.crop, x.shift_days): x for x in b.stage_shift_warnings(CROPS, DAYS, 7)}
    assert set(w) == {("rice", -7), ("mustard", 7)}
    assert {(s0, s1) for _, s0, s1 in w[("rice", -7)].changes} == {("mid-season", "late-season")}
    assert w[("rice", -7)].changes[0][0] == date(2026, 11, 11)
    assert {(s0, s1) for _, s0, s1 in w[("mustard", 7)].changes} == {("development", "initial")}
    assert b.stage_shift_warnings(CROPS, DAYS, 0) == []      # no shift, no warning


def test_grid_point_metadata_from_files():
    got = {n: (m.latitude, m.longitude) for n, m in
           ((n, en.load_model(n, DAYS)) for n in ("GFS", "ECMWF", "ICON"))}
    assert got["GFS"] == (26.25, 91.75) and got["ECMWF"] == (26.25, 91.75)
    assert got["ICON"] == (26.307152, 91.75183)
    north_km = (got["ICON"][0] - 26.25) * 111.2
    assert round(north_km) == 6 and 6.3 < north_km < 6.4
