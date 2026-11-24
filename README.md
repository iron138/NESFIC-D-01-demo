# NESFIC 2026 D-01 demo: illustrative irrigation water demand week

> **Illustrative week. Assumed inputs. Not a scheme gate. Weather data by Open-Meteo.com (CC BY 4.0). Free API is non-commercial.**

A small local Streamlit page. It runs an FAO-56 style crop water balance for **one illustrative
500 ha command area** (400 ha rice, 100 ha mustard) for one assumed week (10 to 16 November 2026)
and compares a release plan that you type in with a demand range taken from three weather-model
ensembles (ECMWF, GFS, ICON).

It is decision-support only. It is **not** a real scheme, **not** validated, and uses **no machine
learning**.

## Banner shown on every screen

> Illustrative week. Assumed inputs. Not a scheme gate. Compare; do not treat as a gate order.

## Screens

1. **Overview**: pin text, the assumptions table (every row labelled), crop stage and Kc for each
   crop and day, and a button to export `assumptions.csv`.
2. **Demand and plan**: ECMWF is the headline band (50 members); GFS (30) and ICON (39) are shown
   beside it ("models disagree; never averaged"). Field and head volumes at P10/P50/P90, the
   break-even depth per model, your typed roster (mm/week at the field, default 20, "example, not a
   department figure") shown as below P10 / inside / above P90, and a bar chart with P10 to P90
   whiskers. Rice demand is a *lower bound (puddling and percolation omitted)*.
3. **Alerts** (only rules that fire): roster below a model's P10 (one-sided; above the band is not
   an alert), missing or Not scored inputs (the soil store is always listed), and a stage warning
   when moving a planting date by +/-7 days changes the Kc stage during the week.

Labels used throughout: Measured / Estimated / Assumed / Not scored.

## How the numbers are made

* Kc is piecewise linear over four stages; day 1 is the planting day.
* Per day and crop: `ETc = Kc x ET0`, `Pe = min(max(rain, 0), ETc)`, `NIR = ETc - Pe`,
  field volume (m3) = `NIR (mm) x area (ha) x 10`. Volumes of crops are added, never depths.
* Head volume = field volume / (Ea x Ec), only when both efficiencies are accepted; otherwise
  "Not scored".
* Per model: for each **numbered** member (keys ending `_memberNN`) the 7-day command volume of
  both crops is computed, then P10/P50/P90 are read from that one sorted list (linear
  interpolation at position `(n-1) x q/100`). The unsuffixed series (control run) is excluded.
* Models are never averaged or pooled, and percentiles of parts are never added.
* Break-even depth = P50 field volume / (area in ha x 10).

## Install and run

Python 3.11 or newer. Run these from the `nesfic_demo` folder.

**Windows (PowerShell)**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process RemoteSigned
pip install -r requirements.txt
streamlit run app.py
```

**Windows (cmd)**

```bat
py -3 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
streamlit run app.py
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open <http://localhost:8501>. `.streamlit/config.toml` sets a light theme, turns Streamlit's
usage statistics off and hides the Deploy button. The app reads only the files in `./data`.

`requirements.txt` pins the exact versions this was run with (streamlit 1.67.0, pandas 3.1.1,
altair 6.3.0, pytest 9.2.0). Other versions have not been tried.

**Where it was run:** Python 3.15.2 on Fedora Linux. It has **not** been run on Windows.

## Run the tests

```
python -m pytest -v
```

The last full output is saved in `tests_report.txt` (37 passed). What the tests do and do not show:

* They check the arithmetic against fixed expected values: a hand-worked day (T1), the no-rain
  control week (T3), the percentile rule (T5), the bands, break-even depths and member counts
  (T6 to T9), the rule that head volume is "Not scored" without both efficiencies (T11), and
  that the alert rules and screens behave as described.
* T10 scans `balance.py`, `ensemble.py` and `app.py` for averaging, summing or pooling calls and for
  network imports. It is a structural guard, not a proof.
* The band, break-even and per-crop expected values (T6 to T9, and the ECMWF z60 sensitivity) came
  from an earlier analysis. The code reproduces them exactly. That shows the code and that analysis
  agree. It does **not** show that either matches real irrigation demand.
* No test compares anything with observed data.

## Layout

```
nesfic_demo/
  assumptions.csv        every assumed input, with a label column
  balance.py             Kc, daily and weekly balance, percentile, roster and alert rules
  ensemble.py            reader for ./data, per-model bands (numbered members only)
  app.py                 Streamlit page
  tests/                 test_balance.py, test_app.py
  data/                  the four JSON files below
  data_checksums.txt     sha256 of the four files
  tests_report.txt       output of `pytest -v`
  screenshots/           1280 px full-page captures
  tools/make_screenshots.py   optional helper (needs Playwright; not in requirements.txt)
  requirements.txt  README.md  .streamlit/config.toml
```

## Data files

Open-Meteo ensemble API JSON, daily values for 2026-11-10 to 2026-11-16 (7 days each). The app
reads these local copies only.

| File | Role | Members | sha256 |
|---|---|---|---|
| `data/ecmwf_ens.json` | ECMWF, headline (grid elevation 215 m) | 50 | `dae46426073f75e6b6ffed3a9f36f0cd8df2494ffe54ab6f4ac9d879b171d97e` |
| `data/om_ensemble_gfs_guwahati.json` | GFS | 30 | `197c3d6bb6a90833d32835516992f4ebd6e5a6a447bcd7d2c4708b07b432a166` |
| `data/icon_ens.json` | ICON (grid point 26.307N, 91.752E) | 39 | `b6bb61037aeaffc3f20b9613806d5f498c738d4e6c26ed14bb49978ba7f2bbb2` |
| `data/ecmwf_ens_z60.json` | ECMWF at 60 m grid elevation, sensitivity test only (not shown in the app) | 50 | `702761cf35eea3f56b02c16c0681e0fa85a375c57d7ec2ed5c217fa0e2496e15` |

Check them:

```
sha256sum -c data_checksums.txt                       # Linux / macOS (run in nesfic_demo)
Get-FileHash -Algorithm SHA256 data\*.json            # Windows PowerShell; compare with the table
```

GFS and ECMWF are at 26.25N, 91.75E. ICON's grid point is about 6 km north of that, so the ICON
band is not a same-cell comparison.

## Licences and data terms

* **Weather data by Open-Meteo.com, CC BY 4.0.** Attribution is shown in the app footer. The free
  Open-Meteo API is for non-commercial use.
* **The code makes no network calls.** There is no live weather fetch, and Streamlit's usage
  statistics are switched off in `.streamlit/config.toml`. (Installing the packages needs a
  network; running the app does not.)
* No licence has been chosen for this code. Add one before sharing it.

## Taking 1280 px wide full-page screenshots (for a PDF)

**By hand, in Chrome or Edge**: start the app, open <http://localhost:8501>, press `F12`, then
`Ctrl+Shift+M` (device toolbar). Choose *Responsive*, set the width to `1280`. Click the tab you
want (Overview, Demand and plan, Alerts). For the Alerts screen with an alert, first type `13` in the
roster box on Demand and plan and press Enter. Open the device toolbar's `...` menu and choose
*Capture full size screenshot*. The PNG goes to your Downloads folder.

**Scripted**: with the app running, `pip install playwright`, `playwright install chromium`, then
`python tools/make_screenshots.py screenshots http://localhost:8501`. This writes `overview.png`,
`demand_default.png` (roster 20), `alerts_default.png` (roster 20) and `alerts_roster13.png`
(roster 13), each 1280 px wide.

## Limits

* **Illustrative inputs.** The area, crop split, planting dates, stage lengths, efficiencies and
  roster are assumed. They do not describe a real scheme, and the pin is not a scheme gate.
* **No machine learning.** The page is a deterministic water balance over model weather output.
* **Not validated.** Nothing here has been compared with measured irrigation demand, and this
  README and the page make no accuracy claim.
* **What a band is.** A band is the spread of one model's members over one week (P10, P50, P90).
  It is not a confidence interval and says nothing about how often real demand falls inside it.
* **Models disagree.** The three bands differ, and the page never averages them. ECMWF is shown as
  the headline only by choice of presentation, not because it has been shown to be better.
* **Rice is a lower bound.** Puddling and percolation are omitted, so rice demand, and the command
  band, are understated.
* **Not scored.** Soil store and bund store are not modelled. Head volume is Not scored unless both
  Ea and Ec are accepted.
* **One week, one point.** Only 10 to 16 November 2026 and one pin are covered. Negative ECMWF rain
  values are set to 0.
* **Ensemble weather only.** ET0 and rain are model output (Estimated); Kc values are table values
  (Estimated).
