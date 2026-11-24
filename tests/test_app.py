"""Smoke tests for app.py using streamlit.testing.v1.AppTest."""
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BANNER = "Illustrative week. Assumed inputs. Not a scheme gate. Compare; do not treat as a gate order."
FOOTER = "Weather data by Open-Meteo.com (CC BY 4.0). Free API is non-commercial."


def run(roster=None):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    if roster is not None:
        at.number_input(key="roster_mm").set_value(roster).run()
    return at


def tab_text(tab):
    parts = [e.value for e in tab.markdown] + [e.value for e in tab.warning]
    parts += [e.value for e in tab.success] + [e.value for e in tab.info]
    return "\n".join(parts)


def test_app_loads_without_exceptions():
    at = run()
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs] == ["Overview", "Demand and plan", "Alerts"]


def test_banner_on_every_screen_and_footer():
    at = run()
    for t in at.tabs:
        assert BANNER in [w.value for w in t.warning], t.label
    assert any(FOOTER == c.value for c in at.caption)


def test_overview_pin_and_assumption_labels():
    at = run()
    assert any("26.25N, 91.75E - not a scheme gate" in m.value for m in at.tabs[0].markdown)
    # first dataframe in the Overview tab is the assumptions table; every row carries a label
    df = at.tabs[0].dataframe[0].value
    assert set(df["Label"]) <= {"Measured", "Estimated", "Assumed", "Not scored"} and len(df) > 0
    kc = at.tabs[0].dataframe[1].value
    assert len(kc) == 14 and "Kc (Estimated)" in kc.columns


def test_demand_screen_default_roster_and_captions():
    at = run()
    assert at.number_input(key="roster_mm").value == 20.0
    t = at.tabs[1]
    captions = " ".join(c.value for c in t.caption)
    assert "models disagree; never averaged" in [c.value for c in t.caption]
    assert "example, not a department figure" in captions
    assert "lower bound (puddling and percolation omitted)" in captions
    text = " ".join(m.value for m in t.markdown)
    assert "ECMWF - headline" in text and "#### GFS" in text and "#### ICON" in text
    assert "50 numbered members" in captions and "30 numbered members" in captions and "39 numbered members" in captions
    # default 20 mm: GFS inside, ECMWF and ICON above P90
    status = [e.value for e in (*t.success, *t.info, *t.warning) if e.value.startswith("Roster ")]
    assert len(status) == 3 and sum("**inside**" in v for v in status) == 1
    assert sum("**above P90**" in v for v in status) == 2


def test_alert_rule_one_is_one_sided():
    def roster_alerts(at):
        return [w.value for w in at.tabs[2].warning if w.value.startswith("**Roster below")]

    assert roster_alerts(run()) == []             # default 20 mm: above ECMWF/ICON band is NOT an alert
    assert roster_alerts(run(500.0)) == []        # far above every band: still no alert
    # 5000 m3 per mm. Band P10s: ECMWF 63,706 (12.74 mm), ICON 61,291 (12.26 mm), GFS 98,623 (19.72 mm)
    one = roster_alerts(run(13.0))                # inside ECMWF and ICON, below GFS P10
    assert len(one) == 1 and "GFS" in one[0]
    two = roster_alerts(run(12.5))                # below ECMWF P10 and GFS P10, inside ICON
    assert len(two) == 2 and any("ECMWF" in w for w in two) and any("GFS" in w for w in two)
    assert not any("ICON" in w for w in two)
    assert len(roster_alerts(run(10.0))) == 3     # below all three bands


def test_alerts_screen_other_rules():
    at = run()
    warnings = [w.value for w in at.tabs[2].warning]
    assert any("Inputs missing or Not scored" in w for w in warnings)
    inputs = at.tabs[2].dataframe[0].value
    assert "soil_store" in set(inputs["Input"])
    stage = [w for w in warnings if w.startswith("**Stage warning")]
    assert len(stage) == 2 and any("rice" in w for w in stage) and any("mustard" in w for w in stage)


def test_export_button_present_on_overview():
    at = run()
    assert "DownloadButton" in [type(e).__name__ for e in at.tabs[0]]


def _chart_spec(at):
    import json
    charts = [e for e in at.tabs[1] if getattr(e, "type", "") == "vega_lite_chart"]
    assert len(charts) == 1
    return json.loads(charts[0].proto.spec)


def _y_scales(spec):
    """Every y-encoding scale found anywhere in the (layered) spec."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            enc = node.get("encoding", {})
            if "y" in enc:
                found.append(enc["y"].get("scale"))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)
    return found


@pytest.mark.parametrize("roster", [None, 13.0, 500.0])
def test_chart_y_axis_starts_at_zero(roster):
    spec = _chart_spec(run(roster))
    scales = _y_scales(spec)
    assert len(scales) >= 5                      # bar, whisker, two caps, roster rule, roster label
    assert all(s is not None and s.get("domainMin") == 0 for s in scales), scales
    # and no layer pins an explicit domain that could start above 0
    assert all("domain" not in s for s in scales), scales


def test_icon_grid_point_caption():
    at = run()
    caps = [c.value for c in at.tabs[1].caption]
    icon = [c for c in caps if c.startswith("ICON's grid point")]
    assert len(icon) == 1
    assert "26.307N, 91.752E" in icon[0]
    assert "about 6 km north of the 26.25N, 91.75E point used for GFS and ECMWF" in icon[0]
    assert icon[0].endswith("so it is not a same-cell comparison.")


def test_per_crop_expander_collapsed_by_default():
    at = run()
    ex = [e for e in at.tabs[1].expander if e.label.startswith("Per-crop detail")]
    assert len(ex) == 1 and ex[0].proto.expanded is False
