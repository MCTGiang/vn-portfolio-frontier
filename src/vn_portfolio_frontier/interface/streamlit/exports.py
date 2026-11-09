"""F2 Rebalance Result - Export PDF + Excel.

Deploy: src/vn_portfolio_frontier/interface/streamlit/exports.py

Integration via buttons in Tab "Chi tiết kỹ thuật" of _render_results.

Dependencies: reportlab, openpyxl
"""

from __future__ import annotations

import statistics
from datetime import datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ============================================================
# Register Vietnamese-capable font
# ============================================================
FONT_NAME = "DejaVuSans"
try:
    for p in [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(p).exists():
            pdfmetrics.registerFont(TTFont(FONT_NAME, p))
            break
except Exception:
    FONT_NAME = "Helvetica"


# ============================================================
# Adapter: Convert result/config/record/decisions to export dicts
# ============================================================
def result_to_export_dicts(result, config, record, decisions):
    """Extract run_metadata, kpis, orders, decisions_list, daily_values.

    Args:
        result: SimulateResult (run_id, trading_days, daily_values_*, rf_annual_pct)
        config: dict from sidebar (target_weights, initial_capital, backtest_*, strategy_*, cost_*)
        record: RunRecord (sharpe_*, total_cost_bps, turnover_avg_pct, n_rebalances)
        decisions: list[RebalanceDecision]

    Returns: 5-tuple (run_metadata, kpis, orders, decisions_list, daily_values)
    """
    # Compute derived KPIs from daily_values_after_cost
    daily_after = [float(v) for v in result.daily_values_after_cost]
    n_days = len(daily_after)
    years = n_days / 252 if n_days > 0 else 1

    if n_days >= 2 and daily_after[0] > 0:
        total_return = (daily_after[-1] / daily_after[0] - 1) * 100
        cagr = ((daily_after[-1] / daily_after[0]) ** (1 / years) - 1) * 100
    else:
        total_return = 0.0
        cagr = 0.0

    # Max drawdown
    peak = daily_after[0] if daily_after else 0
    max_dd = 0.0
    for v in daily_after:
        peak = max(peak, v)
        if peak > 0:
            dd = (v / peak - 1) * 100
            max_dd = min(max_dd, dd)

    # Volatility annualized
    daily_returns = [
        (daily_after[i] / daily_after[i - 1] - 1)
        for i in range(1, n_days)
        if daily_after[i - 1] > 0
    ]
    vol_annual = (
        statistics.stdev(daily_returns) * (252**0.5) * 100 if len(daily_returns) > 1 else 0.0
    )

    run_metadata = {
        "run_id": str(result.run_id),
        "tickers": list(config.get("target_weights", {}).keys()),
        "backtest_start": config.get("backtest_start"),
        "backtest_end": config.get("backtest_end"),
        "initial_capital": config.get("initial_capital"),
        "strategy_name": config.get("strategy_name"),
        "brokerage_pct": config.get("brokerage_pct"),
        "tax_pct": config.get("tax_pct"),
        "market_impact_bps": config.get("market_impact_bps"),
        "rf_source": config.get("rf_source"),
        "rf_annual_pct": float(result.rf_annual_pct),
    }

    kpis = {
        "total_return_pct": round(total_return, 2),
        "cagr_annual_pct": round(cagr, 2),
        "max_drawdown_pct": round(abs(max_dd), 2),
        "volatility_annual_pct": round(vol_annual, 2),
        "sharpe_after_cost": float(record.sharpe_after_cost) if record.sharpe_after_cost else 0.0,
        "n_rebalances": record.n_rebalances or 0,
        "turnover_avg_pct": float(record.turnover_avg_pct) if record.turnover_avg_pct else 0.0,
        "total_cost_bps": record.total_cost_bps or 0,
    }

    decisions_list = [
        {
            "trigger_date": str(getattr(d, "trigger_date", "")),
            "reason": getattr(d, "reason", ""),
            "n_orders": len(getattr(d, "orders", []) or []),
            "total_cost_vnd": float(getattr(d, "total_cost_vnd", 0) or 0),
            "orders_json": str(getattr(d, "orders", "") or ""),
        }
        for d in (decisions or [])
    ]

    daily_values = []
    for i, (d, v) in enumerate(
        zip(result.trading_days, result.daily_values_after_cost, strict=True)
    ):
        v_f = float(v)
        prev_f = float(result.daily_values_after_cost[i - 1]) if i > 0 else v_f
        daily_ret = ((v_f / prev_f) - 1) * 100 if i > 0 and prev_f > 0 else 0.0
        cum_ret = ((v_f / daily_after[0]) - 1) * 100 if daily_after[0] > 0 else 0.0
        daily_values.append(
            {
                "date": str(d),
                "value": v_f,
                "daily_return_pct": round(daily_ret, 4),
                "cumulative_return_pct": round(cum_ret, 4),
            }
        )

    orders: list[dict] = []  # Orders subsumed into decisions.orders_json

    return run_metadata, kpis, orders, decisions_list, daily_values


# ============================================================
# PDF export
# ============================================================
def export_pdf(
    run_metadata: dict,
    kpis: dict,
    orders: list[dict],
    decisions: list[dict],
) -> bytes:
    """Generate PDF report for 1 rebalance run."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Rebalance Report {run_metadata.get('run_id', 'N/A')[:8]}",
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="VNHeading1",
            fontName=FONT_NAME,
            fontSize=18,
            textColor=colors.HexColor("#CE1628"),
            spaceAfter=12,
            alignment=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="VNHeading2",
            fontName=FONT_NAME,
            fontSize=14,
            textColor=colors.HexColor("#231F20"),
            spaceAfter=8,
            alignment=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="VNBody",
            fontName=FONT_NAME,
            fontSize=11,
            textColor=colors.black,
            spaceAfter=6,
            leading=14,
        )
    )

    story = []

    # Title
    story.append(Paragraph("Bao cao Rebalance Simulator - Project 2", styles["VNHeading1"]))
    story.append(
        Paragraph(
            f"Run ID: {run_metadata.get('run_id', 'N/A')[:12]}... "
            f"| Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            styles["VNBody"],
        )
    )
    story.append(Spacer(1, 0.5 * cm))

    # Section 1: Configuration
    story.append(Paragraph("1. Cau hinh", styles["VNHeading2"]))
    config_data = [
        ["Truong", "Gia tri"],
        ["Danh muc", ", ".join(run_metadata.get("tickers", []))],
        ["Giai doan", f"{run_metadata.get('backtest_start')} - {run_metadata.get('backtest_end')}"],
        ["Von ban dau", f"{float(run_metadata.get('initial_capital', 0)):,.0f} VND"],
        ["Chien luoc", run_metadata.get("strategy_name", "N/A")],
        ["Phi moi gioi", f"{float(run_metadata.get('brokerage_pct', 0))*100:.4f}%"],
        ["Thue TNCN", f"{float(run_metadata.get('tax_pct', 0))*100:.4f}%"],
        ["Market impact", f"{run_metadata.get('market_impact_bps', 0)} bps"],
        ["Rf source", run_metadata.get("rf_source", "N/A")],
        ["Rf annual", f"{run_metadata.get('rf_annual_pct', 0):.2f}%"],
    ]
    t = Table(config_data, colWidths=[6 * cm, 10 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#CE1628")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))

    # Section 2: KPIs
    story.append(Paragraph("2. Ket qua KPIs", styles["VNHeading2"]))
    kpi_data = [
        ["Chi so", "Gia tri", "Don vi"],
        ["Loi suat ky cuoi", f"{kpis.get('total_return_pct', 0):.2f}", "%"],
        ["CAGR", f"{kpis.get('cagr_annual_pct', 0):.2f}", "%/nam"],
        ["Max Drawdown", f"{kpis.get('max_drawdown_pct', 0):.2f}", "%"],
        ["Volatility", f"{kpis.get('volatility_annual_pct', 0):.2f}", "%/nam"],
        ["Sharpe (after cost)", f"{kpis.get('sharpe_after_cost', 0):.4f}", ""],
        ["So lan rebalance", str(kpis.get("n_rebalances", 0)), "lan"],
        ["Turnover trung binh", f"{kpis.get('turnover_avg_pct', 0):.2f}", "%/nam"],
        ["Tong chi phi", str(kpis.get("total_cost_bps", 0)), "bps"],
    ]
    t2 = Table(kpi_data, colWidths=[6 * cm, 5 * cm, 5 * cm])
    t2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#CE1628")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(t2)
    story.append(Spacer(1, 0.5 * cm))

    # Section 3: Decisions summary (limit 20 for PDF readability)
    story.append(Paragraph("3. Nhat ky quyet dinh (toi da 20 moi nhat)", styles["VNHeading2"]))
    if decisions:
        dec_data = [["Ngay", "Ly do", "N orders", "Chi phi (VND)"]]
        for d in decisions[:20]:
            dec_data.append(
                [
                    d.get("trigger_date", ""),
                    d.get("reason", "")[:30],
                    str(d.get("n_orders", 0)),
                    f"{d.get('total_cost_vnd', 0):,.0f}",
                ]
            )
        t3 = Table(dec_data, colWidths=[3 * cm, 6 * cm, 3 * cm, 4 * cm])
        t3.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#CE1628")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        story.append(t3)
    else:
        story.append(Paragraph("Khong co quyet dinh rebalance.", styles["VNBody"]))

    story.append(Spacer(1, 0.5 * cm))
    story.append(
        Paragraph(
            "<i>Bao cao sinh tu Rebalance Simulator - Project 2. Giao dien web cho "
            "chi tiet day du.</i>",
            styles["VNBody"],
        )
    )

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ============================================================
# Excel export
# ============================================================
def export_excel(
    run_metadata: dict,
    kpis: dict,
    orders: list[dict],
    decisions: list[dict],
    daily_values: list[dict],
) -> bytes:
    """Generate Excel report with 4 sheets."""
    buf = BytesIO()
    wb = Workbook()

    # Sheet 1 - Config
    ws1 = wb.active
    ws1.title = "Config"
    ws1["A1"] = "Rebalance Simulator - Configuration"
    ws1["A1"].font = Font(bold=True, size=14, color="CE1628")
    ws1["A2"] = f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    config_rows = [
        ("Run ID", run_metadata.get("run_id", "N/A")),
        ("Universe", ", ".join(run_metadata.get("tickers", []))),
        ("Backtest start", str(run_metadata.get("backtest_start"))),
        ("Backtest end", str(run_metadata.get("backtest_end"))),
        ("Initial capital (VND)", float(run_metadata.get("initial_capital", 0))),
        ("Strategy", run_metadata.get("strategy_name", "N/A")),
        ("Brokerage %", float(run_metadata.get("brokerage_pct", 0)) * 100),
        ("Tax % (seller only)", float(run_metadata.get("tax_pct", 0.001)) * 100),
        ("Market impact (bps)", run_metadata.get("market_impact_bps", 0)),
        ("Rf source", run_metadata.get("rf_source", "N/A")),
        ("Rf annual %", float(run_metadata.get("rf_annual_pct", 0))),
    ]
    for i, (k, v) in enumerate(config_rows, start=4):
        ws1.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws1.cell(row=i, column=2, value=v)
    for col_letter in ["A", "B"]:
        ws1.column_dimensions[col_letter].width = 30

    # Sheet 2 - KPIs
    ws2 = wb.create_sheet("KPIs")
    ws2["A1"] = "Ket qua KPIs"
    ws2["A1"].font = Font(bold=True, size=14, color="CE1628")
    kpi_rows = [
        ("Chi so", "Gia tri", "Don vi"),
        ("Loi suat ky cuoi", kpis.get("total_return_pct", 0), "%"),
        ("CAGR", kpis.get("cagr_annual_pct", 0), "%/nam"),
        ("Max Drawdown", kpis.get("max_drawdown_pct", 0), "%"),
        ("Volatility", kpis.get("volatility_annual_pct", 0), "%/nam"),
        ("Sharpe (after cost)", kpis.get("sharpe_after_cost", 0), ""),
        ("So lan rebalance", kpis.get("n_rebalances", 0), "lan"),
        ("Turnover trung binh", kpis.get("turnover_avg_pct", 0), "%/nam"),
        ("Chi phi tong", kpis.get("total_cost_bps", 0), "bps"),
    ]
    for i, row in enumerate(kpi_rows, start=3):
        for j, val in enumerate(row, start=1):
            cell = ws2.cell(row=i, column=j, value=val)
            if i == 3:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="CE1628")
    for col_letter, w in [("A", 30), ("B", 15), ("C", 10)]:
        ws2.column_dimensions[col_letter].width = w

    # Sheet 3 - Decisions
    ws3 = wb.create_sheet("Decisions")
    ws3["A1"] = "Nhat ky quyet dinh rebalance"
    ws3["A1"].font = Font(bold=True, size=14, color="CE1628")
    headers = ["Date", "Reason", "N orders", "Total cost (VND)", "Orders JSON"]
    for j, h in enumerate(headers, start=1):
        cell = ws3.cell(row=3, column=j, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="CE1628")
    for i, d in enumerate(decisions, start=4):
        ws3.cell(row=i, column=1, value=str(d.get("trigger_date", "")))
        ws3.cell(row=i, column=2, value=d.get("reason", ""))
        ws3.cell(row=i, column=3, value=d.get("n_orders", 0))
        ws3.cell(row=i, column=4, value=float(d.get("total_cost_vnd", 0)))
        ws3.cell(row=i, column=5, value=str(d.get("orders_json", "")))
    for col_letter, w in [("A", 12), ("B", 15), ("C", 10), ("D", 18), ("E", 60)]:
        ws3.column_dimensions[col_letter].width = w

    # Sheet 4 - Daily values
    ws4 = wb.create_sheet("DailyValues")
    ws4["A1"] = "Equity curve daily"
    ws4["A1"].font = Font(bold=True, size=14, color="CE1628")
    headers = [
        "Date",
        "Portfolio value (VND)",
        "Daily return (%)",
        "Cumulative return (%)",
    ]
    for j, h in enumerate(headers, start=1):
        cell = ws4.cell(row=3, column=j, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="CE1628")
    for i, dv in enumerate(daily_values, start=4):
        ws4.cell(row=i, column=1, value=str(dv.get("date", "")))
        ws4.cell(row=i, column=2, value=float(dv.get("value", 0)))
        ws4.cell(row=i, column=3, value=float(dv.get("daily_return_pct", 0)))
        ws4.cell(row=i, column=4, value=float(dv.get("cumulative_return_pct", 0)))
    for col_letter, w in [("A", 12), ("B", 20), ("C", 15), ("D", 20)]:
        ws4.column_dimensions[col_letter].width = w

    wb.save(buf)
    buf.seek(0)
    return buf.read()
