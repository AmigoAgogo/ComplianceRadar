from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--keywords", nargs="+", required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    app = create_app(data_dir=REPO_ROOT / "data" / "runtime")
    client = app.test_client()
    response = client.post(
        f"/api/sources/{args.source_id}/live-workflow",
        json={"keywords": args.keywords, "limit": args.limit},
    )
    payload = response.get_json()
    output_path = REPO_ROOT / "docs" / "live_workflow_verification.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote live workflow verification to {output_path}")


if __name__ == "__main__":
    main()
