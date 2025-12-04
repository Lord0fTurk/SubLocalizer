"""
Translator Factory

Factory for creating translator instances.
Supports: Google, DeepL Web, DeepL API (Free/Pro)
"""
from __future__ import annotations

from typing import Optional

from config import SETTINGS
from .base import BaseTranslator
from .google import GoogleTranslator
from .deepl_api import DeepLAPITranslator
from .deepl_web import DeepLWebTranslator


# Available translation engines
AVAILABLE_ENGINES = {
    "google": "Google Translate",
    "deepl_web": "DeepL Web (Free)",
    "deepl_api": "DeepL API",
}


def get_available_engines() -> dict[str, str]:
    """Get available translation engines with display names."""
    return AVAILABLE_ENGINES.copy()


def build_translator(
    engine_name: str,
    *,
    proxy: Optional[str] = None,
    deepl_api_key: Optional[str] = None,
    deepl_plan: Optional[str] = None,
) -> BaseTranslator:
    """Build a translator instance.
    
    Args:
        engine_name: Name of the engine (google, deepl_web, deepl_api)
        proxy: Optional proxy URL
        deepl_api_key: DeepL API key (for deepl_api engine)
        deepl_plan: DeepL plan type (free/pro)
    
    Returns:
        BaseTranslator instance
    
    Raises:
        ValueError: If engine is not supported or required params missing
    """
    engine = engine_name.lower()
    timeout = SETTINGS.translator.session_timeout
    
    if engine == "google":
        return GoogleTranslator(
            proxy=proxy or SETTINGS.secrets.google_proxy,
            timeout=timeout,
        )
    
    if engine == "deepl_web":
        return DeepLWebTranslator(
            proxy=proxy,
            timeout=timeout,
        )
    
    if engine == "deepl_api":
        return _build_deepl_api_translator(
            api_key=deepl_api_key,
            plan=deepl_plan,
            proxy=proxy,
            timeout=timeout,
        )
    
    raise ValueError(f"Unsupported translator engine: {engine_name}")


def _build_deepl_api_translator(
    *,
    api_key: Optional[str] = None,
    plan: Optional[str] = None,
    proxy: Optional[str] = None,
    timeout: float = 30.0,
) -> DeepLAPITranslator:
    """Build DeepL API translator with proper configuration.
    
    Args:
        api_key: API key (falls back to settings)
        plan: Plan type free/pro (auto-detected from key if not provided)
        proxy: Optional proxy URL
        timeout: Request timeout
    
    Returns:
        DeepLAPITranslator instance
    """
    # Get API key
    key = api_key or SETTINGS.secrets.deepl_api_key or SETTINGS.secrets.deepl_free_api_key
    if not key:
        raise ValueError("DeepL API key is required. Please configure it in settings.")
    
    # Determine plan
    if plan:
        resolved_plan = plan.lower()
    elif key.endswith(":fx"):
        resolved_plan = "free"
    else:
        resolved_plan = SETTINGS.secrets.deepl_api_plan.lower() if SETTINGS.secrets.deepl_api_plan else "free"
    
    return DeepLAPITranslator(
        api_key=key,
        plan=resolved_plan,
        proxy=proxy,
        timeout=timeout,
    )
