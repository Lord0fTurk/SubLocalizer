from __future__ import annotations

import asyncio
import json
import locale
import os
import sys
import ctypes
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QUrl, QSize, QPoint
from PyQt6.QtGui import QDesktopServices, QColor, QAction, QIcon, QFont

from config import SETTINGS
from parser.ass_parser import ASSParser
from translator.factory import build_translator
from translator.orchestrator import TranslationOrchestrator
from utils.cache import SessionCache, TranslationMemory
from utils.lang import detect_language
from utils.logging_config import configure_logging

# --- Constants ---

LANGUAGE_CHOICES = [
    {"code": "auto", "allow_target": False, "labels": {"en": "Auto Detect", "tr": "Otomatik"}},
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

# --- Helpers ---

def _determine_initial_language() -> str:
    preferred = (SETTINGS.ui_language or "").strip().lower()
    if preferred and preferred not in {"system", "auto"} and locale_available(preferred):
        return preferred
    # Simple detection logic
    lang = locale.getlocale()[0]
    if lang and lang.lower().startswith("tr"):
        return "tr"
    return "en"

@lru_cache(maxsize=None)
def _load_locale_bundle(language: str) -> dict[str, str]:
    bundles: dict[str, str] = {}
    for code in (language, "en"):
        path = LOCALES_DIR / f"{code}.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                    if isinstance(data, dict):
                        bundles.update(data)
                        break
            except: pass
    return bundles

def get_ui_text(language: str, key: str) -> str:
    bundle = _load_locale_bundle(language)
    fallback = _load_locale_bundle("en")
    return bundle.get(key, fallback.get(key, key))

def locale_available(language: str) -> bool:
    return (LOCALES_DIR / f"{language}.json").exists()

# --- Worker ---

@dataclass(slots=True)
class TranslatorOverrides:
    plan: str | None = None
    api_key: str | None = None

class TranslationWorker(QtCore.QThread):
    progress_changed = QtCore.pyqtSignal(int)
    status_changed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(bool, str)

    def __init__(self, file_path: Path, output_path: Path, engine: str, source: str, target: str, 
                 proxy: str | None, backup: bool, overrides: TranslatorOverrides | None):
        super().__init__()
        self.file_path = file_path
        self.output_path = output_path
        self.engine = engine
        self.source = source
        self.target = target
        self.proxy = proxy
        self.backup = backup
        self.overrides = overrides or TranslatorOverrides()

    def run(self):
        configure_logging()
        try:
            parser = ASSParser.from_file(self.file_path)
            texts = list(parser.iter_texts())
            if not texts: raise RuntimeError("No dialogue lines found.")
            
            # Resolve Source
            if self.source == "auto":
                detected = detect_language(texts)
                final_source = detected if detected else SETTINGS.default_source_lang
                self.status_changed.emit(f"Detected: {final_source}")
            else:
                final_source = self.source

            translator = build_translator(
                self.engine, proxy=self.proxy,
                deepl_api_key=self.overrides.api_key,
                deepl_plan=self.overrides.plan
            )
            
            orchestrator = TranslationOrchestrator(
                translator=translator,
                memory=TranslationMemory(SETTINGS.translation_memory_path),
                session_cache=SessionCache(),
                batch_char_limit=SETTINGS.translator.batch_char_limit
            )

            def progress(done, total):
                self.progress_changed.emit(int(done / max(total, 1) * 100))

            translations = asyncio.run(orchestrator.translate(
                texts=texts, source_lang=final_source, target_lang=self.target,
                progress_cb=progress, log_cb=lambda msg: None
            ))
            
            parser.apply_translations(translations)
            if self.backup: parser.backup_original()
            result = parser.write(self.output_path)
            self.finished.emit(True, str(result))
            
        except Exception as e:
            self.finished.emit(False, str(e))

# --- UI Components ---

class CompactWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui_lang = _determine_initial_language()
        self.setWindowTitle("SubLocalizer")
        self.setFixedSize(400, 580)  # Compact fixed size
        self.selected_file: Path | None = None
        self.worker = None
        
        self._init_ui()
        self._apply_theme()

    def _init_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Set Window Icon
        self.setWindowIcon(QIcon("icon.ico"))

        # 1. Header
        header = QtWidgets.QHBoxLayout()
        
        # App Icon in Header
        app_logo = QtWidgets.QLabel()
        app_logo.setPixmap(QIcon("icon.ico").pixmap(32, 32))
        header.addWidget(app_logo)

        title = QtWidgets.QLabel("SubLocalizer")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00bcd4;")
        
        btn_settings = QtWidgets.QPushButton("⚙️")
        btn_settings.setFixedSize(32, 32)
        btn_settings.setToolTip("Settings")
        btn_settings.clicked.connect(self._show_settings)
        
        btn_history = QtWidgets.QPushButton("📜")
        btn_history.setFixedSize(32, 32)
        btn_history.setToolTip("History")
        btn_history.clicked.connect(self._show_history)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(btn_history)
        header.addWidget(btn_settings)
        layout.addLayout(header)

        # 2. File Card (Drag & Drop)
        self.file_card = QtWidgets.QFrame()
        self.file_card.setObjectName("FileCard")
        self.file_card.setFixedSize(360, 120)
        self.file_card.setCursor(Qt.CursorShape.PointingHandCursor)
        
        card_layout = QtWidgets.QVBoxLayout(self.file_card)
        self.lbl_file_icon = QtWidgets.QLabel("📂")
        self.lbl_file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_file_icon.setStyleSheet("font-size: 32px;")
        
        self.lbl_file_name = QtWidgets.QLabel(get_ui_text(self.ui_lang, "file_placeholder"))
        self.lbl_file_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_file_name.setWordWrap(True)
        
        card_layout.addStretch()
        card_layout.addWidget(self.lbl_file_icon)
        card_layout.addWidget(self.lbl_file_name)
        card_layout.addStretch()
        
        # Enable click to browse
        self.file_card.mousePressEvent = self._browse_file
        self.setAcceptDrops(True) # Window accepts drops
        
        layout.addWidget(self.file_card)

        # 3. Controls
        controls_group = QtWidgets.QGroupBox()
        controls_group.setStyleSheet("border: none;")
        controls_layout = QtWidgets.QVBoxLayout(controls_group)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        # Languages
        lang_row = QtWidgets.QHBoxLayout()
        self.combo_source = QtWidgets.QComboBox()
        self.combo_target = QtWidgets.QComboBox()
        self._populate_langs()
        
        arrow = QtWidgets.QLabel("➜")
        arrow.setStyleSheet("color: #666; font-weight: bold;")
        
        lang_row.addWidget(self.combo_source, 1)
        lang_row.addWidget(arrow)
        lang_row.addWidget(self.combo_target, 1)
        controls_layout.addLayout(lang_row)

        # Engine
        self.combo_engine = QtWidgets.QComboBox()
        self.combo_engine.addItems(["Google Translate", "DeepL Web", "DeepL API"])
        self.combo_engine.setItemData(0, "google")
        self.combo_engine.setItemData(1, "deepl_web")
        self.combo_engine.setItemData(2, "deepl_api")
        controls_layout.addWidget(self.combo_engine)

        layout.addWidget(controls_group)

        # 4. Action
        layout.addStretch()
        
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.status_label)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.btn_start = QtWidgets.QPushButton("TRANSLATE")
        self.btn_start.setObjectName("BtnStart")
        self.btn_start.setFixedHeight(50)
        self.btn_start.clicked.connect(self._start)
        layout.addWidget(self.btn_start)

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QLabel { color: #e0e0e0; font-family: 'Segoe UI'; }
            
            /* Buttons */
            QPushButton {
                background-color: #333;
                border: none;
                border-radius: 8px;
                color: #fff;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #444; }
            
            #BtnStart {
                background-color: #00bcd4;
                color: #000;
                font-weight: bold;
                font-size: 16px;
                border-radius: 10px;
            }
            #BtnStart:hover { background-color: #26c6da; }
            #BtnStart:disabled { background-color: #333; color: #666; }

            /* File Card */
            #FileCard {
                background-color: #252526;
                border: 2px dashed #444;
                border-radius: 12px;
            }
            #FileCard:hover { border-color: #00bcd4; background-color: #2d2d30; }

            /* Combos */
            QComboBox {
                background-color: #2d2d30;
                border: 1px solid #3e3e42;
                border-radius: 6px;
                padding: 8px;
                color: #fff;
                min-height: 20px;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background-color: #252526;
                selection-background-color: #00bcd4;
                selection-color: #000;
            }
            
            /* Progress */
            QProgressBar { background-color: #333; border-radius: 2px; }
            QProgressBar::chunk { background-color: #00bcd4; }
        """)

    def _populate_langs(self):
        for item in LANGUAGE_CHOICES:
            label = item["labels"].get(self.ui_lang, item["labels"]["en"])
            self.combo_source.addItem(label, item["code"])
            if item.get("allow_target", True):
                self.combo_target.addItem(label, item["code"])
        
        # Defaults
        self.combo_source.setCurrentIndex(self.combo_source.findData("auto"))
        self.combo_target.setCurrentIndex(self.combo_target.findData("tr"))

    # --- Events ---

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for f in files:
            if f.lower().endswith(".ass"):
                self._set_file(Path(f))
                break

    def _browse_file(self, event):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select ASS", "", "ASS Files (*.ass)")
        if path: self._set_file(Path(path))

    def _set_file(self, path: Path):
        self.selected_file = path
        self.lbl_file_name.setText(path.name)
        self.lbl_file_icon.setText("📄")
        self.lbl_file_name.setStyleSheet("color: #00bcd4; font-weight: bold;")
        self.file_card.setStyleSheet("#FileCard { border: 2px solid #00bcd4; background-color: #253326; }")

    def _show_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def _show_history(self):
        dlg = HistoryDialog(self)
        dlg.exec()

    def _start(self):
        if not self.selected_file:
            self.status_label.setText("Please select a file first!")
            self.status_label.setStyleSheet("color: #ff5252;")
            return

        engine = self.combo_engine.currentData()
        
        # Check API Key
        overrides = None
        if engine == "deepl_api":
            key = SETTINGS.secrets.deepl_api_key # Assuming loaded from config or we need to ask
            # For this compact UI, we'll check the QSettings or Config object. 
            # Since we don't have a persistent settings UI binding in this snippet, 
            # we'll ask the user if missing.
            if not key:
                # Try to get from dialog
                dlg = SettingsDialog(self)
                if dlg.exec():
                    key = dlg.input_key.text()
                
                if not key:
                    QtWidgets.QMessageBox.warning(self, "API Key", "DeepL API Key required.")
                    return
            
            plan = "free" if key.endswith(":fx") else "pro"
            overrides = TranslatorOverrides(plan=plan, api_key=key)

        self.btn_start.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText("Starting...")
        self.status_label.setStyleSheet("color: #e0e0e0;")

        output = self.selected_file.with_name(f"{self.selected_file.stem}_{self.combo_target.currentData()}.ass")

        self.worker = TranslationWorker(
            self.selected_file, output, engine,
            self.combo_source.currentData(),
            self.combo_target.currentData(),
            SETTINGS.translator.proxy_url,
            True, # Backup always on for simplicity
            overrides
        )
        self.worker.progress_changed.connect(self.progress.setValue)
        self.worker.status_changed.connect(self.status_label.setText)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, success, result):
        self.btn_start.setEnabled(True)
        if success:
            self.status_label.setText("Done!")
            self.status_label.setStyleSheet("color: #4caf50;")
            QtWidgets.QMessageBox.information(self, "Success", f"Saved to:\n{Path(result).name}")
            # Add to history (simple text file append for now or just memory)
        else:
            self.status_label.setText("Error")
            self.status_label.setStyleSheet("color: #ff5252;")
            QtWidgets.QMessageBox.critical(self, "Error", result)

# --- Dialogs ---

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(300, 200)
        self.setStyleSheet("background-color: #252526; color: #fff;")
        
        layout = QtWidgets.QVBoxLayout(self)
        
        layout.addWidget(QtWidgets.QLabel("DeepL API Key:"))
        self.input_key = QtWidgets.QLineEdit()
        self.input_key.setPlaceholderText("xxxx:fx")
        self.input_key.setStyleSheet("background: #333; border: 1px solid #444; padding: 5px; color: #fff;")
        # Load existing if possible
        if SETTINGS.secrets.deepl_api_key:
            self.input_key.setText(SETTINGS.secrets.deepl_api_key)
        layout.addWidget(self.input_key)

        layout.addWidget(QtWidgets.QLabel("Proxy URL:"))
        self.input_proxy = QtWidgets.QLineEdit()
        self.input_proxy.setPlaceholderText("http://...")
        self.input_proxy.setStyleSheet("background: #333; border: 1px solid #444; padding: 5px; color: #fff;")
        if SETTINGS.translator.proxy_url:
            self.input_proxy.setText(SETTINGS.translator.proxy_url)
        layout.addWidget(self.input_proxy)

        layout.addStretch()
        
        btn_save = QtWidgets.QPushButton("Save")
        btn_save.setStyleSheet("background: #00bcd4; color: #000; border-radius: 4px; padding: 6px;")
        btn_save.clicked.connect(self.accept)
        layout.addWidget(btn_save)

    def accept(self):
        # Save to runtime settings (and ideally to disk)
        SETTINGS.secrets.deepl_api_key = self.input_key.text().strip() or None
        SETTINGS.translator.proxy_url = self.input_proxy.text().strip() or None
        super().accept()

class HistoryDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("History")
        self.setFixedSize(300, 400)
        self.setStyleSheet("background-color: #252526; color: #fff;")
        layout = QtWidgets.QVBoxLayout(self)
        list_widget = QtWidgets.QListWidget()
        list_widget.setStyleSheet("background: #333; border: none;")
        # Mock history
        list_widget.addItem("Session started " + datetime.now().strftime("%H:%M"))
        layout.addWidget(list_widget)
        
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_close.setStyleSheet("background: #444; color: #fff; border-radius: 4px; padding: 6px;")
        layout.addWidget(btn_close)

def main():
    # Fix taskbar icon on Windows
    if sys.platform == 'win32':
        myappid = 'sublocalizer.app.1.0'
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    win = CompactWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
