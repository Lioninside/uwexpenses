"""
UwExpenses – Monthly expense processing app.
Entry point.
"""
import sys
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from gui.styles import APP_STYLE

VERSION = "0.5.3"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("UwExpenses")
    app.setOrganizationName("STC")
    app.setStyleSheet(APP_STYLE)

    window = MainWindow(version=VERSION)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
