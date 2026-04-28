"""
Main application window with QStackedWidget page navigation.

Pages (in order):
  0  StartPage          – folder + date selection
  1  PdfParsePage       – parse Revolut PDF or CSV
  2  TransactionReview  – classify each transaction
  3  ReceiptIndexPage   – index receipt images
  4  ReceiptMatching    – match receipts to transactions
  5  ExportPage         – generate Excel + PDF
  6  DonePage           – success screen
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QScrollArea, QStackedWidget, QStatusBar, QWidget,
)

import core.storage as storage
from gui.start_page import StartPage
from gui.pdf_parse_page import PdfParsePage
from gui.transaction_review import TransactionReviewPage
from gui.receipt_index_page import ReceiptIndexPage
from gui.receipt_matching import ReceiptMatchingPage
from gui.export_page import ExportPage
from gui.done_page import DonePage

_PAGE_START = 0
_PAGE_PDF = 1
_PAGE_CLASSIFY = 2
_PAGE_RECEIPTS = 3
_PAGE_MATCH = 4
_PAGE_EXPORT = 5
_PAGE_DONE = 6


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
        # Persistent version label on the right of the status bar
        version_lbl = QLabel(f" v{version} " if version else "")
        version_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self._status_bar.addPermanentWidget(version_lbl)
        self.setStatusBar(self._status_bar)

    @staticmethod
    def _scrolled(page: QWidget) -> QScrollArea:
        """Wrap a page in a frameless, width-resizable scroll area."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sa.setWidget(page)
        return sa

    def _setup_pages(self) -> None:
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._page_start = StartPage(on_continue=self._go_pdf)
        self._page_pdf = PdfParsePage(on_continue=self._go_classify)
        self._page_classify = TransactionReviewPage(on_continue=self._go_receipts)
        self._page_receipts = ReceiptIndexPage(on_continue=self._go_match)
        self._page_match = ReceiptMatchingPage(on_continue=self._go_export)
        self._page_export = ExportPage(on_done=self._go_done)
        self._page_done = DonePage(on_restart=self._go_start)

        for page in [
            self._page_start,
            self._page_pdf,
            self._page_classify,
            self._page_receipts,
            self._page_match,
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
        # If session already has transactions, allow skipping ahead
        if session.step in ("classify", "receipts", "match", "export", "done"):
            self._resume_session(session)
            return
        self._page_pdf.load_session(session)
        self._stack.setCurrentIndex(_PAGE_PDF)
        self._status("PDF / CSV einlesen")

    def _go_classify(self, session: storage.SessionData) -> None:
        self._page_classify.load_session(session)
        self._stack.setCurrentIndex(_PAGE_CLASSIFY)
        self._status("Transaktionen klassifizieren")

    def _go_receipts(self, session: storage.SessionData) -> None:
        self._page_receipts.load_session(session)
        self._stack.setCurrentIndex(_PAGE_RECEIPTS)
        self._status("Belege indexieren")

    def _go_match(self, session: storage.SessionData) -> None:
        self._page_match.load_session(session)
        self._stack.setCurrentIndex(_PAGE_MATCH)
        self._status("Belege zuordnen")

    def _go_export(self, session: storage.SessionData) -> None:
        self._page_export.load_session(session)
        self._stack.setCurrentIndex(_PAGE_EXPORT)
        self._status("Export erstellen")

    def _go_done(self, session: storage.SessionData) -> None:
        self._page_done.load_session(session)
        self._stack.setCurrentIndex(_PAGE_DONE)
        self._status("Fertig")

    def _resume_session(self, session: storage.SessionData) -> None:
        """Jump to the correct page for a resumed session."""
        step_map = {
            "start":   (_PAGE_PDF,      self._page_pdf,      "pdf_parse_page"),
            "classify": (_PAGE_CLASSIFY, self._page_classify, "classify"),
            "receipts": (_PAGE_RECEIPTS, self._page_receipts, "receipts"),
            "match":   (_PAGE_MATCH,    self._page_match,    "match"),
            "export":  (_PAGE_EXPORT,   self._page_export,   "export"),
            "done":    (_PAGE_DONE,     self._page_done,     "done"),
        }
        idx, page, _ = step_map.get(session.step, step_map["start"])
        page.load_session(session)
        self._stack.setCurrentIndex(idx)
        self._status(f"Sitzung fortgesetzt (Schritt: {session.step})")

    def _status(self, msg: str) -> None:
        self._status_bar.showMessage(msg)
