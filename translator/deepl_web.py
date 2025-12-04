"""
DeepL Web Translator (Scraper-based)

Translates text using DeepL's free web interface without API key.
Uses aiohttp with browser-like headers to access DeepL's internal API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Dict, List, Optional

import aiohttp

from .base import BaseTranslator, TranslationRequest


class DeepLWebTranslator(BaseTranslator):
    """DeepL Web Translator using internal API scraping.
    
    Features:
    - No API key required
    - Uses DeepL's internal JSON-RPC API
    - Automatic retry with backoff
    - Rate limiting to avoid blocks
    """
    
    name = "deepl_web"
    supports_batching = True
    max_chars_per_request = 3000
    concurrency_limit = 2
    
    # DeepL internal API endpoint
    DEEPL_API_URL = "https://www2.deepl.com/jsonrpc"
    
    # Language code mapping
    LANG_MAP = {
        "auto": "auto",
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
        "pt": "PT",
        "nl": "NL",
        "pl": "PL",
    }
    
    def __init__(self, *, timeout: float = 30.0, proxy: str | None = None) -> None:
        super().__init__(timeout=timeout, proxy=proxy)
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_id = random.randint(1000000, 99999999)
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            headers = {
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
                "Origin": "https://www.deepl.com",
                "Referer": "https://www.deepl.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
    
    def _get_request_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id
    
    def _map_lang(self, lang: str) -> str:
        """Map language code to DeepL format."""
        return self.LANG_MAP.get(lang.lower(), lang.upper())
    
    def _build_request_body(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> dict:
        """Build JSON-RPC request body."""
        # Count 'i' characters for timestamp calculation (DeepL quirk)
        i_count = sum(text.count("i") for text in texts)
        timestamp = int(time.time() * 1000)
        
        # Adjust timestamp based on i_count (DeepL's anti-bot measure)
        if i_count > 0:
            timestamp = timestamp - (timestamp % (i_count + 1)) + (i_count + 1)
        
        jobs = []
        for idx, text in enumerate(texts):
            jobs.append({
                "kind": "default",
                "sentences": [{"text": text, "id": idx, "prefix": ""}],
                "raw_en_context_before": [],
                "raw_en_context_after": [],
                "preferred_num_beams": 4,
            })
        
        return {
            "jsonrpc": "2.0",
            "method": "LMT_handle_jobs",
            "id": self._get_request_id(),
            "params": {
                "jobs": jobs,
                "lang": {
                    "source_lang_user_selected": self._map_lang(source_lang),
                    "target_lang": self._map_lang(target_lang),
                },
                "priority": 1,
                "commonJobParams": {
                    "mode": "translate",
                    "wasSpoken": False,
                    "transcribe_as": "",
                },
                "timestamp": timestamp,
            },
        }
    
    async def _translate_batch_internal(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        """Translate a batch of texts using DeepL's internal API."""
        session = await self._get_session()
        body = self._build_request_body(texts, source_lang, target_lang)
        
        # Convert to JSON and apply the 'i' count trick
        json_str = json.dumps(body)
        
        # DeepL expects specific spacing based on request ID
        if (self._request_id + 5) % 29 == 0 or (self._request_id + 3) % 13 == 0:
            json_str = json_str.replace('"method":"', '"method" : "')
        else:
            json_str = json_str.replace('"method":"', '"method": "')
        
        try:
            async with session.post(
                self.DEEPL_API_URL,
                data=json_str,
                proxy=self.proxy,
            ) as resp:
                if resp.status == 429:
                    raise RuntimeError("DeepL rate limit exceeded. Please wait and try again.")
                
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"DeepL API error: HTTP {resp.status} - {text[:200]}")
                
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise RuntimeError(f"DeepL connection error: {e}") from e
        
        # Parse response
        if "result" not in data:
            error = data.get("error", {}).get("message", "Unknown error")
            raise RuntimeError(f"DeepL API error: {error}")
        
        translations = []
        for translation in data["result"]["translations"]:
            beams = translation.get("beams", [])
            if beams:
                # Get best translation (first beam)
                sentences = beams[0].get("sentences", [])
                if sentences:
                    translated_text = sentences[0].get("text", "")
                    translations.append(translated_text)
                else:
                    translations.append("")
            else:
                translations.append("")
        
        return translations
    
    async def translate_texts(self, request: TranslationRequest) -> List[str]:
        """Translate texts using DeepL web scraping.
        
        Implements rate limiting and retry logic.
        """
        texts = list(request.texts)
        if not texts:
            return []
        
        results: List[str] = []
        batch_size = 5  # DeepL works better with smaller batches
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
            # Retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    batch_results = await self._translate_batch_internal(
                        batch,
                        request.source_lang,
                        request.target_lang,
                    )
                    results.extend(batch_results)
                    
                    # Rate limiting - wait between batches
                    if i + batch_size < len(texts):
                        await asyncio.sleep(0.5 + random.uniform(0, 0.5))
                    
                    break
                
                except RuntimeError as e:
                    if "rate limit" in str(e).lower() and attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2 + random.uniform(0, 1)
                        self.logger.warning(f"Rate limited, waiting {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                    elif attempt < max_retries - 1:
                        await asyncio.sleep(1)
                    else:
                        raise
        
        # Ensure we have the right number of results
        if len(results) != len(texts):
            self.logger.warning(
                f"Result count mismatch: got {len(results)}, expected {len(texts)}"
            )
            # Pad with empty strings if needed
            while len(results) < len(texts):
                results.append("")
        
        return results
    
    def __del__(self) -> None:
        """Cleanup on deletion."""
        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.close())
            except RuntimeError:
                pass
