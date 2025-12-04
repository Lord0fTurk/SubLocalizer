from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MEMORY_PATH = BASE_DIR / "storage" / "translation_memory.json"


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 4
    backoff_factor: float = 1.5
    backoff_jitter: float = 0.25


@dataclass(slots=True)
class TranslatorSettings:
    batch_char_limit: int = 6000
    batch_size: int = 20
    concurrency_limit: int = 4
    session_timeout: float = 20.0
    proxy_url: str | None = None


@dataclass(slots=True)
class EngineSecrets:
    deepl_api_key: str | None = field(default_factory=lambda: os.getenv("DEEPL_API_KEY"))
    deepl_api_url: str = field(default_factory=lambda: os.getenv("DEEPL_API_URL", "https://api.deepl.com/v2/translate"))
    deepl_free_api_key: str | None = field(default_factory=lambda: os.getenv("DEEPL_API_FREE_KEY"))
    deepl_free_api_url: str = field(default_factory=lambda: os.getenv("DEEPL_API_FREE_URL", "https://api-free.deepl.com/v2/translate"))
    deepl_api_plan: str = field(default_factory=lambda: os.getenv("DEEPL_API_PLAN", "pro"))
    libretranslate_url: str = field(default_factory=lambda: os.getenv("LIBRETRANSLATE_URL", "https://libretranslate.com/translate"))
    google_proxy: str | None = field(default_factory=lambda: os.getenv("GOOGLE_PROXY"))


@dataclass(slots=True)
class AppSettings:
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    translator: TranslatorSettings = field(default_factory=TranslatorSettings)
    secrets: EngineSecrets = field(default_factory=EngineSecrets)
    translation_memory_path: Path = field(default_factory=lambda: Path(os.getenv("SUBLOCALIZER_MEMORY", DEFAULT_MEMORY_PATH)))
    default_source_lang: str = field(default_factory=lambda: os.getenv("SUBLOCALIZER_SOURCE", "en"))
    default_target_lang: str = field(default_factory=lambda: os.getenv("SUBLOCALIZER_TARGET", "tr"))
    ui_language: str = field(default_factory=lambda: os.getenv("SUBLOCALIZER_UI_LANG", "system"))


SETTINGS = AppSettings()
