"""
Step 5: Generate outputs – Excel + receipt PDF.

Assigns receipt numbers, runs both exporters, shows results.
"""
import shutil
from datetime import date
from pathlib import Path
from typing import Callable, List

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

import core.storage as storage
from core.excel_exporter import create_excel
from core.receipt_pdf_exporter import create_receipt_pdf

_NO_RECEIPT = "__no_receipt__"
_NEEDS_REVIEW = "__needs_review__"


class _ExportWorker(QThread):
    progress = Signal(str)
    finished = Signal(list)  # issues

    def __init__(self, session: storage.SessionData) -> None:
        super().__init__()
        self._session = session

    def run(self) -> None:
        issues: List[str] = []
        s = self._session

        try:
            self.progress.emit("Belegnummern vergeben ...")
            business_txs = _business_transactions(s)
            _assign_receipt_numbers(s, business_txs)
            storage.save(s)

            output_dir = Path(s.output_dir)
            excel_dir = output_dir / "02_excel"
            pdf_dir = output_dir / "03_receipt_pdf"
            working_dir = output_dir / "01_working"

            # Excel
            self.progress.emit("Excel-Datei erstellen ...")
            start = date.fromisoformat(s.start_date)
            month_label = start.strftime("%Y-%m")
            excel_path = excel_dir / f"Spesen_{month_label}.xlsx"

            # Detect template
            template = _find_template(Path(s.folder))

            create_excel(
                output_path=excel_path,
                template_path=template,
                business_transactions=business_txs,
                all_transactions=s.all_transactions,
                receipts=s.receipts,
                classifications=s.classifications,
                matches=s.matches,
                justifications=s.justifications,
                receipt_numbers=s.receipt_numbers,
                issues=[],
            )
            self.progress.emit(f"Excel gespeichert: {excel_path.name}")

            # Receipt PDF
            self.progress.emit("Beleg-PDF erstellen ...")
            pdf_path = pdf_dir / f"Belege_{month_label}.pdf"
            pdf_issues = create_receipt_pdf(
                output_path=pdf_path,
                working_dir=working_dir,
                business_transactions=business_txs,
                receipt_numbers=s.receipt_numbers,
                matches=s.matches,
                receipts=s.receipts,
                justifications=s.justifications,
            )
            issues.extend(pdf_issues)
            self.progress.emit(f"Beleg-PDF gespeichert: {pdf_path.name}")

        except Exception as exc:
            issues.append(f"Export-Fehler: {exc}")

        self.finished.emit(issues)


def _business_transactions(s: storage.SessionData) -> list:
    revolut = [
        tx for tx in s.transactions
        if s.classifications.get(tx["id"]) in ("business", "review")
    ]
    # Manual expenses are always business – merge and sort by date
    combined = revolut + list(s.manual_expenses)
    return sorted(combined, key=lambda tx: tx.get("date", ""))


def _assign_receipt_numbers(s: storage.SessionData, business_txs: list) -> None:
    # Sort by date, then assign R001, R002 ...
    sorted_txs = sorted(business_txs, key=lambda tx: tx["date"])
    s.receipt_numbers = {}
    for i, tx in enumerate(sorted_txs, 1):
        s.receipt_numbers[tx["id"]] = f"R{i:03d}"


def _find_template(folder: Path) -> Path | None:
    for p in folder.iterdir():
        if p.suffix.lower() in (".xlsx", ".xls") and "template" in p.name.lower():
            return p
    return None


class ExportPage(QWidget):
    def __init__(self, on_done: Callable[[storage.SessionData], None]) -> None:
        super().__init__()
        self._on_done = on_done
        self._session: storage.SessionData = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(16)

        title = QLabel("Schritt 5 – Export erstellen")
        title.setObjectName("heading")
        root.addWidget(title)

        info = QLabel(
            "Jetzt werden Belegnummern vergeben, die Excel-Spesenliste "
            "und das Beleg-PDF (2 Belege pro Seite) erstellt."
        )
        info.setWordWrap(True)
        info.setObjectName("status")
        root.addWidget(info)

        # Summary
        self._summary_group = QGroupBox("Zusammenfassung")
        sg = QVBoxLayout(self._summary_group)
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        sg.addWidget(self._summary_label)
        root.addWidget(self._summary_group)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(160)
        root.addWidget(self._log)

        # Issues
        self._issues_label = QLabel("")
        self._issues_label.setWordWrap(True)
        self._issues_label.setStyleSheet("color: #CC4400;")
        root.addWidget(self._issues_label)

        root.addStretch()

        nav = QHBoxLayout()
        nav.addStretch()
        self._btn_export = QPushButton("Export starten")
        self._btn_export.setFixedHeight(40)
        self._btn_export.clicked.connect(self._start_export)
        nav.addWidget(self._btn_export)
        self._btn_done = QPushButton("Fertig")
        self._btn_done.setEnabled(False)
        self._btn_done.clicked.connect(lambda: self._on_done(self._session))
        nav.addWidget(self._btn_done)
        root.addLayout(nav)

    def load_session(self, session: storage.SessionData) -> None:
        self._session = session
        self._update_summary()

    def _update_summary(self) -> None:
        s = self._session
        n_total = len(s.transactions)
        n_business = sum(1 for tx in s.transactions
                         if s.classifications.get(tx["id"]) == "business")
        n_review = sum(1 for tx in s.transactions
                       if s.classifications.get(tx["id"]) == "review")
        n_private = sum(1 for tx in s.transactions
                        if s.classifications.get(tx["id"]) == "private")
        n_manual = len(s.manual_expenses)
        n_receipts = len(s.receipts)
        n_matched = sum(
            1 for tx in s.transactions
            if s.matches.get(tx["id"]) not in (None, "", _NO_RECEIPT, _NEEDS_REVIEW)
            and s.classifications.get(tx["id"]) in ("business", "review")
        )
        out = s.output_dir or "(noch nicht erstellt)"
        self._summary_label.setText(
            f"Revolut-Transaktionen: {n_total}\n"
            f"  Geschaeftlich:       {n_business}\n"
            f"  Pruefen:             {n_review}\n"
            f"  Privat:              {n_private}\n"
            f"Manuelle Spesen:       {n_manual}\n"
            f"Belege indexiert:      {n_receipts}\n"
            f"Belege zugeordnet:     {n_matched}\n"
            f"\nOutput-Ordner:  {out}"
        )

    def _start_export(self) -> None:
        self._btn_export.setEnabled(False)
        self._btn_done.setEnabled(False)
        self._progress.setVisible(True)
        self._log.clear()
        self._issues_label.setText("")

        self._worker = _ExportWorker(self._session)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_export_done)
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self._log.append(msg)

    def _on_export_done(self, issues: list) -> None:
        self._progress.setVisible(False)
        self._btn_export.setEnabled(True)
        self._btn_done.setEnabled(True)

        self._session.step = "done"
        storage.save(self._session)

        if issues:
            self._issues_label.setText(
                "Hinweise / Warnungen:\n" + "\n".join(f"  - {i}" for i in issues)
            )
        self._log.append("Export abgeschlossen.")
        self._log.append(f"Output-Ordner: {self._session.output_dir}")
