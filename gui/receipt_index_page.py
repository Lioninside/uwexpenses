"""
Step 3: Receipt indexing.

Automatic step – scans the folder, copies working files, shows index table.
Optional OCR extracts amounts from receipts for better matching in Step 4.
"""
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import core.storage as storage
from core.ocr_extractor import ocr_available
from core.receipt_indexer import index_receipts


class _IndexWorker(QThread):
    progress = Signal(str)
    finished = Signal(list, list)

    def __init__(self, folder: Path, working_dir: Path, run_ocr: bool) -> None:
        super().__init__()
        self._folder = folder
        self._working_dir = working_dir
        self._run_ocr = run_ocr

    def run(self) -> None:
        index, issues = index_receipts(
            self._folder, self._working_dir, run_ocr=self._run_ocr
        )
        self.finished.emit(index, issues)


class ReceiptIndexPage(QWidget):
    def __init__(self, on_continue: Callable[[storage.SessionData], None]) -> None:
        super().__init__()
        self._on_continue = on_continue
        self._session: storage.SessionData = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(16)

        title = QLabel("Schritt 3 – Belege indexieren")
        title.setObjectName("heading")
        root.addWidget(title)

        info = QLabel(
            "Die App sucht alle JPG/PNG/PDF-Dateien im Monatsordner, "
            "liest das Aufnahmedatum aus dem Dateinamen oder EXIF und "
            "erstellt Arbeitskopien im Output-Ordner."
        )
        info.setWordWrap(True)
        info.setObjectName("status")
        root.addWidget(info)

        # OCR option
        ocr_group = QGroupBox("Betragserkennung (OCR)")
        og = QVBoxLayout(ocr_group)
        backend = ocr_available()
        self._chk_ocr = QCheckBox("Betraege per OCR erkennen (verbessert Zuordnung in Schritt 4)")
        if backend == "none":
            self._chk_ocr.setEnabled(False)
            self._chk_ocr.setText(
                "Betraege per OCR erkennen – nicht verfuegbar "
                "(pip install easyocr  oder  pip install pytesseract)"
            )
        else:
            self._chk_ocr.setChecked(True)
            self._chk_ocr.setText(
                f"Betraege per OCR erkennen ({backend})  "
                "– erkennt Beleg-Gesamtbetrag fuer besseres Matching"
            )
        og.addWidget(self._chk_ocr)
        if backend == "easyocr":
            note = QLabel(
                "Hinweis: Beim ersten Start laedt easyocr das Sprachmodell herunter (~1.5 GB). "
                "OCR dauert einige Sekunden pro Beleg."
            )
            note.setWordWrap(True)
            note.setObjectName("status")
            og.addWidget(note)
        root.addWidget(ocr_group)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("status")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._progress_label)

        result_group = QGroupBox("Beleg-Index")
        rg = QVBoxLayout(result_group)
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Originaldatei", "Arbeitsdatei", "Datum/Zeit", "Quelle", "OCR-Betrag", "Hinweise"
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        rg.addWidget(self._table)
        self._count_label = QLabel("")
        self._count_label.setObjectName("status")
        rg.addWidget(self._count_label)
        root.addWidget(result_group)

        self._issues_label = QPlainTextEdit()
        self._issues_label.setReadOnly(True)
        self._issues_label.setMaximumHeight(80)
        self._issues_label.setVisible(False)
        self._issues_label.setStyleSheet(
            "color: #CC4400; font-size: 12px; background: #FFF8F5; border: 1px solid #EEA090;"
        )
        root.addWidget(self._issues_label)

        nav = QHBoxLayout()
        nav.addStretch()
        self._btn_reindex = QPushButton("Erneut indexieren")
        self._btn_reindex.clicked.connect(self._start_index)
        nav.addWidget(self._btn_reindex)
        self._btn_continue = QPushButton("Weiter →")
        self._btn_continue.setEnabled(False)
        self._btn_continue.clicked.connect(self._do_continue)
        nav.addWidget(self._btn_continue)
        root.addLayout(nav)

    def load_session(self, session: storage.SessionData) -> None:
        self._session = session
        if session.receipts:
            self._populate_table(session.receipts)
            self._btn_continue.setEnabled(True)
        else:
            self._start_index()

    def _start_index(self) -> None:
        folder = Path(self._session.folder)
        output_dir = self._ensure_output_dir()
        working_dir = output_dir / "01_working"

        self._progress.setVisible(True)
        self._progress_label.setText("Belege werden indexiert …")
        self._btn_reindex.setEnabled(False)
        self._btn_continue.setEnabled(False)
        self._issues_label.setVisible(False)

        run_ocr = self._chk_ocr.isChecked() and self._chk_ocr.isEnabled()

        self._worker = _IndexWorker(folder, working_dir, run_ocr=run_ocr)
        self._worker.finished.connect(self._on_index_done)
        self._worker.start()

    def _ensure_output_dir(self) -> Path:
        from datetime import date
        start = date.fromisoformat(self._session.start_date)
        month_label = start.strftime("%Y-%m")
        out = Path(self._session.folder) / f"output_{month_label}"
        out.mkdir(exist_ok=True)
        (out / "01_working").mkdir(exist_ok=True)
        (out / "02_excel").mkdir(exist_ok=True)
        (out / "03_receipt_pdf").mkdir(exist_ok=True)
        (out / "04_logs").mkdir(exist_ok=True)
        self._session.output_dir = str(out)
        return out

    def _on_index_done(self, index: list, issues: list) -> None:
        self._progress.setVisible(False)
        self._progress_label.setText("")
        self._btn_reindex.setEnabled(True)

        self._session.receipts = index
        storage.save(self._session)

        self._populate_table(index)
        self._btn_continue.setEnabled(True)

        if issues:
            self._issues_label.setPlainText("Hinweise:\n• " + "\n• ".join(issues))
            self._issues_label.setVisible(True)

    def _populate_table(self, index: list) -> None:
        self._table.setRowCount(len(index))
        for row, entry in enumerate(index):
            self._table.setItem(row, 0, QTableWidgetItem(entry.get("original_filename", "")))
            self._table.setItem(row, 1, QTableWidgetItem(entry.get("working_filename", "")))
            self._table.setItem(row, 2, QTableWidgetItem(entry.get("image_datetime", "")))
            self._table.setItem(row, 3, QTableWidgetItem(entry.get("source", "")))
            amounts = entry.get("ocr_amounts", [])
            amt_text = ", ".join(f"{a:.2f}" for a in amounts[:3]) if amounts else "–"
            self._table.setItem(row, 4, QTableWidgetItem(amt_text))
            self._table.setItem(row, 5, QTableWidgetItem(entry.get("notes", "")))
        self._table.resizeColumnsToContents()
        ocr_count = sum(1 for e in index if e.get("ocr_amounts"))
        self._count_label.setText(
            f"{len(index)} Belege gefunden."
            + (f"  OCR: {ocr_count} Belege mit erkanntem Betrag." if ocr_count else "")
        )

    def _do_continue(self) -> None:
        self._session.step = "match"
        storage.save(self._session)
        self._on_continue(self._session)
