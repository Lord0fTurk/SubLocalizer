from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
import re

try:
    import pysubs2
except ImportError:  # pragma: no cover - optional dependency
    pysubs2 = None


DIALOGUE_PREFIX = re.compile(r"^(Dialogue:\s*)", re.IGNORECASE)
FIELD_NAMES = [
    "layer",
    "start",
    "end",
    "style",
    "name",
    "margin_l",
    "margin_r",
    "margin_v",
    "effect",
]


def _strip_line_ending(raw_line: str) -> tuple[str, str]:
    if raw_line.endswith("\r\n"):
        return raw_line[:-2], "\r\n"
    if raw_line.endswith("\n"):
        return raw_line[:-1], "\n"
    return raw_line, ""


def _format_time(ms: int) -> str:
    total_cs = max(int(ms // 10), 0)
    hours = total_cs // 360000
    minutes = (total_cs // 6000) % 60
    seconds = (total_cs // 100) % 60
    centiseconds = total_cs % 100
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _format_margin(value: int) -> str:
    return f"{value:04d}"


@dataclass(slots=True)
class SubtitleLine:
    index: int
    prefix: str
    fields: dict[str, str]
    text: str
    line_ending: str = "\n"

    @classmethod
    def parse(cls, index: int, raw_line: str) -> "SubtitleLine":
        stripped, line_ending = _strip_line_ending(raw_line)
        match = DIALOGUE_PREFIX.match(stripped)
        if not match:
            raise ValueError("Line does not start with Dialogue: prefix")
        prefix = match.group(1)
        payload = stripped[match.end():]
        parts = payload.split(",", 9)
        if len(parts) < 10:
            parts += [""] * (10 - len(parts))
        metadata = dict(zip(FIELD_NAMES, parts[: len(FIELD_NAMES)]))
        text = parts[-1]
        return cls(index=index, prefix=prefix, fields=metadata, text=text, line_ending=line_ending or "\n")

    @classmethod
    def from_event(cls, index: int, prefix: str, line_ending: str, event: "pysubs2.SSAEvent") -> "SubtitleLine":
        fields = {
            "layer": str(getattr(event, "layer", 0)),
            "start": _format_time(getattr(event, "start", 0)),
            "end": _format_time(getattr(event, "end", 0)),
            "style": getattr(event, "style", "Default"),
            "name": getattr(event, "name", ""),
            "margin_l": _format_margin(getattr(event, "marginl", 0)),
            "margin_r": _format_margin(getattr(event, "marginr", 0)),
            "margin_v": _format_margin(getattr(event, "marginv", 0)),
            "effect": getattr(event, "effect", ""),
        }
        text = getattr(event, "text", "")
        return cls(index=index, prefix=prefix, fields=fields, text=text, line_ending=line_ending or "\n")

    def render(self) -> str:
        ordered = [self.fields[name] for name in FIELD_NAMES]
        payload = ",".join([*ordered, self.text])
        return f"{self.prefix}{payload}{self.line_ending}"


class ASSParser:
    def __init__(self, lines: List[str], source_path: Path | None = None):
        self._lines = lines
        self.source_path = source_path
        self.dialogue_lines: List[SubtitleLine] = []
        self._pysubs_dialogues = self._load_pysubs_dialogues()
        self._extract_dialogues()

    @classmethod
    def from_file(cls, file_path: str | Path) -> "ASSParser":
        path = Path(file_path)
        with path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()
        return cls(lines=lines, source_path=path)

    def _extract_dialogues(self) -> None:
        pysubs_iter = iter(self._pysubs_dialogues) if self._pysubs_dialogues else None
        for idx, line in enumerate(self._lines):
            match = DIALOGUE_PREFIX.match(line)
            if not match:
                continue
            prefix = match.group(1)
            _, line_ending = _strip_line_ending(line)
            pysubs_event = None
            if pysubs_iter:
                try:
                    pysubs_event = next(pysubs_iter)
                except StopIteration:
                    pysubs_iter = None
            try:
                dialogue = SubtitleLine.parse(idx, line)
            except ValueError:
                if pysubs_event is None:
                    continue
                dialogue = SubtitleLine.from_event(idx, prefix, line_ending, pysubs_event)
            self.dialogue_lines.append(dialogue)

    def _load_pysubs_dialogues(self) -> List["pysubs2.SSAEvent"]:
        if not pysubs2 or not self.source_path:
            return []
        try:
            subs = pysubs2.load(str(self.source_path))
        except Exception:  # noqa: BLE001 - optional best-effort parse
            return []
        dialogues: List["pysubs2.SSAEvent"] = []
        for event in subs:
            if getattr(event, "type", "").lower() != "dialogue":
                continue
            if getattr(event, "is_comment", False):
                continue
            dialogues.append(event)
        return dialogues

    def iter_texts(self) -> Iterable[str]:
        for dialogue in self.dialogue_lines:
            yield dialogue.text

    def apply_translations(self, translated_texts: List[str]) -> None:
        if len(translated_texts) != len(self.dialogue_lines):
            raise ValueError("Translation count does not match dialogue count")
        for dialogue, translated in zip(self.dialogue_lines, translated_texts):
            dialogue.text = translated
            self._lines[dialogue.index] = dialogue.render()

    def write(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            handle.writelines(self._lines)
        return path

    def backup_original(self, suffix: str = ".bak") -> Path:
        if not self.source_path:
            raise ValueError("Cannot backup because source_path is missing")
        backup_path = self.source_path.with_suffix(self.source_path.suffix + suffix)
        backup_path.write_text("".join(self._lines), encoding="utf-8")
        return backup_path
