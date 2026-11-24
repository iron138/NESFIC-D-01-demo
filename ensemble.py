"""Reader and percentile bands for the local Open-Meteo ensemble JSON files.

Reads ONLY from ./data (no network). Each model is handled on its own:
nothing here averages, pools or otherwise combines data across models.

Rules implemented:
  * Only numbered members (keys ending _memberNN) form the band.
  * The unsuffixed series (the control run) is kept separately and is NOT a member.
  * Negative rain values are set to 0 when read.
  * A band is built by computing the 7-day command volume (all crops) for each
    member, then taking percentiles of that one list of member volumes.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import balance as bal

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

ET0_KEY = "et0_fao_evapotranspiration"
RAIN_KEY = "precipitation_sum"
_MEMBER_RE = re.compile(rf"^(?P<var>{ET0_KEY}|{RAIN_KEY})_member(?P<n>\d+)$")

# Headline model first. File names are fixed here so that nothing outside ./data is read.
MODEL_FILES: dict[str, str] = {
    "ECMWF": "ecmwf_ens.json",
    "GFS": "om_ensemble_gfs_guwahati.json",
    "ICON": "icon_ens.json",
}
# Sensitivity only (same ECMWF ensemble on a 60 m grid elevation); never the headline.
SENSITIVITY_FILES: dict[str, str] = {
    "ECMWF_z60": "ecmwf_ens_z60.json",
}


@dataclass(frozen=True)
class Series:
    """One weather series over the requested days."""
    et0: tuple[float, ...]
    rain: tuple[float, ...]


@dataclass(frozen=True)
class ModelEnsemble:
    name: str
    source_file: str
    dates: tuple[date, ...]
    control: Series                   # unsuffixed series; NOT a member
    members: dict[str, Series]        # keys "member01", "member02", ... only
    # grid point the file was served for (file metadata; None when not available)
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class Band:
    n: int
    p10: float
    p50: float
    p90: float


# --------------------------------------------------------------------------
# Reader
# --------------------------------------------------------------------------
def _pick(values: Sequence, idx: Sequence[int], what: str) -> list[float]:
    out = []
    for i in idx:
        v = values[i]
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            raise ValueError(f"{what}: missing value inside the requested days")
        out.append(float(v))
    return out


def read_daily(daily: dict, dates: Sequence[date], name: str = "model",
               source_file: str = "", clip_negative_rain: bool = True,
               latitude: float | None = None, longitude: float | None = None) -> ModelEnsemble:
    """Build a ModelEnsemble from an Open-Meteo `daily` dict (already parsed JSON)."""
    times = daily["time"]
    try:
        idx = [times.index(d.isoformat()) for d in dates]
    except ValueError as exc:
        raise ValueError(f"{name}: a requested day is not in the file ({exc})") from None

    def rain_fix(vals: list[float]) -> tuple[float, ...]:
        return tuple(max(v, 0.0) for v in vals) if clip_negative_rain else tuple(vals)

    control = Series(
        et0=tuple(_pick(daily[ET0_KEY], idx, f"{name} control et0")),
        rain=rain_fix(_pick(daily[RAIN_KEY], idx, f"{name} control rain")),
    )

    et0_m: dict[str, list[float]] = {}
    rain_m: dict[str, list[float]] = {}
    for key, vals in daily.items():
        m = _MEMBER_RE.match(key)
        if not m:
            continue                  # time, unsuffixed series, anything else
        member = f"member{m['n']}"
        target = et0_m if m["var"] == ET0_KEY else rain_m
        target[member] = _pick(vals, idx, f"{name} {key}")
    if set(et0_m) != set(rain_m):
        raise ValueError(f"{name}: et0 and rain member lists differ")

    members = {
        k: Series(et0=tuple(et0_m[k]), rain=rain_fix(rain_m[k]))
        for k in sorted(et0_m)
    }
    if not members:
        raise ValueError(f"{name}: no numbered members found")
    return ModelEnsemble(name, source_file, tuple(dates), control, members, latitude, longitude)


def load_model(name: str, dates: Sequence[date], data_dir: Path = DATA_DIR,
               clip_negative_rain: bool = True) -> ModelEnsemble:
    """Load ONE model from ./data. `name` is a key of MODEL_FILES or SENSITIVITY_FILES."""
    files = {**MODEL_FILES, **SENSITIVITY_FILES}
    if name not in files:
        raise KeyError(f"unknown model {name!r}; choose from {sorted(files)}")
    path = Path(data_dir) / files[name]
    doc = json.loads(path.read_text(encoding="utf-8"))
    return read_daily(doc["daily"], dates, name=name, source_file=files[name],
                      clip_negative_rain=clip_negative_rain,
                      latitude=doc.get("latitude"), longitude=doc.get("longitude"))


# --------------------------------------------------------------------------
# Volumes and bands (always one model at a time)
# --------------------------------------------------------------------------
def _band_of(values: Sequence[float]) -> Band:
    return Band(
        n=len(values),
        p10=bal.percentile(values, 10),
        p50=bal.percentile(values, 50),
        p90=bal.percentile(values, 90),
    )


def control_field_volume_m3(model: ModelEnsemble, crops: Sequence[bal.Crop]) -> float:
    """Week field volume of the unsuffixed (control) series. Reference only, not a member."""
    return bal.week_field_volume_m3(model.dates, model.control.et0, model.control.rain, crops)


def member_field_volumes_m3(model: ModelEnsemble, crops: Sequence[bal.Crop]) -> list[float]:
    """7-day command volume (all crops) for each numbered member of this model."""
    return [
        bal.week_field_volume_m3(model.dates, s.et0, s.rain, crops)
        for s in model.members.values()
    ]


def field_volume_band(model: ModelEnsemble, crops: Sequence[bal.Crop]) -> Band:
    """P10/P50/P90 of the member volumes (one list, all crops already added per member)."""
    return _band_of(member_field_volumes_m3(model, crops))


def crop_nir_band(model: ModelEnsemble, crop: bal.Crop) -> Band:
    """P10/P50/P90 of one crop's 7-day NIR depth (mm) across this model's members."""
    return _band_of([
        bal.week_nir_mm(model.dates, s.et0, s.rain, crop) for s in model.members.values()
    ])
