# UwExpenses

Native Python desktop application for monthly expense processing.  
Processes Revolut bank statements (PDF or CSV) against receipt images and generates an Excel expense report plus a receipt PDF.

---

## Requirements

- Python 3.11+
- Windows / macOS / Linux

## Installation

```bash
# 1. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate        # Windows
# or: source .venv/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python main.py
```

## Workflow

1. **Select folder** – choose the month folder containing the Revolut export and receipt images.
2. **Set date range** – pick the start and end date for the expense period.
3. **Import statement** – the app auto-detects the Revolut CSV or PDF in the folder.  
   *CSV export from Revolut is preferred* (more reliable parsing).  
   To export from Revolut: Account → Statement → Custom period → CSV.
4. **Classify transactions** – mark each transaction as Business / Private / Review.
5. **Index receipts** – the app reads all JPG/PNG files, extracts EXIF dates, and creates sorted working copies.
6. **Match receipts** – for each business expense, select the matching receipt image.
7. **Export** – the app generates:
   - `output_YYYY-MM/02_excel/Spesen_YYYY-MM.xlsx` – expense report
   - `output_YYYY-MM/03_receipt_pdf/Belege_YYYY-MM.pdf` – two receipts per page

Progress is saved automatically after every decision. You can close and resume at any time.

## Excel columns

| Column | Content |
|---|---|
| Datum | Transaction date |
| Beleg | Receipt number (R001, R002 ...) |
| Ort | Merchant / description |
| Begründung | Business justification |
| Wrg | Currency |
| Betrag in FW | Foreign currency amount |
| Betrag in CHF | CHF amount |

## Output folder structure

```
output_YYYY-MM/
  01_working/     Working copies of receipt images (renamed/sorted)
  02_excel/       Expense Excel file
  03_receipt_pdf/ Final receipt PDF (2 per page)
  04_logs/        Log files (future use)
```

## Supported Revolut export formats

| Format | Notes |
|---|---|
| CSV (preferred) | Export via Revolut app: Account → Statement → CSV |
| PDF | Revolut "Individueller Auszug" (German) |

## Folder layout expected

```
month_folder/
  Revolut_statement.csv   (or .pdf)
  receipt1.jpg
  receipt2.jpg
  receipt3.png
  ...
  (optional) template.xlsx   # placed in working copies if detected
```

## Dependencies

| Package | Purpose |
|---|---|
| PySide6 | Desktop GUI |
| pdfplumber | Revolut PDF parsing |
| openpyxl | Excel output |
| Pillow | Image processing / EXIF |
| reportlab | Receipt PDF generation |
| python-dateutil | Date parsing |
