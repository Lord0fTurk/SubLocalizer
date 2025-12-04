"""
SubLocalizer Translation Engines

Supported engines:
- Google Translate (multi-endpoint with Lingva fallback)
- DeepL Web (free, no API key required)
- DeepL API (official API, free and pro plans)
"""
from .base import BaseTranslator, TranslationRequest
from .google import GoogleTranslator
from .deepl_api import DeepLAPITranslator
from .deepl_web import DeepLWebTranslator
from .factory import build_translator, get_available_engines, AVAILABLE_ENGINES
from .orchestrator import TranslationOrchestrator

__all__ = [
    "BaseTranslator",
    "TranslationRequest",
    "GoogleTranslator",
    "DeepLAPITranslator",
    "DeepLWebTranslator",
    "build_translator",
    "get_available_engines",
    "AVAILABLE_ENGINES",
    "TranslationOrchestrator",
]
