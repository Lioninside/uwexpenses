"""Final 'Done' screen showing output location and allowing a restart."""
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

import core.storage as storage


class DonePage(QWidget):
    def __init__(self, on_restart: Callable[[], None]) -> None:
        super().__init__()
        self._on_restart = on_restart
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(60, 60, 60, 60)
        root.setSpacing(20)
        root.addStretch()

        title = QLabel("Abrechnung abgeschlossen!")
        title.setObjectName("heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        self._out_label = QLabel("")
        self._out_label.setObjectName("status")
        self._out_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._out_label.setWordWrap(True)
        root.addWidget(self._out_label)

        root.addSpacing(20)

        note = QLabel(
            "Die Originaldateien wurden nicht veraendert.\n"
            "Excel und Beleg-PDF befinden sich im Output-Ordner."
        )
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        root.addWidget(note)

        root.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn = QPushButton("Neue Abrechnung starten")
        btn.setFixedHeight(40)
        btn.clicked.connect(self._on_restart)
        btn_row.addWidget(btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    def load_session(self, session: storage.SessionData) -> None:
        out = session.output_dir or session.folder
        self._out_label.setText(
            f"Output gespeichert in:\n{out}\n\n"
            "02_excel/  →  Excel-Spesenliste\n"
            "03_receipt_pdf/  →  Beleg-PDF"
        )
