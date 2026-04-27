"""Shared stylesheet and palette for UwExpenses."""

APP_STYLE = """
QMainWindow, QDialog {
    background-color: #F5F7FA;
}
QWidget {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #222222;
}
QPushButton {
    background-color: #1F4E79;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 7px 18px;
    font-weight: bold;
    min-width: 90px;
}
QPushButton:hover { background-color: #2D6FAD; }
QPushButton:pressed { background-color: #163759; }
QPushButton:disabled { background-color: #AAAAAA; color: #EEEEEE; }

QPushButton#btn_private {
    background-color: #888888;
}
QPushButton#btn_private:hover { background-color: #666666; }

QPushButton#btn_review {
    background-color: #E07B00;
}
QPushButton#btn_review:hover { background-color: #C06600; }

QPushButton#btn_business {
    background-color: #1A7340;
}
QPushButton#btn_business:hover { background-color: #145E33; }

QLabel#heading {
    font-size: 18px;
    font-weight: bold;
    color: #1F4E79;
}
QLabel#subheading {
    font-size: 14px;
    font-weight: bold;
    color: #333333;
}
QLabel#status {
    font-size: 12px;
    color: #555555;
}
QGroupBox {
    border: 1px solid #C8D4E0;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    background-color: #FFFFFF;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    font-weight: bold;
    color: #1F4E79;
}
QTableWidget {
    border: 1px solid #C8D4E0;
    gridline-color: #E0E8F0;
    background-color: #FFFFFF;
    alternate-background-color: #EEF4FA;
}
QTableWidget::item:selected {
    background-color: #1F4E79;
    color: white;
}
QHeaderView::section {
    background-color: #1F4E79;
    color: white;
    padding: 6px;
    border: none;
    font-weight: bold;
}
QTextEdit, QPlainTextEdit {
    border: 1px solid #C8D4E0;
    border-radius: 4px;
    background-color: #FFFFFF;
    padding: 4px;
}
QLineEdit {
    border: 1px solid #C8D4E0;
    border-radius: 4px;
    padding: 5px 8px;
    background-color: #FFFFFF;
}
QComboBox {
    border: 1px solid #C8D4E0;
    border-radius: 4px;
    padding: 5px 8px;
    background-color: #FFFFFF;
}
QDateEdit {
    border: 1px solid #C8D4E0;
    border-radius: 4px;
    padding: 5px 8px;
    background-color: #FFFFFF;
}
QScrollBar:vertical {
    width: 10px;
    background: #F0F0F0;
}
QScrollBar::handle:vertical {
    background: #AAAAAA;
    border-radius: 5px;
}
QProgressBar {
    border: 1px solid #C8D4E0;
    border-radius: 4px;
    text-align: center;
    background-color: #FFFFFF;
}
QProgressBar::chunk {
    background-color: #1F4E79;
    border-radius: 3px;
}
"""
