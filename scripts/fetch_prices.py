#!/usr/bin/env python3
"""
US Cost of Living Tracker
Fetches CPI data from the BLS API and generates a static HTML dashboard.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None  # Allow import for HTML generation without requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "prices.json"
HTML_FILE = BASE_DIR / "index.html"

BLS_API_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

# CPI-U, Not Seasonally Adjusted, U.S. City Average
SERIES = {
    "CUUR0000SA0":    {"name": "All Items",              "color": "#4e79a7", "category": "headline"},
    "CUUR0000SAF":    {"name": "Food & Beverages",       "color": "#f28e2b", "category": "food"},
    "CUUR0000SAF11":  {"name": "Food at Home",           "color": "#e15759", "category": "food"},
    "CUUR0000SEFV":   {"name": "Food Away from Home",    "color": "#76b7b2", "category": "food"},
    "CUUR0000SAH":    {"name": "Housing",                "color": "#59a14f", "category": "housing"},
    "CUUR0000SEHA":   {"name": "Rent of Primary Residence", "color": "#edc948", "category": "housing"},
    "CUUR0000SA0E":   {"name": "Energy",                 "color": "#b07aa1", "category": "energy"},
    "CUUR0000SETB01": {"name": "Gasoline (All Types)",   "color": "#ff9da7", "category": "energy"},
    "CUUR0000SEHF01": {"name": "Electricity",            "color": "#9c755f", "category": "energy"},
    "CUUR0000SAT":    {"name": "Transportation",         "color": "#bab0ac", "category": "transport"},
    "CUUR0000SAM":    {"name": "Medical Care",           "color": "#d37295", "category": "medical"},
    "CUUR0000SAA":    {"name": "Apparel",                "color": "#a0cbe8", "category": "apparel"},
    "CUUR0000SAE":    {"name": "Education & Communication", "color": "#8cd17d", "category": "education"},
    "CUUR0000SAR":    {"name": "Recreation",             "color": "#ffbe7d", "category": "recreation"},
}

# Groups for the breakdown charts
CHART_GROUPS = {
    "Food":        ["CUUR0000SAF", "CUUR0000SAF11", "CUUR0000SEFV"],
    "Housing":     ["CUUR0000SAH", "CUUR0000SEHA"],
    "Energy":      ["CUUR0000SA0E", "CUUR0000SETB01", "CUUR0000SEHF01"],
    "Services":    ["CUUR0000SAT", "CUUR0000SAM"],
    "Goods":       ["CUUR0000SAA", "CUUR0000SAR"],
    "Education":   ["CUUR0000SAE"],
}

# Key series for the summary cards
CARD_SERIES = ["CUUR0000SA0", "CUUR0000SAF", "CUUR0000SA0E", "CUUR0000SAH", "CUUR0000SAM", "CUUR0000SAT"]


# ---------------------------------------------------------------------------
# BLS data fetching
# ---------------------------------------------------------------------------

def fetch_bls_data() -> dict | None:
    """Fetch CPI data from the BLS API v1 (no key required)."""
    if requests is None:
        print("⚠️  'requests' module not available, skipping API fetch")
        return None
    payload = {"seriesid": list(SERIES.keys())}
    try:
        resp = requests.post(BLS_API_URL, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") != "REQUEST_SUCCEEDED":
            print(f"⚠️  BLS API returned status: {result.get('status')}")
            print(f"   Messages: {result.get('message', [])}")
            return None
        return result
    except requests.RequestException as exc:
        print(f"⚠️  BLS API request failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Data merging
# ---------------------------------------------------------------------------

def load_existing_data() -> dict:
    """Load existing prices.json or return an empty structure."""
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"last_updated": None, "series": {}}


def merge_data(existing: dict, api_result: dict) -> dict:
    """Merge new BLS data into existing data, deduplicating by year+period."""
    for series_entry in api_result["Results"]["series"]:
        sid = series_entry["seriesID"]
        if sid not in SERIES:
            continue

        # Existing observations keyed by year-period
        existing_series = existing["series"].get(sid, {
            "name": SERIES[sid]["name"],
            "data": []
        })
        obs_map = {(d["year"], d["period"]): d for d in existing_series["data"]}

        # Merge new observations
        for obs in series_entry["data"]:
            key = (obs["year"], obs["period"])
            if obs["period"].startswith("M"):
                month = int(obs["period"][1:])
                if month > 12:
                    continue  # Skip annual averages (M13)
                date_str = f"{obs['year']}-{month:02d}"
            else:
                continue
            # Skip unavailable data points (e.g. "-")
            if obs["value"] == "-" or obs["value"] is None:
                continue
            obs_map[key] = {
                "year": obs["year"],
                "period": obs["period"],
                "value": obs["value"],
                "date": date_str,
            }

        # Sort by date
        sorted_data = sorted(obs_map.values(), key=lambda d: d["date"])
        existing_series["name"] = SERIES[sid]["name"]
        existing_series["data"] = sorted_data
        existing["series"][sid] = existing_series

    existing["last_updated"] = datetime.now(timezone.utc).isoformat()
    return existing


# ---------------------------------------------------------------------------
# YoY inflation computation
# ---------------------------------------------------------------------------

def compute_yoy(data: dict) -> dict:
    """
    Compute year-over-year percent changes for each series.
    Returns {series_id: [{"date": "YYYY-MM", "yoy": float}, ...]}
    """
    yoy_data = {}
    for sid, series_info in data["series"].items():
        observations = series_info["data"]
        value_map = {}
        for d in observations:
            try:
                value_map[d["date"]] = float(d["value"])
            except (ValueError, TypeError):
                continue  # Skip unavailable data points
        yoy_list = []
        for obs in observations:
            date = obs["date"]
            year, month = date.split("-")
            prev_date = f"{int(year) - 1}-{month}"
            if prev_date in value_map and value_map[prev_date] != 0:
                change = ((float(obs["value"]) - value_map[prev_date]) / value_map[prev_date]) * 100
                yoy_list.append({"date": date, "yoy": round(change, 2)})
        yoy_data[sid] = yoy_list
    return yoy_data


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(data: dict, yoy_data: dict) -> str:
    """Generate a self-contained HTML dashboard."""

    last_updated = data.get("last_updated", "N/A")
    if last_updated and last_updated != "N/A":
        try:
            dt = datetime.fromisoformat(last_updated)
            last_updated = dt.strftime("%B %d, %Y at %I:%M %p UTC")
        except Exception:
            pass

    # Build card data
    cards_html = ""
    for sid in CARD_SERIES:
        if sid not in yoy_data or not yoy_data[sid]:
            continue
        info = SERIES[sid]
        latest = yoy_data[sid][-1]
        prev = yoy_data[sid][-2] if len(yoy_data[sid]) > 1 else None
        direction = ""
        if prev:
            if latest["yoy"] > prev["yoy"]:
                direction = '<span class="arrow up">▲</span>'
            elif latest["yoy"] < prev["yoy"]:
                direction = '<span class="arrow down">▼</span>'
            else:
                direction = '<span class="arrow flat">▶</span>'

        sign = "+" if latest["yoy"] >= 0 else ""
        rate_class = "rate-up" if latest["yoy"] > 0 else "rate-down" if latest["yoy"] < 0 else ""
        cards_html += f"""
        <div class="card" style="border-top: 4px solid {info['color']}">
            <div class="card-title">{info['name']}</div>
            <div class="card-rate {rate_class}">{sign}{latest['yoy']}% {direction}</div>
            <div class="card-date">YoY as of {latest['date']}</div>
        </div>"""

    # Prepare chart datasets as JSON
    # Main YoY chart
    main_datasets = []
    for sid, info in SERIES.items():
        if sid not in yoy_data or not yoy_data[sid]:
            continue
        points = [{"x": d["date"] + "-01", "y": d["yoy"]} for d in yoy_data[sid]]
        is_headline = sid == "CUUR0000SA0"
        ds = {
            "label": info["name"],
            "data": points,
            "borderColor": info["color"],
            "backgroundColor": info["color"] + "20",
            "borderWidth": 3 if is_headline else 1.5,
            "pointRadius": 0,
            "tension": 0.3,
            "hidden": not is_headline and sid not in [s for s in CARD_SERIES],
        }
        if is_headline:
            ds["trendlineLinear"] = {
                "colorMin": info["color"] + "60",
                "colorMax": info["color"] + "60",
                "lineStyle": "dotted",
                "width": 2,
            }
        main_datasets.append(ds)

    main_chart_json = json.dumps(main_datasets)

    # Breakdown charts
    breakdown_charts_js = ""
    breakdown_charts_html = ""
    for idx, (group_name, series_ids) in enumerate(CHART_GROUPS.items()):
        canvas_id = f"chart-{group_name.lower().replace(' ', '-')}"
        breakdown_charts_html += f"""
        <div class="chart-card">
            <h3>{group_name}</h3>
            <div class="chart-container-small">
                <canvas id="{canvas_id}"></canvas>
            </div>
        </div>"""

        datasets = []
        for sid in series_ids:
            if sid not in yoy_data or not yoy_data[sid]:
                continue
            info = SERIES[sid]
            points = [{"x": d["date"] + "-01", "y": d["yoy"]} for d in yoy_data[sid]]
            datasets.append({
                "label": info["name"],
                "data": points,
                "borderColor": info["color"],
                "backgroundColor": info["color"] + "20",
                "borderWidth": 2,
                "pointRadius": 0,
                "tension": 0.3,
                "fill": len(series_ids) == 1,
                "trendlineLinear": {
                    "colorMin": info["color"] + "50",
                    "colorMax": info["color"] + "50",
                    "lineStyle": "dotted",
                    "width": 1.5,
                },
            })

        ds_json = json.dumps(datasets)
        breakdown_charts_js += f"""
    new Chart(document.getElementById('{canvas_id}'), {{
        type: 'line',
        data: {{ datasets: {ds_json} }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                legend: {{ position: 'bottom', labels: {{ boxWidth: 12, padding: 10, font: {{ size: 11 }} }} }},
                tooltip: {{ mode: 'index', intersect: false, callbacks: {{ label: function(ctx) {{ return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%'; }} }} }}
            }},
            scales: {{
                x: {{ type: 'time', time: {{ unit: 'month', displayFormats: {{ month: 'MMM yyyy' }} }}, grid: {{ display: false }} }},
                y: {{ ticks: {{ callback: function(v) {{ return v + '%'; }} }}, grid: {{ color: 'rgba(0,0,0,0.06)' }} }}
            }},
            interaction: {{ mode: 'nearest', axis: 'x', intersect: false }}
        }}
    }});"""

    # Build data table rows
    table_rows = ""
    for sid in CARD_SERIES:
        if sid not in yoy_data or not yoy_data[sid]:
            continue
        info = SERIES[sid]
        for entry in reversed(yoy_data[sid][-12:]):  # Last 12 months
            sign = "+" if entry["yoy"] >= 0 else ""
            css = "positive" if entry["yoy"] > 0 else "negative" if entry["yoy"] < 0 else ""
            table_rows += f"""
            <tr>
                <td>{info['name']}</td>
                <td>{entry['date']}</td>
                <td class="{css}">{sign}{entry['yoy']}%</td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <title>US Cost of Living Tracker</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f0f2f5;
            color: #333;
            line-height: 1.6;
        }}
        .header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: white;
            padding: 2.5rem 2rem;
            text-align: center;
        }}
        .header h1 {{
            font-size: 2.2rem;
            font-weight: 700;
            margin-bottom: 0.3rem;
            letter-spacing: -0.5px;
        }}
        .header p {{
            opacity: 0.8;
            font-size: 0.95rem;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 1.5rem;
        }}
        .cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 1.2rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        }}
        .card-title {{
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #666;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }}
        .card-rate {{
            font-size: 1.8rem;
            font-weight: 700;
        }}
        .rate-up {{ color: #e74c3c; }}
        .rate-down {{ color: #27ae60; }}
        .arrow {{ font-size: 0.8rem; vertical-align: middle; }}
        .arrow.up {{ color: #e74c3c; }}
        .arrow.down {{ color: #27ae60; }}
        .arrow.flat {{ color: #999; }}
        .card-date {{
            font-size: 0.75rem;
            color: #999;
            margin-top: 0.3rem;
        }}
        .section-title {{
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 1rem;
            color: #1a1a2e;
        }}
        .section-subtitle {{
            font-size: 0.85rem;
            color: #888;
            margin-top: -0.7rem;
            margin-bottom: 1.2rem;
        }}
        .chart-wrapper {{
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 2rem;
        }}
        .chart-container {{
            position: relative;
            height: 420px;
        }}
        .chart-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 1.2rem;
            margin-bottom: 2rem;
        }}
        .chart-card {{
            background: white;
            border-radius: 12px;
            padding: 1.2rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .chart-card h3 {{
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 0.8rem;
            color: #444;
        }}
        .chart-container-small {{
            position: relative;
            height: 250px;
        }}
        .table-wrapper {{
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 2rem;
            overflow-x: auto;
        }}
        .toggle-btn {{
            background: #1a1a2e;
            color: white;
            border: none;
            padding: 0.6rem 1.2rem;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.85rem;
            margin-bottom: 1rem;
            transition: background 0.2s;
        }}
        .toggle-btn:hover {{ background: #0f3460; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}
        th {{
            background: #f8f9fa;
            padding: 0.8rem;
            text-align: left;
            font-weight: 600;
            color: #555;
            border-bottom: 2px solid #e9ecef;
        }}
        td {{
            padding: 0.6rem 0.8rem;
            border-bottom: 1px solid #f0f0f0;
        }}
        tr:hover td {{ background: #f8f9fa; }}
        .positive {{ color: #e74c3c; font-weight: 600; }}
        .negative {{ color: #27ae60; font-weight: 600; }}
        .footer {{
            text-align: center;
            padding: 2rem;
            color: #999;
            font-size: 0.8rem;
            line-height: 1.8;
        }}
        .footer a {{ color: #4e79a7; text-decoration: none; }}
        .footer a:hover {{ text-decoration: underline; }}
        .methodology {{
            background: #e8f4f8;
            border-radius: 8px;
            padding: 1rem 1.5rem;
            margin-bottom: 2rem;
            font-size: 0.85rem;
            color: #555;
        }}
        .methodology strong {{ color: #333; }}
        @media (max-width: 768px) {{
            .header h1 {{ font-size: 1.5rem; }}
            .cards {{ grid-template-columns: repeat(2, 1fr); }}
            .chart-container {{ height: 300px; }}
            .chart-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🇺🇸 US Cost of Living Tracker</h1>
        <p>Consumer Price Index &mdash; Year-over-Year Inflation Rates</p>
        <p style="font-size: 0.8rem; opacity: 0.6; margin-top: 0.5rem;">Last updated: {last_updated}</p>
    </div>

    <div class="container">
        <div class="cards">
            {cards_html}
        </div>

        <div class="methodology">
            <strong>How to read this:</strong> Values show the <em>year-over-year</em> percentage change in the
            Consumer Price Index (CPI-U). A value of +3.2% means prices are 3.2% higher than the same month
            last year. Red ▲ = rate increasing, Green ▼ = rate decreasing.
        </div>

        <h2 class="section-title">Inflation Trends — All Categories</h2>
        <p class="section-subtitle">Click legend items to show/hide categories. Dotted line shows the overall trend.</p>
        <div class="chart-wrapper">
            <div class="chart-container">
                <canvas id="mainChart"></canvas>
            </div>
        </div>

        <h2 class="section-title">Category Breakdown</h2>
        <p class="section-subtitle">Year-over-year inflation by sector with trend lines.</p>
        <div class="chart-grid">
            {breakdown_charts_html}
        </div>

        <h2 class="section-title">Recent Data</h2>
        <div class="table-wrapper">
            <button class="toggle-btn" onclick="document.getElementById('dataTable').classList.toggle('hidden')">
                Toggle Data Table
            </button>
            <table id="dataTable">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Month</th>
                        <th>YoY Change</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
    </div>

    <div class="footer">
        <p>Data Source: <a href="https://www.bls.gov/cpi/" target="_blank">U.S. Bureau of Labor Statistics — Consumer Price Index</a></p>
        <p>CPI-U (All Urban Consumers), Not Seasonally Adjusted, U.S. City Average</p>
        <p>Data is fetched daily via GitHub Actions. CPI data is published monthly, typically in the second week.</p>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-trendline@2.1.3/dist/chartjs-plugin-trendline.min.js"></script>
    <script>
    // Main YoY Chart
    new Chart(document.getElementById('mainChart'), {{
        type: 'line',
        data: {{ datasets: {main_chart_json} }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                legend: {{
                    position: 'bottom',
                    labels: {{ boxWidth: 14, padding: 12, font: {{ size: 11.5 }}, usePointStyle: true }}
                }},
                tooltip: {{
                    mode: 'index',
                    intersect: false,
                    callbacks: {{
                        label: function(ctx) {{
                            return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%';
                        }}
                    }}
                }}
            }},
            scales: {{
                x: {{
                    type: 'time',
                    time: {{ unit: 'month', displayFormats: {{ month: 'MMM yyyy' }} }},
                    grid: {{ display: false }},
                    ticks: {{ maxRotation: 45, font: {{ size: 10 }} }}
                }},
                y: {{
                    ticks: {{ callback: function(v) {{ return v + '%'; }}, font: {{ size: 11 }} }},
                    grid: {{ color: 'rgba(0,0,0,0.06)' }}
                }}
            }},
            interaction: {{ mode: 'nearest', axis: 'x', intersect: false }}
        }}
    }});

    // Breakdown charts
    {breakdown_charts_js}
    </script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("📊 US Cost of Living Tracker")
    print("=" * 40)

    # Load existing data
    existing = load_existing_data()
    print(f"📂 Loaded existing data: {len(existing.get('series', {}))} series")

    # Fetch new data from BLS
    print("🌐 Fetching data from BLS API...")
    api_result = fetch_bls_data()

    if api_result:
        print("✅ BLS data fetched successfully")
        data = merge_data(existing, api_result)
        total_obs = sum(len(s["data"]) for s in data["series"].values())
        print(f"📈 Total observations: {total_obs}")
    else:
        print("⚠️  Using cached data only")
        data = existing

    # Save updated data
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"💾 Saved data to {DATA_FILE}")

    # Compute year-over-year changes
    yoy_data = compute_yoy(data)
    total_yoy = sum(len(v) for v in yoy_data.values())
    print(f"📉 Computed {total_yoy} YoY data points")

    # Generate HTML
    html = generate_html(data, yoy_data)
    with open(HTML_FILE, "w") as f:
        f.write(html)
    print(f"🌐 Generated dashboard: {HTML_FILE}")
    print("✅ Done!")


if __name__ == "__main__":
    main()
