"""
Create the final receipt PDF.

Layout: A4 portrait, two receipts per page.
  - Each receipt cell has a label header (R001, date, merchant, amount)
    printed ABOVE the image – never stamped on it.
  - If no receipt: a grey placeholder block.
"""
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
LABEL_H = 12 * mm
GAP = 6 * mm

# Each receipt slot occupies half the page height minus margins
SLOT_H = (PAGE_H - 2 * MARGIN - GAP) / 2
SLOT_W = PAGE_W - 2 * MARGIN


def create_receipt_pdf(
    output_path: Path,
    working_dir: Path,
    business_transactions: List[Dict],
    receipt_numbers: Dict[str, str],
    matches: Dict[str, str],
    receipts: List[Dict],
    justifications: Dict[str, str],
) -> List[str]:
    """
    Generate the two-receipts-per-page PDF.

    Returns a list of warning strings.
    """
    warnings: List[str] = []

    # Build ordered list of (tx, receipt_number, receipt_dict_or_None)
    receipt_map = {r["working_filename"]: r for r in receipts}

    # Sort by receipt number
    ordered = sorted(
        [tx for tx in business_transactions if tx["id"] in receipt_numbers],
        key=lambda tx: receipt_numbers.get(tx["id"], "R999"),
    )

    c = Canvas(str(output_path), pagesize=A4)

    slots: List[Dict] = []
    for tx in ordered:
        r_num = receipt_numbers.get(tx["id"], "")
        matched_file = matches.get(tx["id"], "")
        receipt = receipt_map.get(matched_file)

        image_path: Optional[Path] = None
        if receipt:
            candidate = working_dir / receipt["working_filename"]
            if candidate.exists():
                image_path = candidate
            else:
                warnings.append(
                    f"{r_num}: working file not found – {receipt['working_filename']}"
                )
        else:
            warnings.append(f"{r_num}: no receipt assigned.")

        slots.append({
            "num": r_num,
            "date": tx.get("date", ""),
            "desc": tx.get("description", ""),
            "amount": tx.get("amount", ""),
            "currency": tx.get("currency", "CHF"),
            "image_path": image_path,
        })

    # Draw two slots per page
    for i in range(0, len(slots), 2):
        _draw_page(c, slots[i], slots[i + 1] if i + 1 < len(slots) else None)
        c.showPage()

    if slots:
        c.save()
    else:
        # Empty PDF
        c.drawString(MARGIN, PAGE_H / 2, "Keine Belege vorhanden.")
        c.save()
        warnings.append("No business expenses with receipts; PDF is empty.")

    return warnings


def _draw_page(c: Canvas, top_slot: Dict, bottom_slot: Optional[Dict]) -> None:
    _draw_slot(c, top_slot, y_top=PAGE_H - MARGIN)
    if bottom_slot:
        _draw_slot(c, bottom_slot, y_top=PAGE_H - MARGIN - SLOT_H - GAP)


def _draw_slot(c: Canvas, slot: Dict, y_top: float) -> None:
    x = MARGIN
    w = SLOT_W
    h = SLOT_H

    # Outer border
    c.setStrokeColor(colors.HexColor("#1F4E79"))
    c.setLineWidth(0.5)
    c.rect(x, y_top - h, w, h)

    # Label bar
    c.setFillColor(colors.HexColor("#1F4E79"))
    c.rect(x, y_top - LABEL_H, w, LABEL_H, fill=1, stroke=0)

    # Label text
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    label_parts = [slot["num"]]
    if slot["date"]:
        label_parts.append(slot["date"])
    if slot["desc"]:
        label_parts.append(slot["desc"][:40])
    if slot["amount"]:
        label_parts.append(f"{abs(float(slot['amount'])):.2f} {slot['currency']}")
    label_text = "   |   ".join(label_parts)
    c.drawString(x + 3 * mm, y_top - LABEL_H + 3 * mm, label_text)

    # Image area
    img_area_top = y_top - LABEL_H
    img_area_h = h - LABEL_H
    img_x = x + 2 * mm
    img_y = img_area_top - img_area_h + 2 * mm
    img_w = w - 4 * mm
    img_h = img_area_h - 4 * mm

    if slot["image_path"]:
        _draw_image(c, slot["image_path"], img_x, img_y, img_w, img_h)
    else:
        _draw_placeholder(c, slot, img_x, img_y, img_w, img_h)


def _draw_image(
    c: Canvas, path: Path,
    x: float, y: float, max_w: float, max_h: float,
) -> None:
    try:
        with PILImage.open(str(path)) as img:
            iw, ih = img.size
        aspect = iw / ih
        if max_w / aspect <= max_h:
            draw_w = max_w
            draw_h = max_w / aspect
        else:
            draw_h = max_h
            draw_w = max_h * aspect

        # Center in slot
        cx = x + (max_w - draw_w) / 2
        cy = y + (max_h - draw_h) / 2
        c.drawImage(str(path), cx, cy, width=draw_w, height=draw_h,
                    preserveAspectRatio=True)
    except Exception as exc:
        _draw_error(c, f"Bild konnte nicht geladen werden:\n{exc}", x, y, max_w, max_h)


def _draw_placeholder(
    c: Canvas, slot: Dict,
    x: float, y: float, w: float, h: float,
) -> None:
    c.setFillColor(colors.HexColor("#F0F0F0"))
    c.setStrokeColor(colors.HexColor("#AAAAAA"))
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#666666"))
    c.setFont("Helvetica", 11)
    text = f"{slot['num']} – Kein Beleg vorhanden / Needs review"
    c.drawCentredString(x + w / 2, y + h / 2, text)


def _draw_error(
    c: Canvas, msg: str,
    x: float, y: float, w: float, h: float,
) -> None:
    c.setFillColor(colors.HexColor("#FFF0F0"))
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(colors.red)
    c.setFont("Helvetica", 9)
    c.drawCentredString(x + w / 2, y + h / 2, msg)
