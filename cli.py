from __future__ import annotations

import asyncio
from pathlib import Path
import typer
from rich.console import Console
from rich.progress import Progress

from config import SETTINGS
from parser.ass_parser import ASSParser
from translator.factory import build_translator
from translator.orchestrator import TranslationOrchestrator
from utils.cache import SessionCache, TranslationMemory
from utils.lang import detect_language
from utils.logging_config import configure_logging

app = typer.Typer(add_completion=False)
console = Console()


def _run_async(coro):
    return asyncio.run(coro)


@app.command(help="Translate a .ass file using the selected engine")
def translate(
    input: Path = typer.Argument(..., exists=True, readable=True),
    output: Path = typer.Argument(...),
    engine: str = typer.Option("google", "--engine", "-e"),
    source: str = typer.Option("auto", "--source", "-s", help="Source language code or 'auto'"),
    target: str = typer.Option(SETTINGS.default_target_lang, "--target", "-t"),
    proxy: str | None = typer.Option(None, help="Proxy URL for engines that support it"),
    backup: bool = typer.Option(True, help="Create a .bak file next to the source"),
    deepl_plan: str | None = typer.Option(None, help="Override DeepL API plan: pro or free"),
    deepl_key: str | None = typer.Option(None, help="Override DeepL API key"),
    deepl_url: str | None = typer.Option(None, help="Override DeepL API endpoint URL"),
) -> None:
    configure_logging()
    parser = ASSParser.from_file(input)
    if backup and parser.source_path:
        parser.backup_original()
    translator = build_translator(
        engine,
        proxy=proxy,
        deepl_plan_override=deepl_plan,
        deepl_api_key_override=deepl_key,
        deepl_api_url_override=deepl_url,
    )
    memory = TranslationMemory(SETTINGS.translation_memory_path)
    session_cache = SessionCache()
    orchestrator = TranslationOrchestrator(translator, memory, session_cache)
    texts = list(parser.iter_texts())
    resolved_source = source
    if source.lower() == "auto":
        detected = detect_language(texts)
        if detected:
            console.log(f"Detected source language: {detected}")
            resolved_source = detected
        else:
            resolved_source = SETTINGS.default_source_lang
            console.log(f"Could not detect language, fallback to {resolved_source}")

    def log_callback(message: str) -> None:
        console.log(message)

    async def runner():
        with Progress() as progress:
            task_id = progress.add_task("Translating", total=len(texts))

            def progress_callback(done: int, total: int) -> None:
                progress.update(task_id, completed=done, total=total)

            translations = await orchestrator.translate(
                texts=texts,
                source_lang=resolved_source,
                target_lang=target,
                progress_cb=progress_callback,
                log_cb=log_callback,
            )
        return translations

    translations = _run_async(runner())
    parser.apply_translations(translations)
    output_path = parser.write(output)
    memory.flush()
    console.print(f"Saved translated file to {output_path}")


if __name__ == "__main__":
    app()
