from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _xdg(env_name: str, fallback: str) -> Path:
    value = os.environ.get(env_name)
    return Path(value).expanduser() if value else Path.home() / fallback


@dataclass(slots=True)
class Paths:
    config_dir: Path = field(
        default_factory=lambda: _xdg("XDG_CONFIG_HOME", ".config") / "mercurio"
    )
    data_dir: Path = field(
        default_factory=lambda: _xdg("XDG_DATA_HOME", ".local/share") / "mercurio"
    )
    state_dir: Path = field(
        default_factory=lambda: _xdg("XDG_STATE_HOME", ".local/state") / "mercurio"
    )

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "mercurio.db"

    @property
    def credential_file(self) -> Path:
        return self.config_dir / "google-token.json"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "sync.lock"

    def ensure(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.state_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)


@dataclass(slots=True)
class Settings:
    timezone: str = "America/Sao_Paulo"
    reminder_minutes: list[int] = field(default_factory=lambda: [10080, 4320, 1440, 120])
    sync_interval_minutes: int = 15
    whatsapp_base_url: str | None = None
    whatsapp_recipient_id: str | None = None
    whatsapp_device_token: str | None = None

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.sync_interval_minutes < 1:
            raise ValueError("sync_interval_minutes deve ser positivo")
        if not self.reminder_minutes or any(v <= 0 for v in self.reminder_minutes):
            raise ValueError("marcos de lembrete devem ser positivos")
        self.reminder_minutes = sorted(set(self.reminder_minutes), reverse=True)

    @classmethod
    def load(cls, paths: Paths | None = None) -> Settings:
        paths = paths or Paths()
        if not paths.config_file.exists():
            result = cls()
        else:
            result = cls(**json.loads(paths.config_file.read_text(encoding="utf-8")))
        result.validate()
        return result

    def save(self, paths: Paths | None = None) -> None:
        paths = paths or Paths()
        paths.ensure()
        self.validate()
        paths.config_file.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        paths.config_file.chmod(0o600)
