from __future__ import annotations

import json
import sys
from pathlib import Path
import argparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", dest="source_id", default="")
    args = parser.parse_args()

    app = create_app(data_dir=REPO_ROOT / "data" / "runtime")
    client = app.test_client()
    sources = client.get("/api/sources").get_json()
    report: list[dict] = []

    for source in sources:
        if args.source_id and source["source_id"] != args.source_id:
            continue
        response = client.get(f"/api/sources/{source['source_id']}/diagnostics")
        payload = response.get_json()
        report.append(payload)
        print("=" * 72)
        print(source["name"])
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    output = REPO_ROOT / "docs" / "source_diagnostics_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 72)
    print(f"Wrote diagnostics report to {output}")


if __name__ == "__main__":
    main()
