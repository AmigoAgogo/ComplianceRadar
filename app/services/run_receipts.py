from __future__ import annotations

import json
from pathlib import Path


class RunReceiptWriter:
    def __init__(self, runtime_root: Path) -> None:
        self.output_dir = runtime_root / "logs" / "update_runs"

    def write(self, receipt: dict) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{receipt['run_id']}.json"
        path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
