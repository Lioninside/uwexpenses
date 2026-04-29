# UwExpenses

Monthly expense processing for Revolut business accounts.

Imports a Revolut bank statement (PDF or CSV/XLSX export), lets you classify
each transaction as business or private while viewing receipt photos side by
side, and produces a formatted Excel expense report plus a two-receipts-per-page
PDF — ready for submission.

---

## Quick Start (Windows)

1. Install [Python 3.10+](https://www.python.org/downloads/) — tick **"Add Python to PATH"**
2. Double-click **`install.bat`** — creates a virtual environment and installs all dependencies
3. Double-click **`start.bat`** — launches the app

---

## Workflow

| Step | Page | What happens |
|------|------|-------------|
| 0 | Start | Choose the month folder and date range; resumes an existing session automatically |
| 1 | Revolut einlesen | Import Revolut PDF or CSV/XLSX; filter by date range |
| 2 | Belege indexieren | Scan the folder for receipt images/PDFs; apply EXIF rotation; optionally run OCR to extract totals |
| 3 | Klassifizieren & zuordnen | Work through every transaction — receipt candidates appear alongside; classify and assign receipt in one click |
| 4 | Export | Assign receipt numbers R001…, generate Excel and receipt PDF |

All decisions are auto-saved to `uw_session.json` after every action.
Closing and re-opening resumes from where you left off.
**Original files are never modified.**

---

## Output

```
output_YYYY-MM/
├── 01_working/      EXIF-corrected copies of all receipt images
├── 02_excel/        Spesen_YYYY-MM.xlsx  (5 sheets)
└── 03_receipt_pdf/  Belege_YYYY-MM.pdf   (2 receipts per A4 page)
```

### Excel sheets

| Sheet | Contents |
|-------|----------|
| Spesenabrechnung | Official expense table: date, receipt number, place, justification, amount |
| Alle Transaktionen | Full Revolut statement for reference |
| Privat Ausgeschlossen | Transactions classified as private |
| Beleg-Zuordnung | Receipt-to-transaction mapping with file names |
| Probleme | Warnings and issues from the export run |

---

## Supported Input Formats

### Revolut statement
- **CSV/XLSX export** (preferred) — Revolut exports a `.csv` that is actually an XLSX;
  the app unwraps it automatically and fixes double-encoded German umlauts.
  Export via Revolut app: *Account → Statement → Custom period → CSV*
- **PDF statement** — parsed with pdfplumber; supports the German Revolut column layout

### Receipts
Accepted file types: **JPEG, PNG, PDF**

EXIF orientation is applied when creating working copies so sideways phone
photos are straightened automatically.

#### Filename date recognition (priority order)
1. **Adobe Scan**: `28-04-2026-17h45min.pdf`
2. **Android / Samsung**: `20260421_180629.jpg` or `20260421-180629.jpg`
3. **Chrome screenshot**: `Screenshot_20260323-231614_Chrome.jpg`
4. **ISO format**: `2026-04-21_180629.jpg`
5. **EXIF** DateTimeOriginal / DateTime
6. **File modification time** — fallback; a warning is shown

---

## Receipt Matching

Candidates are ranked by a combined score so the best match floats to the top:

| Signal | Points |
|--------|--------|
| Same day as transaction | 7 |
| 1 day apart | 6 … 1 |
| > 7 days apart | 0 |
| OCR: exact amount match (± 0.01 CHF) | +10 |
| OCR: close amount match (± 0.50 CHF) | +3 |

All receipts are always shown — nothing is hidden by a cap.
Already-matched receipts appear in orange with a `!USED` prefix.

---

## Optional Features

### PDF receipt preview
Requires [poppler](https://github.com/oschwartz10612/poppler-windows/releases)
(extract, add `bin/` to PATH) and:
```
.venv\Scripts\pip install pdf2image
```

### OCR amount extraction
Reads the total from each receipt during Step 2 for better matching in Step 3.

**easyocr** — pure Python, no system binaries needed (~1.5 GB model on first use):
```
.venv\Scripts\pip install easyocr
```

**pytesseract** — lighter; requires [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki):
```
.venv\Scripts\pip install pytesseract
```

If neither is installed the app works without OCR; the checkbox is shown
disabled with installation instructions.

---

## Project Structure

```
uwexpenses/
├── main.py                       Entry point; VERSION constant
├── requirements.txt              Python dependencies
├── install.bat                   One-click setup (Windows)
├── start.bat                     One-click launch (Windows)
│
├── core/
│   ├── constants.py              Shared sentinels: NO_RECEIPT, NEEDS_REVIEW
│   ├── storage.py                Session persistence (JSON, forward-compatible)
│   ├── revolut_parser.py         Revolut PDF statement parser (German layout)
│   ├── csv_parser.py             Revolut CSV/XLSX statement parser
│   ├── receipt_indexer.py        Receipt scanner, EXIF correction, date extraction
│   ├── matcher.py                Combined date + OCR-amount candidate scoring
│   ├── ocr_extractor.py          OCR backends: easyocr / pytesseract / pdfplumber
│   ├── excel_exporter.py         5-sheet Excel report (openpyxl)
│   └── receipt_pdf_exporter.py   2-up receipt PDF (reportlab)
│
└── gui/
    ├── styles.py                 Centralised QSS stylesheet
    ├── main_window.py            QStackedWidget navigation
    ├── start_page.py             Step 0: folder + date selection
    ├── pdf_parse_page.py         Step 1: Revolut import
    ├── receipt_index_page.py     Step 2: receipt indexing (+ optional OCR)
    ├── combined_review_page.py   Step 3: classify + assign receipts
    ├── manual_expense_dialog.py  Dialog: cash / non-Revolut manual expenses
    ├── export_page.py            Step 4: Excel + PDF export
    └── done_page.py              Final success screen
```

---

## Session File

`uw_session.json` is written to the expense folder after every action.
Unknown keys from older or newer versions are silently ignored on load.

---

## Dependencies

| Package | Version | Purpose | Required |
|---------|---------|---------|---------|
| PySide6 | >= 6.5 | Desktop GUI | Yes |
| pdfplumber | >= 0.10 | Revolut PDF + PDF receipt text | Yes |
| openpyxl | >= 3.1 | Excel export | Yes |
| Pillow | >= 10.0 | Image handling, EXIF correction | Yes |
| reportlab | >= 4.0 | Receipt PDF generation | Yes |
| pdf2image | >= 1.16 | PDF receipt preview / rendering | Optional |
| easyocr | >= 1.7 | OCR amount extraction (images) | Optional |
| pytesseract | >= 0.3.10 | OCR amount extraction (alternative) | Optional |

Python **3.10 or newer** required.
