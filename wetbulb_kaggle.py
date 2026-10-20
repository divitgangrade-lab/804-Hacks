# =====================================================================
# WETBULB: carbon + water aware scheduling for Virginia data centers
# 804 Hacks 2026 · Track 2: Build a Sustainable Future
# =====================================================================
# KAGGLE SETUP
#   1. Attach these inputs (right panel -> Add Input):
#        kaitoland/us-grid-hourly-demand-generation-eia-930   (REQUIRED)
#        selfishgene/historical-hourly-weather-data           (fallback humidity)
#        arimancy/pjm-hourly-demand-weather                   (fallback temperature)
#   2. Settings -> Internet ON (for Open-Meteo weather; falls back without it)
#   3. Run All. Outputs land in /kaggle/working:
#        results.json, wetbulb_profile.json, replay_days.json, 1_..5_*.png
# =====================================================================

import glob
import json
import math
import os
import time
import urllib.request
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------- settings ----------------
INPUT_DIRS = ["/kaggle/input", "."]
OUT_DIR = "/kaggle/working" if os.path.isdir("/kaggle/working") else "."
BA = "PJM"                      # grid operator serving Virginia
LOCAL_TZ = "America/New_York"
LAT, LON = 39.04, -77.49        # Ashburn, VA: "Data Center Alley"
JOB_HOURS = 4                   # flexible AI job length
JOB_KW = 500                    # job power draw
SUBMIT_HOUR = 9                 # submitted 9 AM, must finish within 24 h
PUE = 1.3                       # facility power / IT power
BLEND_W = 0.5                   # Wetbulb default: equal weight carbon / water
FORECAST_DAYS = 7               # grid forecast = same hour, averaged over last 7 days

# Scale-up assumptions (printed with the result; change if you find better numbers)
VA_DC_AVG_LOAD_GW = 4.0         # average Virginia data center load (JLARC 2024: ~5 GW capacity)
FLEXIBLE_SHARE = 0.15           # share of that load that can wait a few hours
OLYMPIC_POOL_L = 2_500_000

# Direct emission factors, kg CO2 per MWh (= g per kWh). Approximate.
CARBON = {"coal": 1000, "natural_gas": 430, "petroleum": 800, "other_fuel": 500}
# Water CONSUMED by power plants, L per kWh (NREL, Macknick et al. 2012, medians,
# cooling-tower plants; hydro reservoir evaporation excluded). Approximate.
GRID_WATER = {"nuclear": 2.54, "coal": 2.60, "natural_gas": 0.75, "petroleum": 2.60, "other_fuel": 1.0}
GEN_COLS = ["coal", "natural_gas", "nuclear", "petroleum", "hydro", "solar",
            "solar_with_battery", "wind", "geothermal", "other_fuel"]


def step(msg):
    print(f"\n{'=' * 8} {msg} {'=' * (60 - len(msg))}", flush=True)


def find(name, dirs=None):
    for d in dirs or INPUT_DIRS:
        for root, _, files in os.walk(d, followlinks=True):
            if name in files:
                return os.path.join(root, name)
    return None


def stull_wetbulb(t_c, rh):
    """Wet-bulb temperature (C) from air temperature (C) and RH (%), Stull 2011."""
    t, rh = np.asarray(t_c, float), np.clip(np.asarray(rh, float), 1, 100)
    return (t * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + np.arctan(t + rh)
            - np.arctan(rh - 1.676331) + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh)
            - 4.686035)


def cooling_wue(twb):
    """Cooling-tower water, L per kWh. Free cooling below 10 C wet-bulb.
    Illustrative linear model tuned to the ~1.8 L/kWh US average (LBNL 2016)."""
    return np.clip(0.15 * (np.asarray(twb, float) - 10.0), 0.0, 3.0)


# =====================================================================
# 1. GRID: PJM fuel mix -> carbon and power-plant water per kWh
# =====================================================================
step("1. Loading PJM fuel mix (EIA-930)")
FUEL_FILE = "ba_hourly_generation_by_fuel.csv"
KAGGLE_SLUG = "kaitoland/us-grid-hourly-demand-generation-eia-930"
# EIA bulk-file column -> our column (the "(Adjusted)" generation columns)
EIA_MAP = {"coal": "coal", "natural gas": "natural_gas", "nuclear": "nuclear",
           "all petroleum products": "petroleum", "hydropower excluding pumped storage": "hydro",
           "solar without integrated battery storage": "solar",
           "solar with integrated battery storage": "solar_with_battery",
           "wind without integrated battery storage": "wind", "geothermal": "geothermal",
           "other fuel sources": "other_fuel"}


def load_kaggle_csv(path):
    header = pd.read_csv(path, nrows=0).columns
    cols = ["ba_code", "utc_hour_end"] + [c for c in GEN_COLS if c in header]
    parts = [ch[ch["ba_code"] == BA] for ch in pd.read_csv(path, usecols=cols, chunksize=500_000)]
    raw = pd.concat(parts)
    raw["t"] = pd.to_datetime(raw["utc_hour_end"], utc=True)
    return raw.groupby("t")[[c for c in GEN_COLS if c in raw]].mean()


def load_eia_direct():
    """Public EIA-930 six-month bulk files (needs Internet ON)."""
    frames = []
    for year in (2024, 2025, 2026):
        for half in ("Jan_Jun", "Jul_Dec"):
            url = f"https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{year}_{half}.csv"
            try:
                d = pd.read_csv(url, thousands=",", low_memory=False)
            except Exception as e:
                print(f"  skip {year} {half}: {str(e)[:60]}")
                continue
            d = d[d["Balancing Authority"] == BA]
            out = pd.DataFrame({"t": pd.to_datetime(d["UTC Time at End of Hour"], format="%m/%d/%Y %I:%M:%S %p", utc=True)})
            for col in d.columns:
                low = " ".join(col.lower().split())
                for k, v in EIA_MAP.items():
                    if low == f"net generation (mw) from {k} (adjusted)":
                        out[v] = pd.to_numeric(d[col], errors="coerce").to_numpy()
            print(f"  EIA {year} {half}: {len(out):,} PJM hours")
            frames.append(out)
    assert frames, "Could not download EIA files either. Turn Settings -> Internet ON."
    return pd.concat(frames).groupby("t").mean()


fuel_path = find(FUEL_FILE)
if not fuel_path:
    print("  Not found under /kaggle/input. Files that ARE there:")
    for root, _, files in os.walk("/kaggle/input", followlinks=True):
        for f in files[:5]:
            print("   ", os.path.join(root, f))
    try:
        import kagglehub
        print("  Trying kagglehub download...")
        fuel_path = find(FUEL_FILE, [kagglehub.dataset_download(KAGGLE_SLUG)])
    except Exception as e:
        print("  kagglehub failed:", str(e)[:120])
if fuel_path:
    print("file:", fuel_path)
    gen = load_kaggle_csv(fuel_path)
else:
    print("  Falling back to EIA's public bulk files (about 1-2 minutes)...")
    gen = load_eia_direct()
gen = gen.clip(lower=0).fillna(0)
total = gen.sum(axis=1)
gen, total = gen[total > 0], total[total > 0]
grid = pd.DataFrame(index=gen.index)
grid["ci"] = sum(gen[f] * v for f, v in CARBON.items() if f in gen) / total
grid["gw"] = sum(gen[f] * v for f, v in GRID_WATER.items() if f in gen) / total
grid["nuclear_share"] = gen.get("nuclear", 0) / total
grid["solar_share"] = (gen.get("solar", 0) + gen.get("solar_with_battery", 0)) / total
grid = grid.resample("h").mean().interpolate(limit=6).dropna()
print(f"{len(grid):,} hours, {grid.index.min():%Y-%m-%d} to {grid.index.max():%Y-%m-%d}")
print(f"carbon avg {grid.ci.mean():.0f} g/kWh (min {grid.ci.min():.0f}, max {grid.ci.max():.0f})")
print(f"power-plant water avg {grid.gw.mean():.2f} L/kWh")

# =====================================================================
# 2. WEATHER: Ashburn temperature, humidity, wet-bulb
# =====================================================================
step("2. Loading Ashburn weather")
weather, weather_source = None, None
try:
    start = grid.index.min().strftime("%Y-%m-%d")
    end = min(grid.index.max(), pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={LAT}&longitude={LON}&start_date={start}&end_date={end}"
           "&hourly=temperature_2m,relative_humidity_2m,wet_bulb_temperature_2m&timezone=GMT")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                js = json.load(r)["hourly"]
            break
        except Exception as e:
            print(f"  Open-Meteo attempt {attempt + 1} failed: {e}")
            time.sleep(3)
    else:
        raise RuntimeError("Open-Meteo unreachable")
    weather = pd.DataFrame({"temp": js["temperature_2m"], "rh": js["relative_humidity_2m"],
                            "twb": js["wet_bulb_temperature_2m"]},
                           index=pd.to_datetime(js["time"], utc=True)).astype(float)
    weather["twb"] = weather["twb"].fillna(pd.Series(stull_wetbulb(weather.temp, weather.rh), index=weather.index))
    weather = weather.dropna()
    weather_source = "Open-Meteo archive (ERA5), Ashburn VA"
except Exception as e:
    print("  No internet weather:", e)

if weather is None or len(weather) < 1000:
    print("  Using offline fallback: Philadelphia humidity climatology (selfishgene)")
    hum_p, tmp_p = find("humidity.csv"), find("temperature.csv")
    if hum_p and tmp_p:
        h = pd.read_csv(hum_p, usecols=["datetime", "Philadelphia"], parse_dates=["datetime"]).dropna()
        tk = pd.read_csv(tmp_p, usecols=["datetime", "Philadelphia"], parse_dates=["datetime"]).dropna()
        clim = h.merge(tk, on="datetime", suffixes=("_rh", "_k"))
        clim["month"], clim["hour"] = clim.datetime.dt.month, clim.datetime.dt.hour  # source is UTC
        clim = clim.groupby(["month", "hour"]).agg(rh=("Philadelphia_rh", "mean"),
                                                   temp=("Philadelphia_k", lambda k: (k - 273.15).mean()))
    else:
        clim = None
    idx = grid.index
    key = pd.MultiIndex.from_arrays([idx.month, idx.hour])
    weather = pd.DataFrame(index=idx)
    weather["rh"] = clim["rh"].reindex(key).to_numpy() if clim is not None else 65.0
    weather["temp"] = clim["temp"].reindex(key).to_numpy() if clim is not None else 15.0
    dc_p = find("pjm_demand_weather_hourly_v1.parquet")
    if dc_p:   # real Washington DC temperatures beat the climatology
        dc = pd.read_parquet(dc_p, columns=["datetime_utc", "temp_c_washington_dc"])
        dc = dc.set_index(pd.to_datetime(dc["datetime_utc"], utc=True))["temp_c_washington_dc"]
        weather["temp"] = dc.reindex(idx).fillna(weather["temp"]).to_numpy()
    weather["twb"] = stull_wetbulb(weather.temp, weather.rh)
    weather = weather.dropna()
    weather_source = "Fallback: humidity climatology" + (" + real DC temperature" if dc_p else "")
print("source:", weather_source)
print(f"wet-bulb avg {weather.twb.mean():.1f} C (max {weather.twb.max():.1f})")

# =====================================================================
# 3. COMBINE: total water per kWh of IT load
# =====================================================================
step("3. Combining carbon + water")
df = grid.join(weather, how="inner")
df["wue"] = cooling_wue(df.twb)
df["water"] = df.wue + PUE * df.gw          # L per kWh of IT load
df["ci_fac"] = df.ci * PUE                   # g CO2 per kWh of IT load
loc = df.index.tz_convert(LOCAL_TZ)
df["hour"], df["month"], df["date"] = loc.hour, loc.month, loc.date
df["season"] = df.month.map(lambda m: "Summer" if m in (6, 7, 8) else "Winter" if m in (12, 1, 2) else "Spring/Fall")
print(f"{len(df):,} joined hours | water avg {df.water.mean():.2f} L/kWh "
      f"(cooling {df.wue.mean():.2f} + grid {PUE * df.gw.mean():.2f})")

# =====================================================================
# 4. STORY CHECK: do carbon and water want the same hours?
# =====================================================================
step("4. Story check: CONFLICT or ALIGNED?")
dev = df[["ci", "water"]] - df.groupby("date")[["ci", "water"]].transform("mean")
within_day_corr = float(dev.ci.corr(dev.water))


def best_start(values, hours=JOB_HOURS):
    v = np.asarray(values, float)
    means = np.convolve(v, np.ones(hours) / hours, mode="valid")
    return int(np.argmin(means))


gaps = []
for d, g in df.groupby("date"):
    if len(g) == 24:
        gaps.append(abs(best_start(g.ci) - best_start(g.water)))
gaps = np.array(gaps)
conflict_share = float((gaps >= 4).mean()) if len(gaps) else float("nan")
verdict = "CONFLICT" if (within_day_corr < 0.3 or conflict_share >= 0.3) else "ALIGNED"
prof = df.groupby("hour")[["ci", "water", "wue", "gw"]].mean()
cleanest_hour, thirstiest_hour = int(prof.ci.idxmin()), int(prof.water.idxmax())
least_thirsty_hour, dirtiest_hour = int(prof.water.idxmin()), int(prof.ci.idxmax())
print(f"within-day correlation (carbon vs water): {within_day_corr:+.2f}")
print(f"days where best carbon window and best water window are 4+ h apart: {100 * conflict_share:.0f}%")
print(f"cleanest hour on average: {cleanest_hour}:00 | least thirsty hour: {least_thirsty_hour}:00")
print(f"\n>>> VERDICT: {verdict}")
print("   CONFLICT -> pitch 'the cleanest hour is often the thirstiest hour'" if verdict == "CONFLICT"
      else "   ALIGNED  -> pitch 'the night shift wins twice'")

# =====================================================================
# 5. BACKTEST: 4 policies, job submitted 9 AM, 24 h deadline
# =====================================================================
step("5. Backtest")
# Honest forecasts: grid = same hour averaged over the previous FORECAST_DAYS days;
# weather = actual (stand-in for a next-day weather forecast, which is accurate).
for c in ("ci_fac", "gw"):
    df[f"pred_{c}"] = df.groupby("hour")[c].transform(
        lambda s: s.shift(1).rolling(FORECAST_DAYS, min_periods=3).mean())
df["pred_water"] = df.wue + PUE * df.pred_gw
POLICIES = {"Run now": None, "Carbon only": 1.0, "Water only": 0.0, "Wetbulb": BLEND_W}
kwh = JOB_KW * JOB_HOURS


def choose(win, w):
    if w is None:
        return 0
    c, wa = win.pred_ci_fac.to_numpy(), win.pred_water.to_numpy()
    score = w * c / c.mean() + (1 - w) * wa / wa.mean()
    return best_start(score)


def backtest(submit_hour, weights=POLICIES):
    rows = []
    starts = np.where((df.hour.to_numpy() == submit_hour))[0]
    for i in starts:
        win = df.iloc[i:i + 24]
        if len(win) < 24 or (win.index[-1] - win.index[0]) != pd.Timedelta(hours=23) or win.isna().any().any():
            continue
        row = {"i": int(i), "date": str(df.date.iloc[i])}
        for name, w in weights.items():
            s = choose(win, w)
            seg = win.iloc[s:s + JOB_HOURS]
            row[f"{name}|start"] = s
            row[f"{name}|kg"] = seg.ci_fac.mean() * kwh / 1000
            row[f"{name}|L"] = seg.water.mean() * kwh
            row[f"{name}|onsite"] = seg.wue.mean() * kwh
        row["month"] = int(df.month.iloc[i])
        rows.append(row)
    return pd.DataFrame(rows)


bt = backtest(SUBMIT_HOUR)
assert len(bt), "Backtest found no complete days; check the data printouts above."
def summarize(b):
    out = []
    for name in POLICIES:
        kg, L, on = b[f"{name}|kg"].mean(), b[f"{name}|L"].mean(), b[f"{name}|onsite"].mean()
        out.append({"policy": name, "kg_co2": round(kg, 1), "liters": round(L, 0), "onsite_liters": round(on, 0),
                    "co2_saved_pct": round(100 * (1 - kg / b["Run now|kg"].mean()), 1),
                    "water_saved_pct": round(100 * (1 - L / b["Run now|L"].mean()), 1),
                    "onsite_saved_pct": round(100 * (1 - on / max(b["Run now|onsite"].mean(), 1e-9)), 1)})
    return pd.DataFrame(out)


summary = summarize(bt)
summary_summer = summarize(bt[bt.month.isin([6, 7, 8])])
print(f"{len(bt)} days | {JOB_HOURS} h job at {JOB_KW} kW, submitted {SUBMIT_HOUR}:00, 24 h deadline")
print(summary.to_string(index=False))
print("\nSUMMER ONLY (Jun-Aug):")
print(summary_summer.to_string(index=False))
wb = summary.set_index("policy").loc["Wetbulb"]
print(f"\n>>> Wetbulb: -{wb.onsite_saved_pct}% on-site cooling water, -{wb.water_saved_pct}% total water, "
      f"-{wb.co2_saved_pct}% CO2 vs running immediately")

# trade-off sweep (the slider)
sweep = []
for w in np.round(np.linspace(0, 1, 11), 1):
    b = backtest(SUBMIT_HOUR, {"Run now": None, "x": w})
    sweep.append({"w_carbon": float(w),
                  "co2_saved_pct": round(100 * (1 - b["x|kg"].mean() / b["Run now|kg"].mean()), 1),
                  "water_saved_pct": round(100 * (1 - b["x|L"].mean() / b["Run now|L"].mean()), 1)})
sweep = pd.DataFrame(sweep)
print("\nSlider sweep (w_carbon = 1 means carbon only):")
print(sweep.to_string(index=False))

# =====================================================================
# 6. VIRGINIA SCALE-UP (all submit hours, not just 9 AM)
# =====================================================================
step("6. Virginia scale-up")
allh = pd.concat([backtest(h, {"Run now": None, "Wetbulb": BLEND_W}) for h in range(0, 24, 3)])
d_g = (allh["Run now|kg"].mean() - allh["Wetbulb|kg"].mean()) * 1000 / kwh     # g CO2 saved per kWh
d_l = (allh["Run now|L"].mean() - allh["Wetbulb|L"].mean()) / kwh              # L saved per kWh
d_on = (allh["Run now|onsite"].mean() - allh["Wetbulb|onsite"].mean()) / kwh    # on-site L saved per kWh
flex_kwh = VA_DC_AVG_LOAD_GW * 1e6 * FLEXIBLE_SHARE * 8760
scale = {"assumptions": f"{VA_DC_AVG_LOAD_GW} GW average Virginia data center load, "
                        f"{int(FLEXIBLE_SHARE * 100)}% flexible, savings averaged over submit times every 3 h",
         "flexible_kwh_per_year": flex_kwh,
         "co2_tons_per_year": round(flex_kwh * d_g / 1e6, 0),
         "water_liters_per_year": round(flex_kwh * d_l, 0),
         "olympic_pools_per_year": round(flex_kwh * d_l / OLYMPIC_POOL_L, 0),
         "onsite_water_liters_per_year": round(flex_kwh * d_on, 0),
         "onsite_water_gallons_per_year": round(flex_kwh * d_on / 3.785, 0),
         "onsite_olympic_pools_per_year": round(flex_kwh * d_on / OLYMPIC_POOL_L, 0),
         "onsite_saved_pct_all_hours": round(100 * d_on * kwh / allh["Run now|onsite"].mean(), 1),
         "co2_saved_pct_all_hours": round(100 * d_g * kwh / 1000 / allh["Run now|kg"].mean(), 1),
         "water_saved_pct_all_hours": round(100 * d_l * kwh / allh["Run now|L"].mean(), 1)}
print("assumptions:", scale["assumptions"])
print(f">>> ~{scale['co2_tons_per_year']:,.0f} t CO2 and ~{scale['olympic_pools_per_year']:,.0f} "
      f"Olympic pools of water per year")
print(f">>> on-site cooling water: ~{scale['onsite_water_gallons_per_year'] / 1e6:,.0f} million gallons "
      f"({scale['onsite_saved_pct_all_hours']}% of flexible jobs' cooling water) per year")

# =====================================================================
# 7. REPLAY DAYS for the live demo
# =====================================================================
step("7. Picking replay days")
bt["mean_twb"] = [df.twb.iloc[i:i + 24].mean() for i in bt.i]
bt["month"] = [df.month.iloc[i] for i in bt.i]
bt["gap"] = (bt["Carbon only|start"] - bt["Water only|start"]).abs()
bt["onsite_saved"] = bt["Run now|onsite"] - bt["Wetbulb|onsite"]
summer = bt[bt.month.isin([6, 7, 8])]
winter = bt[bt.month.isin([12, 1, 2])]
picks = {}
if len(summer):
    picks["best_summer"] = summer.sort_values("onsite_saved").iloc[-1]
if len(summer):
    latest = summer.date.str[:4].max()
    picks["humid_summer"] = summer[summer.date.str[:4] == latest].sort_values("mean_twb").iloc[-1]
if len(winter):
    picks["cold_winter"] = winter.sort_values("mean_twb").iloc[0]
picks["conflict"] = bt.sort_values(["gap", "mean_twb"]).iloc[-1]
titles = {"best_summer": "The summer day where waiting saved the most water",
          "humid_summer": "The most humid summer day", "cold_winter": "The coldest winter day",
          "conflict": "The day carbon and water disagreed most"}
replay = []
for key, r in picks.items():
    win = df.iloc[int(r.i):int(r.i) + 24]
    lt = win.index.tz_convert(LOCAL_TZ)
    replay.append({
        "id": key, "title": titles[key], "date": r.date,
        "label": lt[0].strftime("%B %-d, %Y"),
        "hours": [{"t": t.strftime("%Y-%m-%dT%H:00"), "label": t.strftime("%-I%p"),
                   "temp": round(x.temp, 1), "rh": round(x.rh, 0), "twb": round(x.twb, 1),
                   "ci": round(x.ci_fac, 0), "gw": round(PUE * x.gw, 2), "wue": round(x.wue, 2),
                   "water": round(x.water, 2), "pred_ci": round(x.pred_ci_fac, 0),
                   "pred_water": round(x.pred_water, 2)}
                  for t, (_, x) in zip(lt, win.iterrows())],
        "starts": {p: int(r[f"{p}|start"]) for p in POLICIES},
        "kg": {p: round(float(r[f"{p}|kg"]), 1) for p in POLICIES},
        "liters": {p: round(float(r[f"{p}|L"]), 0) for p in POLICIES},
    })
    print(f"{key:13s} {r.date}  wet-bulb avg {r.mean_twb:.1f} C  | Wetbulb starts +{int(r['Wetbulb|start'])} h, "
          f"saves {r['Run now|L'] - r['Wetbulb|L']:.0f} L, {r['Run now|kg'] - r['Wetbulb|kg']:.0f} kg CO2")

# =====================================================================
# 8. CHARTS
# =====================================================================
step("8. Charts")
plt.rcParams.update({"figure.dpi": 120, "axes.spines.top": False, "axes.spines.right": False})
C_CARBON, C_WATER, C_PICK = "#4a4f57", "#1f6fb2", "#c98a12"

fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
for ax, col, title, cmap in [(axes[0], "ci_fac", "Carbon (g CO2 per kWh)", "Greys"),
                             (axes[1], "water", "Water (L per kWh)", "Blues")]:
    hm = df.pivot_table(index="month", columns="hour", values=col, aggfunc="mean")
    im = ax.imshow(hm, aspect="auto", cmap=cmap)
    ax.set(title=title, xlabel="Hour of day (Eastern)", ylabel="Month",
           yticks=range(len(hm.index)), yticklabels=hm.index)
    fig.colorbar(im, ax=ax)
fig.suptitle(f"Two footprints, PJM grid + Ashburn weather  ·  verdict: {verdict}")
fig.tight_layout(); fig.savefig(f"{OUT_DIR}/1_heatmaps.png"); plt.show()

fig, ax = plt.subplots(figsize=(10, 4.5))
for season, ls in [("Summer", "-"), ("Winter", "--")]:
    p = df[df.season == season].groupby("hour")[["ci_fac", "water"]].mean()
    ax.plot(p.index, p.ci_fac / p.ci_fac.mean(), color=C_CARBON, ls=ls, lw=2, label=f"Carbon, {season}")
    ax.plot(p.index, p.water / p.water.mean(), color=C_WATER, ls=ls, lw=2, label=f"Water, {season}")
ax.axhline(1, color="#ccc", lw=1)
ax.set(title="Daily rhythm (1.0 = that season's average)", xlabel="Hour of day (Eastern)",
       ylabel="Relative to average")
ax.legend(ncol=2); fig.tight_layout(); fig.savefig(f"{OUT_DIR}/2_daily_rhythm.png"); plt.show()

fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
colors = ["#bbbbbb", C_CARBON, C_WATER, C_PICK]
axes[0].bar(summary.policy, summary.kg_co2, color=colors); axes[0].set(title="kg CO2 per job", ylabel="kg")
axes[1].bar(summary.policy, summary.liters, color=colors); axes[1].set(title="Liters of water per job", ylabel="L")
fig.suptitle(f"Backtest: {len(bt)} real days, {JOB_HOURS} h job at {JOB_KW} kW submitted {SUBMIT_HOUR} AM")
fig.tight_layout(); fig.savefig(f"{OUT_DIR}/3_backtest.png"); plt.show()

fig, ax = plt.subplots(figsize=(6.5, 5))
ax.plot(sweep.co2_saved_pct, sweep.water_saved_pct, "-o", color=C_PICK)
for _, r in sweep.iloc[[0, 5, 10]].iterrows():
    ax.annotate(f"w={r.w_carbon:.1f}", (r.co2_saved_pct, r.water_saved_pct), textcoords="offset points", xytext=(6, 6))
ax.set(title="The slider: carbon saved vs water saved", xlabel="% CO2 saved", ylabel="% water saved")
fig.tight_layout(); fig.savefig(f"{OUT_DIR}/4_tradeoff.png"); plt.show()

demo = replay[0]
hrs = demo["hours"]
fig, ax = plt.subplots(figsize=(12, 4.5))
x = np.arange(24)
ax.plot(x, [h["ci"] / np.mean([k["ci"] for k in hrs]) for h in hrs], color=C_CARBON, lw=2.5, label="Carbon")
ax.plot(x, [h["water"] / np.mean([k["water"] for k in hrs]) for h in hrs], color=C_WATER, lw=2.5, ls="--", label="Water")
ax.axvspan(-0.5, JOB_HOURS - 0.5, color="#dddddd", label="Run now")
s = demo["starts"]["Wetbulb"]
ax.axvspan(s - 0.5, s + JOB_HOURS - 0.5, color=C_PICK, alpha=0.3, label="Wetbulb pick")
ax.set_xticks(x[::2]); ax.set_xticklabels([h["label"] for h in hrs][::2])
ax.set(title=f"Replay: {demo['title']} ({demo['label']})", ylabel="Relative to day average")
ax.legend(); fig.tight_layout(); fig.savefig(f"{OUT_DIR}/5_replay_day.png"); plt.show()

# =====================================================================
# 9. EXPORT JSON for the dashboard and slides
# =====================================================================
step("9. Export")
recent = df[df.index >= df.index.max() - pd.Timedelta(days=FORECAST_DAYS)].groupby("hour")[["ci_fac", "gw"]].mean()
mh = df.groupby(["month", "hour"])[["ci_fac", "gw", "wue", "water", "twb"]].mean().round(3)
profile = {
    "generated": pd.Timestamp.now(tz="UTC").isoformat(),
    "constants": {"pue": PUE, "wue_formula": "clip(0.15*(twb-10),0,3)", "job_hours": JOB_HOURS, "job_kw": JOB_KW,
                  "carbon_factors_kg_per_mwh": CARBON, "grid_water_l_per_kwh": GRID_WATER},
    "recent_grid_by_hour": {int(h): {"ci": round(r.ci_fac, 1), "gw": round(PUE * r.gw, 3)} for h, r in recent.iterrows()},
    "month_hour": {f"{m}-{h}": {"ci": r.ci_fac, "gw": round(PUE * r.gw, 3), "wue": r.wue, "water": r.water, "twb": r.twb}
                   for (m, h), r in mh.iterrows()},
}
results = {
    "data": {"grid": "EIA-930 via Kaggle (kaitoland), PJM", "weather": weather_source,
             "start": str(df.index.min().date()), "end": str(df.index.max().date()), "hours": len(df),
             "days_backtested": len(bt)},
    "averages": {"carbon_g_per_kwh": round(df.ci_fac.mean(), 0), "water_l_per_kwh": round(df.water.mean(), 2),
                 "cooling_l_per_kwh": round(df.wue.mean(), 2), "grid_water_l_per_kwh": round(PUE * df.gw.mean(), 2),
                 "max_wetbulb_c": round(df.twb.max(), 1)},
    "story": {"verdict": verdict, "within_day_corr": round(within_day_corr, 2),
              "conflict_share_pct": round(100 * conflict_share, 0), "cleanest_hour": cleanest_hour,
              "dirtiest_hour": dirtiest_hour, "least_thirsty_hour": least_thirsty_hour,
              "thirstiest_hour": thirstiest_hour},
    "job": {"hours": JOB_HOURS, "kw": JOB_KW, "submit_hour": SUBMIT_HOUR},
    "backtest": summary.to_dict("records"),
    "backtest_summer": summary_summer.to_dict("records"),
    "tradeoff": sweep.to_dict("records"),
    "scale_up": scale,
    "replay_days": [{"id": r["id"], "title": r["title"], "label": r["label"], "kg": r["kg"], "liters": r["liters"]}
                    for r in replay],
}
for name, obj in [("results.json", results), ("wetbulb_profile.json", profile), ("replay_days.json", replay)]:
    with open(os.path.join(OUT_DIR, name), "w") as f:
        json.dump(obj, f, indent=1, default=float)
    print("saved", os.path.join(OUT_DIR, name))
print("\nDONE. Download results.json, wetbulb_profile.json, replay_days.json and the 5 PNGs from /kaggle/working.")
print(json.dumps(results["story"], indent=1))
