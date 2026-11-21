"""Measure API latency (p50 / p95) against an existing data directory.

Usage:
    uv run python scripts/bench_api.py DATA_DIR [--runs 20]

Facets are measured twice: cold (cache cleared before every call) and warm.
"""

import argparse
import statistics
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from salevault.api.app import create_app
from salevault.catalog.queries import facet_cache
from salevault.config import Settings


def measure(
    client: TestClient, path: str, params: dict[str, Any], runs: int, *, cold: bool = False
) -> tuple[float, float]:
    timings = []
    for _ in range(runs):
        if cold:
            facet_cache.clear()
        start = time.perf_counter()
        response = client.get(path, params=params)
        timings.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200, response.text
    timings.sort()
    return statistics.median(timings), timings[max(0, int(len(timings) * 0.95) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()

    app = create_app(Settings(data_dir=args.data_dir, frontend_dist=args.data_dir / "no-dist"))
    with TestClient(app) as client:
        total = client.get("/api/products", params={"page_size": 1}).json()["total"]
        some = client.get("/api/products", params={"page_size": 1}).json()["items"][0]
        brand = some["brand"]["id"]
        facets = client.get("/api/facets").json()
        category = facets["categories"][0]["id"]
        client.put("/api/settings", json={"my_sizes": ["M", "42"]})
        print(f"catalog: {total:,} active items\n")

        cases: list[tuple[str, str, dict[str, Any], bool]] = [
            ("list: default", "/api/products", {}, False),
            ("list: page 200", "/api/products", {"page": 200}, False),
            (
                "list: women, >= 50%",
                "/api/products",
                {"gender": "women", "discount_min": 50},
                False,
            ),
            ("list: brand + price", "/api/products", {"brand": brand, "price_max": 5000}, False),
            ("list: category", "/api/products", {"category": category}, False),
            ("list: size M", "/api/products", {"size": "M"}, False),
            ("list: my sizes", "/api/products", {"my_sizes": True}, False),
            ("list: search 'jacket 1'", "/api/products", {"q": "jacket 1"}, False),
            ("list: new", "/api/products", {"flags": "new"}, False),
            ("list: price drop", "/api/products", {"flags": "price_drop"}, False),
            ("list: honest discount", "/api/products", {"sort": "discount_min30_desc"}, False),
            ("detail", f"/api/products/{some['id']}", {}, False),
            ("facets: default (warm)", "/api/facets", {}, False),
            ("facets: default (cold)", "/api/facets", {}, True),
            (
                "facets: women >= 50% (cold)",
                "/api/facets",
                {"gender": "women", "discount_min": 50},
                True,
            ),
            ("facets: size M (cold)", "/api/facets", {"size": "M"}, True),
            ("facets: brand (cold)", "/api/facets", {"brand": brand}, True),
            ("facets: core only (cold)", "/api/facets", {"heavy": False}, True),
            (
                "facets: core, women >= 50% (cold)",
                "/api/facets",
                {"heavy": False, "gender": "women", "discount_min": 50},
                True,
            ),
        ]
        print(f"{'case':32} {'p50 ms':>8} {'p95 ms':>8}")
        for label, path, params, cold in cases:
            p50, p95 = measure(client, path, params, args.runs, cold=cold)
            print(f"{label:32} {p50:8.1f} {p95:8.1f}")


if __name__ == "__main__":
    main()
