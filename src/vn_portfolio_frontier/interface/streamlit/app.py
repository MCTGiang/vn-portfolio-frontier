"""Streamlit UI v11 for RebalanceSimulator (ADR-015 interface/streamlit layer).

Day 8 v11: Final polish before ship
===================================
1. Error message with scope context (VN30 explained)
2. Data range + min period recommendation visible to user
3. Date input constrained to actual data range (min 2021-01-04)
4. Sidebar collapse CSS - aggressive position:fixed attempt
5. "Giới hạn" lot size note strengthened for Day 9
"""

from __future__ import annotations

import contextlib as _contextlib_vn  # noqa: E402
import html

# ---------------------------------------------------------------------------
# vnstock Sponsor Silver tier activation (Day 9) - Streamlit entrypoint
# Streamlit Cloud: reads from st.secrets.VNSTOCK_API_KEY (secrets.toml)
# Local dev:       falls back to os.environ.VNSTOCK_API_KEY (.env)
# ---------------------------------------------------------------------------
import os as _os_vn  # noqa: E402
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_vn_api_key = None
with _contextlib_vn.suppress(Exception):
    _vn_api_key = st.secrets.get("VNSTOCK_API_KEY")
_vn_api_key = _vn_api_key or _os_vn.environ.get("VNSTOCK_API_KEY")
if _vn_api_key:
    try:
        import vnstock as _vns_login

        _vns_login.login(_vn_api_key)
    except Exception:
        pass


from vn_portfolio_frontier.application.services import (  # noqa: E402
    SimulateRequest,
)
from vn_portfolio_frontier.infrastructure.factory import AppFactory  # noqa: E402

st.set_page_config(
    page_title="Mô phỏng tái cân bằng danh mục",
    page_icon="chart",
    layout="wide",
)

PROJECT_VERSION = "v11.0-sprint11-day8"
TRADING_DAYS_PER_YEAR = 252

# v11: Data scope constants (from Sprint 10 B.3 VN30 ingest)
DATA_MIN_DATE = date(2021, 1, 4)


@st.cache_data(ttl=3600, show_spinner=False)
def _get_data_max_date() -> date:
    """Fetch max available trade_date from DB (cached 1h).

    Day 11 Cụm 3f fix: Prevents date_input allowing selection beyond data
    availability. Smoke test observed UI showed results for 17-20/10 while
    DB only had data up to 16/10 — silent data integrity bug.
    """
    try:
        from vn_portfolio_frontier.infrastructure.factory import AppFactory

        factory = AppFactory()
        latest = factory.price_repo().get_latest_dates()
        return max(latest.values()) if latest else date.today()
    except Exception:
        # Fallback to today if DB unreachable (dev offline mode)
        return date.today()


def _sharpe_badge(sharpe: float | None) -> str:
    """Return HTML pill badge for Sharpe ratio quality.

    Day 11 Cụm 3f #15: synced with _assess_sharpe (5-tier) + _SEV_CLASS color
    mapping used by result KPI cards, so F1 badge and Simulation KPI tell the
    same story with the same labels (kém/yếu/trung bình/tốt/xuất sắc).

    Thresholds (via _assess_sharpe):
        - < 0:    kém     (red)
        - 0-0.5:  yếu     (yellow)
        - 0.5-1:  trung bình (grey)
        - 1-2:    tốt     (green)
        - >= 2:   xuất sắc (green)
    """
    if sharpe is None:
        return ""
    label = _assess_sharpe(sharpe)
    sev_class = _sev_class(label)
    # Color mapping aligned with _SEV_CLASS → sev-{class}-bg CSS variants
    color_map = {
        "good": ("#D1FAE5", "#065F46"),  # green
        "neutral": ("#E5E7EB", "#374151"),  # grey
        "warning": ("#FEF3C7", "#92400E"),  # yellow
        "bad": ("#FEE2E2", "#991B1B"),  # red
        "plain": ("#F3F4F6", "#6B7280"),  # muted
    }
    bg, fg = color_map.get(sev_class, color_map["plain"])
    return (
        f'<span style="display:inline-block;padding:2px 10px;margin-left:8px;'
        f"border-radius:999px;background:{bg};color:{fg};"
        f'font-size:11px;font-weight:600;vertical-align:middle;">{label}</span>'
    )


@st.cache_data(ttl=86400, show_spinner=False)  # cache 1 day
def _get_vn30_sector_map() -> dict:
    """Returns {ticker: (icb_code_lv2, icb_name_vi)} for all HOSE tickers.

    Day 13 reference enhancement: sector breakdown via vnstock Reference.
    Cached 1 day since ICB classifications rarely change.
    """
    try:
        from vnstock import Reference

        ref = Reference()
        tickers_df = ref.equity.list_by_exchange()
        inds_df = ref.industry.list()
        lv2 = inds_df[inds_df["icb_level"] == 2]
        code_to_name = dict(zip(lv2["icb_code"].astype(str), lv2["icb_name"], strict=False))
        return {
            row["symbol"]: (
                str(row["icb_code_lv2"]),
                code_to_name.get(str(row["icb_code_lv2"]), "Khác"),
            )
            for _, row in tickers_df.iterrows()
        }
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=3600, show_spinner=False)  # cache 1 hour
def _get_upcoming_events(tickers_tuple: tuple, days_ahead: int = 30):
    """Returns upcoming corporate events DataFrame for given tickers.

    Day 13 reference enhancement: events.calendar context widget.
    Cache 1h — events don't change intraday meaningfully.
    """
    try:
        from vnstock import Reference

        ref = Reference()
        today = date.today()
        end = today + timedelta(days=days_ahead)
        cal = ref.events.calendar(start=today.isoformat(), end=end.isoformat())
        if cal is None or len(cal) == 0:
            return None
        filtered = cal[cal["symbol"].isin(tickers_tuple)].copy()
        if len(filtered) == 0:
            return None
        # Sort by ex_right_date ascending (nearest first)
        filtered = filtered.sort_values("ex_right_date", na_position="last")
        return filtered
    except Exception:  # noqa: BLE001
        return None


MIN_RECOMMENDED_YEARS = 2.0


_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0&display=swap');

:root {
  --brand: #146026;
  --tag: #80c433;
  --text: #1F2937;
  --muted: #6B7280;
  --card-bg: #F9FAFB;
  --border: #E5E7EB;
  --up: #16A34A;
  --down: #DC2626;
}

html, body, [class*="st-"], .stMarkdown, .stText {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* P1 ticker chip: lime bg, white text */
span[data-baseweb="tag"] {
    background-color: var(--tag) !important;
    border-radius: 4px !important;
    padding: 1px 8px !important;
}
span[data-baseweb="tag"] span {
    color: #fff !important;
    font-size: 12px !important;
    font-weight: 600 !important;
}

/* P1 KPI tune: 28px bold value, 11px uppercase label */
.kpi-value {
    font-size: 28px !important;
    letter-spacing: -0.5px !important;
}
.kpi-label {
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    color: var(--muted) !important;
}

/* Day 10 Step C: compliance info chip (Lot size + Rf) */
.compliance-chip {
    display: inline-block;
    font-size: 10px;
    color: var(--brand);
    background: #e8f3e8;
    padding: 3px 8px;
    border-radius: 10px;
    border: 1px solid var(--tag);
    margin: 4px 0 2px 0;
}
.block-container { padding-top: 2rem !important; }

/* v11: Aggressive sidebar collapse button pinning - fixed to viewport */
button[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] {
    position: fixed !important;
    top: 0.5rem !important;
    z-index: 999999 !important;
}

/* v11: Scope info caption */
.scope-info {
    font-size: 11px;
    color: #6b7280;
    background: #f3f4f6;
    padding: 6px 10px;
    border-radius: 4px;
    margin-bottom: 8px;
    line-height: 1.4;
}
.period-rec {
    font-size: 11px;
    color: #0369a1;
    background: #e0f2fe;
    padding: 6px 10px;
    border-radius: 4px;
    margin-top: 4px;
    line-height: 1.4;
}

.combined-header h1 {
    font-size: 28px;
    margin: 0 0 2px 0;
    font-weight: 700;
    line-height: 1.1;
}
.combined-header .subtitle {
    font-size: 13px;
    color: #6b7280;
    margin-bottom: 8px;
}

.hero-number { font-size: 42px; font-weight: 700; line-height: 1.1; margin: 0 0 4px 0; }
.hero-delta-pos { font-size: 18px; color: #16a34a; font-weight: 600; margin-bottom: 6px; }
.hero-delta-neg { font-size: 18px; color: #dc2626; font-weight: 600; margin-bottom: 6px; }
.hero-sub { font-size: 13px; color: #6b7280; margin-bottom: 12px; }

.verdict-box {
    padding: 8px 12px;
    border-radius: 6px;
    margin: 6px 0;
    font-size: 14px;
    line-height: 1.4;
}
.verdict-win { background: #ecfdf5; border-left: 4px solid #10b981; }
.verdict-neutral { background: #fefce8; border-left: 4px solid #eab308; }
.verdict-lose { background: #fef2f2; border-left: 4px solid #ef4444; }

.kpi-card {
    padding: 10px 12px;
    border-radius: 8px;
    margin-bottom: 6px;
    min-height: 100px;
    display: flex;
    flex-direction: column;
}
.kpi-label {
    font-size: 11px;
    color: #6b7280;
    margin-bottom: 2px;
    font-weight: 500;
    line-height: 1.3;
    min-height: 28px;
}
.kpi-value { font-size: 24px; font-weight: 700; line-height: 1.2; margin: 2px 0; }
.kpi-severity { font-size: 11px; font-weight: 500; margin-top: 2px; }
.kpi-practical {
    font-size: 11px;
    color: #4b5563;
    margin-top: auto;
    padding-top: 8px;
    border-top: 1px dashed #e5e7eb;
    line-height: 1.4;
}

.sev-good { color: #16a34a; }
.sev-good-bg { background: #ecfdf5; border-left: 3px solid #16a34a; }
.sev-neutral { color: #ca8a04; }
.sev-neutral-bg { background: #fefce8; border-left: 3px solid #eab308; }
.sev-warning { color: #ea580c; }
.sev-warning-bg { background: #fff7ed; border-left: 3px solid #f97316; }
.sev-bad { color: #dc2626; }
.sev-bad-bg { background: #fef2f2; border-left: 3px solid #ef4444; }
.sev-plain { color: #374151; }
.sev-plain-bg { background: #f9fafb; border-left: 3px solid #d1d5db; }

.ticker-chip {
    display: inline-block;
    padding: 3px 10px;
    background: #e0e7ff;
    color: #3730a3;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
    margin-right: 4px;
    margin-bottom: 4px;
}
.ticker-sum-ok {
    display: inline-block;
    padding: 3px 10px;
    font-size: 12px;
    color: #16a34a;
    font-weight: 600;
}
.ticker-sum-bad {
    display: inline-block;
    padding: 3px 10px;
    font-size: 12px;
    color: #dc2626;
    font-weight: 600;
}

.rec-box {
    background: #eff6ff;
    border-left: 4px solid #3b82f6;
    padding: 10px 14px;
    border-radius: 6px;
    margin: 10px 0 4px 0;
    font-size: 14px;
    line-height: 1.5;
}
.rec-header-text { font-weight: 600; margin-bottom: 4px; }

.badge-init {
    display: inline-block; padding: 2px 8px;
    background: #dbeafe; color: #1e40af;
    border-radius: 4px; font-size: 11px; font-weight: 600; letter-spacing: 0.3px;
}
.badge-rebal {
    display: inline-block; padding: 2px 8px;
    background: #fed7aa; color: #9a3412;
    border-radius: 4px; font-size: 11px; font-weight: 600; letter-spacing: 0.3px;
}

.footer-caption { text-align: right; color: #9ca3af; font-size: 11px; margin-top: 24px; }
/* Day 10 Step C: Material Symbols for Streamlit CSS-in-JS (emotion-cache) icons */
.material-symbols-rounded,
.material-symbols-outlined,
.material-icons,
[class*="material-symbols"],
span[translate="no"],
button[data-testid*="Collapse"] span,
button[data-testid*="Icon"] span,
button[data-testid*="Sidebar"] span,
[data-testid*="stIconMaterial"],
[class*="iconContainer"],
[class*="IconContainer"],
.stMarkdown span[class*="e1vmumty"],
[class*="e1vmumty"],
[class*="e1ocqwht"] {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
    font-weight: normal;
    font-style: normal;
    font-size: 24px;
    line-height: 1;
    letter-spacing: normal;
    text-transform: none;
    display: inline-block;
    white-space: nowrap;
    word-wrap: normal;
    direction: ltr;
    -webkit-font-feature-settings: 'liga';
    -webkit-font-smoothing: antialiased;
}

/* Day 10 Step C: compact VI/EN toggle buttons (narrow 32px height) */
button[kind="primary"][data-testid*="lang_"],
button[kind="secondary"][data-testid*="lang_"] {
    min-height: 32px !important;
    padding: 4px 10px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
}

</style>
"""


@st.cache_resource
def get_factory() -> AppFactory:
    """Build AppFactory once per Streamlit session (reused across reruns)."""
    return AppFactory()


TRANSLATIONS = {
    "vi": {
        "page_title": "Mô phỏng tái cân bằng danh mục",
        "page_subtitle": "Công cụ mô phỏng chiến lược tái cân bằng cho nhà đầu tư cá nhân Việt Nam.",
        "lang_label": "Ngôn ngữ",
        "about_header": "ℹ️ Về công cụ này",
        "about_purpose_title": "🎯 Mục đích",
        "about_purpose_body": "Giúp nhà đầu tư kiểm thử chiến lược tái cân bằng danh mục trước khi đưa vốn thật vào thị trường, dựa trên dữ liệu lịch sử của 30 cổ phiếu VN30.",
        "about_value_title": "📚 Giá trị thực tiễn",
        "about_value_list": [
            "Hiểu chiến lược có hiệu quả không trong nhiều giai đoạn thị trường (tăng/giảm/đi ngang)",
            "So sánh với các lựa chọn khác (Mua rồi giữ, gửi tiết kiệm, quỹ mở)",
            "Lượng hóa rủi ro trước: mức sụt giảm tối đa, mức dao động — giúp chuẩn bị tâm lý",
            "Lượng hóa chi phí trước: biết trước phí giao dịch ăn vào lợi nhuận bao nhiêu",
            "**Gợi ý tỷ trọng tối ưu** theo lý thuyết Markowitz (1952) — chọn mức rủi ro mong muốn, hệ thống đề xuất tỷ trọng cân bằng phù hợp",
        ],
        "about_limit_title": "⚠️ Giới hạn (quan trọng để không hiểu nhầm)",
        "about_limit_list": [
            "Dựa trên dữ liệu quá khứ — KHÔNG dự đoán tương lai",
            "Kết quả mô phỏng ≠ kết quả thực tế (còn nhiều yếu tố thực chưa mô phỏng)",
            "Dùng để so sánh TƯƠNG ĐỐI giữa chiến lược, không dự đoán lợi nhuận cụ thể",
            "Chỉ test chiến lược rebalancing (passive) — chưa có cắt lỗ (stop-loss) hoặc thay mã động (dynamic selection); phase sau sẽ bổ sung",
            "Hiện tại cho phép mua lẻ cổ phiếu (fractional/odd shares) — thực tế HSX/HNX yêu cầu lô 100 shares; Day 9 sẽ fix compliance",
            "Khuyến nghị kết hợp với phân tích cơ bản và theo dõi diễn biến thị trường thực",
        ],
        "sidebar_title": "⚙️ Thiết lập mô phỏng",
        "capital_section": "💰 Tiền của tôi",
        "capital_caption": "Nhập số vốn ban đầu bạn muốn dùng cho danh mục (VD: 100 triệu VND)",
        "ticker_section_caption": "Chọn danh mục cổ phiếu và tỷ trọng mong muốn (tối đa 10 mã VN30)",
        "range_section_caption": "Chọn khoảng thời gian lịch sử để kiểm thử chiến lược (dữ liệu từ 04/01/2021)",
        "capital_label": "Vốn ban đầu (triệu VND)",
        "update_prices_btn": "Cập nhật dữ liệu giá",
        "updating_prices": "Đang tải...",
        "update_success": "Đã cập nhật",
        "update_success_fmt": "✓ Đã cập nhật đến {date}",
        "lot_compliance_chip": "Lot: 100 cổ phiếu (HSX từ 04/01/2021)",
        "lot_compliance_tooltip": "Theo QĐ 496/QĐ-SGDHCM: tất cả lệnh HSX phải là bội số của 100 kể từ 04/01/2021",
        "rf_source_label": "Nguồn lãi suất phi rủi ro (Rf)",
        "rf_source_help": "Rf dùng trong công thức Sharpe = (lãi suất portfolio − Rf) / độ lệch chuẩn. Giá trị thực = trung bình (AVG) qua khoảng thời gian backtest đã chọn, không phải giá trị cố định.",
        "rf_vcb_13m": "VCB tiết kiệm 13 tháng (bán lẻ)",
        "rf_vn_bond_1y": "Trái phiếu Chính phủ VN 1 năm (chuẩn học thuật)",
        "rf_sbv_refinance": "Lãi suất tái cấp vốn SBV (chính sách)",
        "rf_zero": "Không điều chỉnh Rf (Perold 1988)",
        "rf_source_caption": "ℹ️ Giá trị thực tế hiển thị trong tab Chi tiết kỹ thuật sau khi chạy mô phỏng",
        "rf_actual_fmt": "Rf thực tế dùng: {value}%/năm (trung bình qua giai đoạn backtest)",
        # ==== F1 Efficient Frontier (Day 11) ====
        "f1_section_header": "📈 Đường biên hiệu quả (F1)",
        "f1_section_intro": "**📌 Workflow F1 (Tùy chọn):**\n\n1. Chọn tối thiểu 2 mã + giai đoạn kiểm thử ở sidebar\n2. Điều chỉnh tham số bên dưới nếu cần (giới hạn 40% + 20 điểm là mặc định tốt)\n3. Nhấn 🔍 **Tính đường biên hiệu quả** → hệ thống tính 20 danh mục tối ưu + 3 danh mục tham chiếu\n4. Trượt thanh **Chọn điểm** để xem từng danh mục (lợi suất/rủi ro/tỷ trọng)\n5. Nhấn ⚡ **Dùng tỷ trọng này cho mô phỏng** → tỷ trọng tự chuyển sang sidebar\n6. Quay lại sidebar nhấn **Chạy mô phỏng** để backtest với tỷ trọng F1\n\n*Bỏ qua F1 → nhập tỷ trọng tay ở sidebar.*",
        "f1_compute_btn": "🔍 Tính đường biên hiệu quả",
        "f1_compute_btn_help": "Dựa trên dữ liệu lịch sử theo giai đoạn kiểm thử + rổ cổ phiếu đã chọn + nguồn Rf",
        "f1_need_min_tickers": "ℹ️ Cần chọn ≥ 2 mã cổ phiếu ở sidebar trước khi tính F1",
        "f1_upper_bound_label": "Giới hạn tỷ trọng tối đa/mã",
        "f1_upper_bound_help": "Mức tối đa cho phép phân bổ vào 1 mã. Mặc định 40% (phổ biến cho nhà đầu tư cá nhân VN)",
        "f1_n_points_label": "Số điểm trên đường biên",
        "f1_n_points_help": "Càng nhiều điểm = đường cong càng mịn. Mặc định 20",
        "f1_computing": "Đang tính đường biên hiệu quả...",
        "f1_computed_ok": "✓ Đã tính xong đường biên {n} điểm từ {days} ngày dữ liệu ({rows} observations)",
        "f1_chart_title": "Đường biên hiệu quả — tối ưu rủi ro vs lợi suất",
        "f1_chart_x_label": "Rủi ro (độ lệch chuẩn %/năm)",
        "f1_chart_y_label": "Lợi suất kỳ vọng (%/năm)",
        "f1_curve_label": "Đường biên",
        "f1_slider_label": "Chọn điểm trên đường biên",
        "f1_slider_help": "Trượt để chọn điểm có tỷ lệ rủi ro/lợi suất mong muốn. Trái = ít rủi ro + lợi suất thấp; phải = rủi ro cao + lợi suất cao",
        "f1_selected_point_header": "📌 Điểm đã chọn",
        "f1_selected_point_metrics": "Lợi suất kỳ vọng: **{ret}%/năm** · Rủi ro: **{vol}%/năm** · Sharpe: **{sharpe}**",
        "f1_ex_ante_caption": "📘 **Số liệu lý thuyết (ex-ante)** — Lợi suất/Sharpe trên là trung bình số học của returns quá khứ. Simulation thực tế có thể khác do rebalancing threshold + chi phí giao dịch + path-dependence. **Rủi ro MAX** (max drawdown) chỉ xuất hiện ở Kết quả mô phỏng, không có ở F1.",
        "f1_weights_table_header": "Tỷ trọng danh mục",
        "f1_apply_btn": "⚡ Dùng tỷ trọng này cho mô phỏng",
        "f1_apply_success": "✓ Đã áp dụng tỷ trọng. Nhấn 'Chạy mô phỏng' để kiểm thử.",
        "f1_ref_portfolios_header": "📊 3 danh mục tham chiếu",
        "f1_ref_min_variance": "Rủi ro tối thiểu",
        "f1_ref_max_sharpe": "Sharpe tối đa",
        "f1_ref_risk_parity": "Cân bằng rủi ro",
        "f1_defense_note": "ℹ️ F1 là ứng dụng của lý thuyết Markowitz (1952). Các điểm trên đường biên tối ưu rủi ro cho mỗi mức lợi suất kỳ vọng. 3 điểm tham chiếu đại diện cho 3 chiến lược phổ biến.",
        "update_failed": "Thất bại",
        "tickers_section": "📊 Danh mục của tôi",
        "ticker_scope_info": "📌 Scope: 30 cổ phiếu VN30 (HOSE) — dữ liệu từ {min_date} đến {max_date}",
        "vn30_roster_info": "📊 Rổ VN30 áp dụng tại thời điểm {snapshot_date} (danh sách thay đổi mỗi quý theo quyết định HOSE)",
        "ticker_chip_empty": "Chưa chọn mã nào",
        # v10: text_input UX
        "ticker_input_label": "Gõ mã rồi Enter để thêm",
        "ticker_input_placeholder": "VD: VCB",
        "ticker_input_submit": "➕ Thêm",
        "ticker_err_not_in_vn30": "Mã '{ticker}' không có trong danh sách VN30 (30 cổ phiếu vốn hóa lớn nhất HOSE)",
        "ticker_err_duplicate": "Mã '{ticker}' đã có trong danh mục",
        "ticker_remove_tooltip": "Xóa {ticker}",
        "weight_label": "Tỷ trọng {ticker} (%)",
        "sum_ok": "Tổng: {sum:.1f}%",
        "sum_bad": "Tổng: {sum:.1f}% (phải = 100%)",
        "equal_weight_btn": "📊 Phân bổ đều",
        "manual_weight_btn": "✏️ Nhập tỷ trọng kỳ vọng",
        "weight_mode_label": "Cách phân bổ tỷ trọng:",
        "weight_mode_equal_help": "Chia đều 1/N cho mỗi mã",
        "weight_mode_manual_help": "Nhập tỷ trọng kỳ vọng từng mã (tổng phải = 100%)",
        "range_section": "📅 Giai đoạn kiểm thử chiến lược",
        "range_period_rec": "💡 Dữ liệu có sẵn từ 04/01/2021. Khuyến nghị khoảng thời gian ≥ {min_years:.0f}-3 năm để kết quả phản ánh được nhiều chu kỳ thị trường",
        "rec_header": "Khuyến nghị",
        "range_too_short": "⚠️ Giai đoạn quá ngắn ({years:.1f} năm) — kết quả có thể không đáng tin cậy. Khuyến nghị ≥ 2 năm.",
        "start_date_label": "Từ ngày",
        "end_date_label": "Đến ngày",
        "range_err": "Ngày bắt đầu phải trước ngày kết thúc",
        "advanced_expander": "⚙️ Nâng cao (chiến lược + chi phí)",
        "strategy_info": "**Chiến lược:** Threshold Band - Hệ thống tự động cân đối lại danh mục khi tỷ trọng bất kỳ mã nào lệch quá ngưỡng cho phép.",
        "band_label": "Ngưỡng lệch cho phép (basis points)",
        "band_help": "Ngưỡng drift (độ lệch tỷ trọng) cho phép trước khi cân đối lại. 500 bps = 5%. Trade-off: ngưỡng rộng (1000 bps) = ít giao dịch + chi phí thấp + drift lớn; ngưỡng hẹp (100 bps) = nhiều giao dịch + chi phí cao + tỷ trọng sát target.",
        "cost_subheader": "Chi phí giao dịch",
        "brokerage_label": "Phí môi giới (%)",
        "brokerage_help": "Phí môi giới CTCK (0.15% là trung bình thị trường VN cho khách cá nhân 2024-2026). Lưu ý: đã bao gồm phí sở (0.03% HSX/HNX); CTCK zero-fee (Pinetree, DNSE) thì tổng = 0.03%.",
        "tax_label": "Thuế TNCN bán (%)",
        "tax_help": "0.10% theo Thông tư 111/2013/TT-BTC (áp dụng khi bán)",
        "market_impact_label": "Tác động thị trường (basis points)",
        "market_impact_help": "Chi phí trượt giá khi vào/ra lệnh (giá thực tế lệch so với giá kỳ vọng). Mặc định 10 bps (0.1%) cho VN30 do thanh khoản cao; mã small-cap thường 20-50 bps.",
        "run_btn": "🚀 Chạy mô phỏng",
        "run_header": "Kết quả mô phỏng",
        "tab_overview": "📊 Tổng quan",
        "tab_journal": "📝 Nhật ký cân đối",
        "tab_technical": "📈 Chi tiết kỹ thuật",
        "hero_sub": "Vốn {initial} trong {years:.1f} năm · Có cân đối",
        "hero_metric_cagr": "Tăng trưởng/năm",
        "hero_metric_mdd": "Rủi ro max",
        "hero_metric_sharpe": "Hiệu quả rủi ro",
        "verdict_vs_bh_win": "✓ **Thắng Mua & Giữ** {delta:+.1f}% ({delta_vnd})",
        "verdict_vs_bh_lose": "✗ **Thua Mua & Giữ** {delta:.1f}% ({delta_vnd}) — thử band hẹp hơn",
        "verdict_vs_bh_neutral": "≈ **Tương đương Mua & Giữ** ({delta:+.1f}%)",
        "verdict_savings_win": "✓ **Cao hơn gửi tiết kiệm** (5-7%/năm) — {cagr:.1f}%/năm",
        "verdict_savings_near": "≈ **Tương đương gửi tiết kiệm** (5-7%/năm) — {cagr:.1f}%/năm",
        "verdict_savings_lose": "✗ **Thấp hơn gửi tiết kiệm** (5-7%/năm) — {cagr:.1f}%/năm",
        # v10: FIXED risk warning showing peak + trough (not initial)
        "risk_warning": "⚠️ **Rủi ro:** Danh mục đã có lúc đạt đỉnh **{peak}** rồi sụt xuống **{trough}** (giảm {mdd:.0f}%)",
        "cost_summary": "💰 **{total_trades} giao dịch, phí tổng {cost_pct}** — {verdict}",
        "savings_caveat": "",
        "cost_verdict_negligible": "không đáng kể",
        "cost_verdict_moderate": "có ảnh hưởng vừa",
        "cost_verdict_significant": "cắn đáng kể",
        "rec_diversify": "Thêm 3-5 mã nữa để giảm rủi ro tập trung (đa dạng hoá)",
        "rec_mdd_high": "Mức sụt giảm {mdd:.0f}% khá cao — chuẩn bị tâm lý giữ danh mục khi thị trường điều chỉnh",
        "rec_vs_bh_lose": "Cân đối lại thua chiến lược mua rồi giữ — thử ngưỡng hẹp hơn (300 bps = 3%)",
        "rec_vs_bh_win": "Cân đối lại tạo thêm {delta:+.1f}% so với mua rồi giữ — hiệu quả",
        "rec_low_return": "Lợi nhuận {cagr:.1f}%/năm chưa tương xứng với rủi ro — cân nhắc đa dạng hoá",
        "rec_frequent_rebalance": "Tần suất {freq:.1f} lần/năm hơi cao — ngưỡng band hẹp dễ dẫn tới giao dịch quá nhiều",
        "chart_title": "Diễn biến giá trị danh mục",
        "chart_strategy": "Chiến lược của bạn",
        "chart_before_cost": "Giả sử không có chi phí giao dịch",
        "chart_buy_and_hold": "Mua rồi giữ (không cân đối)",
        "chart_x_label": "",
        "chart_y_label": "Giá trị (VND)",
        "chart_insufficient": "Chart cần tối thiểu 2 ngày dữ liệu",
        "journal_summary_header": "📋 Tổng kết hoạt động giao dịch",
        "journal_summary_total": "**{total}** giao dịch",
        "journal_summary_init": "**1 lần khởi tạo** ({date})",
        "journal_summary_rebal": "**{n} lần cân đối lại**",
        "journal_summary_cost": "💰 Chi phí tổng: **{total_cost}** ({pct:.3f}% giá trị giao dịch)",
        "journal_summary_init_cost": "• Phí khởi tạo: {cost}",
        "journal_summary_rebal_cost": "• Phí cân đối lại: {cost}",
        "journal_empty": "Chiến lược không kích hoạt lần nào. Thử ngưỡng band hẹp hơn.",
        "journal_date": "📅 {date}",
        "journal_badge_init": "🏁 KHỞI TẠO",
        "journal_badge_rebal": "🔄 CÂN ĐỐI",
        "journal_reason_init": "Mua các mã lần đầu tiên để lập danh mục",
        "journal_reason_band_drift": "Danh mục lệch khỏi tỷ trọng mục tiêu",
        "journal_reason_periodic": "Cân bằng định kỳ",
        "journal_order_buy": "Mua {shares:,} {ticker} (~{amount})",
        "journal_order_sell": "Bán {shares:,} {ticker} (~{amount})",
        "journal_impact_header": "Tác động:",
        "journal_impact_item": "{ticker}: {before:.0f}%→{after:.0f}%",
        "journal_cost_line": "Chi phí: **{total}** ({pct:.3f}%)",
        "journal_cost_detail": "Môi giới {brokerage} + Thuế {tax} + Trượt giá {slippage}",
        "download_csv_btn": "📥 Tải CSV đầy đủ",
        "kpi_tier_a_header": "⭐ Chỉ số quan trọng nhất",
        "kpi_tier_b_header": "📊 Chỉ số bổ sung",
        "kpi_tier_c_header": "🔧 Chỉ số kỹ thuật",
        "kpi_rebalances": "Số giao dịch",
        "kpi_total_cost_pct": "Tổng chi phí",
        "kpi_turnover": "Xoay vòng (%/lần)",
        "kpi_sharpe_before": "Hiệu quả rủi ro (trước phí)",
        "kpi_sharpe_after": "Hiệu quả rủi ro (Sharpe)",
        "kpi_mdd": "Sụt giảm sâu nhất",
        "kpi_vol": "Biến động/năm",
        "kpi_cagr": "Tăng trưởng/năm (CAGR)",
        "kpi_sharpe_help": "Thang: <1 chưa hiệu quả, 1-2 tốt, >2 xuất sắc. (Giả định lãi suất phi rủi ro = 0 - Perold 1988)",
        "kpi_mdd_help": "Thang: <10% thấp, 10-20% trung bình, 20-35% cao, >35% rất cao",
        "kpi_vol_help": "Thang: <15% thấp, 15-25% trung bình, 25-40% cao, >40% rất cao",
        "kpi_cagr_help": "Thang: <5% yếu, 5-10% trung bình, 10-20% tốt, >20% xuất sắc",
        "kpi_cost_help": "Thang: <0.5%/giai đoạn test là thấp, 0.5-1% trung bình, >1% cao",
        "kpi_turnover_help": "% danh mục thay đổi mỗi lần cân đối",
        "kpi_sharpe_before_help": "Sharpe nếu không có phí - để so sánh ảnh hưởng của phí",
        "kpi_rebal_help": "Thang: <2 lần/năm = ít (bị động), 2-4 = trung bình (lý tưởng), 4-8 = nhiều (chủ động), >8 = quá nhiều (overtrading)",
        "kpi_practical_sharpe": "So sánh hiệu quả giữa các chiến lược. Chỉ số VN30 trung bình ~0.3-0.5. Thêm mã đa dạng hoá thường cải thiện.",
        "kpi_practical_mdd": "Mức tiền có thể mất tạm thời tối đa. Trên 30% là báo động — cần chuẩn bị tâm lý và dòng tiền dự phòng.",
        "kpi_practical_vol": "Mức dao động hàng ngày của tài sản. Cao đồng nghĩa cảm xúc bất ổn.",
        "kpi_practical_cagr": "Lãi suất 'kép' hàng năm. So với tiết kiệm (6-7%) và quỹ mở (8-12%) để đánh giá.",
        "kpi_practical_cost": "Phí dưới 0.5%/giai đoạn test là tốt. Quỹ mở VN thu phí 1-2%/năm.",
        "kpi_practical_rebal_tpl": "~{freq:.1f} lần/năm. Mức trung bình long-term holder: 2-4 lần/năm. {verdict}.",
        "kpi_practical_rebal_verdict_high": "Tần suất cao → chiến lược chủ động, chi phí tăng",
        "kpi_practical_rebal_verdict_mid": "Tần suất vừa phải",
        "kpi_practical_rebal_verdict_low": "Tần suất thấp → chiến lược bị động",
        "kpi_practical_turnover_tpl": "{avg:.0f}%/lần × {freq:.1f} lần/năm = ~{total:.0f}%/năm. {verdict}.",
        "kpi_practical_turnover_verdict_high": "Mức active trading cao",
        "kpi_practical_turnover_verdict_mid": "Mức active trading vừa phải",
        "kpi_practical_turnover_verdict_low": "Mức passive, ít giao dịch",
        "kpi_practical_sharpe_before": "So với Sharpe sau phí để biết phí ăn vào bao nhiêu. Chênh lệch lớn = chi phí nặng.",
        "sev_excellent": "xuất sắc",
        "sev_good": "tốt",
        "sev_average": "trung bình",
        "sev_weak": "yếu",
        "sev_poor": "kém",
        "sev_very_high": "rất cao",
        "sev_high": "cao",
        "sev_moderate": "vừa",
        "sev_low": "thấp",
        "sev_negligible": "không đáng kể",
        "sev_na": "N/A",
        "help_header": "📖 Hướng dẫn sử dụng",
        "help_step1": "**Bước 1:** Nhập vốn đầu tư (triệu VND)",
        "help_step2": "**Bước 2:** Gõ mã (VD: VCB) rồi Enter để thêm, nhập tỷ trọng % (tổng = 100%)",
        "help_step3": "**Bước 3:** Chọn giai đoạn test",
        "help_step4": "**Bước 4:** (Tùy chọn) Mở 'Nâng cao' để điều chỉnh ngưỡng + chi phí + chọn nguồn Rf",
        "help_step5": "**Bước 5:** (Tùy chọn) Dùng F1 Đường biên hiệu quả ở khu vực chính → chọn điểm tối ưu Markowitz → ⚡ Dùng tỷ trọng → ▶️ **Chạy mô phỏng ngay** để backtest luôn (không cần quay lại sidebar)",
        "help_step6": "**Bước 6:** Hoặc nếu không dùng F1: nhập tỷ trọng tay ở sidebar → nhấn 'Chạy mô phỏng' ở sidebar",
        "help_step7": "**Bước 7:** Xem Tổng quan — mở các tab Nhật ký cân đối / Chi tiết kỹ thuật nếu cần chi tiết",
        "idle_msg": "Hoàn tất thiết lập ở sidebar bên trái rồi nhấn Chạy mô phỏng",
        "failed_msg": "Mô phỏng thất bại: {error}",
        "footer_meta": "Mô phỏng #{run_id} • {ts}",
        "csv_date": "Ngày",
        "csv_reason": "Lý do",
        "csv_brokerage": "Phí môi giới",
        "csv_slippage": "Trượt giá",
        "csv_tax": "Thuế",
        "csv_cost": "Chi phí",
    },
    "en": {
        "page_title": "Portfolio Rebalance Simulator",
        "page_subtitle": "Rebalance strategy simulator for Vietnamese retail investors.",
        "lang_label": "Language",
        "about_header": "ℹ️ About this tool",
        "about_purpose_title": "🎯 Purpose",
        "about_purpose_body": "Helps investors backtest a rebalancing strategy before deploying real capital, based on VN30 historical data.",
        "about_value_title": "📚 Practical value",
        "about_value_list": [
            "Understand if strategy works across market phases (up/down/sideways)",
            "Compare vs alternatives (Buy & Hold, savings, mutual funds)",
            "Quantify risk upfront: max drawdown, volatility — helps mental preparation",
            "Quantify costs upfront: know how much fees eat into profits",
            "**Optimal weight recommendations** via Markowitz (1952) theory — select desired risk level, system suggests balanced portfolio weights",
        ],
        "about_limit_title": "⚠️ Limitations (important)",
        "about_limit_list": [
            "Based on past data — does NOT predict the future",
            "Simulation ≠ live results (many factors not modeled)",
            "Use for RELATIVE comparison, not absolute return prediction",
            "Only tests rebalancing strategies — no stop-loss or dynamic ticker selection yet (future phase)",
            "Currently allows fractional shares — HSX/HNX require 100-share lots; Day 9 will fix",
            "Combine with fundamental analysis and real market monitoring",
        ],
        "sidebar_title": "⚙️ Simulation setup",
        "capital_section": "💰 My capital",
        "capital_caption": "Enter initial capital for your portfolio (e.g. 100M VND)",
        "ticker_section_caption": "Select tickers and target weights (max 10 VN30 constituents)",
        "range_section_caption": "Historical window to backtest the strategy (data from 04/01/2021)",
        "vn30_roster_info": "📊 VN30 roster as of {snapshot_date} (list changes quarterly per HOSE decision)",
        "capital_label": "Initial capital (million VND)",
        "update_prices_btn": "Update price data",
        "updating_prices": "Loading...",
        "update_success": "Updated",
        "update_success_fmt": "✓ Updated through {date}",
        "lot_compliance_chip": "Lot: 100 shares (HSX since 04/01/2021)",
        "lot_compliance_tooltip": "Per Decision 496/QĐ-SGDHCM: all HSX orders must be multiples of 100 since 04/01/2021",
        "rf_source_label": "Risk-free rate source (Rf)",
        "rf_source_help": "Rf used in Sharpe = (portfolio return − Rf) / standard deviation. Actual value = mean (AVG) across the selected backtest window, not a fixed constant.",
        "rf_vcb_13m": "VCB 13-month deposit (retail)",
        "rf_vn_bond_1y": "VN Government Bond 1-year (academic standard)",
        "rf_sbv_refinance": "SBV refinance rate (policy)",
        "rf_zero": "No Rf adjustment (Perold 1988)",
        "rf_source_caption": "ℹ️ Actual value shown in Technical Details tab after simulation runs",
        "rf_actual_fmt": "Actual Rf used: {value}%/year (mean across backtest period)",
        # ==== F1 Efficient Frontier (Day 11) ====
        "f1_section_header": "📈 Efficient Frontier (F1)",
        "f1_section_intro": "**📌 F1 workflow (Optional):**\n\n1. Pick ≥ 2 tickers + backtest period in sidebar\n2. Adjust params below if needed (40% cap + 20 points are good defaults)\n3. Click 🔍 **Compute efficient frontier** → system computes 20 optimal portfolios + 3 reference\n4. Slide **Select point** to inspect each (return/risk/weights)\n5. Click ⚡ **Use these weights for simulation** → weights auto-transfer to sidebar\n6. Return to sidebar, click **Run simulation** to backtest with F1 weights\n\n*Skip F1 → enter weights manually in sidebar.*",
        "f1_compute_btn": "🔍 Compute efficient frontier",
        "f1_compute_btn_help": "Based on historical data within selected backtest window + ticker universe + Rf source",
        "f1_need_min_tickers": "ℹ️ Select ≥ 2 tickers in the sidebar before computing F1",
        "f1_upper_bound_label": "Max weight per asset",
        "f1_upper_bound_help": "Diversification cap on single-asset allocation. Default 40% (common for VN retail investors)",
        "f1_n_points_label": "Number of frontier points",
        "f1_n_points_help": "More points = smoother curve. Default 20",
        "f1_computing": "Computing efficient frontier...",
        "f1_computed_ok": "✓ Frontier computed: {n} points from {days} days of data ({rows} observations)",
        "f1_chart_title": "Efficient Frontier - risk/return optimization",
        "f1_chart_x_label": "Risk (annualized std deviation %)",
        "f1_chart_y_label": "Expected return (%/year)",
        "f1_curve_label": "Frontier",
        "f1_slider_label": "Select point on frontier",
        "f1_slider_help": "Slide to pick desired risk/return ratio. Left = lower risk + lower return; right = higher risk + higher return",
        "f1_selected_point_header": "📌 Selected point",
        "f1_selected_point_metrics": "Expected return: **{ret}%/year** · Risk: **{vol}%/year** · Sharpe: **{sharpe}**",
        "f1_ex_ante_caption": "📘 **Theoretical values (ex-ante)** — Return/Sharpe above are arithmetic means of historical returns. Actual simulation may differ due to rebalancing threshold + transaction costs + path-dependence. **Max drawdown** only appears in Simulation results, not in F1.",
        "f1_weights_table_header": "Portfolio weights",
        "f1_apply_btn": "⚡ Use these weights for simulation",
        "f1_apply_success": "✓ Weights applied. Click 'Run simulation' to backtest.",
        "f1_ref_portfolios_header": "📊 3 reference portfolios",
        "f1_ref_min_variance": "Min Variance",
        "f1_ref_max_sharpe": "Max Sharpe",
        "f1_ref_risk_parity": "Risk Parity",
        "f1_defense_note": "ℹ️ F1 implements Markowitz (1952) portfolio theory. Points on the frontier are risk-optimal for each expected return level. The 3 reference portfolios represent common strategies.",
        "update_failed": "Failed",
        "tickers_section": "📊 My portfolio",
        "ticker_scope_info": "📌 Scope: 30 VN30 constituents (HOSE) — data from {min_date} to {max_date}",
        "ticker_chip_empty": "No tickers selected",
        "ticker_input_label": "Type ticker, press Enter to add",
        "ticker_input_placeholder": "e.g. VCB",
        "ticker_input_submit": "➕ Add",
        "ticker_err_not_in_vn30": "Ticker '{ticker}' not in VN30 (30 largest HOSE stocks by market cap)",
        "ticker_err_duplicate": "Ticker '{ticker}' already in portfolio",
        "ticker_remove_tooltip": "Remove {ticker}",
        "weight_label": "Weight {ticker} (%)",
        "sum_ok": "Sum: {sum:.1f}%",
        "sum_bad": "Sum: {sum:.1f}% (must = 100%)",
        "equal_weight_btn": "📊 Equal weights",
        "manual_weight_btn": "✏️ Custom weights",
        "weight_mode_label": "Allocation mode:",
        "weight_mode_equal_help": "Split 1/N across all tickers",
        "weight_mode_manual_help": "Enter custom weights per ticker (must sum to 100%)",
        "range_section": "📅 Strategy backtest period",
        "range_period_rec": "💡 Data available from 04/01/2021. Recommended period ≥ {min_years:.0f}-3 years to capture multiple market cycles",
        "range_too_short": "⚠️ Period too short ({years:.1f} yr) — results may be unreliable. Recommend ≥ 2 years.",
        "start_date_label": "From",
        "end_date_label": "To",
        "range_err": "Start must be before end",
        "advanced_expander": "⚙️ Advanced (strategy + costs)",
        "strategy_info": "**Strategy:** Threshold Band - Auto-rebalances when any ticker drifts beyond threshold.",
        "band_label": "Drift threshold (basis points)",
        "band_help": "Drift tolerance threshold before rebalancing. 500 bps = 5%. Trade-off: wider threshold (1000 bps) = fewer trades + lower cost + more drift; narrower (100 bps) = more trades + higher cost + closer to target.",
        "cost_subheader": "Transaction costs",
        "brokerage_label": "Brokerage (%)",
        "brokerage_help": "Broker commission (0.15% is VN retail market average 2024-2026). Note: already includes exchange fee (0.03% HSX/HNX); zero-fee brokers (Pinetree, DNSE) total = 0.03%.",
        "tax_label": "Sell tax (%)",
        "tax_help": "0.10% per Circular 111/2013/TT-BTC",
        "market_impact_label": "Market impact (basis points)",
        "market_impact_help": "Slippage cost when entering/exiting positions. Default 10 bps (0.1%) for VN30 due to high liquidity; small-caps typically 20-50 bps.",
        "run_btn": "🚀 Run",
        "run_header": "Simulation result",
        "tab_overview": "📊 Overview",
        "tab_journal": "📝 Journal",
        "tab_technical": "📈 Technical",
        "hero_sub": "Capital {initial} over {years:.1f} years · With rebalancing",
        "hero_metric_cagr": "Growth/year",
        "hero_metric_mdd": "Max risk",
        "hero_metric_sharpe": "Risk efficiency",
        "verdict_vs_bh_win": "✓ **Beats Buy & Hold** {delta:+.1f}% ({delta_vnd})",
        "verdict_vs_bh_lose": "✗ **Loses to Buy & Hold** {delta:.1f}% ({delta_vnd}) — try tighter band",
        "verdict_vs_bh_neutral": "≈ **Similar to Buy & Hold** ({delta:+.1f}%)",
        "verdict_savings_win": "✓ **Above savings** (5-7%/yr) — {cagr:.1f}%/yr",
        "verdict_savings_near": "≈ **Similar to savings** (5-7%/yr) — {cagr:.1f}%/yr",
        "verdict_savings_lose": "✗ **Below savings** (5-7%/yr) — {cagr:.1f}%/yr",
        "risk_warning": "⚠️ **Risk:** Portfolio once peaked at **{peak}** then dropped to **{trough}** (down {mdd:.0f}%)",
        "cost_summary": "💰 **{total_trades} transactions, total cost {cost_pct}** — {verdict}",
        "savings_caveat": "",
        "rec_header": "Tips",
        "cost_verdict_negligible": "negligible",
        "cost_verdict_moderate": "moderate",
        "cost_verdict_significant": "significant",
        "rec_diversify": "Add 3-5 more tickers to reduce concentration risk",
        "rec_mdd_high": "Drawdown {mdd:.0f}% is high — prepare mentally for market corrections",
        "rec_vs_bh_lose": "Rebalancing underperforms B&H — try tighter band (300 bps = 3%)",
        "rec_vs_bh_win": "Rebalancing added {delta:+.1f}% vs B&H — effective",
        "rec_low_return": "Return {cagr:.1f}%/yr doesn't justify risk — consider more diversification",
        "rec_frequent_rebalance": "Frequency {freq:.1f}/yr is high — may cause overtrading",
        "chart_title": "Portfolio value over time",
        "chart_strategy": "Your strategy",
        "chart_before_cost": "Hypothetical no-cost scenario",
        "chart_buy_and_hold": "Buy & hold",
        "chart_x_label": "",
        "chart_y_label": "Value (VND)",
        "chart_insufficient": "Need at least 2 days",
        "journal_summary_header": "📋 Trading activity summary",
        "journal_summary_total": "**{total}** transactions",
        "journal_summary_init": "**1 initial setup** ({date})",
        "journal_summary_rebal": "**{n} rebalances**",
        "journal_summary_cost": "💰 Total cost: **{total_cost}** ({pct:.3f}% of trade value)",
        "journal_summary_init_cost": "• Initial setup cost: {cost}",
        "journal_summary_rebal_cost": "• Rebalancing cost: {cost}",
        "journal_empty": "Strategy did not trigger. Try tighter band.",
        "journal_date": "📅 {date}",
        "journal_badge_init": "🏁 INITIAL",
        "journal_badge_rebal": "🔄 REBALANCE",
        "journal_reason_init": "Initial portfolio allocation from cash",
        "journal_reason_band_drift": "Portfolio drifted from target weights",
        "journal_reason_periodic": "Scheduled rebalance",
        "journal_order_buy": "Bought {shares:,} {ticker} (~{amount})",
        "journal_order_sell": "Sold {shares:,} {ticker} (~{amount})",
        "journal_impact_header": "Impact:",
        "journal_impact_item": "{ticker}: {before:.0f}%→{after:.0f}%",
        "journal_cost_line": "Cost: **{total}** ({pct:.3f}%)",
        "journal_cost_detail": "Brokerage {brokerage} + Tax {tax} + Slippage {slippage}",
        "download_csv_btn": "📥 Download full CSV",
        "kpi_tier_a_header": "⭐ Most important",
        "kpi_tier_b_header": "📊 Supplementary",
        "kpi_tier_c_header": "🔧 Technical",
        "kpi_rebalances": "Transactions",
        "kpi_total_cost_pct": "Total cost",
        "kpi_turnover": "Turnover (%/time)",
        "kpi_sharpe_before": "Sharpe (before cost)",
        "kpi_sharpe_after": "Sharpe (after cost)",
        "kpi_mdd": "Max drawdown",
        "kpi_vol": "Vol/year",
        "kpi_cagr": "CAGR/year",
        "kpi_sharpe_help": "Scale: <1 inefficient, 1-2 good, >2 excellent. (Rf=0 - Perold 1988)",
        "kpi_mdd_help": "Scale: <10% low, 10-20% moderate, 20-35% high, >35% very high",
        "kpi_vol_help": "Scale: <15% low, 15-25% moderate, 25-40% high, >40% very high",
        "kpi_cagr_help": "Scale: <5% weak, 5-10% avg, 10-20% good, >20% excellent",
        "kpi_cost_help": "Scale: <0.5%/period low, 0.5-1% moderate, >1% high",
        "kpi_turnover_help": "% of portfolio churned per rebalance",
        "kpi_sharpe_before_help": "Sharpe without costs - for comparing cost impact",
        "kpi_rebal_help": "Scale: <2/yr = low (passive), 2-4 = moderate (ideal), 4-8 = high (active), >8 = too high (overtrading)",
        "kpi_practical_sharpe": "Compare strategy efficiency. VN30 Index average ~0.3-0.5. Adding diversification usually improves.",
        "kpi_practical_mdd": "Max temporary loss. Above 30% is alarm — prepare mentally and keep buffer.",
        "kpi_practical_vol": "Daily fluctuation. High = emotional ride.",
        "kpi_practical_cagr": "Compound annual rate. Compare to savings (6-7%) and mutual funds (8-12%).",
        "kpi_practical_cost": "Below 0.5%/period is good. VN mutual funds charge 1-2%/year.",
        "kpi_practical_rebal_tpl": "~{freq:.1f}/year. Long-term holder average: 2-4/year. {verdict}.",
        "kpi_practical_rebal_verdict_high": "High frequency → active strategy, higher costs",
        "kpi_practical_rebal_verdict_mid": "Moderate frequency",
        "kpi_practical_rebal_verdict_low": "Low frequency → passive strategy",
        "kpi_practical_turnover_tpl": "{avg:.0f}%/time × {freq:.1f}/year = ~{total:.0f}%/year. {verdict}.",
        "kpi_practical_turnover_verdict_high": "High active trading",
        "kpi_practical_turnover_verdict_mid": "Moderate active trading",
        "kpi_practical_turnover_verdict_low": "Passive, low trading",
        "kpi_practical_sharpe_before": "Compare to after-cost to see cost impact. Large gap = heavy fees.",
        "sev_excellent": "excellent",
        "sev_good": "good",
        "sev_average": "average",
        "sev_weak": "weak",
        "sev_poor": "poor",
        "sev_very_high": "very high",
        "sev_high": "high",
        "sev_moderate": "moderate",
        "sev_low": "low",
        "sev_negligible": "negligible",
        "sev_na": "N/A",
        "help_header": "📖 User guide",
        "help_step1": "**Step 1:** Enter capital (million VND)",
        "help_step2": "**Step 2:** Type ticker (e.g. VCB) then Enter to add, pick weight allocation mode",
        "help_step3": "**Step 3:** Select strategy backtest period (data from 04/01/2021)",
        "help_step4": "**Step 4:** (Optional) Open 'Advanced' to tweak threshold + costs + Rf source",
        "help_step5": "**Step 5:** (Optional) Use F1 Efficient Frontier in main area → pick optimal Markowitz point → ⚡ Apply weights → ▶️ **Run simulation now** (no need to scroll back to sidebar)",
        "help_step6": "**Step 6:** Or if skipping F1: enter weights manually in sidebar → click 'Run simulation' in sidebar",
        "help_step7": "**Step 7:** View Overview — open Journal / Technical Details tabs for details",
        "idle_msg": "Complete setup in the left sidebar then click Run Simulation",
        "failed_msg": "Simulation failed: {error}",
        "footer_meta": "Run #{run_id} • {ts}",
        "csv_date": "Date",
        "csv_reason": "Reason",
        "csv_brokerage": "Brokerage",
        "csv_slippage": "Slippage",
        "csv_tax": "Tax",
        "csv_cost": "Cost",
    },
}


def _t(key: str, **kwargs):
    lang = st.session_state.get("lang", "vi")
    text = TRANSLATIONS.get(lang, TRANSLATIONS["vi"]).get(key, key)
    if isinstance(text, list):
        return text
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


# =====================================================================
# Formatting helpers
# =====================================================================


def _format_vnd(amount, compact=False):
    if amount is None:
        return "—"
    val = float(amount)
    if compact:
        if abs(val) >= 1_000_000_000:
            return f"{val / 1_000_000_000:.2f} tỷ ₫"
        if abs(val) >= 1_000_000:
            return f"{val / 1_000_000:.1f} triệu ₫"
        if abs(val) >= 1_000:
            return f"{val / 1_000:.0f}k ₫"
        return f"{val:,.0f} ₫".replace(",", ".")
    formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} ₫"


def _format_pct(value, decimals=2, signed=False):
    if value is None:
        return "—"
    fmt = f"{{:+.{decimals}f}}%" if signed else f"{{:.{decimals}f}}%"
    return fmt.format(float(value))


def _bps_to_pct_str(cost_bps, decimals=2):
    if cost_bps is None:
        return "—"
    return f"{cost_bps / 100:.{decimals}f}%"


# =====================================================================
# Severity assessment
# =====================================================================


_SEV_CLASS = {
    "xuất sắc": "good",
    "excellent": "good",
    "tốt": "good",
    "good": "good",
    "thấp": "good",
    "low": "good",
    "không đáng kể": "good",
    "negligible": "good",
    "trung bình": "neutral",
    "average": "neutral",
    "vừa": "neutral",
    "moderate": "neutral",
    "yếu": "warning",
    "weak": "warning",
    "cao": "warning",
    "high": "warning",
    "có ảnh hưởng vừa": "warning",
    "moderate impact": "warning",
    "kém": "bad",
    "poor": "bad",
    "rất cao": "bad",
    "very high": "bad",
    "cắn đáng kể": "bad",
    "significant": "bad",
    "n/a": "plain",
}


def _sev_class(label):
    return _SEV_CLASS.get(label.lower(), "plain")


def _assess_sharpe(value):
    if value is None:
        return _t("sev_na")
    v = float(value)
    if v < 0:
        return _t("sev_poor")
    if v < 0.5:
        return _t("sev_weak")
    if v < 1.0:
        return _t("sev_average")
    if v < 2.0:
        return _t("sev_good")
    return _t("sev_excellent")


def _assess_mdd(value):
    if value is None:
        return _t("sev_na")
    v = float(value)
    if v < 10:
        return _t("sev_low")
    if v < 20:
        return _t("sev_moderate")
    if v < 35:
        return _t("sev_high")
    return _t("sev_very_high")


def _assess_cagr(value):
    if value is None:
        return _t("sev_na")
    if value < 0:
        return _t("sev_poor")
    if value < 5:
        return _t("sev_weak")
    if value < 10:
        return _t("sev_average")
    if value < 20:
        return _t("sev_good")
    return _t("sev_excellent")


def _assess_vol(value):
    if value is None:
        return _t("sev_na")
    v = float(value)
    if v < 15:
        return _t("sev_low")
    if v < 25:
        return _t("sev_moderate")
    if v < 40:
        return _t("sev_high")
    return _t("sev_very_high")


def _assess_cost(cost_bps):
    if cost_bps is None:
        return _t("sev_na")
    if cost_bps < 50:
        return _t("sev_low")
    if cost_bps < 100:
        return _t("sev_moderate")
    return _t("sev_high")


def _assess_rebal_frequency(n_rebal, years):
    if not n_rebal or years <= 0:
        return _t("sev_na")
    freq = n_rebal / years
    if freq < 2.0:
        return _t("sev_low")
    if freq <= 4.0:
        return _t("sev_moderate")
    if freq <= 8.0:
        return _t("sev_high")
    return _t("sev_very_high")


def _assess_turnover_per_year(turnover_avg_pct, n_rebal, years):
    if turnover_avg_pct is None or not n_rebal or years <= 0:
        return _t("sev_na")
    freq = n_rebal / years
    total_per_year = float(turnover_avg_pct) * 100 * freq
    if total_per_year < 20:
        return _t("sev_low")
    if total_per_year <= 60:
        return _t("sev_moderate")
    if total_per_year <= 150:
        return _t("sev_high")
    return _t("sev_very_high")


# =====================================================================
# Custom KPI card
# =====================================================================


def _render_kpi_card(label, value, severity="plain", severity_label="", help_text="", practical=""):
    label_safe = html.escape(label)
    help_html = (
        f'<span title="{html.escape(help_text)}" style="cursor:help;color:#9ca3af;margin-left:4px;">ⓘ</span>'
        if help_text
        else ""
    )
    sev_label_html = (
        f'<div class="kpi-severity sev-{severity}">{html.escape(severity_label)}</div>'
        if severity_label
        else ""
    )
    practical_html = (
        f'<div class="kpi-practical">💡 {html.escape(practical)}</div>' if practical else ""
    )
    html_block = (
        f'<div class="kpi-card sev-{severity}-bg">'
        f'<div class="kpi-label">{label_safe}{help_html}</div>'
        f'<div class="kpi-value sev-{severity}">{value}</div>'
        f"{sev_label_html}"
        f"{practical_html}"
        f"</div>"
    )
    st.markdown(html_block, unsafe_allow_html=True)


# =====================================================================
# Infrastructure helpers
# =====================================================================


def _get_git_commit_sha():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        sha = result.stdout.strip()
        if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
            return sha
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "0" * 40


@st.cache_data(ttl=3600)
def _get_available_tickers():
    try:
        factory = get_factory()
        latest = factory.price_repo().get_latest_dates()
        return sorted(latest.keys())
    except Exception:
        return ["VCB", "FPT", "VHM", "VNM", "HPG", "TCB", "MWG", "MBB"]


def _run_sync_prices():
    try:
        result = subprocess.run(
            [sys.executable, "scripts/sync_prices.py", "--today"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode == 0:
            return True, result.stdout[-500:]
        return False, (result.stderr or result.stdout)[-500:]
    except subprocess.TimeoutExpired:
        return False, "Timeout after 5 minutes"
    except Exception as exc:
        return False, str(exc)


# =====================================================================
# Analytical helpers
# =====================================================================


def _compute_cagr_pct(initial, final, years):
    if years <= 0 or initial <= 0:
        return None
    ratio = float(final) / float(initial)
    if ratio <= 0:
        return None
    return (ratio ** (1.0 / years) - 1.0) * 100.0


# v10: Return (peak, trough) at point of maximum drawdown for accurate messaging
def _find_mdd_peak_trough(values):
    """Return (peak_at_mdd, trough_at_mdd) - both are values from the series.

    The peak is the highest value BEFORE the trough (not necessarily series max).
    This matches how MDD is defined: max drop from running peak.
    """
    if len(values) < 2:
        return None, None
    peak = values[0]
    max_dd = Decimal("0")
    peak_at_mdd = values[0]
    trough_at_mdd = values[0]
    for v in values[1:]:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * Decimal("100")
            if dd > max_dd:
                max_dd = dd
                peak_at_mdd = peak
                trough_at_mdd = v
    return peak_at_mdd, trough_at_mdd


def _is_initial_allocation(decision):
    if not decision.weights_before:
        return True
    sum_before = sum(float(w) for w in decision.weights_before.values())
    return abs(sum_before) < 0.01


# =====================================================================
# Session state
# =====================================================================


def _init_state():
    defaults = {
        "lang": "vi",
        "selected_tickers": ["VCB", "FPT"],
        "weights_pct": {"VCB": 50.0, "FPT": 50.0},
        "run_status": "idle",
        "last_result": None,
        "last_error": None,
        "last_config": None,
        "ticker_add_error": None,  # v10: validation error message
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()


# =====================================================================
# About section
# =====================================================================


def _render_about():
    with st.expander(_t("about_header")):
        value_items = _t("about_value_list")
        limit_items = _t("about_limit_list")
        value_bullets = "\n".join(f"- {item}" for item in value_items)
        limit_bullets = "\n".join(f"- {item}" for item in limit_items)
        content = (
            f"**{_t('about_purpose_title')}**\n\n"
            f"{_t('about_purpose_body')}\n\n"
            f"**{_t('about_value_title')}**\n\n"
            f"{value_bullets}\n\n"
            f"**{_t('about_limit_title')}**\n\n"
            f"{limit_bullets}"
        )
        st.markdown(content)


# =====================================================================
# Sidebar - v10: text_input + Enter for ticker add
# =====================================================================


def _apply_equal_weight(tickers):
    if not tickers:
        return
    equal = 100.0 / len(tickers)
    for ticker in tickers:
        st.session_state[f"weight_pct_{ticker}"] = equal
        st.session_state.weights_pct[ticker] = equal


def _render_portfolio_chips():
    if not st.session_state.selected_tickers:
        st.sidebar.caption(_t("ticker_chip_empty"))
        return
    chips = []
    total_pct = 0.0
    hidden_count = 0
    for ticker in st.session_state.selected_tickers:
        pct = st.session_state.weights_pct.get(ticker, 0.0)
        total_pct += pct
        # Day 11 Cum 5 D1: hide 0% tickers from chip display (less clutter);
        # user still sees them trong weight inputs section below
        if pct > 0:
            chips.append(f'<span class="ticker-chip">{ticker} {pct:.0f}%</span>')
        else:
            hidden_count += 1
    if hidden_count > 0:
        chips.append(
            f'<span class="ticker-chip" '
            f'style="opacity:0.6;font-style:italic;background:#F3F4F6;color:#6B7280;">'
            f"+{hidden_count} ẩn 0%</span>"
        )
    sum_class = "ticker-sum-ok" if abs(total_pct - 100.0) <= 1.0 else "ticker-sum-bad"
    sum_text = (
        _t("sum_ok", sum=total_pct)
        if abs(total_pct - 100.0) <= 1.0
        else _t("sum_bad", sum=total_pct)
    )
    chips.append(f'<span class="{sum_class}">{sum_text}</span>')
    st.sidebar.markdown("".join(chips), unsafe_allow_html=True)

    # Day 13 A2: Sector allocation pie chart (collapsed expander)
    _sector_map = _get_vn30_sector_map()
    if _sector_map:
        _sector_weights = {}
        for _ticker, _pct in st.session_state.weights_pct.items():
            if _pct <= 0:
                continue
            _sector = _sector_map.get(_ticker, (None, "Khác"))[1]
            _sector_weights[_sector] = _sector_weights.get(_sector, 0.0) + _pct
        if _sector_weights:
            with st.sidebar.expander("🏭 Phân bổ theo ngành (ICB)", expanded=False):
                _sorted_sectors = sorted(_sector_weights.items(), key=lambda x: -x[1])
                _total = sum(_sector_weights.values())
                for _s, _w in _sorted_sectors:
                    _pct_sector = _w / _total * 100 if _total > 0 else 0
                    st.markdown(
                        f'<div style="font-size:12px;margin:3px 0;">'
                        f'<span style="color:#146026;font-weight:600;">{_s}</span>: '
                        f'<span style="color:#1F2937;">{_pct_sector:.1f}%</span></div>',
                        unsafe_allow_html=True,
                    )
                st.caption(f"Tổng {len(_sorted_sectors)} ngành · nguồn: ICB L2 (vnstock Reference)")


def _render_sidebar():
    st.sidebar.title(_t("sidebar_title"))

    # Day 10 Step C: compact language toggle VI/EN (SSOT — replaces main-area dropdown)
    lang_cur = st.session_state.get("lang", "vi")
    _tb_c1, _tb_c2, _tb_spacer = st.sidebar.columns([1, 1, 2])
    with _tb_c1:
        if st.button(
            "VI",
            key="lang_btn_vi",
            use_container_width=True,
            type="primary" if lang_cur == "vi" else "secondary",
        ):
            st.session_state["lang"] = "vi"
            st.rerun()
    with _tb_c2:
        if st.button(
            "EN",
            key="lang_btn_en",
            use_container_width=True,
            type="primary" if lang_cur == "en" else "secondary",
        ):
            st.session_state["lang"] = "en"
            st.rerun()

    # Day 10 Step C: compliance chip (NFR-R-02 lot size) — i18n + diacritics
    st.sidebar.markdown(
        f'<span class="compliance-chip" title="{_t("lot_compliance_tooltip")}">'
        f'{_t("lot_compliance_chip")}</span>',
        unsafe_allow_html=True,
    )

    st.sidebar.subheader(_t("capital_section"))
    st.sidebar.caption(_t("capital_caption"))
    initial_capital_m = st.sidebar.number_input(
        _t("capital_label"),
        min_value=1.0,
        value=100.0,
        step=10.0,
        format="%.2f",
    )
    initial_capital = Decimal(str(initial_capital_m)) * Decimal("1000000")

    if st.sidebar.button(
        _t("update_prices_btn"),
        type="primary",
        use_container_width=True,
    ):
        with st.spinner(_t("updating_prices")):
            ok, msg = _run_sync_prices()
            if ok:
                # Day 10 Step C: compact success chip (replaces oversized st.success box)
                _update_date = datetime.now().strftime("%d/%m/%Y %H:%M")
                st.sidebar.markdown(
                    f'<div style="font-size:12px;color:#16A34A;padding:4px 8px;'
                    f"background:#F0FDF4;border-left:3px solid #16A34A;border-radius:4px;"
                    f'margin:6px 0;">{_t("update_success_fmt", date=_update_date)}</div>',
                    unsafe_allow_html=True,
                )
                _get_available_tickers.clear()
            else:
                st.sidebar.error(f"{_t('update_failed')}: {msg}")

    # v10: Ticker section with text_input + Enter form
    st.sidebar.subheader(_t("tickers_section"))
    st.sidebar.caption(_t("ticker_section_caption"))

    # v11: scope info banner
    all_tickers = _get_available_tickers()
    try:
        latest_dates = get_factory().price_repo().get_latest_dates()
        max_date = max(latest_dates.values()) if latest_dates else date.today()
    except Exception:
        max_date = date.today()
    st.sidebar.markdown(
        f'<div class="scope-info">{_t("ticker_scope_info", min_date=DATA_MIN_DATE.strftime("%d/%m/%Y"), max_date=max_date.strftime("%d/%m/%Y"))}</div>'
        f'<div class="scope-info" style="margin-top:4px;">{_t("vn30_roster_info", snapshot_date=max_date.strftime("%d/%m/%Y"))}</div>',
        unsafe_allow_html=True,
    )

    _render_portfolio_chips()

    # Add ticker via form - Enter in text_input submits form (clear_on_submit=True clears input)
    with st.sidebar.form("add_ticker_form", clear_on_submit=True):
        new_ticker_input = st.text_input(
            _t("ticker_input_label"),
            placeholder=_t("ticker_input_placeholder"),
            key="ticker_text_input",
        )
        submitted = st.form_submit_button(
            _t("ticker_input_submit"),
            use_container_width=True,
        )
        if submitted and new_ticker_input:
            val = new_ticker_input.strip().upper()
            if val not in all_tickers:
                st.session_state.ticker_add_error = _t("ticker_err_not_in_vn30", ticker=val)
            elif val in st.session_state.selected_tickers:
                st.session_state.ticker_add_error = _t("ticker_err_duplicate", ticker=val)
            else:
                st.session_state.selected_tickers.append(val)
                st.session_state.weights_pct[val] = 0.0
                st.session_state.ticker_add_error = None
                st.rerun()

    # Show validation error (persists until next successful add or clear)
    if st.session_state.get("ticker_add_error"):
        st.sidebar.warning(st.session_state.ticker_add_error)

    # Weight inputs + remove buttons (Day 10 Step C Phase 2: mode toggle Option A)
    weights_pct = {}
    if st.session_state.selected_tickers:
        n = len(st.session_state.selected_tickers)

        # Mode toggle: Phân bổ đều vs Nhập tỷ trọng kỳ vọng
        # Day 11 Cụm 3e: default to manual mode when F1 weights applied
        _f1_source = st.session_state.get("weights_source", "")
        _default_mode_index = 1 if _f1_source.startswith("F1") else 0
        weight_mode = st.sidebar.radio(
            _t("weight_mode_label"),
            options=["equal", "manual"],
            format_func=lambda m: (
                _t("equal_weight_btn") if m == "equal" else _t("manual_weight_btn")
            ),
            captions=[_t("weight_mode_equal_help"), _t("weight_mode_manual_help")],
            horizontal=True,
            index=_default_mode_index,
            key="weight_mode",
        )

        if weight_mode == "equal":
            # Day 11 Cụm 3e: compute weights (preserve F1-applied if source matches)
            if not st.session_state.get("weights_source", "").startswith("F1"):
                # Auto-distribute 1/N
                equal_pct_val = 100.0 / n
                for ticker in list(st.session_state.selected_tickers):
                    weights_pct[ticker] = equal_pct_val
                    st.session_state.weights_pct[ticker] = equal_pct_val
            else:
                # F1 weights preserved — read from session state (per-ticker, not uniform)
                for ticker in list(st.session_state.selected_tickers):
                    weights_pct[ticker] = st.session_state.weights_pct.get(ticker, 0.0)
            # Render preview rows with per-ticker % + remove button
            for ticker in list(st.session_state.selected_tickers):
                row_c1, row_c2 = st.sidebar.columns([5, 1])
                with row_c1:
                    _pct_display = weights_pct.get(ticker, 0.0)
                    st.markdown(
                        f'<div style="padding:6px 10px;background:#F9FAFB;'
                        f'border:1px solid #E5E7EB;border-radius:4px;font-size:13px;">'
                        f"<b>{ticker}</b>: {_pct_display:.2f}%</div>",
                        unsafe_allow_html=True,
                    )
                with row_c2:
                    if st.button(
                        "✕",
                        key=f"ticker_remove_{ticker}",
                        help=_t("ticker_remove_tooltip", ticker=ticker),
                    ):
                        st.session_state.selected_tickers.remove(ticker)
                        if ticker in st.session_state.weights_pct:
                            del st.session_state.weights_pct[ticker]
                        st.rerun()
            # Day 11 Cum 5 D9: dedup F1 source chip - keep only sidebar bottom chip
            # (line ~1430) which always shows when weights_source exists; this
            # equal-mode info now only shows the equal-average message
            _avg_pct = sum(weights_pct.values()) / n if n > 0 else 0.0
            st.sidebar.info(f"✓ {_t('weight_mode_equal_help')}: {_avg_pct:.2f}% × {n} mã")
        else:
            # Manual mode: per-ticker number inputs
            for ticker in list(st.session_state.selected_tickers):
                row_c1, row_c2 = st.sidebar.columns([5, 1])
                with row_c1:
                    default_pct = st.session_state.weights_pct.get(ticker, 100.0 / max(n, 1))
                    pct = st.number_input(
                        _t("weight_label", ticker=ticker),
                        min_value=0.0,
                        max_value=100.0,
                        value=float(default_pct),
                        step=1.0,
                        format="%.2f",
                        key=f"weight_pct_{ticker}",
                    )
                    weights_pct[ticker] = pct
                    st.session_state.weights_pct[ticker] = pct
                with row_c2:
                    st.markdown("<div style='padding-top:28px;'></div>", unsafe_allow_html=True)
                    if st.button(
                        "✕",
                        key=f"ticker_remove_{ticker}",
                        help=_t("ticker_remove_tooltip", ticker=ticker),
                    ):
                        st.session_state.selected_tickers.remove(ticker)
                        if ticker in st.session_state.weights_pct:
                            del st.session_state.weights_pct[ticker]
                        if f"weight_pct_{ticker}" in st.session_state:
                            del st.session_state[f"weight_pct_{ticker}"]
                        st.rerun()

    weight_sum = sum(weights_pct.values())
    target_weights = {t: p / 100.0 for t, p in weights_pct.items() if p > 0}

    # Day 11 Cụm 3d: show current weights source if applied from F1
    _weights_source = st.session_state.get("weights_source", "")
    if _weights_source:
        st.sidebar.markdown(
            f'<div style="font-size:11px;color:#146026;padding:4px 8px;'
            f"background:#F0FDF4;border-left:3px solid #146026;"
            f'border-radius:4px;margin:6px 0;">📌 Nguồn tỷ trọng: <b>{_weights_source}</b></div>',
            unsafe_allow_html=True,
        )

    st.sidebar.subheader(_t("range_section"))
    st.sidebar.caption(_t("range_section_caption"))
    # Day 10 Step C Phase 2: period recommendation shown BEFORE date pickers
    st.sidebar.markdown(
        f'<div class="period-rec">{_t("range_period_rec", min_years=MIN_RECOMMENDED_YEARS)}</div>',
        unsafe_allow_html=True,
    )
    # Day 11 Cụm 3f: enforce DB max date (data integrity bug fix)
    data_max_date = _get_data_max_date()
    st.sidebar.caption(f"📅 Dữ liệu có sẵn đến **{data_max_date.strftime('%d/%m/%Y')}**")
    # Default to 3 years (within data range), bounded by DB max date
    default_start = max(DATA_MIN_DATE, data_max_date - timedelta(days=365 * 3))
    backtest_start = st.sidebar.date_input(
        _t("start_date_label"),
        value=default_start,
        min_value=DATA_MIN_DATE,
        max_value=data_max_date,
        format="DD/MM/YYYY",
        key="backtest_start",
    )
    backtest_end = st.sidebar.date_input(
        _t("end_date_label"),
        value=data_max_date,
        min_value=DATA_MIN_DATE,
        max_value=data_max_date,
        format="DD/MM/YYYY",
        key="backtest_end",
    )
    if backtest_start <= backtest_end:
        test_years = (backtest_end - backtest_start).days / 365.25
        if test_years < MIN_RECOMMENDED_YEARS:
            st.sidebar.warning(_t("range_too_short", years=test_years))

    with st.sidebar.expander(_t("advanced_expander")):
        st.info(_t("strategy_info"))
        band_bps = st.number_input(
            _t("band_label"),
            min_value=1,
            max_value=10000,
            value=500,
            step=50,
            help=_t("band_help"),
        )
        st.subheader(_t("cost_subheader"))
        brokerage_pct_input = st.number_input(
            _t("brokerage_label"),
            min_value=0.0,
            max_value=1.0,
            value=0.15,
            step=0.01,
            format="%.4f",
            help=_t("brokerage_help"),
        )
        brokerage_pct = Decimal(str(brokerage_pct_input)) / Decimal("100")
        tax_pct_input = st.number_input(
            _t("tax_label"),
            min_value=0.0,
            max_value=1.0,
            value=0.10,
            step=0.01,
            format="%.4f",
            help=_t("tax_help"),
        )
        tax_pct = Decimal(str(tax_pct_input)) / Decimal("100")
        market_impact_bps = st.number_input(
            _t("market_impact_label"),
            min_value=0,
            max_value=500,
            value=10,
            step=5,
            help=_t("market_impact_help"),
        )

    weights_ok = abs(weight_sum - 100.0) <= 1.0 and len(target_weights) >= 1
    dates_ok = backtest_start <= backtest_end
    capital_ok = initial_capital > 0
    all_ok = weights_ok and dates_ok and capital_ok
    if not dates_ok:
        st.sidebar.error(_t("range_err"))

    # Day 10 Step C: Rf source selector (Day 9 Step B feature wire-up)
    # Day 10 Step C: Rf source selectbox (priority order per ADR-016 + i18n)
    # Order: retail realistic (default) → academic standard → policy → baseline
    rf_sources_order = [
        "vcb_13m_deposit",  # DEFAULT: big-4 bank savings opportunity cost
        "vn_bond_1y",  # Academic standard (Sharpe 1994 convention)
        "sbv_refinance",  # Policy rate (less common for retail)
        "zero",  # Baseline no-adjustment (Perold 1988)
    ]
    rf_label_key = {
        "vcb_13m_deposit": "rf_vcb_13m",
        "vn_bond_1y": "rf_vn_bond_1y",
        "sbv_refinance": "rf_sbv_refinance",
        "zero": "rf_zero",
    }
    rf_source = st.sidebar.selectbox(
        _t("rf_source_label"),
        options=rf_sources_order,
        index=0,
        format_func=lambda src: _t(rf_label_key[src]),
        help=_t("rf_source_help"),
        key="rf_source_select",
    )
    st.sidebar.caption(_t("rf_source_caption"))

    # Day 13 A1: Upcoming corporate events next 30 days (collapsed expander)
    _tickers_tuple = tuple(st.session_state.get("selected_tickers", []))
    if _tickers_tuple:
        _events_df = _get_upcoming_events(_tickers_tuple, days_ahead=30)
        if _events_df is not None and len(_events_df) > 0:
            with st.sidebar.expander(f"📅 Sự kiện 30 ngày tới ({len(_events_df)})", expanded=False):
                for _, _ev in _events_df.head(10).iterrows():
                    _ex_date = _ev.get("ex_right_date")
                    _ex_str = (
                        _ex_date.strftime("%d/%m")
                        if _ex_date is not None and hasattr(_ex_date, "strftime")
                        else "—"
                    )
                    _sym = _ev.get("symbol", "?")
                    _name = str(_ev.get("event_title", ""))[:50]
                    _val = _ev.get("value")
                    _val_str = f" ({float(_val):,.0f}đ)" if _val and str(_val) != "nan" else ""
                    st.markdown(
                        f'<div style="font-size:11px;margin:3px 0;line-height:1.4;">'
                        f'<span style="color:#DC2626;font-weight:600;">{_ex_str}</span> · '
                        f'<span style="color:#146026;font-weight:600;">{_sym}</span>: '
                        f'<span style="color:#374151;">{_name}{_val_str}</span></div>',
                        unsafe_allow_html=True,
                    )
                if len(_events_df) > 10:
                    st.caption(f"...và {len(_events_df) - 10} sự kiện khác")

    run_pressed = st.sidebar.button(
        _t("run_btn"),
        type="primary",
        disabled=not all_ok,
        use_container_width=True,
    )
    # Day 11 Cụm 3f #3 (X4-micro): also honor "Chạy ngay" from F1 section
    # so user doesn't need to scroll back to sidebar after applying F1 weights
    _f1_trigger = st.session_state.pop("f1_trigger_sim", False)
    if not run_pressed and not _f1_trigger:
        return None

    return {
        "target_weights": target_weights,
        "initial_capital": initial_capital,
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "strategy_name": "threshold_band",
        "strategy_params": {"band_bps": band_bps},
        "brokerage_pct": brokerage_pct,
        "tax_pct": tax_pct,
        "market_impact_bps": market_impact_bps,
        "rf_source": rf_source,
    }


# =====================================================================
# Run execution
# =====================================================================


def _run_backtest(config):
    factory = get_factory()
    simulator = factory.rebalance_simulator()

    try:
        request = SimulateRequest(
            target_weights=config["target_weights"],
            initial_capital=config["initial_capital"],
            backtest_start=config["backtest_start"],
            backtest_end=config["backtest_end"],
            strategy_name=config["strategy_name"],
            strategy_params=config["strategy_params"],
            brokerage_pct=config["brokerage_pct"],
            tax_pct=config["tax_pct"],
            market_impact_bps=config["market_impact_bps"],
            git_commit_sha=_get_git_commit_sha(),
            code_version=PROJECT_VERSION,
            rf_source=config["rf_source"],
        )
    except ValueError as exc:
        st.session_state.run_status = "failed"
        st.session_state.last_error = str(exc)
        return

    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def on_progress(day, done, total):
        progress_bar.progress(done / total)
        status_text.text(f"Đang xử lý {day} ({done} / {total})")

    try:
        result = simulator.simulate(request, on_progress=on_progress)
        st.session_state.run_status = "completed"
        st.session_state.last_result = result
        st.session_state.last_error = None
    except ValueError as exc:
        st.session_state.run_status = "failed"
        st.session_state.last_error = str(exc)
        st.session_state.last_result = None
    finally:
        progress_bar.empty()
        status_text.empty()


# =====================================================================
# Hero - v10: accurate peak+trough in risk warning
# =====================================================================


def _render_hero_dense(result, record, config, decisions):
    initial = (
        result.daily_values_after_cost[0]
        if result.daily_values_after_cost
        else config["initial_capital"]
    )
    final = result.daily_values_after_cost[-1] if result.daily_values_after_cost else initial
    final_bh = result.daily_values_buy_and_hold[-1] if result.daily_values_buy_and_hold else None

    n_days = len(result.trading_days)
    years = n_days / TRADING_DAYS_PER_YEAR if n_days > 0 else 0.0
    total_return_pct = (float(final) / float(initial) - 1.0) * 100.0 if initial > 0 else 0.0
    gain_vnd = final - initial
    cagr = _compute_cagr_pct(initial, final, years)
    total_trades = len(decisions)

    left_col, right_col = st.columns([2, 3], gap="large")

    with left_col:
        delta_class = "hero-delta-pos" if gain_vnd >= 0 else "hero-delta-neg"
        gain_sign = "+" if gain_vnd >= 0 else ""
        st.markdown(
            f'<div class="hero-number">{_format_vnd(final, compact=True)}</div>',
            unsafe_allow_html=True,
        )
        cagr_str = f"{cagr:+.1f}%/năm" if cagr is not None else "—"
        st.markdown(
            f'<div class="{delta_class}">{gain_sign}{total_return_pct:.1f}% '
            f"({gain_sign}{_format_vnd(gain_vnd, compact=True)}) · {cagr_str}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="hero-sub">{_t("hero_sub", initial=_format_vnd(initial, compact=True), years=years)}</div>',
            unsafe_allow_html=True,
        )

        m1, m2, m3 = st.columns(3)
        with m1:
            cagr_label = _assess_cagr(cagr)
            _render_kpi_card(
                label=_t("hero_metric_cagr"),
                value=f"{cagr:+.1f}%" if cagr is not None else "—",
                severity=_sev_class(cagr_label),
                severity_label=cagr_label,
                help_text=_t("kpi_cagr_help"),
            )
        with m2:
            mdd_label = _assess_mdd(record.max_drawdown_pct)
            _render_kpi_card(
                label=_t("hero_metric_mdd"),
                value=_format_pct(record.max_drawdown_pct),
                severity=_sev_class(mdd_label),
                severity_label=mdd_label,
                help_text=_t("kpi_mdd_help"),
            )
        with m3:
            sa_label = _assess_sharpe(record.sharpe_after_cost)
            _render_kpi_card(
                label=_t("hero_metric_sharpe"),
                value=(
                    f"{float(record.sharpe_after_cost):.2f}"
                    if record.sharpe_after_cost is not None
                    else "—"
                ),
                severity=_sev_class(sa_label),
                severity_label=sa_label,
                help_text=_t("kpi_sharpe_help"),
            )

        if final_bh is not None and final_bh > 0:
            delta_vs_bh = float(final) - float(final_bh)
            delta_pct = (float(final) / float(final_bh) - 1.0) * 100.0
            delta_vnd_str = _format_vnd(Decimal(str(delta_vs_bh)), compact=True)
            if delta_pct > 2.0:
                verdict_text = _t("verdict_vs_bh_win", delta=delta_pct, delta_vnd=delta_vnd_str)
                verdict_class = "verdict-win"
            elif delta_pct < -2.0:
                verdict_text = _t("verdict_vs_bh_lose", delta=delta_pct, delta_vnd=delta_vnd_str)
                verdict_class = "verdict-lose"
            else:
                verdict_text = _t("verdict_vs_bh_neutral", delta=delta_pct)
                verdict_class = "verdict-neutral"
            st.markdown(
                f'<div class="verdict-box {verdict_class}">{verdict_text}</div>',
                unsafe_allow_html=True,
            )

        if cagr is not None:
            if cagr > 7.5:
                sv_text = _t("verdict_savings_win", cagr=cagr)
                sv_class = "verdict-win"
            elif cagr < 4.5:
                sv_text = _t("verdict_savings_lose", cagr=cagr)
                sv_class = "verdict-lose"
            else:
                sv_text = _t("verdict_savings_near", cagr=cagr)
                sv_class = "verdict-neutral"
            st.markdown(
                f'<div class="verdict-box {sv_class}">{sv_text}</div>',
                unsafe_allow_html=True,
            )

        # v10: FIXED - show peak + trough instead of initial + trough
        if record.max_drawdown_pct is not None:
            peak_value, trough_value = _find_mdd_peak_trough(result.daily_values_after_cost)
            st.markdown(
                _t(
                    "risk_warning",
                    peak=_format_vnd(peak_value, compact=True) if peak_value else "—",
                    trough=_format_vnd(trough_value, compact=True) if trough_value else "—",
                    mdd=float(record.max_drawdown_pct),
                )
            )

        cost_verdict = _assess_cost(record.total_cost_bps)
        cost_pct_str = _bps_to_pct_str(record.total_cost_bps)
        st.markdown(
            _t(
                "cost_summary",
                total_trades=total_trades,
                cost_pct=cost_pct_str,
                verdict=cost_verdict,
            )
        )

        recs = _generate_recommendations(record, config, cagr, final, final_bh, years)
        if recs:
            rec_items = "<br>".join(f"• {html.escape(r)}" for r in recs)
            st.markdown(
                f'<div class="rec-box">'
                f'<div class="rec-header-text">💡 {_t("rec_header")}</div>'
                f"{rec_items}"
                f"</div>",
                unsafe_allow_html=True,
            )

    with right_col:
        _render_chart_compact(result)


def _generate_recommendations(record, config, cagr, final, final_bh, years):
    recs = []
    n_tickers = len(config["target_weights"])

    if n_tickers < 5:
        recs.append(_t("rec_diversify"))

    if record.max_drawdown_pct and float(record.max_drawdown_pct) > 25:
        recs.append(_t("rec_mdd_high", mdd=float(record.max_drawdown_pct)))

    if final_bh is not None and final_bh > 0:
        delta_bh_pct = (float(final) / float(final_bh) - 1.0) * 100.0
        if delta_bh_pct < -2.0:
            recs.append(_t("rec_vs_bh_lose"))
        elif delta_bh_pct > 2.0:
            recs.append(_t("rec_vs_bh_win", delta=delta_bh_pct))

    if cagr is not None and cagr < 5.0:
        recs.append(_t("rec_low_return", cagr=cagr))

    if record.n_rebalances and years > 0:
        freq = record.n_rebalances / years
        if freq > 4.0:
            recs.append(_t("rec_frequent_rebalance", freq=freq))

    return recs[:3]


def _render_chart_compact(result):
    if len(result.trading_days) < 2:
        st.info(_t("chart_insufficient"))
        return

    chart_df = pd.DataFrame(
        {
            "date": result.trading_days,
            "after_cost": [float(v) for v in result.daily_values_after_cost],
            "before_cost": [float(v) for v in result.daily_values_before_cost],
        }
    )
    bh_values = getattr(result, "daily_values_buy_and_hold", None)
    if bh_values:
        chart_df["buy_and_hold"] = [float(v) for v in bh_values]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["after_cost"],
            name=_t("chart_strategy"),
            mode="lines",
            line={"color": "#2563eb", "width": 2.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["before_cost"],
            name=_t("chart_before_cost"),
            mode="lines",
            line={"color": "#93c5fd", "width": 1, "dash": "dot"},
        )
    )
    if "buy_and_hold" in chart_df.columns:
        fig.add_trace(
            go.Scatter(
                x=chart_df["date"],
                y=chart_df["buy_and_hold"],
                name=_t("chart_buy_and_hold"),
                mode="lines",
                line={"color": "#f97316", "width": 2, "dash": "dash"},
            )
        )
    fig.update_layout(
        title=_t("chart_title"),
        xaxis_title=_t("chart_x_label"),
        yaxis_title=_t("chart_y_label"),
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.12,
            "xanchor": "center",
            "x": 0.5,
        },
        margin={"t": 40, "b": 60, "l": 50, "r": 20},
        hovermode="x unified",
        height=580,
    )
    st.plotly_chart(fig, use_container_width=True)


# =====================================================================
# Journal
# =====================================================================


def _translate_reason(reason, is_initial):
    if is_initial:
        return _t("journal_reason_init")
    key = {
        "band_drift": "journal_reason_band_drift",
        "periodic": "journal_reason_periodic",
    }.get(reason)
    return _t(key) if key else reason


def _format_orders_markdown(orders):
    lines = []
    for order in orders:
        amount = Decimal(order.shares) * order.est_price
        amount_str = _format_vnd(amount, compact=True)
        side_str = order.side.value if hasattr(order.side, "value") else str(order.side)
        key = "journal_order_buy" if side_str.upper() == "BUY" else "journal_order_sell"
        lines.append(
            _t(
                key,
                shares=order.shares,
                ticker=order.ticker,
                amount=amount_str,
            )
        )
    return "\n".join(f"- {line}" for line in lines)


def _format_weights_impact(weights_before, weights_after):
    tickers = sorted(set(weights_before.keys()) | set(weights_after.keys()))
    parts = []
    for t in tickers:
        before = weights_before.get(t, 0.0) * 100
        after = weights_after.get(t, 0.0) * 100
        parts.append(_t("journal_impact_item", ticker=t, before=before, after=after))
    return ", ".join(parts)


def _render_decisions_journal(decisions, years):
    if not decisions:
        st.info(_t("journal_empty"))
        return

    initial_decisions = [d for d in decisions if _is_initial_allocation(d)]
    rebalance_decisions = [d for d in decisions if not _is_initial_allocation(d)]

    total_cost = sum((d.costs.total() for d in decisions), start=Decimal("0"))
    total_gross = sum(
        (Decimal(o.shares) * o.est_price for d in decisions for o in d.orders),
        start=Decimal("0"),
    )
    total_cost_pct = float(total_cost) / float(total_gross) * 100 if total_gross > 0 else 0.0

    init_cost = sum((d.costs.total() for d in initial_decisions), start=Decimal("0"))
    rebal_cost = sum((d.costs.total() for d in rebalance_decisions), start=Decimal("0"))

    with st.container(border=True):
        st.markdown(f"**{_t('journal_summary_header')}**")
        sum_c1, sum_c2, sum_c3 = st.columns(3)
        sum_c1.markdown(_t("journal_summary_total", total=len(decisions)))
        if initial_decisions:
            first_init = initial_decisions[0]
            sum_c2.markdown(
                _t(
                    "journal_summary_init",
                    date=first_init.triggered_at.strftime("%d/%m/%Y"),
                )
            )
        sum_c3.markdown(_t("journal_summary_rebal", n=len(rebalance_decisions)))
        st.markdown(
            _t(
                "journal_summary_cost",
                total_cost=_format_vnd(total_cost, compact=True),
                pct=total_cost_pct,
            )
        )
        if initial_decisions and rebalance_decisions:
            st.caption(
                _t("journal_summary_init_cost", cost=_format_vnd(init_cost, compact=True))
                + " · "
                + _t("journal_summary_rebal_cost", cost=_format_vnd(rebal_cost, compact=True))
            )

    st.markdown("")

    for d in decisions:
        is_initial = _is_initial_allocation(d)
        badge_html = (
            f'<span class="badge-init">{_t("journal_badge_init")}</span>'
            if is_initial
            else f'<span class="badge-rebal">{_t("journal_badge_rebal")}</span>'
        )

        with st.container(border=True):
            cols = st.columns([2, 5, 2])
            cols[0].markdown(
                f'{_t("journal_date", date=d.triggered_at.strftime("%d/%m/%Y"))} &nbsp; {badge_html}',
                unsafe_allow_html=True,
            )
            cols[0].caption(_translate_reason(d.reason, is_initial))
            cols[1].markdown(_format_orders_markdown(d.orders))
            cols[1].caption(
                f"**{_t('journal_impact_header')}** {_format_weights_impact(d.weights_before, d.weights_after)}"
            )
            gross = sum((Decimal(o.shares) * o.est_price for o in d.orders), start=Decimal("0"))
            cost_pct = float(d.costs.total()) / float(gross) * 100 if gross > 0 else 0.0
            cols[2].markdown(
                _t(
                    "journal_cost_line",
                    total=_format_vnd(d.costs.total(), compact=True),
                    pct=cost_pct,
                )
            )
            cols[2].caption(
                _t(
                    "journal_cost_detail",
                    brokerage=_format_vnd(d.costs.brokerage, compact=True),
                    tax=_format_vnd(d.costs.tax, compact=True),
                    slippage=_format_vnd(d.costs.slippage, compact=True),
                )
            )

    csv_rows = []
    for d in decisions:
        for order in d.orders:
            side_str = order.side.value if hasattr(order.side, "value") else str(order.side)
            csv_rows.append(
                {
                    _t("csv_date"): d.triggered_at,
                    "type": "initial" if _is_initial_allocation(d) else "rebalance",
                    _t("csv_reason"): d.reason,
                    "ticker": order.ticker,
                    "side": side_str,
                    "shares": order.shares,
                    "est_price": float(order.est_price),
                    _t("csv_brokerage"): float(d.costs.brokerage),
                    _t("csv_slippage"): float(d.costs.slippage),
                    _t("csv_tax"): float(d.costs.tax),
                    _t("csv_cost"): float(d.costs.total()),
                }
            )
    csv_df = pd.DataFrame(csv_rows)
    csv_bytes = csv_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        _t("download_csv_btn"),
        data=csv_bytes,
        file_name="decisions.csv",
        mime="text/csv",
    )


# =====================================================================
# Technical KPIs
# =====================================================================


def _build_rebal_practical(n_rebal, years):
    if not n_rebal or years <= 0:
        return _t("kpi_practical_sharpe")
    freq = n_rebal / years
    if freq > 4.0:
        verdict = _t("kpi_practical_rebal_verdict_high")
    elif freq >= 2.0:
        verdict = _t("kpi_practical_rebal_verdict_mid")
    else:
        verdict = _t("kpi_practical_rebal_verdict_low")
    return _t("kpi_practical_rebal_tpl", freq=freq, verdict=verdict)


def _build_turnover_practical(turnover_avg_pct, n_rebal, years):
    if turnover_avg_pct is None or not n_rebal or years <= 0:
        return _t(
            "kpi_practical_turnover_tpl",
            avg=0.0,
            freq=0.0,
            total=0.0,
            verdict=_t("kpi_practical_turnover_verdict_low"),
        )
    avg = float(turnover_avg_pct) * 100
    freq = n_rebal / years
    total_per_year = avg * freq
    if total_per_year > 100:
        verdict = _t("kpi_practical_turnover_verdict_high")
    elif total_per_year > 30:
        verdict = _t("kpi_practical_turnover_verdict_mid")
    else:
        verdict = _t("kpi_practical_turnover_verdict_low")
    return _t(
        "kpi_practical_turnover_tpl", avg=avg, freq=freq, total=total_per_year, verdict=verdict
    )


def _render_kpi_tiered(result, record):
    if result.daily_values_after_cost and len(result.daily_values_after_cost) >= 2:
        initial = result.daily_values_after_cost[0]
        final = result.daily_values_after_cost[-1]
        years = len(result.trading_days) / TRADING_DAYS_PER_YEAR
        cagr = _compute_cagr_pct(initial, final, years)
    else:
        cagr = None
        years = 0.0

    st.subheader(_t("kpi_tier_a_header"))
    c1, c2, c3 = st.columns(3)
    with c1:
        cagr_label = _assess_cagr(cagr)
        _render_kpi_card(
            label=_t("kpi_cagr"),
            value=f"{cagr:+.2f}%" if cagr is not None else "—",
            severity=_sev_class(cagr_label),
            severity_label=cagr_label,
            help_text=_t("kpi_cagr_help"),
            practical=_t("kpi_practical_cagr"),
        )
    with c2:
        mdd_label = _assess_mdd(record.max_drawdown_pct)
        _render_kpi_card(
            label=_t("kpi_mdd"),
            value=_format_pct(record.max_drawdown_pct),
            severity=_sev_class(mdd_label),
            severity_label=mdd_label,
            help_text=_t("kpi_mdd_help"),
            practical=_t("kpi_practical_mdd"),
        )
    with c3:
        sa_label = _assess_sharpe(record.sharpe_after_cost)
        _render_kpi_card(
            label=_t("kpi_sharpe_after"),
            value=(
                f"{float(record.sharpe_after_cost):.4f}"
                if record.sharpe_after_cost is not None
                else "—"
            ),
            severity=_sev_class(sa_label),
            severity_label=sa_label,
            help_text=_t("kpi_sharpe_help"),
            practical=_t("kpi_practical_sharpe"),
        )

    st.divider()

    st.subheader(_t("kpi_tier_b_header"))
    c4, c5, c6 = st.columns(3)
    with c4:
        vol_label = _assess_vol(record.volatility_annualized_pct)
        _render_kpi_card(
            label=_t("kpi_vol"),
            value=_format_pct(record.volatility_annualized_pct),
            severity=_sev_class(vol_label),
            severity_label=vol_label,
            help_text=_t("kpi_vol_help"),
            practical=_t("kpi_practical_vol"),
        )
    with c5:
        cost_label = _assess_cost(record.total_cost_bps)
        _render_kpi_card(
            label=_t("kpi_total_cost_pct"),
            value=_bps_to_pct_str(record.total_cost_bps),
            severity=_sev_class(cost_label),
            severity_label=cost_label,
            help_text=_t("kpi_cost_help"),
            practical=_t("kpi_practical_cost"),
        )
    with c6:
        rebal_label = _assess_rebal_frequency(record.n_rebalances, years)
        _render_kpi_card(
            label=_t("kpi_rebalances"),
            value=str(record.n_rebalances or 0),
            severity=_sev_class(rebal_label),
            severity_label=rebal_label,
            help_text=_t("kpi_rebal_help"),
            practical=_build_rebal_practical(record.n_rebalances, years),
        )

    st.divider()

    # Day 11 Cum 3f #16: wrap Technical tier in expander (collapsed default)
    # Turnover + Gross Sharpe = advanced metrics for defense/analyst use,
    # not primary end-user signals
    with st.expander(_t("kpi_tier_c_header"), expanded=False):
        c7, c8 = st.columns(2)
        with c7:
            turnover_label = _assess_turnover_per_year(
                record.turnover_avg_pct, record.n_rebalances, years
            )
            _render_kpi_card(
                label=_t("kpi_turnover"),
                value=(
                    f"{float(record.turnover_avg_pct) * 100:.2f}%"
                    if record.turnover_avg_pct is not None
                    else "—"
                ),
                severity=_sev_class(turnover_label),
                severity_label=turnover_label,
                help_text=_t("kpi_turnover_help"),
                practical=_build_turnover_practical(
                    record.turnover_avg_pct, record.n_rebalances, years
                ),
            )
        with c8:
            sb_label = _assess_sharpe(record.sharpe_before_cost)
            _render_kpi_card(
                label=_t("kpi_sharpe_before"),
                value=(
                    f"{float(record.sharpe_before_cost):.4f}"
                    if record.sharpe_before_cost is not None
                    else "—"
                ),
                severity=_sev_class(sb_label),
                severity_label=sb_label,
                help_text=_t("kpi_sharpe_before_help"),
                practical=_t("kpi_practical_sharpe_before"),
            )


# =====================================================================
# Results orchestrator
# =====================================================================


def _render_results(result, config):
    factory = get_factory()
    run_repo = factory.run_repo()
    decision_repo = factory.decision_repo()

    record = run_repo.find_by_id(result.run_id)
    decisions = decision_repo.find_by_run(result.run_id)

    st.header(_t("run_header"))

    # Day 11 Cụm 3f #14: show weights source (F1 point / Chia đều / Nhập tay)
    # for audit trail — user knows which weight set produced these results
    _ws = st.session_state.get("weights_source", "")
    _chip_label = f"Chạy với tỷ trọng: {_ws}" if _ws else "Chạy với tỷ trọng tự nhập"
    st.markdown(
        f'<div style="display:inline-block;font-size:12px;color:#146026;'
        f"padding:4px 12px;background:#F0FDF4;border-left:3px solid #146026;"
        f'border-radius:4px;margin:4px 0 16px 0;">📌 {_chip_label}</div>',
        unsafe_allow_html=True,
    )

    tab_overview, tab_journal, tab_tech = st.tabs(
        [
            _t("tab_overview"),
            _t("tab_journal"),
            _t("tab_technical"),
        ]
    )

    with tab_overview:
        _render_hero_dense(result, record, config, decisions)

    with tab_journal:
        years = len(result.trading_days) / TRADING_DAYS_PER_YEAR
        _render_decisions_journal(decisions, years)

    with tab_tech:
        _render_kpi_tiered(result, record)
        # Day 10 Step C Phase B: display actual Rf used (period mean over backtest)
        if hasattr(result, "rf_annual_pct"):
            if result.rf_annual_pct > 0:
                st.caption(
                    _t(
                        "rf_actual_fmt",
                        value=f"{float(result.rf_annual_pct):.2f}",
                    )
                )
            else:
                st.caption(f"ℹ️ Rf = 0% ({_t('rf_zero')})")

    now_str = datetime.now().strftime("%H:%M %d/%m/%Y")
    st.markdown(
        f'<div class="footer-caption">{_t("footer_meta", run_id=result.run_id, ts=now_str)}</div>',
        unsafe_allow_html=True,
    )


def _build_preview_config() -> dict | None:
    """Build config dict for F1 preview without requiring Run button.

    Reads sidebar widget values from session_state (Day 11 Patch A added
    keys to date_input + Day 10 Step C had key for rf_source_select).
    Returns None if required fields missing (selected_tickers < 2).
    Used by _render_f1_section to compute frontier before user commits
    to full simulation.
    """
    tickers = st.session_state.get("selected_tickers", [])
    if len(tickers) < 2:
        return None

    # Day 11 Cụm 3f: use DB max date (consistency with sidebar)
    data_max_date = _get_data_max_date()
    default_start = max(DATA_MIN_DATE, data_max_date - timedelta(days=365 * 3))

    return {
        "tickers": tuple(sorted(tickers)),
        "backtest_start": st.session_state.get("backtest_start", default_start),
        "backtest_end": st.session_state.get("backtest_end", data_max_date),
        "rf_source": st.session_state.get("rf_source_select", "zero"),
    }


def _render_f1_chart(curve, selected_idx: int | None = None) -> None:
    """Render Plotly scatter chart: frontier curve + 3 reference markers.

    Day 11 F1 Sprint 11. Uses module-level `go` import (plotly.graph_objects).
    If selected_idx provided, adds a highlighted marker at that point (Cụm 3d).
    """
    df = curve.as_dataframe()

    fig = go.Figure()

    # Main curve - frontier points
    fig.add_trace(
        go.Scatter(
            x=df["volatility"],
            y=df["expected_return"],
            mode="lines+markers",
            name=_t("f1_curve_label"),
            line={"color": "#146026", "width": 3},
            marker={"size": 8, "color": "#146026"},
            hovertemplate=(
                "<b>Diem %{customdata}</b><br>"
                "Rủi ro: %{x:.2f}%/năm<br>"
                "Lợi suất: %{y:.2f}%/năm<br>"
                "<extra></extra>"
            ),
            customdata=list(range(len(df))),
        )
    )

    # 3 reference portfolios as star markers
    # Day 11 Cum 5 D3: per-marker textposition to prevent label overlap with
    # frontier curve. MinVar bottom-left, Sharpe top-right, RiskParity bottom-center
    refs = [
        (curve.ref_min_variance, _t("f1_ref_min_variance"), "#80c433", "bottom left"),
        (curve.ref_max_sharpe, _t("f1_ref_max_sharpe"), "#DC2626", "top right"),
        (curve.ref_risk_parity, _t("f1_ref_risk_parity"), "#cbdd56", "bottom center"),
    ]
    for portfolio, label, color, text_pos in refs:
        fig.add_trace(
            go.Scatter(
                x=[float(portfolio.volatility_annual_pct)],
                y=[float(portfolio.expected_return_annual_pct)],
                mode="markers+text",
                name=label,
                marker={
                    "size": 16,
                    "color": color,
                    "symbol": "star",
                    "line": {"color": "white", "width": 2},
                },
                text=[f"  {label}  "],
                textposition=text_pos,
                textfont={"size": 11, "color": color, "family": "Inter, sans-serif"},
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    "Rủi ro: %{x:.2f}%<br>"
                    "Lợi suất: %{y:.2f}%<br>"
                    "<extra></extra>"
                ),
            )
        )

    # Day 11 Cụm 3d: highlighted marker for user-selected point via slider
    if selected_idx is not None and 0 <= selected_idx < len(curve.points):
        sp = curve.points[selected_idx]
        fig.add_trace(
            go.Scatter(
                x=[float(sp.volatility_annual_pct)],
                y=[float(sp.expected_return_annual_pct)],
                mode="markers",
                name=f"Điểm chọn ({selected_idx + 1})",
                marker={
                    "size": 22,
                    "color": "rgba(255, 160, 74, 0.3)",
                    "symbol": "circle",
                    "line": {"color": "#DC2626", "width": 3},
                },
                hovertemplate=(
                    f"<b>Điểm đã chọn ({selected_idx + 1})</b><br>"
                    "Rủi ro: %{x:.2f}%/năm<br>"
                    "Lợi suất: %{y:.2f}%/năm<br>"
                    "<extra></extra>"
                ),
                showlegend=True,
            )
        )

    fig.update_layout(
        title=_t("f1_chart_title"),
        xaxis_title=_t("f1_chart_x_label"),
        yaxis_title=_t("f1_chart_y_label"),
        height=450,
        hovermode="closest",
        template="plotly_white",
        margin={"l": 60, "r": 20, "t": 50, "b": 50},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": -0.25,
            "xanchor": "center",
            "x": 0.5,
        },
    )

    st.plotly_chart(fig, use_container_width=True)


def _apply_f1_weights_callback(new_weights_pct: dict, source_label: str) -> None:
    """Callback: safely apply F1 weights to sidebar state (Day 11 Cụm 3d).

    Streamlit forbids direct assignment to a widget's key AFTER the widget
    is instantiated. Callbacks run BEFORE widget re-instantiation on the
    next rerun, so they can safely modify session_state.

    Clears:
        - weight_pct_<TICKER> widget keys (per-ticker number_input)
        - weight_mode widget key (sidebar radio)
    Sets:
        - weights_pct dict (new ticker->pct mapping)
        - weights_source (display label for sidebar status chip)
    """
    st.session_state["weights_pct"] = new_weights_pct
    st.session_state["weights_source"] = source_label
    # Delete per-ticker widget keys so number_input picks up new values
    for key in list(st.session_state.keys()):
        if key.startswith("weight_pct_"):
            del st.session_state[key]
    # Delete radio widget key so it picks up index=1 (manual) default on rerun
    if "weight_mode" in st.session_state:
        del st.session_state["weight_mode"]


def _clear_f1_weights_callback() -> None:
    """Clear F1-applied weights state so user can switch back to manual/equal."""
    if "weights_source" in st.session_state:
        del st.session_state["weights_source"]
    if "weight_mode" in st.session_state:
        del st.session_state["weight_mode"]
    # Keep weights_pct dict so manual inputs show previous F1 values as starting point


def _render_f1_section(preview_config: dict | None, factory) -> None:
    """Day 11 F1: Efficient Frontier section rendered in main area.

    Flow (Option C design):
        1. Section header + intro + defense note
        2. Advanced controls (upper_bound slider + n_points input)
        3. "Compute Frontier" button -> calls FrontierService
        4. If result in session_state: render Plotly chart + slider + weights
        5. "Apply weights" button -> populates session_state.weights_pct
           and reruns (user then clicks "Run simulation" in sidebar)
    """
    st.markdown("---")
    st.markdown(f"### {_t('f1_section_header')}")
    st.markdown(_t("f1_section_intro"))

    # Advanced controls - 2 columns side by side
    _f1_c1, _f1_c2 = st.columns([1, 1])
    with _f1_c1:
        upper_bound = st.slider(
            _t("f1_upper_bound_label"),
            min_value=0.1,
            max_value=1.0,
            value=st.session_state.get("f1_upper_bound_val", 0.4),
            step=0.05,
            format="%.2f",
            help=_t("f1_upper_bound_help"),
            key="f1_upper_bound_val",  # gitleaks:allow (Streamlit widget key, not a secret)
        )
    with _f1_c2:
        n_points = st.number_input(
            _t("f1_n_points_label"),
            min_value=5,
            max_value=50,
            value=st.session_state.get("f1_n_points_val", 20),
            step=1,
            help=_t("f1_n_points_help"),
            key="f1_n_points_val",
        )

    # Guard: F1 compute requires >= 2 tickers
    f1_ready = preview_config is not None

    compute_pressed = st.button(
        _t("f1_compute_btn"),
        type="primary",
        disabled=not f1_ready,
        help=_t("f1_compute_btn_help"),
        key="f1_compute_btn_action",
        use_container_width=True,
    )

    if not f1_ready:
        st.info(_t("f1_need_min_tickers"))

    if compute_pressed and f1_ready:
        from vn_portfolio_frontier.application.services import FrontierRequest

        try:
            with st.spinner(_t("f1_computing")):
                service = factory.frontier_service()
                request = FrontierRequest(
                    tickers=preview_config["tickers"],
                    backtest_start=preview_config["backtest_start"],
                    backtest_end=preview_config["backtest_end"],
                    rf_source=preview_config["rf_source"],
                    upper_bound=float(upper_bound),
                    n_frontier_points=int(n_points),
                )
                result = service.compute(request)
                st.session_state["f1_result"] = result
                # Day 11 Cụm 3f #2: default slider = frontier point closest to MaxSharpe
                # (optimal risk-adjusted return per Markowitz theory) instead of midpoint
                # which has no financial meaning
                _curve = result.frontier_curve
                _target_sharpe = _curve.ref_max_sharpe.sharpe
                _best_idx = min(
                    range(len(_curve.points)),
                    key=lambda i: abs(_curve.points[i].sharpe - _target_sharpe),
                )
                st.session_state["f1_slider_val"] = _best_idx + 1
                st.session_state["f1_selected_point_idx"] = _best_idx
                st.success(
                    _t(
                        "f1_computed_ok",
                        n=len(result.frontier_curve.points),
                        days=result.data_window_days,
                        rows=result.returns_rows,
                    )
                )
        except Exception as exc:
            st.error(f"F1 computation failed: {exc}")
            if "f1_result" in st.session_state:
                del st.session_state["f1_result"]

    # Render chart + slider + weights if result available
    result = st.session_state.get("f1_result")
    if result is None:
        st.markdown("---")
        return

    curve = result.frontier_curve
    # Day 11 Cụm 3d: pass selected_idx so chart highlights the picked point
    _selected_idx_from_state = st.session_state.get("f1_selected_point_idx", len(curve.points) // 2)
    _selected_idx_clamped = min(_selected_idx_from_state, len(curve.points) - 1)
    _render_f1_chart(curve, selected_idx=_selected_idx_clamped)

    # Slider for point selection (1-indexed display for UX, 0-indexed internal)
    n_points_total = len(curve.points)
    default_1idx = st.session_state.get("f1_slider_val", n_points_total // 2 + 1)
    default_1idx = max(1, min(default_1idx, n_points_total))
    slider_1idx = st.slider(
        _t("f1_slider_label"),
        min_value=1,
        max_value=n_points_total,
        value=default_1idx,
        step=1,
        help=_t("f1_slider_help"),
        key="f1_slider_val",
    )
    selected_idx = slider_1idx - 1  # 0-indexed for list access
    st.session_state["f1_selected_point_idx"] = selected_idx  # for chart highlight
    selected_point = curve.points[selected_idx]

    # Selected point metrics + weights
    st.markdown(f"#### {_t('f1_selected_point_header')}")
    sharpe_display = (
        f"{float(selected_point.sharpe):.4f}" if selected_point.sharpe is not None else "N/A"
    )
    # Day 11 Cụm 3f #4: visual Sharpe quality badge next to numeric value
    _sharpe_val = float(selected_point.sharpe) if selected_point.sharpe is not None else None
    _badge_html = _sharpe_badge(_sharpe_val)
    _metrics_text = _t(
        "f1_selected_point_metrics",
        ret=f"{float(selected_point.expected_return_annual_pct):.2f}",
        vol=f"{float(selected_point.volatility_annual_pct):.2f}",
        sharpe=sharpe_display,
    )
    st.markdown(_metrics_text + _badge_html, unsafe_allow_html=True)
    # Day 11 Cụm 3f #13: ex-ante disclaimer to prevent confusion between F1
    # theoretical metrics and realized simulation metrics
    st.caption(_t("f1_ex_ante_caption"))

    # Day 11 Cụm 3e D.1: Chip-style weights (compact, scannable, no dataframe grid)
    # Color intensity by weight magnitude: top-weight = dark green, lighter = pastel
    non_zero_weights = {ticker: w for ticker, w in selected_point.weights.items() if w > 0.001}
    _sorted_weights = sorted(non_zero_weights.items(), key=lambda kv: kv[1], reverse=True)

    st.markdown(f"**{_t('f1_weights_table_header')}:**")

    _chip_parts = []
    for _ticker, _w in _sorted_weights:
        _pct = _w * 100
        if _pct >= 25:
            _bg, _fg = "#146026", "#FFFFFF"
        elif _pct >= 15:
            _bg, _fg = "#D1FAE5", "#065F46"
        else:
            _bg, _fg = "#F0FDF4", "#146026"
        _chip_parts.append(
            f'<span style="display:inline-block;padding:5px 12px;margin:3px 5px 3px 0;'
            f"border-radius:999px;background:{_bg};color:{_fg};"
            f'font-size:13px;font-weight:600;line-height:1.4;">'
            f'{_ticker}&nbsp;<span style="opacity:0.9;font-weight:500;">{_pct:.1f}%</span>'
            f"</span>"
        )
    st.markdown(
        f'<div style="margin:6px 0 14px 0;line-height:2;">{"".join(_chip_parts)}</div>',
        unsafe_allow_html=True,
    )

    # Apply weights button — uses on_click callback (Day 11 Cụm 3d fix)
    # Callback runs BEFORE widget re-instantiation on next rerun, safe to
    # modify weight_mode widget key then.
    new_weights_pct = {ticker: w * 100 for ticker, w in non_zero_weights.items()}
    for ticker in st.session_state.get("selected_tickers", []):
        if ticker not in new_weights_pct:
            new_weights_pct[ticker] = 0.0

    # Day 11 Cụm 3f #3 (X4-micro): add 3rd column "Chạy mô phỏng ngay" to avoid
    # ping-pong UX (user had to scroll back to sidebar after applying F1 weights)
    _f1_btn_col1, _f1_btn_col2, _f1_btn_col3 = st.columns([2, 1, 2])
    _has_f1_applied = st.session_state.get("weights_source", "").startswith("F1")

    with _f1_btn_col1:
        # Day 11 Cum 5 D6: demote to secondary after apply so "Chạy mô phỏng ngay"
        # (primary) becomes the clear next action
        st.button(
            _t("f1_apply_btn"),
            type="secondary" if _has_f1_applied else "primary",
            on_click=_apply_f1_weights_callback,
            args=(new_weights_pct, f"F1 Điểm {selected_idx + 1}"),
            key="f1_apply_action",
            use_container_width=True,
        )
    with _f1_btn_col2:
        if _has_f1_applied:
            st.button(
                "↩️ Hủy F1",
                type="secondary",
                on_click=_clear_f1_weights_callback,
                key="f1_clear_action",
                use_container_width=True,
                help="Hủy áp dụng F1, quay về tự nhập tỷ trọng ở sidebar",
            )
    with _f1_btn_col3:
        if _has_f1_applied and st.button(
            "▶️ Chạy mô phỏng ngay",
            type="primary",
            key="f1_run_action",
            use_container_width=True,
            help="Chạy backtest ngay với tỷ trọng F1 vừa áp dụng",
        ):
            st.session_state["f1_trigger_sim"] = True
            st.rerun()

    # 3 reference portfolios footer
    with st.expander(_t("f1_ref_portfolios_header"), expanded=False):
        _ref_cols = st.columns(3)
        ref_entries = [
            ("f1_ref_min_variance", curve.ref_min_variance),
            ("f1_ref_max_sharpe", curve.ref_max_sharpe),
            ("f1_ref_risk_parity", curve.ref_risk_parity),
        ]
        for i, (label_key, portfolio) in enumerate(ref_entries):
            with _ref_cols[i]:
                # Day 11 Cum 5 D7: concentration warning if top-2 weights > 70%
                _sorted_w = sorted(portfolio.weights.values(), reverse=True)
                _top2_sum = sum(_sorted_w[:2]) if len(_sorted_w) >= 2 else 0.0
                _concentration_badge = ""
                if _top2_sum > 0.70:
                    _concentration_badge = (
                        f'<span style="display:inline-block;padding:1px 6px;'
                        f"margin-left:6px;border-radius:999px;background:#FEF3C7;"
                        f'color:#92400E;font-size:10px;font-weight:600;">'
                        f"⚠ Tập trung {_top2_sum*100:.0f}% top-2</span>"
                    )
                # Day 11 Cum 5 D8: card wrapper with bg + border for visual separation
                sharpe_text = (
                    f"Sharpe: {float(portfolio.sharpe):.4f}"
                    if portfolio.sharpe is not None
                    else "Sharpe: N/A"
                )
                top_weights = sorted(portfolio.weights.items(), key=lambda x: -x[1])[:5]
                _weights_html = "<br>".join(
                    f"{t}: {w*100:.1f}%" for t, w in top_weights if w > 0.001
                )
                st.markdown(
                    f'<div style="background:#F9FAFB;border:1px solid #E5E7EB;'
                    f'border-radius:8px;padding:12px;margin:4px 0;">'
                    f'<div style="font-weight:600;font-size:14px;margin-bottom:8px;">'
                    f"{_t(label_key)}{_concentration_badge}</div>"
                    f'<div style="font-size:12px;color:#6B7280;line-height:1.6;">'
                    f"Lợi suất: {float(portfolio.expected_return_annual_pct):.2f}%/năm<br>"
                    f"Rủi ro: {float(portfolio.volatility_annual_pct):.2f}%/năm<br>"
                    f"{sharpe_text}"
                    f"</div>"
                    f'<div style="font-size:12px;color:#1F2937;margin-top:8px;line-height:1.6;">'
                    f"{_weights_html}"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    st.caption(_t("f1_defense_note"))
    st.markdown("---")


def _render_help():
    with st.expander(_t("help_header")):
        content = (
            f"{_t('help_step1')}\n\n"
            f"{_t('help_step2')}\n\n"
            f"{_t('help_step3')}\n\n"
            f"{_t('help_step4')}\n\n"
            f"{_t('help_step5')}\n\n"
            f"{_t('help_step6')}\n\n"
            f"{_t('help_step7')}"
        )
        st.markdown(content)


# =====================================================================
# Main
# =====================================================================


def main():
    st.markdown(_CSS, unsafe_allow_html=True)

    # Day 10 Step C: removed main-area language selector (duplicate of sidebar
    # VI/EN toggle). Sidebar is single source of truth for language choice.
    st.markdown(
        f'<div class="combined-header">'
        f'<h1>{html.escape(_t("page_title"))}</h1>'
        f'<div class="subtitle">{html.escape(_t("page_subtitle"))}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    _render_about()
    _render_help()

    config = _render_sidebar()

    # Day 11 F1: Efficient Frontier section (optional, computed independently of Run button)
    # Allows user to preview optimal portfolios + apply weights before full simulation.
    preview_config = _build_preview_config()
    _render_f1_section(preview_config, get_factory())

    if config is not None:
        st.session_state.run_status = "running"
        st.session_state.last_config = config
        _run_backtest(config)

    if st.session_state.run_status == "idle":
        st.info(_t("idle_msg"))
    elif st.session_state.run_status == "failed":
        st.error(_t("failed_msg", error=st.session_state.last_error))
    elif st.session_state.run_status == "completed" and st.session_state.last_result is not None:
        _render_results(
            st.session_state.last_result,
            st.session_state.get("last_config", {}),
        )


if __name__ == "__main__":
    main()
