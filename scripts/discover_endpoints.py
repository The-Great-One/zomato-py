"""Re-runnable endpoint discovery script for Zomato web API.

Scrapes Zomato's frontend JS bundles to discover and verify API endpoints.
Usage:
    python scripts/discover_endpoints.py [--probe] [--output endpoints.json]

Without --probe:  extracts endpoints from JS bundles (fast, read-only)
With --probe:    additionally tests each endpoint with a minimal request
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Known JS bundle hosts
ZOMATO_STATIC = "https://zwstatic.zomato.com"
ZOMATO_WEB = "https://www.zomato.com"


def fetch(url: str) -> str:
    """Fetch a URL and return the response body."""
    r = subprocess.run(
        ["curl", "-sL", "-A", UA, "--max-time", "20", url],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout


def get_js_urls() -> list[str]:
    """Get JS bundle URLs from Zomato's city pages."""
    html = fetch(f"{ZOMATO_WEB}/gurugram/restaurants")
    scripts = re.findall(r'src="(https://zwstatic\.zomato\.com/[^"]+\.js[^"]*)"', html)
    # Also get homepage bundles
    home_html = fetch(ZOMATO_WEB)
    home_scripts = re.findall(r'src="(https://www\.zomato\.com/z-homepage/[^"]+\.js[^"]*)"', home_html)
    return list(set(scripts + home_scripts))


def extract_endpoints(js: str) -> dict[str, list[str]]:
    """Extract API endpoint patterns from JS bundle content."""
    endpoints: dict[str, list[str]] = defaultdict(list)

    # /webroutes/ endpoints
    for m in re.finditer(r'["\'`](/webroutes/[^"\'`]+)["\'`]', js):
        endpoints["webroutes"].append(m.group(1))

    # /dining-gw/ endpoints
    for m in re.finditer(r'["\'`](/dining-gw/[^"\'`]+)["\'`]', js):
        endpoints["dining-gw"].append(m.group(1))

    # /webapi/ endpoints (legacy)
    for m in re.finditer(r'["\'`](/webapi/[^"\'`]+)["\'`]', js):
        endpoints["webapi"].append(m.group(1))

    # jumbo.zomato.com endpoints
    for m in re.finditer(r'(jumbo\.zomato\.com[^"\'`\s,)]*)', js):
        endpoints["jumbo"].append(m.group(1))

    # /api/ endpoints
    for m in re.finditer(r'["\'`](/api/[^"\'`]+)["\'`]', js):
        endpoints["api"].append(m.group(1))

    # /gw/ endpoints (District gateway)
    for m in re.finditer(r'["\'`](/gw/[^"\'`]+)["\'`]', js):
        endpoints["gw"].append(m.group(1))

    # /php/ endpoints (legacy)
    for m in re.finditer(r'["\'`](/php/[^"\'`]+)["\'`]', js):
        endpoints["php"].append(m.group(1))

    return endpoints


def probe_endpoint(url: str) -> dict:
    """Probe a single endpoint and return the result."""
    r = subprocess.run(
        ["curl", "-sL", "-A", UA, "-H", "Accept: application/json",
         "-H", "Referer: https://www.zomato.com/",
         "--max-time", "10", "-w", "\\n__HTTP__:%{http_code}", url],
        capture_output=True, text=True, timeout=15,
    )
    output = r.stdout
    http_code = "?"
    if "__HTTP__:" in output:
        parts = output.rsplit("__HTTP__:", 1)
        body = parts[0].strip()
        http_code = parts[1].strip()
    else:
        body = output.strip()

    try:
        data = json.loads(body)
        if isinstance(data, dict):
            return {"status": http_code, "type": "json", "keys": list(data.keys())[:5]}
        elif isinstance(data, list):
            return {"status": http_code, "type": "json", "length": len(data)}
    except Exception:
        pass

    return {"status": http_code, "type": "text", "snippet": body[:100]}


def main():
    parser = argparse.ArgumentParser(description="Discover Zomato API endpoints")
    parser.add_argument("--probe", action="store_true", help="Probe endpoints live")
    parser.add_argument("--output", default="endpoints.json", help="Output file")
    args = parser.parse_args()

    print("Fetching JS bundle URLs...")
    js_urls = get_js_urls()
    print(f"Found {len(js_urls)} JS bundles")

    all_endpoints: dict[str, set[str]] = defaultdict(set)
    for url in js_urls:
        name = url.split("/")[-1][:50]
        js = fetch(url)
        if not js:
            continue
        print(f"  Analyzing {name} ({len(js)} bytes)...")
        found = extract_endpoints(js)
        for category, paths in found.items():
            all_endpoints[category].update(paths)

    # Convert to sorted lists
    result: dict[str, list[str] | dict] = {}
    for category, paths in all_endpoints.items():
        result[category] = sorted(paths)

    print(f"\n{'='*60}")
    total = sum(len(v) for v in all_endpoints.values())
    print(f"TOTAL ENDPOINTS: {total}")
    for category, paths in sorted(all_endpoints.items()):
        print(f"  {category}: {len(paths)}")
        for p in sorted(paths)[:5]:
            print(f"    {p}")
        if len(paths) > 5:
            print(f"    ... and {len(paths) - 5} more")

    # Probe if requested
    if args.probe:
        print(f"\n{'='*60}")
        print("Probing read-only endpoints...")
        probes = {}
        for ep_path in sorted(all_endpoints.get("webroutes", set())):
            url = f"{ZOMATO_WEB}{ep_path}"
            result_probe = probe_endpoint(url)
            probes[ep_path] = result_probe
            status = result_probe["status"]
            print(f"  {status} {ep_path}")
        result["probes"] = probes

    # Write output
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()