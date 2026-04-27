"""
Create the final receipt PDF.

Layout: A4 portrait, two receipts per page.
  - Label bar ABOVE each receipt (never stamped over the image).
  - Receipt can be a JPG/PNG (embedded as image) or a PDF (first page
    rendered via pdf2image if available, otherwise informative placeholder).
  - Missing receipt: grey placeholder block.
"""
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
LABEL_H = 12 * mm
GAP = 6 * mm
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
    receipt_map = {r["working_filename"]: r for r in receipts}

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
        is_pdf_receipt = False

        if receipt:
            candidate = working_dir / receipt["working_filename"]
            if candidate.exists():
                image_path = candidate
                is_pdf_receipt = receipt.get("is_pdf", False)
            else:
                warnings.append(
                    f"{r_num}: Arbeitsdatei nicht gefunden – "
                    f"{receipt['working_filename']}"
                )
        else:
            warnings.append(f"{r_num}: kein Beleg zugeordnet.")

        slots.append({
            "num": r_num,
            "date": tx.get("date", ""),
            "desc": tx.get("description", ""),
            "amount": tx.get("amount", ""),
            "currency": tx.get("currency", "CHF"),
            "image_path": image_path,
            "is_pdf": is_pdf_receipt,
        })

    for i in range(0, len(slots), 2):
        _draw_page(c, slots[i], slots[i + 1] if i + 1 < len(slots) else None)
        c.showPage()

    if not slots:
        c.drawString(MARGIN, PAGE_H / 2, "Keine Belege vorhanden.")

    c.save()
    return warnings


def _draw_page(c: Canvas, top: Dict, bottom: Optional[Dict]) -> None:
    _draw_slot(c, top, y_top=PAGE_H - MARGIN)
    if bottom:
        _draw_slot(c, bottom, y_top=PAGE_H - MARGIN - SLOT_H - GAP)


def _draw_slot(c: Canvas, slot: Dict, y_top: float) -> None:
    x, w, h = MARGIN, SLOT_W, SLOT_H

    # Outer border
    c.setStrokeColor(colors.HexColor("#1F4E79"))
    c.setLineWidth(0.5)
    c.rect(x, y_top - h, w, h)

    # Label bar
    c.setFillColor(colors.HexColor("#1F4E79"))
    c.rect(x, y_top - LABEL_H, w, LABEL_H, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    parts = [slot["num"]]
    if slot["date"]:
        parts.append(slot["date"])
    if slot["desc"]:
        parts.append(slot["desc"][:40])
    if slot["amount"]:
        try:
            parts.append(f"{abs(float(slot['amount'])):.2f} {slot['currency']}")
        except (ValueError, TypeError):
            pass
    c.drawString(x + 3 * mm, y_top - LABEL_H + 3 * mm, "   |   ".join(parts))

    # Content area
    img_x = x + 2 * mm
    img_y = (y_top - h) + 2 * mm
    img_w = w - 4 * mm
    img_h = h - LABEL_H - 4 * mm

    if slot["image_path"]:
        if slot["is_pdf"]:
            _draw_pdf_receipt(c, slot["image_path"], img_x, img_y, img_w, img_h, slot)
        else:
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
            dw, dh = max_w, max_w / aspect
        else:
            dh, dw = max_h, max_h * aspect
        cx = x + (max_w - dw) / 2
        cy = y + (max_h - dh) / 2
        c.drawImage(str(path), cx, cy, width=dw, height=dh,
                    preserveAspectRatio=True)
    except Exception as exc:
        _draw_error(c, f"Bild konnte nicht geladen werden: {exc}",
                    x, y, max_w, max_h)


def _draw_pdf_receipt(
    c: Canvas, path: Path,
    x: float, y: float, w: float, h: float,
    slot: Dict,
) -> None:
    """
    Try to render the first page of a PDF receipt as an image.
    Falls back to an info block if pdf2image/poppler is unavailable.
    """
    rendered = _try_render_pdf_page(path)
    if rendered:
        _draw_image(c, rendered, x, y, w, h)
        return

    # Informative placeholder
    c.setFillColor(colors.HexColor("#EEF4FA"))
    c.setStrokeColor(colors.HexColor("#1F4E79"))
    c.rect(x, y, w, h, fill=1, stroke=1)

    c.setFillColor(colors.HexColor("#1F4E79"))
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(x + w / 2, y + h * 0.65, "PDF-Beleg")

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#333333"))
    c.drawCentredString(x + w / 2, y + h * 0.50, path.name)
    c.drawCentredString(
        x + w / 2, y + h * 0.38,
        "Original-PDF befindet sich im Ordner 01_working/"
    )

    # Small hint about poppler
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawCentredString(
        x + w / 2, y + h * 0.18,
        "Tipp: poppler + pdf2image installieren fuer PDF-Vorschau"
    )


def _try_render_pdf_page(path: Path) -> Optional[Path]:
    """
    Try to render the first page of a PDF to a temp PNG using pdf2image.
    Returns the temp PNG path, or None if pdf2image/poppler is unavailable.
    """
    try:
        from pdf2image import convert_from_path
        import tempfile

        pages = convert_from_path(str(path), dpi=150, first_page=1, last_page=1)
        if not pages:
            return None
        tmp = Path(tempfile.mktemp(suffix=".png"))
        pages[0].save(str(tmp), "PNG")
        return tmp
    except Exception:
        return None


def _draw_placeholder(
    c: Canvas, slot: Dict,
    x: float, y: float, w: float, h: float,
) -> None:
    c.setFillColor(colors.HexColor("#F0F0F0"))
    c.setStrokeColor(colors.HexColor("#AAAAAA"))
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#666666"))
    c.setFont("Helvetica", 11)
    c.drawCentredString(
        x + w / 2, y + h / 2,
        f"{slot['num']} – Kein Beleg vorhanden / Needs review"
    )


def _draw_error(
    c: Canvas, msg: str,
    x: float, y: float, w: float, h: float,
) -> None:
    c.setFillColor(colors.HexColor("#FFF0F0"))
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(colors.red)
    c.setFont("Helvetica", 9)
    c.drawCentredString(x + w / 2, y + h / 2, msg)
