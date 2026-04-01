#!/usr/bin/env python3
"""
Standalone HTML generator - reads data/prices.json and generates index.html.
No external dependencies required (stdlib only).
Used for local dev when 'requests' is unavailable.
"""
import json
import sys
from pathlib import Path

# Add parent so we can import the generate logic
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_prices import load_existing_data, compute_yoy, generate_html, HTML_FILE

def main():
    data = load_existing_data()
    if not data.get("series"):
        print("❌ No data found in prices.json")
        sys.exit(1)

    total_obs = sum(len(s["data"]) for s in data["series"].values())
    print(f"📂 Loaded {len(data['series'])} series, {total_obs} observations")

    yoy_data = compute_yoy(data)
    total_yoy = sum(len(v) for v in yoy_data.values())
    print(f"📉 Computed {total_yoy} YoY data points")

    html = generate_html(data, yoy_data)
    with open(HTML_FILE, "w") as f:
        f.write(html)
    print(f"🌐 Generated dashboard: {HTML_FILE}")
    print("✅ Done!")

if __name__ == "__main__":
    main()
