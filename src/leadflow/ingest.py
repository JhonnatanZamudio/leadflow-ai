"""Batch file readers. A malformed line becomes an (invalid) record, not a crash."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def read_leads(path: str | Path) -> Iterator[dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as fh:
            yield from csv.DictReader(fh)
        return
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = {"_error": f"line {lineno}: invalid JSON"}
            yield (
                record if isinstance(record, dict) else {"_error": f"line {lineno}: not an object"}
            )
