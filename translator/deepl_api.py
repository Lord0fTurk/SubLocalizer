"""
DeepL API Translator

Official DeepL API translator supporting both Free and Pro plans.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

import aiohttp

from .base import BaseTranslator, TranslationRequest


class DeepLAPITranslator(BaseTranslator):
    """DeepL API Translator with Free and Pro plan support.
    
    Features:
    - Supports both Free and Pro API plans
    - Automatic URL selection based on plan
    - Batch translation support
    - Proper error handling
    """
    
    name = "deepl_api"
    supports_batching = True
    max_chars_per_request = 5000
    concurrency_limit = 4
    
    # API URLs
    PRO_API_URL = "https://api.deepl.com/v2/translate"
    FREE_API_URL = "https://api-free.deepl.com/v2/translate"
    
    # Language code mapping
    LANG_MAP = {
        "auto": None,  # DeepL uses null for auto-detect
        "en": "EN",
        "tr": "TR",
        "de": "DE",
        "fr": "FR",
        "es": "ES",
        "it": "IT",
        "ja": "JA",
        "ko": "KO",
        "ru": "RU",
        "zh": "ZH",
        "pt": "PT-PT",
        "nl": "NL",
        "pl": "PL",
    }
    
    def __init__(
        self,
        *,
        api_key: str,
        plan: str = "free",
        api_url: str | None = None,
        timeout: float = 30.0,
        proxy: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DeepL API key is required")
        
        super().__init__(timeout=timeout, proxy=proxy)
        self.api_key = api_key
        self.plan = plan.lower()
        
        # Determine API URL
        if api_url:
            self.api_url = api_url
        elif self.plan == "free" or api_key.endswith(":fx"):
            self.api_url = self.FREE_API_URL
        else:
            self.api_url = self.PRO_API_URL
        
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            headers = {
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
                "Content-Type": "application/json",
            }
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session
    
    async def close(self) -> None:
        """Close the session."""
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
    
    def _map_lang(self, lang: str) -> Optional[str]:
        """Map language code to DeepL format."""
        mapped = self.LANG_MAP.get(lang.lower())
        if mapped is None and lang.lower() != "auto":
            return lang.upper()
        return mapped
    
    async def translate_texts(self, request: TranslationRequest) -> List[str]:
        """Translate texts using DeepL API."""
        texts = list(request.texts)
        if not texts:
            return []
        
        session = await self._get_session()
        
        # Build request payload
        payload = {
            "text": texts,
            "target_lang": self._map_lang(request.target_lang),
        }
        
        # Add source language if not auto
        source_lang = self._map_lang(request.source_lang)
        if source_lang:
            payload["source_lang"] = source_lang
        
        try:
            async with session.post(
                self.api_url,
                json=payload,
                proxy=self.proxy,
            ) as resp:
                if resp.status == 403:
                    raise RuntimeError("DeepL API: Invalid API key or insufficient permissions")
                
                if resp.status == 456:
                    raise RuntimeError("DeepL API: Quota exceeded")
                
                if resp.status == 429:
                    raise RuntimeError("DeepL API: Too many requests. Please slow down.")
                
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"DeepL API error: HTTP {resp.status} - {text[:200]}")
                
                data = await resp.json()
        
        except aiohttp.ClientError as e:
            raise RuntimeError(f"DeepL API connection error: {e}") from e
        
        # Parse response
        translations = []
        for item in data.get("translations", []):
            translations.append(item.get("text", ""))
        
        # Verify count
        if len(translations) != len(texts):
            self.logger.warning(
                f"DeepL returned {len(translations)} translations for {len(texts)} texts"
            )
            while len(translations) < len(texts):
                translations.append("")
        
        return translations
    
    def __del__(self) -> None:
        """Cleanup on deletion."""
        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.close())
            except RuntimeError:
                pass
