"""FAO-56 style crop water balance for ONE illustrative command area.

Decision-support demo only. Not validated. No machine learning.
All functions here work on one weather series at a time; nothing in this
module combines or averages data across models.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

HERE = Path(__file__).resolve().parent
ASSUMPTIONS_CSV = HERE / "assumptions.csv"

NOT_SCORED = "Not scored"
LABELS = ("Measured", "Estimated", "Assumed", NOT_SCORED)

# 1 mm of water over 1 ha = 10 m3
M3_PER_MM_HA = 10.0


# --------------------------------------------------------------------------
# Assumptions
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Assumption:
    parameter: str
    value: str
    unit: str
    label: str
    note: str


def load_assumptions(path: Path = ASSUMPTIONS_CSV) -> dict[str, Assumption]:
    out: dict[str, Assumption] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a = Assumption(
                parameter=row["parameter"].strip(),
                value=row["value"].strip(),
                unit=row["unit"].strip(),
                label=row["label"].strip(),
                note=row["note"].strip(),
            )
            if a.label not in LABELS:
                raise ValueError(f"{a.parameter}: label {a.label!r} not in {LABELS}")
            out[a.parameter] = a
    return out


def accepted_efficiency(x) -> float | None:
    """Return x as a float if it is a usable efficiency in (0, 1], else None."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or not (0.0 < v <= 1.0):
        return None
    return v


def efficiencies(a: dict[str, Assumption]) -> tuple[float | None, float | None]:
    """(Ea, Ec) from assumptions; None when missing, blank, Not scored or rejected."""
    def one(key: str) -> float | None:
        row = a.get(key)
        if row is None or row.label == NOT_SCORED or row.value == "":
            return None
        return accepted_efficiency(row.value)

    return one("Ea"), one("Ec")


# --------------------------------------------------------------------------
# Crops and Kc
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Crop:
    name: str
    area_ha: float
    plant_date: date
    l_ini: int
    l_dev: int
    l_mid: int
    l_late: int
    kc_ini: float
    kc_mid: float
    kc_end: float

    def day_number(self, d: date) -> int:
        """Day 1 = planting day."""
        return (d - self.plant_date).days + 1

    def kc_on(self, d: date) -> float:
        return kc_by_day(self.day_number(d), self)

    def stage_on(self, d: date) -> str:
        return stage_by_day(self.day_number(d), self)

    def shifted(self, days: int) -> "Crop":
        """Same crop with the planting date moved by `days`."""
        return replace(self, plant_date=self.plant_date + timedelta(days=days))


def kc_by_day(day: int, c: Crop) -> float:
    """Piecewise-linear Kc. Flat Kc_ini for day<=L_ini, linear rise to Kc_mid
    over L_dev, flat Kc_mid for L_mid, linear fall to Kc_end over L_late,
    Kc_end afterwards."""
    if day < 1:
        raise ValueError(f"{c.name}: day {day} is before planting (day 1)")
    end_ini = c.l_ini
    end_dev = end_ini + c.l_dev
    end_mid = end_dev + c.l_mid
    end_late = end_mid + c.l_late
    if day <= end_ini:
        return c.kc_ini
    if day <= end_dev:
        return c.kc_ini + (day - end_ini) / c.l_dev * (c.kc_mid - c.kc_ini)
    if day <= end_mid:
        return c.kc_mid
    if day <= end_late:
        return c.kc_mid + (day - end_mid) / c.l_late * (c.kc_end - c.kc_mid)
    return c.kc_end


STAGE_NAMES = ("initial", "development", "mid-season", "late-season", "after season")


def stage_by_day(day: int, c: Crop) -> str:
    if day < 1:
        return "before planting"
    end_ini = c.l_ini
    end_dev = end_ini + c.l_dev
    end_mid = end_dev + c.l_mid
    end_late = end_mid + c.l_late
    if day <= end_ini:
        return STAGE_NAMES[0]
    if day <= end_dev:
        return STAGE_NAMES[1]
    if day <= end_mid:
        return STAGE_NAMES[2]
    if day <= end_late:
        return STAGE_NAMES[3]
    return STAGE_NAMES[4]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def crop_from_assumptions(a: dict[str, Assumption], key: str) -> Crop:
    g = lambda suffix: a[f"{key}_{suffix}"].value  # noqa: E731
    return Crop(
        name=key,
        area_ha=float(g("area_ha")),
        plant_date=_d(g("plant_date")),
        l_ini=int(g("L_ini")),
        l_dev=int(g("L_dev")),
        l_mid=int(g("L_mid")),
        l_late=int(g("L_late")),
        kc_ini=float(g("Kc_ini")),
        kc_mid=float(g("Kc_mid")),
        kc_end=float(g("Kc_end")),
    )


def crops_from_assumptions(a: dict[str, Assumption]) -> list[Crop]:
    return [crop_from_assumptions(a, "rice"), crop_from_assumptions(a, "mustard")]


def week_dates(a: dict[str, Assumption]) -> list[date]:
    start, end = _d(a["week_start"].value), _d(a["week_end"].value)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# --------------------------------------------------------------------------
# Daily and weekly balance
# --------------------------------------------------------------------------
def _check_number(name: str, x: float) -> float:
    if x is None or not math.isfinite(x):
        raise ValueError(f"{name} is missing or not finite: {x!r}")
    return float(x)


def etc_mm(kc: float, et0: float) -> float:
    return kc * et0


def effective_rain_mm(rain: float, etc: float) -> float:
    """Pe = min(max(rain, 0), ETc). Negative rain values are set to 0."""
    return min(max(rain, 0.0), etc)


def field_volume_m3(nir_mm: float, area_ha: float) -> float:
    return nir_mm * area_ha * M3_PER_MM_HA


@dataclass(frozen=True)
class CropDay:
    kc: float
    etc_mm: float
    pe_mm: float
    nir_mm: float
    volume_m3: float


def crop_day(crop: Crop, d: date, et0: float, rain: float) -> CropDay:
    et0 = _check_number("et0", et0)
    rain = _check_number("rain", rain)
    kc = crop.kc_on(d)
    etc = etc_mm(kc, et0)
    pe = effective_rain_mm(rain, etc)
    nir = etc - pe
    return CropDay(kc, etc, pe, nir, field_volume_m3(nir, crop.area_ha))


def week_nir_mm(dates: Sequence[date], et0: Sequence[float], rain: Sequence[float], crop: Crop) -> float:
    """7-day (or n-day) NIR depth for one crop, mm."""
    _same_length(dates, et0, rain)
    return sum(crop_day(crop, d, e, r).nir_mm for d, e, r in zip(dates, et0, rain))


def week_field_volume_m3(
    dates: Sequence[date], et0: Sequence[float], rain: Sequence[float], crops: Sequence[Crop]
) -> float:
    """Sum of daily VOLUMES over all days and crops (never sums depths across crops)."""
    _same_length(dates, et0, rain)
    return sum(
        crop_day(c, d, e, r).volume_m3
        for c in crops
        for d, e, r in zip(dates, et0, rain)
    )


def breakeven_depth_mm(volume_m3: float, area_ha: float) -> float:
    """Depth (mm over the whole area) that equals a volume: volume / (area_ha * 10)."""
    return volume_m3 / (area_ha * M3_PER_MM_HA)


def _same_length(*seqs: Sequence) -> None:
    if len({len(s) for s in seqs}) != 1:
        raise ValueError("dates, et0 and rain must have the same length")


def head_volume_m3(field_m3: float, ea, ec):
    """Head (intake) volume = field / (Ea * Ec).

    Returns NOT_SCORED (the string "Not scored", never a number) unless BOTH
    efficiencies are accepted values in (0, 1].
    """
    ea_ok, ec_ok = accepted_efficiency(ea), accepted_efficiency(ec)
    if ea_ok is None or ec_ok is None:
        return NOT_SCORED
    return field_m3 / (ea_ok * ec_ok)


# --------------------------------------------------------------------------
# Percentiles
# --------------------------------------------------------------------------
def percentile(values: Sequence[float], q: float) -> float:
    """Percentile at position (n-1)*q/100 of the sorted list, linear interpolation."""
    if not values:
        raise ValueError("percentile of an empty list")
    if not (0 <= q <= 100):
        raise ValueError("q must be within 0..100")
    s = sorted(values)
    pos = (len(s) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (pos - lo) * (s[hi] - s[lo])


# --------------------------------------------------------------------------
# Roster comparison and alert rules (pure functions; the app only displays them)
# --------------------------------------------------------------------------
BELOW_P10 = "below P10"
INSIDE = "inside"
ABOVE_P90 = "above P90"


def roster_status(volume_m3: float, p10: float, p90: float) -> str:
    """Where a roster volume sits against ONE model's band."""
    if volume_m3 < p10:
        return BELOW_P10
    if volume_m3 > p90:
        return ABOVE_P90
    return INSIDE


def roster_alert_fires(status: str) -> bool:
    """One-sided: only a roster below the model's P10 is an alert. Above P90 is not."""
    return status == BELOW_P10


REQUIRED_INPUTS = ("Ea", "Ec", "soil_store", "bund_store")


def missing_inputs(a: dict[str, Assumption]) -> list[tuple[str, str]]:
    """(parameter, status) for every input that is missing, rejected or Not scored.

    The soil store is always listed: this demo does not model it.
    """
    listed: dict[str, str] = {}
    for key, row in a.items():
        if row.label == NOT_SCORED:
            listed[key] = NOT_SCORED
        elif row.value == "":
            listed[key] = "value missing"
    for key in REQUIRED_INPUTS:
        if key not in a and key not in listed:
            listed[key] = "missing"
    ea, ec = efficiencies(a)
    for key, val in (("Ea", ea), ("Ec", ec)):
        if val is None and key not in listed:
            listed[key] = "missing or rejected"
    if ea is None or ec is None:
        listed["head volume"] = f"{NOT_SCORED} (needs both Ea and Ec)"
    listed.setdefault("soil_store", NOT_SCORED)
    return list(listed.items())


@dataclass(frozen=True)
class StageShift:
    crop: str
    shift_days: int
    # (day, stage with the assumed planting date, stage with the shifted date)
    changes: tuple[tuple[date, str, str], ...]


def stage_shift_warnings(crops: Sequence[Crop], dates: Sequence[date], shift_days: int = 7) -> list[StageShift]:
    """Moving a planting date by +/- shift_days: list crops whose Kc stage changes
    on at least one day of the week."""
    out: list[StageShift] = []
    for c in crops:
        for s in (-shift_days, shift_days):
            moved = c.shifted(s)
            changes = tuple(
                (d, c.stage_on(d), moved.stage_on(d))
                for d in dates
                if c.stage_on(d) != moved.stage_on(d)
            )
            if changes:
                out.append(StageShift(c.name, s, changes))
    return out
