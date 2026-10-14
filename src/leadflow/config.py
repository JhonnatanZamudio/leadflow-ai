"""Settings from environment variables (12-factor). No hidden globals."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "fake"
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 0.5
    fake_failure_rate: float = 0.0
    fake_seed: int = 7
    db_path: Path = Path("out/leadflow.db")
    crm_sink: str = "sqlite"
    csv_export_path: Path = Path("out/crm_export.csv")
    google_service_account_file: str | None = None
    google_sheet_id: str | None = None
    google_worksheet: str = "Leads"
    notifier: str | None = None
    slack_webhook_url: str | None = None
    hot_fit_threshold: int = 70
    default_phone_country: str = "57"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        values: dict[str, object] = {}
        for f in fields(cls):
            raw = env.get(f.name.upper()) or env.get(f"LEADFLOW_{f.name.upper()}")
            if raw is None or raw == "":
                continue
            default = f.default
            if isinstance(default, int):
                values[f.name] = int(raw)
            elif isinstance(default, float):
                values[f.name] = float(raw)
            elif isinstance(default, Path):
                values[f.name] = Path(raw)
            else:
                values[f.name] = raw
        return cls(**values)  # type: ignore[arg-type]

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise ValueError(f"{name.upper()} must be set for this configuration")
        return str(value)
