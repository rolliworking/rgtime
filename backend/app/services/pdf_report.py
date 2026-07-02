"""PDF pay-period report generation."""

from __future__ import annotations

import io
from typing import Any

from fpdf import FPDF


class PayPeriodPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 8, "RG Time - Pay Period Report", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)


def _table_section(pdf: FPDF, title: str, rows: list[dict[str, Any]], period_label: str) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, f"{title} ({len(rows)} staff) - {period_label}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 7)
    headers = [
        "Name",
        "Days",
        "Hours",
        "Qual8h",
        "PTO+",
        "PTO-",
        "Bal",
        "Late",
        "Wk1",
        "Wk2",
        "Absences",
    ]
    col_w = [28, 10, 12, 12, 12, 12, 12, 10, 12, 12, 38]
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 5, h, border=1)
    pdf.ln()
    for row in rows:
        abs_str = ", ".join(f"{k}:{v}" for k, v in row.get("absences_by_reason", {}).items()) or "-"
        vals = [
            row["name"][:18],
            str(row["days_worked"]),
            row["total_hours"],
            str(row["qualifying_days"]),
            row["pto_earned"],
            row["pto_used"],
            row["pto_balance"],
            str(row["late_arrivals"]),
            row["week1_hours"],
            row["week2_hours"],
            abs_str[:40],
        ]
        for i, v in enumerate(vals):
            pdf.cell(col_w[i], 5, v, border=1)
        pdf.ln()
    pdf.ln(4)


def render_time_card_pdf(summary: dict[str, Any], days: list[dict[str, Any]]) -> bytes:
    pdf = PayPeriodPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, f"Time card: {summary['name']} ({summary['staff_code']})", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(
        0,
        5,
        f"Hours {summary['total_hours']} | Qualifying {summary['qualifying_days']} | "
        f"Wk1 {summary['week1_hours']} Wk2 {summary['week2_hours']}",
        ln=True,
    )
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(22, 5, "Date", border=1)
    pdf.cell(14, 5, "Hours", border=1)
    pdf.cell(80, 5, "Events / absence", border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 7)
    for day in days:
        ev = ", ".join(f"{e['event_type']}@{e['occurred_at'][11:16]}" for e in day.get("events", []))
        ab = day.get("absence")
        note = ev or (f"Absence: {ab['reason_name']}" if ab else "-")
        pdf.cell(22, 5, day["work_date"], border=1)
        pdf.cell(14, 5, day["hours_worked"], border=1)
        pdf.cell(80, 5, note[:70], border=1)
        pdf.ln()
    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return out.encode("latin-1")


def render_pay_period_pdf(report: dict[str, Any]) -> bytes:
    pdf = PayPeriodPDF()
    pdf.add_page()
    label = f"{report['pay_period_start']} - {report['pay_period_end']}"
    _table_section(pdf, "FLAGGED", report.get("flagged", []), label)
    if pdf.get_y() > 240:
        pdf.add_page()
    _table_section(pdf, "CLEAN", report.get("clean", []), label)
    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return out.encode("latin-1")
