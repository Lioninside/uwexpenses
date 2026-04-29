"""
Main application window with QStackedWidget page navigation.

Pages (in order):
  0  StartPage           – folder + date selection
  1  PdfParsePage        – parse Revolut PDF or CSV
  2  ReceiptIndexPage    – index receipt images
  3  CombinedReviewPage  – classify transactions AND assign receipts
  4  ExportPage          – generate Excel + PDF
  5  DonePage            – success screen
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QScrollArea, QStackedWidget, QStatusBar, QWidget,
)

import core.storage as storage
from gui.start_page import StartPage
from gui.pdf_parse_page import PdfParsePage
from gui.receipt_index_page import ReceiptIndexPage
from gui.combined_review_page import CombinedReviewPage
from gui.export_page import ExportPage
from gui.done_page import DonePage

_PAGE_START    = 0
_PAGE_PDF      = 1
_PAGE_RECEIPTS = 2
_PAGE_REVIEW   = 3
_PAGE_EXPORT   = 4
_PAGE_DONE     = 5


class MainWindow(QMainWindow):
    def __init__(self, version: str = "") -> None:
        super().__init__()
        self._version = version
        title = f"UwExpenses v{version}" if version else "UwExpenses"
        self.setWindowTitle(f"{title} – Monatliche Spesenabrechnung")
        self.resize(960, 660)
        self.setMinimumSize(700, 480)
        self._setup_pages()
        self._status_bar = QStatusBar()
        version_lbl = QLabel(f" v{version} " if version else "")
        version_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self._status_bar.addPermanentWidget(version_lbl)
        self.setStatusBar(self._status_bar)

    @staticmethod
    def _scrolled(page: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa.setWidget(page)
        return sa

    def _setup_pages(self) -> None:
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._page_start    = StartPage(on_continue=self._go_pdf)
        self._page_pdf      = PdfParsePage(on_continue=self._go_receipts)
        self._page_receipts = ReceiptIndexPage(on_continue=self._go_review)
        self._page_review   = CombinedReviewPage(on_continue=self._go_export)
        self._page_export   = ExportPage(on_done=self._go_done)
        self._page_done     = DonePage(on_restart=self._go_start)

        for page in [
            self._page_start,
            self._page_pdf,
            self._page_receipts,
            self._page_review,
            self._page_export,
            self._page_done,
        ]:
            self._stack.addWidget(self._scrolled(page))

        self._stack.setCurrentIndex(_PAGE_START)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_start(self) -> None:
        self._stack.setCurrentIndex(_PAGE_START)
        self._status("Startseite")

    def _go_pdf(self, session: storage.SessionData) -> None:
        step = session.step
        # "classify" and "match" are old step names from pre-v0.5 sessions
        if step in ("receipts", "review", "export", "done", "classify", "match"):
            self._resume_session(session)
            return
        self._page_pdf.load_session(session)
        self._stack.setCurrentIndex(_PAGE_PDF)
        self._status("PDF / CSV einlesen")

    def _go_receipts(self, session: storage.SessionData) -> None:
        self._page_receipts.load_session(session)
        self._stack.setCurrentIndex(_PAGE_RECEIPTS)
        self._status("Belege indexieren")

    def _go_review(self, session: storage.SessionData) -> None:
        self._page_review.load_session(session)
        self._stack.setCurrentIndex(_PAGE_REVIEW)
        self._status("Klassifizieren & Belege zuordnen")

    def _go_export(self, session: storage.SessionData) -> None:
        self._page_export.load_session(session)
        self._stack.setCurrentIndex(_PAGE_EXPORT)
        self._status("Export erstellen")

    def _go_done(self, session: storage.SessionData) -> None:
        self._page_done.load_session(session)
        self._stack.setCurrentIndex(_PAGE_DONE)
        self._status("Fertig")

    def _resume_session(self, session: storage.SessionData) -> None:
        """Jump to the right page; handle both new and old step names."""
        step = session.step
        # Map old step names to new ones
        step = {"classify": "review", "match": "review"}.get(step, step)

        step_map = {
            "start":    (_PAGE_PDF,      self._page_pdf),
            "receipts": (_PAGE_RECEIPTS, self._page_receipts),
            "review":   (_PAGE_REVIEW,   self._page_review),
            "export":   (_PAGE_EXPORT,   self._page_export),
            "done":     (_PAGE_DONE,     self._page_done),
        }
        idx, page = step_map.get(step, step_map["start"])
        page.load_session(session)
        self._stack.setCurrentIndex(idx)
        self._status(f"Sitzung fortgesetzt (Schritt: {session.step})")

    def _status(self, msg: str) -> None:
        self._status_bar.showMessage(msg)
