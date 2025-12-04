"""
SubLocalizer - Modern UI with compact, user-friendly design
"""
from __future__ import annotations

import asyncio
import json
import locale
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import sys

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from config import SETTINGS
from parser.ass_parser import ASSParser
from translator.factory import build_translator
from translator.orchestrator import TranslationOrchestrator
from utils.cache import SessionCache, TranslationMemory
from utils.lang import detect_language
from utils.logging_config import configure_logging


LANGUAGE_CHOICES = [
    {"code": "auto", "allow_target": False, "labels": {"en": "Auto", "tr": "Otomatik"}},
    {"code": "en", "labels": {"en": "English", "tr": "İngilizce"}},
    {"code": "tr", "labels": {"en": "Turkish", "tr": "Türkçe"}},
    {"code": "de", "labels": {"en": "German", "tr": "Almanca"}},
    {"code": "fr", "labels": {"en": "French", "tr": "Fransızca"}},
    {"code": "es", "labels": {"en": "Spanish", "tr": "İspanyolca"}},
    {"code": "it", "labels": {"en": "Italian", "tr": "İtalyanca"}},
    {"code": "ja", "labels": {"en": "Japanese", "tr": "Japonca"}},
    {"code": "ko", "labels": {"en": "Korean", "tr": "Korece"}},
    {"code": "ru", "labels": {"en": "Russian", "tr": "Rusça"}},
    {"code": "zh", "labels": {"en": "Chinese", "tr": "Çince"}},
]

LOCALES_DIR = Path(__file__).parent / "locales"
TURKIC_LANGUAGE_CODES = {"tr", "az", "uz", "tk", "kk", "ky", "tt", "ba", "crh", "sah", "ug"}


def _determine_initial_language() -> str:
    """Determine the initial UI language."""
    preferred = (SETTINGS.ui_language or "").strip().lower()
    if preferred and preferred not in {"system", "auto"} and locale_available(preferred):
        return preferred

    candidates: list[str] = []
    qt_locale = QtCore.QLocale.system()
    for name in (qt_locale.bcp47Name(), qt_locale.name()):
        if not name:
            continue
        candidates.append(name.split("-")[0].split("_")[0].lower())

    lang_tuple = locale.getlocale()
    if lang_tuple and lang_tuple[0]:
        candidates.append(lang_tuple[0].split("_")[0].lower())

    env_lang = os.environ.get("LANG")
    if env_lang:
        candidates.append(env_lang.split("_")[0].lower())

    for code in candidates:
        if code in TURKIC_LANGUAGE_CODES:
            return "tr"
    return "en"


@lru_cache(maxsize=None)
def _load_locale_bundle(language: str) -> dict[str, str]:
    """Load locale strings."""
    bundles: dict[str, str] = {}
    tried: set[str] = set()
    for code in (language, "en"):
        if code in tried or not code:
            continue
        tried.add(code)
        path = LOCALES_DIR / f"{code}.json"
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            bundles.update(data)
            break
    return bundles


def get_ui_text(language: str, key: str) -> str:
    """Get UI text for a key in the given language."""
    bundle = _load_locale_bundle(language)
    fallback = _load_locale_bundle("en")
    return bundle.get(key, fallback.get(key, key))


def locale_available(language: str) -> bool:
    """Check if a locale is available."""
    if not language:
        return False
    return (LOCALES_DIR / f"{language}.json").exists()


@dataclass(slots=True)
class TranslatorOverrides:
    plan: str | None = None
    api_key: str | None = None


class TranslationWorker(QtCore.QThread):
    """Worker thread for translation."""
    progress_changed = QtCore.pyqtSignal(int)
    log_emitted = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(bool, str)

    def __init__(
        self,
        *,
        file_path: Path,
        output_path: Path,
        engine: str,
        source_lang: str,
        target_lang: str,
        proxy: str | None,
        backup: bool,
        ui_language: str,
        translator_overrides: TranslatorOverrides | None,
        batch_char_limit: int | None,
    ) -> None:
        super().__init__()
        self.file_path = file_path
        self.output_path = output_path
        self.engine = engine
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.proxy = proxy
        self.backup = backup
        self.ui_language = ui_language
        self.translator_overrides = translator_overrides or TranslatorOverrides()
        self.batch_char_limit = batch_char_limit or SETTINGS.translator.batch_char_limit

    def run(self) -> None:
        """Run the translation."""
        configure_logging()
        try:
            parser = ASSParser.from_file(self.file_path)
            texts = list(parser.iter_texts())
            if not texts:
                raise RuntimeError(get_ui_text(self.ui_language, "no_texts_error"))
            
            resolved_source = self._resolve_source_language(texts)
            translator = build_translator(
                self.engine,
                proxy=self.proxy,
                deepl_api_key=self.translator_overrides.api_key,
                deepl_plan=self.translator_overrides.plan,
            )
            session_cache = SessionCache()
            memory = TranslationMemory(SETTINGS.translation_memory_path)
            orchestrator = TranslationOrchestrator(
                translator=translator,
                memory=memory,
                session_cache=session_cache,
                batch_char_limit=self.batch_char_limit,
            )

            def progress_cb(done: int, total: int) -> None:
                total = max(total, 1)
                percent = int(done / total * 100)
                self.progress_changed.emit(percent)

            translations = asyncio.run(
                orchestrator.translate(
                    texts=texts,
                    source_lang=resolved_source,
                    target_lang=self.target_lang,
                    progress_cb=progress_cb,
                    log_cb=self.log_emitted.emit,
                )
            )
            parser.apply_translations(translations)
            if self.backup:
                try:
                    parser.backup_original()
                except Exception as backup_error:
                    self.log_emitted.emit(f"Backup failed: {backup_error}")
            result_path = parser.write(self.output_path)
            self.finished.emit(True, str(result_path))
        except Exception as exc:
            self.log_emitted.emit(str(exc))
            self.finished.emit(False, str(exc))

    def _resolve_source_language(self, texts: list[str]) -> str:
        """Resolve source language."""
        if self.source_lang != "auto":
            return self.source_lang
        detected = detect_language(texts)
        if detected:
            self.log_emitted.emit(get_ui_text(self.ui_language, "detect_success").format(lang=detected))
            return detected
        fallback = SETTINGS.default_source_lang
        self.log_emitted.emit(get_ui_text(self.ui_language, "detect_fallback").format(lang=fallback))
        return fallback


class MainWindow(QtWidgets.QMainWindow):
    """Modern, compact main window."""
    
    def __init__(self) -> None:
        super().__init__()
        self.current_ui_language = _determine_initial_language()
        self.setWindowTitle("SubLocalizer")
        self.resize(900, 650)
        self.worker: TranslationWorker | None = None
        self.last_output_path: Path | None = None
        self._selected_file_path: Path | None = None
        self._build_ui()
        self._apply_style()
        self._apply_ui_language()

    def _build_ui(self) -> None:
        """Build the UI."""
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # === SIDEBAR ===
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(160)
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(8)

        # Language selector
        lang_combo = QtWidgets.QComboBox()
        lang_combo.addItem("English", userData="en")
        lang_combo.addItem("Türkçe", userData="tr")
        lang_combo.setCurrentData(self.current_ui_language)
        lang_combo.currentIndexChanged.connect(self._on_language_changed)
        sidebar_layout.addWidget(lang_combo)
        sidebar_layout.addSpacing(12)

        # Nav buttons
        self.nav_buttons: list[QtWidgets.QPushButton] = []
        nav_items = [
            ("translator", "🎯", "Çevirmen"),
            ("settings", "⚙️", "Ayarlar"),
            ("history", "📜", "Geçmiş"),
            ("help", "❓", "Yardım"),
        ]
        
        for page_id, icon, label in nav_items:
            btn = QtWidgets.QPushButton(f"{icon}\n{label}")
            btn.setCheckable(True)
            btn.setObjectName("NavButton")
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.setMinimumHeight(70)
            btn.clicked.connect(lambda checked=False, pid=page_id: self._switch_page(pid))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()
        root.addWidget(sidebar)

        # === CONTENT STACK ===
        self.stack = QtWidgets.QStackedWidget()
        self.pages = {
            "translator": self._build_translator_page(),
            "settings": self._build_settings_page(),
            "history": self._build_history_page(),
            "help": self._build_help_page(),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._switch_page("translator")

    def _build_translator_page(self) -> QtWidgets.QWidget:
        """Build translator page."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # File section
        file_group = QtWidgets.QGroupBox()
        file_group.setObjectName("CompactGroup")
        file_layout = QtWidgets.QGridLayout(file_group)
        file_layout.setContentsMargins(12, 12, 12, 12)
        file_layout.setSpacing(8)
        file_layout.setColumnStretch(1, 1)

        self.input_file_edit = QtWidgets.QLineEdit()
        self.input_file_edit.setPlaceholderText("Select .ass file...")
        self.input_file_edit.setClearButtonEnabled(True)
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.clicked.connect(self._select_input_file)
        browse_btn.setMaximumWidth(80)
        file_layout.addWidget(QtWidgets.QLabel("Input:"), 0, 0)
        file_layout.addWidget(self.input_file_edit, 0, 1)
        file_layout.addWidget(browse_btn, 0, 2)

        self.output_file_edit = QtWidgets.QLineEdit()
        self.output_file_edit.setPlaceholderText("translated.ass")
        self.output_file_edit.setClearButtonEnabled(True)
        save_btn = QtWidgets.QPushButton("Browse")
        save_btn.clicked.connect(self._select_output_file)
        save_btn.setMaximumWidth(80)
        file_layout.addWidget(QtWidgets.QLabel("Output:"), 1, 0)
        file_layout.addWidget(self.output_file_edit, 1, 1)
        file_layout.addWidget(save_btn, 1, 2)

        layout.addWidget(file_group)

        # Translation section
        trans_group = QtWidgets.QGroupBox()
        trans_group.setObjectName("CompactGroup")
        trans_layout = QtWidgets.QGridLayout(trans_group)
        trans_layout.setContentsMargins(12, 12, 12, 12)
        trans_layout.setSpacing(8)
        trans_layout.setColumnStretch(1, 1)

        self.engine_combo = QtWidgets.QComboBox()
        self.engine_combo.addItem("Google Translate", userData="google")
        self.engine_combo.addItem("DeepL Web", userData="deepl_web")
        self.engine_combo.addItem("DeepL API", userData="deepl_api")
        trans_layout.addWidget(QtWidgets.QLabel("Engine:"), 0, 0)
        trans_layout.addWidget(self.engine_combo, 0, 1)

        self.source_combo = QtWidgets.QComboBox()
        self.target_combo = QtWidgets.QComboBox()
        for definition in LANGUAGE_CHOICES:
            label = definition["labels"].get(self.current_ui_language, definition["labels"]["en"])
            self.source_combo.addItem(label, userData=definition["code"])
            if definition.get("allow_target", True):
                self.target_combo.addItem(label, userData=definition["code"])

        trans_layout.addWidget(QtWidgets.QLabel("From:"), 1, 0)
        trans_layout.addWidget(self.source_combo, 1, 1)
        trans_layout.addWidget(QtWidgets.QLabel("To:"), 2, 0)
        trans_layout.addWidget(self.target_combo, 2, 1)

        layout.addWidget(trans_group)

        # Options section (compact)
        options_group = QtWidgets.QGroupBox()
        options_group.setObjectName("CompactGroup")
        options_layout = QtWidgets.QGridLayout(options_group)
        options_layout.setContentsMargins(12, 12, 12, 12)
        options_layout.setSpacing(8)
        options_layout.setColumnStretch(1, 1)

        self.auto_detect_check = QtWidgets.QCheckBox("Auto-detect source")
        self.auto_detect_check.setChecked(True)
        self.auto_detect_check.stateChanged.connect(self._sync_source_combo)
        options_layout.addWidget(self.auto_detect_check, 0, 0, 1, 2)

        self.backup_check = QtWidgets.QCheckBox("Backup original file")
        self.backup_check.setChecked(True)
        options_layout.addWidget(self.backup_check, 1, 0, 1, 2)

        self.proxy_check = QtWidgets.QCheckBox("Use proxy:")
        self.proxy_check.stateChanged.connect(self._update_proxy_state)
        self.proxy_edit = QtWidgets.QLineEdit()
        self.proxy_edit.setPlaceholderText("http://proxy:port")
        self.proxy_edit.setClearButtonEnabled(True)
        options_layout.addWidget(self.proxy_check, 2, 0)
        options_layout.addWidget(self.proxy_edit, 2, 1)

        layout.addWidget(options_group)

        # Progress and Log section
        log_group = QtWidgets.QGroupBox()
        log_group.setObjectName("CompactGroup")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_layout.setSpacing(8)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        log_layout.addWidget(self.log_view)

        # Progress bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setMaximumHeight(24)
        log_layout.addWidget(self.progress_bar)

        layout.addWidget(log_group)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(8)

        self.preview_btn = QtWidgets.QPushButton("Preview")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self._preview_output)
        btn_layout.addWidget(self.preview_btn)

        self.open_btn = QtWidgets.QPushButton("Open File")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output)
        btn_layout.addWidget(self.open_btn)

        btn_layout.addStretch()

        self.start_btn = QtWidgets.QPushButton("▶ START")
        self.start_btn.setObjectName("StartButton")
        self.start_btn.clicked.connect(self._start_translation)
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setMinimumWidth(150)
        btn_layout.addWidget(self.start_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        self._set_default_languages()
        return page

    def _build_settings_page(self) -> QtWidgets.QWidget:
        """Build settings page."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # DeepL API section
        deepl_group = QtWidgets.QGroupBox("DeepL API")
        deepl_group.setObjectName("CompactGroup")
        deepl_layout = QtWidgets.QFormLayout(deepl_group)
        deepl_layout.setSpacing(8)

        self.deepl_key_edit = QtWidgets.QLineEdit()
        self.deepl_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.deepl_key_edit.setClearButtonEnabled(True)
        self.deepl_key_edit.setPlaceholderText("API Key (Free: ends with :fx)")
        deepl_layout.addRow("API Key:", self.deepl_key_edit)

        layout.addWidget(deepl_group)
        layout.addStretch()
        return page

    def _build_history_page(self) -> QtWidgets.QWidget:
        """Build history page."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        self.history_list = QtWidgets.QListWidget()
        layout.addWidget(self.history_list)

        return page

    def _build_help_page(self) -> QtWidgets.QWidget:
        """Build help page."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        self.help_view = QtWidgets.QTextBrowser()
        self.help_view.setOpenExternalLinks(True)
        layout.addWidget(self.help_view)

        return page

    def _apply_style(self) -> None:
        """Apply modern dark theme."""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #f0f0f0;
                font-family: "Segoe UI", "Roboto", sans-serif;
                font-size: 10pt;
            }
            
            #Sidebar {
                background-color: #1f2123;
                border-right: 1px solid #3c3f41;
            }
            
            #NavButton {
                background-color: transparent;
                border: none;
                border-radius: 8px;
                padding: 8px;
                text-align: center;
                color: #d0d0d0;
            }
            
            #NavButton:hover {
                background-color: #35383b;
            }
            
            #NavButton:checked {
                background-color: #00bcd4;
                color: #ffffff;
                font-weight: 600;
            }
            
            #CompactGroup {
                background-color: #3c3f41;
                border: 1px solid #505357;
                border-radius: 8px;
                margin-top: 12px;
                padding: 12px;
            }
            
            #CompactGroup::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
                font-weight: 600;
                color: #f0f0f0;
            }
            
            QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QListWidget {
                background-color: #2f3235;
                border: 1px solid #505357;
                border-radius: 6px;
                padding: 6px 8px;
                color: #f0f0f0;
            }
            
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
                border: 1px solid #00bcd4;
            }
            
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                color: #f0f0f0;
                border: 1px solid #00bcd4;
                border-radius: 6px;
                selection-background-color: #00bcd4;
                selection-color: #000000;
            }
            
            QCheckBox {
                background-color: transparent;
                color: #f0f0f0;
            }
            
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 2px solid #707070;
                background-color: #1f1f1f;
            }
            
            QCheckBox::indicator:checked {
                background-color: #00bcd4;
                border-color: #00bcd4;
            }
            
            QPushButton {
                background-color: #00bcd4;
                color: #000000;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }
            
            QPushButton:hover:!disabled {
                background-color: #18cfe6;
            }
            
            QPushButton:pressed:!disabled {
                background-color: #009ab3;
            }
            
            QPushButton:disabled {
                background-color: #505357;
                color: #a0a0a0;
            }
            
            #StartButton {
                background-color: #4caf50;
                color: #ffffff;
                font-weight: 700;
                font-size: 11pt;
            }
            
            #StartButton:hover:!disabled {
                background-color: #66bb6a;
            }
            
            QProgressBar {
                background-color: #2f3235;
                border: 1px solid #505357;
                border-radius: 4px;
            }
            
            QProgressBar::chunk {
                background-color: #00bcd4;
                border-radius: 4px;
            }
            
            QLabel {
                color: #f0f0f0;
                font-weight: 500;
            }
        """)

    def _switch_page(self, page_id: str) -> None:
        """Switch to a page."""
        page_order = ["translator", "settings", "history", "help"]
        if page_id in page_order:
            idx = page_order.index(page_id)
            self.stack.setCurrentIndex(idx)
            for i, btn in enumerate(self.nav_buttons):
                btn.setChecked(i == idx)

    def _on_language_changed(self, index: int) -> None:
        """Handle language change."""
        combo = self.sender()
        if combo:
            lang = combo.currentData()
            if lang:
                self.current_ui_language = lang
                self._apply_ui_language()

    def _apply_ui_language(self) -> None:
        """Apply UI language."""
        lang = self.current_ui_language
        
        # Sidebar buttons
        nav_labels = [
            ("Çevirmen", "Translator"),
            ("Ayarlar", "Settings"),
            ("Geçmiş", "History"),
            ("Yardım", "Help"),
        ]
        icons = ["🎯", "⚙️", "📜", "❓"]
        for i, (tr, en) in enumerate(nav_labels):
            text = tr if lang == "tr" else en
            self.nav_buttons[i].setText(f"{icons[i]}\n{text}")

        # Translator page
        self.auto_detect_check.setText(
            "Kaynağı otomatik algıla" if lang == "tr" else "Auto-detect source"
        )
        self.backup_check.setText(
            "Orijinal dosyayı yedekle" if lang == "tr" else "Backup original file"
        )
        self.proxy_check.setText(
            "Proxy kullan:" if lang == "tr" else "Use proxy:"
        )
        self.preview_btn.setText("Önizle" if lang == "tr" else "Preview")
        self.open_btn.setText("Dosyayı Aç" if lang == "tr" else "Open File")
        self.start_btn.setText("▶ BAŞLAT" if lang == "tr" else "▶ START")

    def _set_default_languages(self) -> None:
        """Set default languages."""
        source_idx = self.source_combo.findData(SETTINGS.default_source_lang)
        target_idx = self.target_combo.findData(SETTINGS.default_target_lang)
        if source_idx >= 0:
            self.source_combo.setCurrentIndex(source_idx)
        if target_idx >= 0:
            self.target_combo.setCurrentIndex(target_idx)
        self._sync_source_combo()

    def _sync_source_combo(self) -> None:
        """Sync source combo state with auto-detect."""
        auto_enabled = self.auto_detect_check.isChecked()
        self.source_combo.setEnabled(not auto_enabled)
        if auto_enabled:
            auto_idx = self.source_combo.findData("auto")
            if auto_idx >= 0:
                self.source_combo.setCurrentIndex(auto_idx)

    def _update_proxy_state(self) -> None:
        """Update proxy input state."""
        enabled = self.proxy_check.isChecked()
        self.proxy_edit.setEnabled(enabled)

    def _select_input_file(self) -> None:
        """Select input file."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select .ass file",
            filter="ASS Files (*.ass)"
        )
        if path:
            self.input_file_edit.setText(path)
            if not self.output_file_edit.text():
                self.output_file_edit.setText(str(Path(path).with_name("translated.ass")))
            self._selected_file_path = Path(path)

    def _select_output_file(self) -> None:
        """Select output file."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save as",
            filter="ASS Files (*.ass)"
        )
        if path:
            self.output_file_edit.setText(path)

    def _start_translation(self) -> None:
        """Start translation."""
        input_path = self.input_file_edit.text().strip()
        if not input_path:
            QtWidgets.QMessageBox.warning(self, "Error", "Please select an input file")
            return

        if not Path(input_path).exists():
            QtWidgets.QMessageBox.critical(self, "Error", "Input file not found")
            return

        output_path = self.output_file_edit.text().strip() or str(
            Path(input_path).with_name("translated.ass")
        )
        
        engine = self.engine_combo.currentData()
        source_lang = self.source_combo.currentData()
        target_lang = self.target_combo.currentData()
        proxy = self.proxy_edit.text().strip() if self.proxy_check.isChecked() else None
        backup = self.backup_check.isChecked()

        # Handle DeepL API key
        overrides = None
        if engine == "deepl_api":
            key = self.deepl_key_edit.text().strip()
            if not key:
                QtWidgets.QMessageBox.warning(self, "Error", "DeepL API key required")
                return
            plan = "free" if key.endswith(":fx") else "pro"
            overrides = TranslatorOverrides(plan=plan, api_key=key)

        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.log_view.clear()
        self._append_log("Starting translation...")

        self.worker = TranslationWorker(
            file_path=Path(input_path),
            output_path=Path(output_path),
            engine=engine,
            source_lang=source_lang,
            target_lang=target_lang,
            proxy=proxy,
            backup=backup,
            ui_language=self.current_ui_language,
            translator_overrides=overrides,
            batch_char_limit=None,
        )
        self.worker.progress_changed.connect(self.progress_bar.setValue)
        self.worker.log_emitted.connect(self._append_log)
        self.worker.finished.connect(self._on_translation_finished)
        self.worker.start()

    def _append_log(self, message: str) -> None:
        """Append message to log."""
        self.log_view.appendPlainText(message)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def _on_translation_finished(self, success: bool, details: str) -> None:
        """Handle translation completion."""
        self.start_btn.setEnabled(True)
        if success:
            self.last_output_path = Path(details)
            self.preview_btn.setEnabled(True)
            self.open_btn.setEnabled(True)
            self._append_log(f"✅ Completed: {details}")
            self.history_list.addItem(f"✓ {datetime.now().strftime('%H:%M')} - {Path(details).name}")
            QtWidgets.QMessageBox.information(
                self, "Success", f"Translation completed:\n{details}"
            )
        else:
            self._append_log(f"❌ Error: {details}")
            QtWidgets.QMessageBox.critical(self, "Error", details)

    def _preview_output(self) -> None:
        """Preview output file."""
        if not self.last_output_path or not self.last_output_path.exists():
            return
        
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Preview")
        dialog.resize(700, 500)
        layout = QtWidgets.QVBoxLayout(dialog)
        
        viewer = QtWidgets.QPlainTextEdit()
        viewer.setReadOnly(True)
        try:
            viewer.setPlainText(self.last_output_path.read_text(encoding="utf-8"))
        except OSError:
            viewer.setPlainText("(Unable to load file)")
        layout.addWidget(viewer)
        
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()

    def _open_output(self) -> None:
        """Open output file."""
        if self.last_output_path and self.last_output_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output_path)))


def main() -> None:
    """Main entry point."""
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
