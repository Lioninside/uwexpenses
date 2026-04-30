"""Start page: folder selection, date range, session detection."""
import os
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import core.storage as storage


class StartPage(QWidget):
    """First page the user sees."""

    def __init__(self, on_continue: Callable[[storage.SessionData], None],
                 version: str = "") -> None:
        super().__init__()
        self._on_continue = on_continue
        self._version = version
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 30)
        root.setSpacing(20)

        # Title
        title = QLabel("UwExpenses")
        title.setObjectName("heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        ver_text = f"Monatliche Spesenabrechnung – Revolut + Belege"
        if self._version:
            ver_text += f"   |   v{self._version}"
        sub = QLabel(ver_text)
        sub.setObjectName("status")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(sub)

        root.addSpacing(10)

        # Folder group
        folder_group = QGroupBox("Monatsordner")
        fg = QVBoxLayout(folder_group)
        fg.setSpacing(8)

        folder_hint = QLabel(
            "Wähle den Ordner für den Abrechnungsmonat.\n"
            "Er soll das Revolut-PDF und alle Belege (JPG/PNG) enthalten."
        )
        folder_hint.setObjectName("status")
        folder_hint.setWordWrap(True)
        fg.addWidget(folder_hint)

        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Kein Ordner gewählt …")
        self._folder_edit.setReadOnly(True)
        folder_row.addWidget(self._folder_edit)
        btn_browse = QPushButton("Durchsuchen …")
        btn_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(btn_browse)
        fg.addLayout(folder_row)
        root.addWidget(folder_group)

        # Date range group
        date_group = QGroupBox("Datumsbereich")
        dg = QHBoxLayout(date_group)
        dg.setSpacing(12)

        dg.addWidget(QLabel("Von:"))
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._start_date.setDate(QDate.currentDate().addMonths(-1).addDays(
            -(QDate.currentDate().addMonths(-1).day() - 1)
        ))
        dg.addWidget(self._start_date)

        dg.addSpacing(20)
        dg.addWidget(QLabel("Bis:"))
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        prev = QDate.currentDate().addMonths(-1)
        last_day = prev.daysInMonth()
        self._end_date.setDate(QDate(prev.year(), prev.month(), last_day))
        dg.addWidget(self._end_date)
        dg.addStretch()
        root.addWidget(date_group)

        # Session status
        self._session_label = QLabel("")
        self._session_label.setObjectName("status")
        self._session_label.setWordWrap(True)
        root.addWidget(self._session_label)

        root.addStretch()

        # Continue button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_continue = QPushButton("Weiter →")
        self._btn_continue.setFixedHeight(38)
        self._btn_continue.clicked.connect(self._on_click_continue)
        btn_row.addWidget(self._btn_continue)
        root.addLayout(btn_row)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Monatsordner wählen", os.path.expanduser("~")
        )
        if folder:
            self._folder_edit.setText(folder)
            self._check_session(folder)

    def _check_session(self, folder: str) -> None:
        session = storage.load(folder)
        if session:
            self._session_label.setText(
                f"Bestehende Sitzung gefunden (Schritt: {session.step}). "
                "Fortfahren lädt den gespeicherten Stand."
            )
        else:
            self._session_label.setText("Neuer Ordner – neue Sitzung wird erstellt.")

    def _on_click_continue(self) -> None:
        folder = self._folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, "Fehler", "Bitte wähle einen gültigen Ordner.")
            return

        qsd = self._start_date.date()
        qed = self._end_date.date()
        start = date(qsd.year(), qsd.month(), qsd.day())
        end = date(qed.year(), qed.month(), qed.day())

        if start > end:
            QMessageBox.warning(self, "Fehler", "Startdatum muss vor Enddatum liegen.")
            return

        session = storage.load(folder)
        if session is None:
            session = storage.SessionData(
                folder=folder,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
        else:
            # Allow updating dates even on resumed session
            session.start_date = start.isoformat()
            session.end_date = end.isoformat()

        self._on_continue(session)
