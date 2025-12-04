"""
Multi-endpoint Google Translator with Lingva fallback.

Uses multiple Google mirrors in parallel for faster translation,
with Lingva Translate as a free fallback when Google fails.

Ported from RenLocalizer project.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Dict, List, Optional

import aiohttp

from .base import BaseTranslator, TranslationRequest


class GoogleTranslator(BaseTranslator):
    """Multi-endpoint Google Translator with Lingva fallback.
    
    Features:
    - Multiple Google mirrors for parallel requests
    - Lingva Translate as free fallback
    - Endpoint failure tracking with round-robin selection
    - Parallel batch translation
    - Separator-based batch optimization
    """
    
    name = "google"
    supports_batching = True
    max_chars_per_request = 5000
    concurrency_limit = 16
    
    # Multiple Google endpoints for parallel requests
    google_endpoints = [
        "https://translate.googleapis.com/translate_a/single",
        "https://translate.google.com/translate_a/single",
        "https://translate.google.com.tr/translate_a/single",
        "https://translate.google.co.uk/translate_a/single",
    ]
    
    # Lingva instances (free, no API key needed)
    lingva_instances = [
        "https://lingva.ml",
        "https://lingva.lunar.icu",
        "https://translate.plausibility.cloud",
    ]
    
    # Batch separator - unlikely to be translated
    BATCH_SEPARATOR = "\n|||RNLSEP999|||\n"
    
    # Default settings
    use_multi_endpoint = True
    enable_lingva_fallback = True
    max_slice_chars = 3000
    max_texts_per_slice = 25
    
    def __init__(self, *, timeout: float = 20.0, proxy: str | None = None) -> None:
        super().__init__(timeout=timeout, proxy=proxy)
        self._endpoint_index = 0
        self._lingva_index = 0
        self._endpoint_failures: Dict[str, int] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(limit=256, ttl_dns_cache=300)
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(connector=self._connector, timeout=timeout)
        return self._session
    
    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
            self._connector = None
    
    def _get_next_endpoint(self) -> str:
        """Round-robin endpoint selection with failure tracking."""
        min_failures = min(self._endpoint_failures.get(ep, 0) for ep in self.google_endpoints)
        available = [
            ep for ep in self.google_endpoints
            if self._endpoint_failures.get(ep, 0) <= min_failures + 2
        ]
        
        if not available:
            self._endpoint_failures.clear()
            available = self.google_endpoints
        
        self._endpoint_index = (self._endpoint_index + 1) % len(available)
        return available[self._endpoint_index]
    
    def _get_next_lingva(self) -> str:
        """Round-robin Lingva instance selection."""
        self._lingva_index = (self._lingva_index + 1) % len(self.lingva_instances)
        return self.lingva_instances[self._lingva_index]
    
    async def _translate_via_lingva(self, text: str, source: str, target: str) -> Optional[str]:
        """Translate using Lingva (free Google proxy, no API key)."""
        lingva_source = source if source != "auto" else "auto"
        
        for _ in range(len(self.lingva_instances)):
            instance = self._get_next_lingva()
            url = f"{instance}/api/v1/{lingva_source}/{target}/{urllib.parse.quote(text)}"
            
            try:
                session = await self._get_session()
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and "translation" in data:
                            return data["translation"]
            except Exception as e:
                self.logger.debug(f"Lingva {instance} failed: {e}")
                continue
        
        return None
    
    async def _translate_single(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        """Translate a single text with multi-endpoint + Lingva fallback."""
        params = {
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": text,
        }
        
        async def try_endpoint(endpoint: str) -> Optional[str]:
            try:
                query = urllib.parse.urlencode(params, doseq=True, safe="")
                url = f"{endpoint}?{query}"
                session = await self._get_session()
                
                async with session.get(url, proxy=self.proxy, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if data and isinstance(data, list) and data[0]:
                            translated = "".join(part[0] for part in data[0] if part and part[0])
                            self._endpoint_failures[endpoint] = 0
                            return translated
                    self._endpoint_failures[endpoint] = self._endpoint_failures.get(endpoint, 0) + 1
            except Exception:
                self._endpoint_failures[endpoint] = self._endpoint_failures.get(endpoint, 0) + 1
            return None
        
        # Multi-endpoint mode: Try 2 endpoints in parallel (fastest wins)
        if self.use_multi_endpoint:
            endpoints_to_try = [self._get_next_endpoint(), self._get_next_endpoint()]
            tasks = [asyncio.create_task(try_endpoint(ep)) for ep in endpoints_to_try]
            
            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return result
        else:
            result = await try_endpoint(self._get_next_endpoint())
            if result:
                return result
        
        # All Google endpoints failed, try Lingva fallback
        if self.enable_lingva_fallback:
            self.logger.debug("Google endpoints failed, trying Lingva fallback...")
            lingva_result = await self._translate_via_lingva(text, source_lang, target_lang)
            if lingva_result:
                return lingva_result
        
        # Last resort: sync requests library
        try:
            import requests as req_lib
            
            def do_request():
                return req_lib.get(
                    self.google_endpoints[0],
                    params=params,
                    timeout=5,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
            
            resp = await asyncio.to_thread(do_request)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and data[0]:
                    return "".join(part[0] for part in data[0] if part and part[0])
        except Exception:
            pass
        
        return None
    
    async def _try_batch_separator(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> Optional[List[str]]:
        """Try batch translation with separator. Returns None if fails."""
        combined_text = self.BATCH_SEPARATOR.join(texts)
        
        params = {
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": combined_text,
        }
        query = urllib.parse.urlencode(params)
        
        async def try_endpoint(endpoint: str) -> Optional[List[str]]:
            try:
                url = f"{endpoint}?{query}"
                session = await self._get_session()
                
                async with session.get(url, proxy=self.proxy, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self._endpoint_failures[endpoint] = self._endpoint_failures.get(endpoint, 0) + 1
                        return None
                    
                    data = await resp.json(content_type=None)
                    segs = data[0] if isinstance(data, list) and data else None
                    if not segs:
                        return None
                    
                    full_translation = ""
                    for seg in segs:
                        if seg and seg[0]:
                            full_translation += seg[0]
                    
                    parts = full_translation.split(self.BATCH_SEPARATOR)
                    
                    if len(parts) != len(texts):
                        self.logger.debug(
                            f"Batch-sep {endpoint}: Part count mismatch - expected {len(texts)}, got {len(parts)}"
                        )
                        return None
                    
                    self._endpoint_failures[endpoint] = 0
                    return [p.strip() for p in parts]
            
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._endpoint_failures[endpoint] = self._endpoint_failures.get(endpoint, 0) + 1
                self.logger.debug(f"Batch-sep failed on {endpoint}: {e}")
                return None
        
        # Parallel endpoint racing
        if self.use_multi_endpoint:
            endpoints_to_try = [self._get_next_endpoint() for _ in range(min(3, len(self.google_endpoints)))]
            tasks = [asyncio.create_task(try_endpoint(ep)) for ep in endpoints_to_try]
            
            try:
                for coro in asyncio.as_completed(tasks):
                    try:
                        result = await coro
                        if result:
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            self.logger.debug(f"Batch-sep success: {len(texts)} texts translated")
                            return result
                    except asyncio.CancelledError:
                        raise
            except asyncio.CancelledError:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                raise
        else:
            for _ in range(3):
                result = await try_endpoint(self._get_next_endpoint())
                if result:
                    return result
        
        return None
    
    async def _translate_parallel(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[str]:
        """Translate texts in parallel using multiple endpoints for speed."""
        if not texts:
            return []
        
        sem = asyncio.Semaphore(self.concurrency_limit)
        
        async def translate_one(text: str) -> str:
            async with sem:
                result = await self._translate_single(text, source_lang, target_lang)
                return result if result else ""
        
        tasks = [asyncio.create_task(translate_one(text)) for text in texts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.debug(f"Parallel translation failed for text {i + 1}: {result}")
                final_results.append("")
            else:
                final_results.append(result if result else "")
        
        success_count = sum(1 for r in final_results if r)
        self.logger.debug(f"Parallel translation: {success_count}/{len(texts)} successful")
        
        return final_results
    
    async def translate_texts(self, request: TranslationRequest) -> List[str]:
        """Translate a batch of texts.
        
        Strategy:
        1. For small batches (≤8 texts, ≤1200 chars), try separator method first
        2. Fall back to parallel individual translation
        """
        texts = list(request.texts)
        if not texts:
            return []
        
        if len(texts) == 1:
            result = await self._translate_single(texts[0], request.source_lang, request.target_lang)
            return [result if result else ""]
        
        total_chars = sum(len(t) for t in texts)
        
        # For small batches, try separator method (faster)
        if len(texts) <= 8 and total_chars <= 1200:
            result = await self._try_batch_separator(texts, request.source_lang, request.target_lang)
            if result:
                return result
        
        # Fall back to parallel translation
        self.logger.debug(f"Using parallel translation for {len(texts)} texts")
        return await self._translate_parallel(texts, request.source_lang, request.target_lang)
    
    def __del__(self) -> None:
        """Cleanup on deletion."""
        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.close())
            except RuntimeError:
                pass
