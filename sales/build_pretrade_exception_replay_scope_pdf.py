from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = letter
MARGIN = 32
CONTENT_W = PAGE_W - (2 * MARGIN)

INK = colors.HexColor("#122033")
MUTED = colors.HexColor("#4F6073")
LINE = colors.HexColor("#D8DEE7")
PANEL = colors.HexColor("#F5F7FA")
ACCENT = colors.HexColor("#0F6C5B")
ACCENT_SOFT = colors.HexColor("#DFF3EE")


def wrap_lines(text: str, width: float, font_name: str, font_size: float) -> list[str]:
    return simpleSplit(text, font_name, font_size, width)


def draw_text_block(
    pdf: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    text: str,
    font_name: str,
    font_size: float,
    leading: float,
    color=INK,
) -> float:
    lines = wrap_lines(text, width, font_name, font_size)
    pdf.setFillColor(color)
    pdf.setFont(font_name, font_size)
    cursor_y = y
    for line in lines:
        pdf.drawString(x, cursor_y, line)
        cursor_y -= leading
    return cursor_y


def draw_bullets(
    pdf: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    bullets: list[str],
    font_size: float = 8.6,
    leading: float = 10.2,
) -> float:
    cursor_y = y
    bullet_width = 8
    text_width = width - bullet_width
    for bullet in bullets:
        lines = wrap_lines(bullet, text_width, "Helvetica", font_size)
        first = True
        for line in lines:
            pdf.setFillColor(INK)
            pdf.setFont("Helvetica", font_size)
            if first:
                pdf.drawString(x, cursor_y, u"\u2022")
                pdf.drawString(x + bullet_width, cursor_y, line)
                first = False
            else:
                pdf.drawString(x + bullet_width, cursor_y, line)
            cursor_y -= leading
        cursor_y -= 1.6
    return cursor_y


def draw_section(
    pdf: canvas.Canvas,
    *,
    x: float,
    y_top: float,
    width: float,
    height: float,
    kicker: str,
    title: str,
    bullets: list[str],
) -> None:
    pdf.setStrokeColor(LINE)
    pdf.setFillColor(colors.white)
    pdf.roundRect(x, y_top - height, width, height, 12, stroke=1, fill=1)

    kicker_w = stringWidth(kicker, "Helvetica-Bold", 8.3) + 16
    pdf.setFillColor(ACCENT_SOFT)
    pdf.roundRect(x + 10, y_top - 18, kicker_w, 14, 7, stroke=0, fill=1)
    pdf.setFillColor(ACCENT)
    pdf.setFont("Helvetica-Bold", 8.3)
    pdf.drawString(x + 18, y_top - 13.5, kicker)

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(x + 10, y_top - 34, title)

    draw_bullets(
        pdf,
        x=x + 12,
        y=y_top - 48,
        width=width - 24,
        bullets=bullets,
    )


def build_pdf(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(out_path), pagesize=letter)
    pdf.setTitle("Memla Pre-Trade Exception Replay Pilot")

    left_w = 346
    right_w = CONTENT_W - left_w - 16
    top_y = PAGE_H - MARGIN

    pdf.setFillColor(ACCENT)
    pdf.setFont("Helvetica-Bold", 8.6)
    pdf.drawString(MARGIN, top_y, "MEMLA PILOT SCOPE")

    pdf.setFillColor(INK)
    pdf.setFont("Times-Bold", 21)
    pdf.drawString(MARGIN, top_y - 22, "Pre-Trade Exception Replay Pilot")

    subtitle = (
        "A fixed-fee pilot to replay recent blocked or soft-flagged trade exceptions, "
        "propose compliant next actions, and return audit-ready rationale without changing "
        "your live rule engine."
    )
    draw_text_block(
        pdf,
        x=MARGIN,
        y=top_y - 39,
        width=left_w,
        text=subtitle,
        font_name="Helvetica",
        font_size=10.3,
        leading=12.4,
        color=MUTED,
    )

    scope_x = MARGIN + left_w + 16
    scope_y = top_y - 6
    scope_h = 94
    pdf.setStrokeColor(LINE)
    pdf.setFillColor(colors.HexColor("#F7FBFF"))
    pdf.roundRect(scope_x, scope_y - scope_h, right_w, scope_h, 14, stroke=1, fill=1)

    scope_rows = [
        ("Fee", "$5,000 flat"),
        ("Timeline", "5 business days"),
        ("Volume", "50-100 exceptions"),
        ("Mode", "Offline replay only"),
    ]
    row_y = scope_y - 15
    for idx, (label, value) in enumerate(scope_rows):
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica-Bold", 8.1)
        pdf.drawString(scope_x + 12, row_y, label.upper())
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica-Bold", 10.0)
        value_width = stringWidth(value, "Helvetica-Bold", 10.0)
        pdf.drawString(scope_x + right_w - 12 - value_width, row_y, value)
        if idx < len(scope_rows) - 1:
            pdf.setStrokeColor(colors.HexColor("#E8EDF3"))
            pdf.line(scope_x + 12, row_y - 6, scope_x + right_w - 12, row_y - 6)
        row_y -= 19

    intro_y = top_y - 95
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(1.6)
    pdf.line(MARGIN, intro_y, MARGIN + CONTENT_W, intro_y)
    pdf.setLineWidth(1)
    intro = (
        "Memla runs a verifier-backed remediation loop over historical exceptions. For each row, "
        "it explains the constraint hit, proposes the next compliant action, and records why that "
        "action is safer than a raw block, rewrite, or escalation. This pilot is designed to show "
        "whether your team has a repeatable exception-handling workflow worth productizing."
    )
    intro_end = draw_text_block(
        pdf,
        x=MARGIN,
        y=intro_y - 13,
        width=CONTENT_W,
        text=intro,
        font_name="Helvetica",
        font_size=9.35,
        leading=11.2,
        color=INK,
    )
    pdf.setStrokeColor(LINE)
    pdf.line(MARGIN, intro_end + 3, MARGIN + CONTENT_W, intro_end + 3)

    section_top = intro_end - 10
    col_gap = 14
    col_w = (CONTENT_W - col_gap) / 2
    section_h = 117

    draw_section(
        pdf,
        x=MARGIN,
        y_top=section_top,
        width=col_w,
        height=section_h,
        kicker="Client Provides",
        title="Inputs",
        bullets=[
            "50-100 anonymized blocked or soft-flagged exception rows in CSV or JSONL.",
            "Reject reasons, rule ids, or exception notes from the current control stack.",
            "Short rule reference, threshold sheet, or desk playbook for the covered workflow.",
        ],
    )
    draw_section(
        pdf,
        x=MARGIN + col_w + col_gap,
        y_top=section_top,
        width=col_w,
        height=section_h,
        kicker="We Deliver",
        title="Outputs",
        bullets=[
            "Replay report for every exception with proposed next action.",
            "Suggested remediation, escalation path, or safe block rationale.",
            "Constraint hit summary and audit-ready explanation per row.",
            "Top-line metrics: pass rate, action mix, and exception pattern summary.",
        ],
    )

    second_top = section_top - section_h - 12
    draw_section(
        pdf,
        x=MARGIN,
        y_top=second_top,
        width=col_w,
        height=section_h,
        kicker="Guardrails",
        title="What This Pilot Is Not",
        bullets=[
            "No live trading integration or autonomous order release.",
            "No production threshold changes or rule ownership transfer.",
            "No legal opinion or regulatory certification.",
            "No requirement to send non-anonymized production identifiers.",
        ],
    )
    draw_section(
        pdf,
        x=MARGIN + col_w + col_gap,
        y_top=second_top,
        width=col_w,
        height=section_h,
        kicker="Success Criteria",
        title="What Good Looks Like",
        bullets=[
            "Clear triage of which exceptions should be modified, escalated, or blocked.",
            "Cleaner audit notes than the current manual process.",
            "A concrete list of exception types suitable for shadow-mode automation next.",
            "A go/no-go decision on a larger on-prem pilot.",
        ],
    )

    wide_top = second_top - section_h - 12
    wide_h = 74
    draw_section(
        pdf,
        x=MARGIN,
        y_top=wide_top,
        width=CONTENT_W,
        height=wide_h,
        kicker="Pilot Deliverable Format",
        title="Delivery Package",
        bullets=[
            "One CSV or JSONL output file with row-by-row recommendations.",
            "One PDF summary covering exception categories, remediation patterns, and proposed next phase.",
            "One review call to walk through results, false positives, and the highest-value workflow to automate next.",
        ],
    )

    footer_top = wide_top - wide_h - 12
    note_w = 410
    cta_w = CONTENT_W - note_w - 14
    note = (
        "Scope note: this is a paid replay pilot for a single bounded workflow, intended to evaluate "
        "real exception handling pain before any production integration. If useful, the next phase would "
        "be a shadow-mode adapter against the firm's existing control outputs."
    )
    draw_text_block(
        pdf,
        x=MARGIN,
        y=footer_top,
        width=note_w,
        text=note,
        font_name="Helvetica",
        font_size=8.5,
        leading=10.2,
        color=MUTED,
    )

    cta_x = MARGIN + note_w + 14
    cta_h = 56
    pdf.setStrokeColor(LINE)
    pdf.setFillColor(PANEL)
    pdf.roundRect(cta_x, footer_top - 40, cta_w, cta_h, 12, stroke=1, fill=1)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 10.2)
    pdf.drawString(cta_x + 12, footer_top - 20, "Suggested Next Step")
    cta = "Send a sample export and rule reference set. Memla returns the replay package by Friday for a flat $5,000."
    draw_text_block(
        pdf,
        x=cta_x + 12,
        y=footer_top - 33,
        width=cta_w - 24,
        text=cta,
        font_name="Helvetica",
        font_size=8.8,
        leading=10.2,
        color=MUTED,
    )

    pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    build_pdf(root / "pretrade_exception_replay_scope.pdf")
