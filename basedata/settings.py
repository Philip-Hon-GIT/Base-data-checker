"""Innstillinger for basedata-modulen, fra miljøvariabler (BASEDATA_*) eller kommandolinjen.

Appen kan også lage et Settings-objekt selv og sende det inn.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

STORE_DIR = "_basedata"  # mappa i kildemappa der registeret ligger; hoppes over når filer leses


def _env(name: str, default: str = "") -> str:
    """Read one BASEDATA_ environment variable."""
    return os.environ.get(f"BASEDATA_{name}", default)


@dataclass
class Settings:
    """All app-wide settings for the module. Project-specific values live in basedata_projects."""

    enabled: bool = True
    source_folder: str = ""          # mappen der grunnlagsdata legges (lokal mappe eller OneDrive-mappe)
    store_path: str = ""             # SQLite-fila med registeret; tom = <source_folder>/_basedata/register.db
    scan_minutes: int = 5            # hvor ofte `start` ser etter nye filer (0 = bare når du trykker «Kjør»)
    user_name: str = ""              # navnet ditt i registeret; tom = Windows-brukernavnet
    user_email: str = ""
    ai_provider: str = ""            # "", "anthropic", "azure_openai" or "offline_demo"
    ai_model: str = ""
    ai_api_key: str = ""
    azure_endpoint: str = ""
    azure_api_version: str = "2024-10-21"
    ai_timeout_s: int = 60
    review_below_confidence: float = 0.7
    max_text_excerpt_chars: int = 6000
    app_base_url: str = "/basedata"  # used in links inside notifications and the Excel export

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from BASEDATA_* environment variables, falling back to the defaults."""
        s = cls()
        s.enabled = _env("ENABLED", "true").lower() in ("1", "true", "yes", "on")
        s.source_folder = _env("SOURCE_FOLDER", s.source_folder)
        s.store_path = _env("STORE", s.store_path)
        s.scan_minutes = int(_env("SCAN_MINUTES", str(s.scan_minutes)) or 0)
        s.user_name = _env("USER_NAME", s.user_name)
        s.user_email = _env("USER_EMAIL", s.user_email)
        s.ai_provider = _env("AI_PROVIDER", s.ai_provider)
        s.ai_model = _env("AI_MODEL", s.ai_model)
        s.ai_api_key = _env("AI_API_KEY", s.ai_api_key)
        s.azure_endpoint = _env("AZURE_ENDPOINT", s.azure_endpoint)
        s.azure_api_version = _env("AZURE_API_VERSION", s.azure_api_version)
        s.review_below_confidence = float(_env("REVIEW_BELOW_CONFIDENCE", str(s.review_below_confidence)))
        s.app_base_url = _env("APP_BASE_URL", s.app_base_url)
        return s

    def resolved_store_path(self) -> Path:
        """Hvor registeret lagres: BASEDATA_STORE, ellers _basedata/register.db i kildemappa."""
        if self.store_path:
            return Path(self.store_path).expanduser()
        if self.source_folder:
            return Path(self.source_folder).expanduser() / STORE_DIR / "register.db"
        return Path.home() / "basedata" / "register.db"

    @property
    def ai_enabled(self) -> bool:
        """True when an AI provider is configured."""
        if self.ai_provider == "offline_demo":
            return True
        return bool(self.ai_provider and self.ai_model and self.ai_api_key)
