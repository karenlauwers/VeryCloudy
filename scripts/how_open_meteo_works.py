"""
How Open-Meteo historical weather API works — demonstration script.

Five real locations + dates are queried and the results are printed in two ways:
  1. A readable summary table for each location
  2. The raw JSON response for one example (so you can see the full structure)

No API key needed — Open-Meteo is completely free.
Endpoint: https://archive-api.open-meteo.com/v1/archive
"""

import json
import requests

# -------------------------
# 5 demo locations + dates
# -------------------------

EXAMPLES = [
    {
        "label":    "Rotselaar, België",
        "lat":      50.9530,
        "lon":      4.7167,
        "date":     "2009-07-28",
        "hour":     7,
    },
    {
        "label":    "Skagen, Denemarken",
        "lat":      57.7209,
        "lon":      10.5839,
        "date":     "2007-07-04",
        "hour":     9,
    },
    {
        "label":    "Granada, Spanje",
        "lat":      37.1882,
        "lon":      -3.6067,
        "date":     "2001-03-01",
        "hour":     11,
    },
    {
        "label":    "Erbusco, Italië",
        "lat":      45.5999,
        "lon":      9.9719,
        "date":     "2013-03-19",
        "hour":     15,
    },
    {
        "label":    "Hamont, België",
        "lat":      51.2500,
        "lon":      5.5500,
        "date":     "2024-09-22",
        "hour":     14,
    },
]

# Variables we request from Open-Meteo
HOURLY_VARS = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,"
    "pressure_msl,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
    "temperature_850hPa,temperature_500hPa,cape,"
    "wind_speed_10m,wind_direction_10m,"
    "rain,snowfall,weather_code"
)

URL = "https://archive-api.open-meteo.com/v1/archive"

# WMO weather code → human-readable description
WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm + slight hail", 99: "Thunderstorm + heavy hail",
}


# -------------------------
# Helper: fetch one example
# -------------------------

def fetch(example: dict) -> dict | None:
    """Call Open-Meteo for one location/date and return the full response dict."""
    params = {
        "latitude":   example["lat"],
        "longitude":  example["lon"],
        "start_date": example["date"],
        "end_date":   example["date"],
        "hourly":     HOURLY_VARS,
        "timezone":   "UTC",
    }
    resp = requests.get(URL, params=params, timeout=30)
    if resp.status_code != 200:
        print(f"  [ERROR] {resp.status_code}: {resp.text[:120]}")
        return None
    return resp.json()


def extract_hour(data: dict, hour: int) -> dict | None:
    """Pick the values for the requested UTC hour from the hourly arrays."""
    times = data.get("hourly", {}).get("time", [])
    target = f"{data['hourly']['time'][0][:10]}T{hour:02d}:00"
    try:
        idx = times.index(target)
    except ValueError:
        return None
    h = data["hourly"]
    def v(key):
        vals = h.get(key, [])
        return vals[idx] if idx < len(vals) else None
    return {
        "temp_2m":       v("temperature_2m"),
        "humidity":      v("relative_humidity_2m"),
        "dew_point":     v("dew_point_2m"),
        "pressure":      v("pressure_msl"),
        "clouds_total":  v("cloud_cover"),
        "clouds_low":    v("cloud_cover_low"),
        "clouds_mid":    v("cloud_cover_mid"),
        "clouds_high":   v("cloud_cover_high"),
        "temp_850hpa":   v("temperature_850hPa"),
        "temp_500hpa":   v("temperature_500hPa"),
        "cape":          v("cape"),
        "wind_speed":    v("wind_speed_10m"),
        "wind_deg":      v("wind_direction_10m"),
        "rain":          v("rain"),
        "snow":          v("snowfall"),
        "weather_code":  v("weather_code"),
    }


def weather_label(code) -> str:
    if code is None:
        return "—"
    return WMO_CODES.get(int(code), f"code {code}")


# -------------------------
# Pretty-print one result
# -------------------------

def print_summary(example: dict, values: dict):
    print(f"\n{'-' * 58}")
    print(f"  {example['label']}  |  {example['date']}  {example['hour']:02d}:00 UTC")
    print(f"  lat={example['lat']}, lon={example['lon']}")
    print(f"{'-' * 58}")
    print(f"  Weer:              {weather_label(values['weather_code'])}")
    print(f"  Temperatuur (2m):  {values['temp_2m']} °C")
    print(f"  Dauwpunt:          {values['dew_point']} °C")
    print(f"  Relatieve vochtigheid: {values['humidity']} %")
    print(f"  Luchtdruk:         {values['pressure']} hPa")
    print(f"  Bewolking totaal:  {values['clouds_total']} %")
    print(f"    waarvan laag:    {values['clouds_low']} %")
    print(f"    waarvan midden:  {values['clouds_mid']} %")
    print(f"    waarvan hoog:    {values['clouds_high']} %")
    print(f"  Temp @ 850 hPa:    {values['temp_850hpa']} °C  (~1500 m)")
    print(f"  Temp @ 500 hPa:    {values['temp_500hpa']} °C  (~5500 m)")
    print(f"  CAPE:              {values['cape']} J/kg  (convectie-energie)")
    print(f"  Wind:              {values['wind_speed']} km/h  richting {values['wind_deg']}°")
    print(f"  Neerslag:          regen {values['rain']} mm  |  sneeuw {values['snow']} cm")


# -------------------------
# Main demo
# -------------------------

print("=" * 58)
print("  Open-Meteo Historical API — demonstratie")
print("  Endpoint:", URL)
print("=" * 58)

raw_json_example = None  # we'll store one raw response to show the full structure

for i, example in enumerate(EXAMPLES):
    print(f"\n[{i+1}/5] Ophalen: {example['label']} ({example['date']} {example['hour']:02d}:00) …")
    data = fetch(example)
    if data is None:
        print("  Mislukt — sla over.")
        continue

    # Save raw JSON from the first example for the structural demo below
    if raw_json_example is None:
        raw_json_example = (example, data)

    values = extract_hour(data, example["hour"])
    if values is None:
        print("  Uur niet gevonden in response.")
        continue

    print_summary(example, values)

# -------------------------
# Show raw JSON structure
# -------------------------

if raw_json_example:
    ex, raw = raw_json_example
    print(f"\n\n{'=' * 58}")
    print(f"  RAW JSON response — {ex['label']} ({ex['date']})")
    print(f"  (eerste 3 uren getoond per variabele)")
    print(f"{'=' * 58}")

    # Trim each hourly array to first 3 values so output stays readable
    trimmed = dict(raw)
    if "hourly" in trimmed:
        trimmed["hourly"] = {
            k: (v[:3] if isinstance(v, list) else v)
            for k, v in raw["hourly"].items()
        }
    print(json.dumps(trimmed, indent=2))
