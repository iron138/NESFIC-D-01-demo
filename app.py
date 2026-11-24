"""Streamlit demo: FAO-56 crop water balance for ONE illustrative 500 ha command area.

Decision-support only. Illustrative, Assumed inputs. Not validated. Not a scheme gate.

Rules for this file:
  * all bands, volumes and alert logic come from ensemble.py / balance.py;
  * each model is handled on its own - nothing here averages, sums or blends
    values across models (tests/test_balance.py scans this file for that);
  * data are read only from ./data through ensemble.py; no network calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import balance as bal  # noqa: E402
import ensemble as en  # noqa: E402

BANNER = "Illustrative week. Assumed inputs. Not a scheme gate. Compare; do not treat as a gate order."
FOOTER = "Weather data by Open-Meteo.com (CC BY 4.0). Free API is non-commercial."
MODELS_NOTE = "models disagree; never averaged"
RICE_NOTE = "lower bound (puddling and percolation omitted)"
ROSTER_NOTE = "example, not a department figure"
DEFAULT_ROSTER_MM = 20.0
SHIFT_DAYS = 7
KM_PER_DEG_LAT = 111.2

HEADLINE = "ECMWF"
ORDER = [HEADLINE] + [m for m in en.MODEL_FILES if m != HEADLINE]   # ECMWF, GFS, ICON

st.set_page_config(page_title="NESFIC D-01 demo - illustrative", layout="wide")


# --------------------------------------------------------------------------
# Inputs (assumptions.csv is the single source) and per-model results
# --------------------------------------------------------------------------
A = bal.load_assumptions()
CROPS = bal.crops_from_assumptions(A)
DAYS = bal.week_dates(A)
EA, EC = bal.efficiencies(A)
AREA_HA = float(A["command_area_ha"].value)
RICE = next(c for c in CROPS if c.name == "rice")


def fmt_m3(x) -> str:
    return x if isinstance(x, str) else f"{x:,.0f}"


def fmt_mm(x) -> str:
    return f"{x:,.2f}"


def head_label() -> str:
    """Head volumes are Estimated only when both efficiencies are accepted."""
    return "Estimated" if (EA is not None and EC is not None) else bal.NOT_SCORED


def model_result(name: str, roster_mm: float) -> dict:
    """Everything shown for ONE model. Called once per model; results are never combined."""
    model = en.load_model(name, DAYS)
    band = en.field_volume_band(model, CROPS)
    rows = []
    for q, v in (("P10", band.p10), ("P50", band.p50), ("P90", band.p90)):
        rows.append({
            "Percentile": q,
            # same volume also shown as a depth over the whole command area (volume / (area_ha * 10))
            "Field (Estimated)": f"{fmt_m3(v)} m³ ({fmt_mm(bal.breakeven_depth_mm(v, AREA_HA))} mm)",
            # head = field / (Ea*Ec) is a fixed scaling of each band value
            f"Head m³ ({head_label()})": fmt_m3(bal.head_volume_m3(v, EA, EC)),
        })
    roster_m3 = bal.field_volume_m3(roster_mm, AREA_HA)
    status = bal.roster_status(roster_m3, band.p10, band.p90)
    return {
        "model": model, "band": band, "table": pd.DataFrame(rows).set_index("Percentile"),
        "breakeven_mm": bal.breakeven_depth_mm(band.p50, AREA_HA),
        "p10_mm": bal.breakeven_depth_mm(band.p10, AREA_HA),
        "status": status,
        "alert": bal.roster_alert_fires(status),
        "crop_nir": {c.name: en.crop_nir_band(model, c).p50 for c in CROPS},
    }


def banner() -> None:
    st.warning(BANNER)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
st.title("Irrigation water demand: illustrative week")
st.caption("NESFIC 2026, problem D-01. FAO-56 crop water balance for one illustrative command area. "
           "Decision-support only; not validated; not a real scheme.")

tab_overview, tab_demand, tab_alerts = st.tabs(["Overview", "Demand and plan", "Alerts"])

# ---- Screen 1: Overview ---------------------------------------------------
with tab_overview:
    banner()
    st.subheader("Overview")
    pin = f"{A['pin_lat'].value}N, {A['pin_lon'].value}E - not a scheme gate"
    st.markdown(f"**{pin}**")
    st.caption(f"Label: {A['pin_lat'].label}. Week: {DAYS[0]:%d %b %Y} to {DAYS[-1]:%d %b %Y} "
               f"(label: {A['week_start'].label}).")

    st.markdown("#### Assumptions")
    adf = pd.DataFrame([
        {"Parameter": a.parameter, "Value": a.value, "Unit": a.unit, "Label": a.label, "Note": a.note}
        for a in A.values()
    ])
    st.dataframe(adf, hide_index=True, width="stretch", height="content")
    st.download_button(
        "Export assumptions.csv",
        data=bal.ASSUMPTIONS_CSV.read_bytes(),
        file_name="assumptions.csv",
        mime="text/csv",
    )

    st.markdown("#### Crop stage and Kc, each day of the week")
    kc_rows = []
    for c in CROPS:
        for d in DAYS:
            kc_rows.append({
                "Date": f"{d:%a %d %b}",
                "Crop": c.name,
                "Day no. (Assumed)": c.day_number(d),
                "Stage (Assumed)": c.stage_on(d),
                "Kc (Estimated)": f"{c.kc_on(d):.3f}",
            })
    st.dataframe(pd.DataFrame(kc_rows), hide_index=True, width="stretch", height="content")
    st.caption("Day 1 = planting day. Stage lengths and planting dates are Assumed; Kc values follow the "
               "Estimated Kc table, interpolated linearly in the development and late stages.")

# ---- Screen 2: Demand and plan -------------------------------------------
with tab_demand:
    banner()
    st.subheader("Demand range and release plan")

    r1, r2 = st.columns([1, 3])
    with r1:
        roster_mm = st.number_input(
            "Release plan (mm/week at the field)", min_value=0.0, max_value=500.0,
            value=DEFAULT_ROSTER_MM, step=1.0, format="%.1f", key="roster_mm",
        )
    with r2:
        st.caption(f"Roster: {ROSTER_NOTE}. Label: Assumed (typed by you). "
                   "Compared as a depth over the whole assumed command area.")

    results = {name: model_result(name, roster_mm) for name in ORDER}

    st.caption(f"Rice demand is a **{RICE_NOTE}**, so every band below understates rice demand. "
               "Bands are the P10, P50 and P90 of per-member 7-day command volumes (rice + mustard added "
               "per member, then percentiles).")

    cols = st.columns([2, 1.2, 1.2])
    for col, name in zip(cols, ORDER):
        res = results[name]
        with col:
            st.markdown(f"#### {name}" + (" - headline" if name == HEADLINE else ""))
            st.caption(f"Estimated from {res['band'].n} numbered members (control series excluded)")
            st.table(res["table"])
            st.metric("Break-even depth, P50 (Estimated)", f"{res['breakeven_mm']:.2f} mm")
            msg = f"Roster {roster_mm:.1f} mm [Assumed] is **{res['status']}**"
            if res["status"] == bal.BELOW_P10:
                st.warning(msg)
            elif res["status"] == bal.INSIDE:
                st.success(msg)
            else:
                st.info(msg)
    st.caption(MODELS_NOTE)
    st.caption("Field cells show m³ and, in brackets, the same volume as mm over the whole assumed command "
               "area. Head = field / (Ea x Ec).")
    icon = results["ICON"]["model"]
    km_north = (icon.latitude - float(A["pin_lat"].value)) * KM_PER_DEG_LAT
    st.caption(
        f"ICON's grid point is {icon.latitude:.3f}N, {icon.longitude:.3f}E (about {km_north:.0f} km north of "
        f"the {A['pin_lat'].value}N, {A['pin_lon'].value}E point used for GFS and ECMWF), so it is not a "
        "same-cell comparison."
    )

    # ---- chart: one bar per model (P50) with a P10-P90 whisker -------------
    chart_df = pd.DataFrame([
        {"Model": name + (" (headline)" if name == HEADLINE else ""),
         "P10": r["band"].p10, "P50": r["band"].p50, "P90": r["band"].p90}
        for name, r in results.items()
    ])
    model_order = list(chart_df["Model"])
    roster_m3 = bal.field_volume_m3(roster_mm, AREA_HA)
    roster_df = pd.DataFrame({"y": [roster_m3], "text": [f"Roster {roster_mm:.1f} mm [Assumed]"]})

    ink = "#0b0b0b"
    y_scale = alt.Scale(domainMin=0)          # the volume axis always starts at 0
    x = alt.X("Model:N", sort=model_order, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=13))
    tips = [alt.Tooltip("Model:N"),
            alt.Tooltip("P10:Q", format=",.0f", title="P10 field m³ (Estimated)"),
            alt.Tooltip("P50:Q", format=",.0f", title="P50 field m³ (Estimated)"),
            alt.Tooltip("P90:Q", format=",.0f", title="P90 field m³ (Estimated)")]
    base = alt.Chart(chart_df).encode(x=x, tooltip=tips)
    bars = base.mark_bar(size=56, color="#2a78d6", opacity=0.75, cornerRadiusTopLeft=4,
                         cornerRadiusTopRight=4).encode(
        y=alt.Y("P50:Q", scale=y_scale, title="Field volume, 7 days, m³ (Estimated)",
                axis=alt.Axis(format=",.0f")))
    whisker = base.mark_rule(color=ink, strokeWidth=2).encode(y=alt.Y("P10:Q", scale=y_scale), y2="P90:Q")
    caps = (base.mark_tick(color=ink, thickness=2, size=28).encode(y=alt.Y("P10:Q", scale=y_scale))
            + base.mark_tick(color=ink, thickness=2, size=28).encode(y=alt.Y("P90:Q", scale=y_scale)))
    line = alt.Chart(roster_df).mark_rule(color="#eb6834", strokeDash=[6, 4], strokeWidth=2).encode(
        y=alt.Y("y:Q", scale=y_scale))
    label = alt.Chart(roster_df).mark_text(align="left", dx=6, dy=-8, color=ink, fontSize=12).encode(
        y=alt.Y("y:Q", scale=y_scale), text="text:N", x=alt.value(4))
    chart = (bars + whisker + caps + line + label).properties(
        height=380, title="Bar = P50, whisker = P10 to P90, per model (each model on its own)")
    st.altair_chart(chart, width="stretch")
    st.caption(f"Rice is {RICE_NOTE}. Dashed line = your roster expressed as a field volume.")

    with st.expander("Per-crop detail (do not add these up)", expanded=False):
        crop_rows = []
        for name in ORDER:
            for c in CROPS:
                crop_rows.append({
                    "Model": name, "Crop": c.name,
                    "7-day NIR, P50 (mm, Estimated)": f"{results[name]['crop_nir'][c.name]:.2f}",
                    "Note": RICE_NOTE if c.name == "rice" else "",
                })
        st.dataframe(pd.DataFrame(crop_rows), hide_index=True, width="stretch")
        st.caption("Per-crop medians do not add up to the command-area median: percentiles are taken "
                   "once, over the per-member command volumes.")

# ---- Screen 3: Alerts ----------------------------------------------------
with tab_alerts:
    banner()
    st.subheader("Alerts")
    fired = 0

    # (1) roster below a model's P10 (one-sided)
    for name in ORDER:
        res = results[name]
        if res["alert"]:
            fired += 1
            st.warning(
                f"**Roster below the {name} band.** Roster {roster_mm:.1f} mm [Assumed, example] is below "
                f"that model's P10: {res['p10_mm']:.2f} mm field-equivalent [Estimated] "
                f"({fmt_m3(res['band'].p10)} m³ [Estimated])."
            )

    # (2) missing or Not scored inputs (soil store always listed)
    miss = bal.missing_inputs(A)
    if miss:
        fired += 1
        st.warning("**Inputs missing or Not scored** (soil store is always listed).")
        st.dataframe(
            pd.DataFrame([
                {"Input": k, "Status": v, "Label": bal.NOT_SCORED,
                 "Note": A[k].note if k in A else ""}
                for k, v in miss
            ]),
            hide_index=True, width="stretch",
        )

    # (3) planting date +/- 7 days changes the Kc stage during the week
    for w in bal.stage_shift_warnings(CROPS, DAYS, SHIFT_DAYS):
        fired += 1
        first, last = w.changes[0], w.changes[-1]
        stages = sorted({f"{b} -> {s}" for _, b, s in w.changes})
        st.warning(
            f"**Stage warning, {w.crop}.** What-if (Assumed): planting date moved by {w.shift_days:+d} days "
            f"changes the Kc stage on {len(w.changes)} day(s), {first[0]:%d %b} to {last[0]:%d %b}: "
            f"{'; '.join(stages)}."
        )

    if not fired:
        st.success("No alert rule fired.")

    with st.expander("What can raise an alert"):
        st.markdown(
            "- Roster below a model's P10 (one-sided: a roster above the band is **not** an alert).\n"
            "- Missing or Not scored inputs (soil store always listed).\n"
            "- Moving a planting date by +/-7 days (what-if) puts a crop in a different Kc stage during the week."
        )

st.divider()
st.caption(FOOTER)
