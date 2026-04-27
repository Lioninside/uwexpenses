"""
Step 1: Revolut statement import (PDF or CSV).

Auto-detects which file(s) are in the folder.
Preference order: CSV > PDF (CSV is easier to parse reliably).
User can override the file choice at any time.
"""
from pathlib import Path
from typing import Callable, List

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QProgressBar,
)

import core.storage as storage
from core.revolut_parser import parse_revolut_pdf, filter_transactions
from core.csv_parser import parse_revolut_csv


class _ParseWorker(QThread):
    finished = Signal(list, list, str)  # (transactions, issues, file_type)

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self._path = file_path

    def run(self) -> None:
        path = Path(self._path)
        if path.suffix.lower() == ".csv":
            txs, issues = parse_revolut_csv(self._path)
            self.finished.emit(txs, issues, "csv")
        else:
            txs, issues = parse_revolut_pdf(self._path)
            self.finished.emit(txs, issues, "pdf")


class PdfParsePage(QWidget):
    def __init__(self, on_continue: Callable[[storage.SessionData], None]) -> None:
        super().__init__()
        self._on_continue = on_continue
        self._session: storage.SessionData = None
        self._worker: _ParseWorker = None
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(16)

        title = QLabel("Schritt 1 – Revolut-Auszug einlesen")
        title.setObjectName("heading")
        root.addWidget(title)

        info = QLabel(
            "Unterstuetzt werden: Revolut PDF-Auszug und Revolut CSV-Export.\n"
            "CSV wird bevorzugt (zuverlaessigere Erkennung). "
            "Die Datei wird automatisch erkannt."
        )
        info.setWordWrap(True)
        info.setObjectName("status")
        root.addWidget(info)

        # File selection
        file_group = QGroupBox("Revolut-Datei (PDF oder CSV)")
        fg = QVBoxLayout(file_group)
        self._file_label = QLabel("Wird automatisch erkannt ...")
        self._file_label.setWordWrap(True)
        fg.addWidget(self._file_label)
        btn_row = QHBoxLayout()
        self._btn_change = QPushButton("Andere Datei waehlen ...")
        self._btn_change.clicked.connect(self._pick_file)
        btn_row.addWidget(self._btn_change)
        btn_row.addStretch()
        fg.addLayout(btn_row)
        root.addWidget(file_group)

        # Options
        opt_group = QGroupBox("Optionen")
        og = QHBoxLayout(opt_group)
        self._chk_incoming = QCheckBox(
            "Eingehende Zahlungen anzeigen (normalerweise ausgeblendet)"
        )
        og.addWidget(self._chk_incoming)
        og.addStretch()
        root.addWidget(opt_group)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # Results
        result_group = QGroupBox("Gefundene Transaktionen im Datumsbereich")
        rg = QVBoxLayout(result_group)
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["Datum", "Beschreibung", "Kategorie", "Betrag", "Waehrung", "Saldo"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        rg.addWidget(self._table)
        self._count_label = QLabel("")
        self._count_label.setObjectName("status")
        rg.addWidget(self._count_label)
        root.addWidget(result_group)

        # Issues
        self._issues_label = QLabel("")
        self._issues_label.setWordWrap(True)
        self._issues_label.setStyleSheet("color: #CC4400; font-size: 12px;")
        root.addWidget(self._issues_label)

        # Nav
        nav = QHBoxLayout()
        nav.addStretch()
        self._btn_parse = QPushButton("Datei einlesen")
        self._btn_parse.clicked.connect(self._start_parse)
        nav.addWidget(self._btn_parse)
        self._btn_continue = QPushButton("Weiter ->")
        self._btn_continue.setEnabled(False)
        self._btn_continue.clicked.connect(self._do_continue)
        nav.addWidget(self._btn_continue)
        root.addLayout(nav)

    # ------------------------------------------------------------------
    def load_session(self, session: storage.SessionData) -> None:
        self._session = session
        detected = self._detect_statement_file()
        if detected:
            self._file_label.setText(str(detected))
            self._session.revolut_pdf = str(detected)
        else:
            self._file_label.setText(
                "Keine Revolut-Datei erkannt – bitte manuell waehlen."
            )

        self._chk_incoming.setChecked(session.include_incoming)

        if session.transactions:
            self._populate_table(session.transactions)
            self._btn_continue.setEnabled(True)

    def _detect_statement_file(self) -> Path:
        """Prefer CSV over PDF if both exist. Warn if multiple found."""
        if self._session and self._session.revolut_pdf:
            p = Path(self._session.revolut_pdf)
            if p.exists():
                return p

        folder = Path(self._session.folder)
        csvs = list(folder.glob("*.csv")) + list(folder.glob("*.CSV"))
        pdfs = list(folder.glob("*.pdf")) + list(folder.glob("*.PDF"))

        if len(csvs) == 1:
            return csvs[0]
        if len(csvs) > 1:
            self._issues_label.setText(
                f"Mehrere CSV-Dateien gefunden: {[p.name for p in csvs]}. "
                "Bitte manuell waehlen."
            )
        if len(pdfs) == 1:
            return pdfs[0]
        if len(pdfs) > 1:
            self._issues_label.setText(
                f"Mehrere PDF-Dateien gefunden: {[p.name for p in pdfs]}. "
                "Bitte manuell waehlen."
            )
        return None

    def _pick_file(self) -> None:
        start = self._session.folder if self._session else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Revolut-Datei waehlen", start,
            "Revolut-Dateien (*.pdf *.PDF *.csv *.CSV)"
        )
        if path:
            self._file_label.setText(path)
            self._session.revolut_pdf = path

    def _start_parse(self) -> None:
        file_path = self._session.revolut_pdf if self._session else ""
        if not file_path or not Path(file_path).exists():
            QMessageBox.warning(self, "Fehler", "Keine gueltige Datei ausgewaehlt.")
            return

        self._progress.setVisible(True)
        self._btn_parse.setEnabled(False)
        self._btn_continue.setEnabled(False)
        self._issues_label.setText("")

        self._worker = _ParseWorker(file_path)
        self._worker.finished.connect(self._on_parse_done)
        self._worker.start()

    def _on_parse_done(self, all_txs: list, issues: list, file_type: str) -> None:
        self._progress.setVisible(False)
        self._btn_parse.setEnabled(True)

        if issues:
            self._issues_label.setText("Hinweise:\n* " + "\n* ".join(issues))

        from datetime import date as _date
        start = _date.fromisoformat(self._session.start_date)
        end = _date.fromisoformat(self._session.end_date)
        include = self._chk_incoming.isChecked()
        filtered = filter_transactions(all_txs, start, end, include)

        self._session.all_transactions = all_txs
        self._session.transactions = filtered
        self._session.include_incoming = include
        storage.save(self._session)

        self._populate_table(filtered)
        self._btn_continue.setEnabled(True)
        type_label = "CSV" if file_type == "csv" else "PDF"
        self._count_label.setText(
            f"{len(filtered)} Transaktionen im Zeitraum gefunden "
            f"({len(all_txs)} gesamt in {type_label})."
        )

    def _populate_table(self, transactions: list) -> None:
        self._table.setRowCount(len(transactions))
        for row, tx in enumerate(transactions):
            self._table.setItem(row, 0, QTableWidgetItem(tx.get("date", "")))
            self._table.setItem(row, 1, QTableWidgetItem(tx.get("description", "")))
            self._table.setItem(row, 2, QTableWidgetItem(tx.get("category", "")))
            amt = tx.get("amount", "")
            item = QTableWidgetItem(
                f"{amt:.2f}" if isinstance(amt, float) else str(amt)
            )
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(row, 3, item)
            self._table.setItem(row, 4, QTableWidgetItem(tx.get("currency", "")))
            bal = tx.get("balance", "")
            bal_item = QTableWidgetItem(
                f"{bal:.2f}" if isinstance(bal, float) else str(bal or "")
            )
            bal_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(row, 5, bal_item)
        self._table.resizeColumnsToContents()

    def _do_continue(self) -> None:
        self._session.step = "classify"
        storage.save(self._session)
        self._on_continue(self._session)
