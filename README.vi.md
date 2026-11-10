# vn-portfolio-frontier

> **Nền tảng nghiên cứu** cho tối ưu danh mục Markowitz, mô phỏng tái cân bằng tự động, và trích xuất tín hiệu có cấu trúc từ tin tức tài chính Việt Nam trên rổ VN30. Là bước nền tảng cho một trợ lý AI đầu tư dài hạn được phát triển trong khuôn khổ một đồ án nghiên cứu học thuật.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Trạng thái](https://img.shields.io/badge/trạng%20thái-đang%20phát%20triển-green)]()
[![Mục đích học thuật](https://img.shields.io/badge/mục%20đích-học%20thuật%20%2F%20giáo%20dục-blueviolet)]()

> ⚠️ **Chỉ dùng cho mục đích học thuật và nghiên cứu.** Nền tảng này là một đồ án nghiên cứu đại học. Nó **không phải** dịch vụ tư vấn đầu tư chứng khoán được cấp phép theo Điều 72 Luật Chứng khoán Việt Nam (54/2019/QH14). Nền tảng không đưa ra khuyến nghị mua/bán/nắm giữ cho các mã chứng khoán cụ thể. Mọi quyết định đầu tư là trách nhiệm của người dùng và nên tham khảo chuyên gia tư vấn có giấy phép.

**English README (chi tiết đầy đủ hơn):** [README.md](./README.md)

---

## Giới thiệu

Nhà đầu tư cá nhân Việt Nam thường đối mặt với ba câu hỏi định lượng mà các công cụ cấp tổ chức giải quyết tốt nhưng công cụ công khai dành cho giáo dục thì ít khi làm được:

1. **Phân bổ** — Tỷ trọng danh mục nào tối ưu đánh đổi rủi ro-lợi nhuận cho một tập mã cho trước?
2. **Tái cân bằng** — Khi nào và như thế nào nên điều chỉnh phân bổ để duy trì rủi ro mục tiêu, có tính đến chi phí giao dịch đặc thù Việt Nam?
3. **Tín hiệu thông tin** — Làm sao chuyển hóa tin tức tài chính công bố thành tín hiệu có cấu trúc, có thể kiểm toán, thay vì các điểm số sentiment mờ ảo?

Đồ án xây dựng ba thành phần nền tảng cho một lộ trình nghiên cứu học thuật trả lời các câu hỏi này, với phạm vi được xác định rõ ràng cho bối cảnh thị trường Việt Nam (quy định lot size HSX, thuế TNCN theo Thông tư 111/2013, sự tiến hóa của rổ VN30, lãi suất tham chiếu từ NHNN).

Đối tượng: **nhà nghiên cứu học thuật, sinh viên định lượng tài chính, và nhà đầu tư tự chủ (self-directed) muốn tìm công cụ giáo dục để hiểu về lý thuyết danh mục và động học thị trường do tin tức dẫn dắt**. Nền tảng được định vị là một tạo tác nghiên cứu và công cụ giáo dục — không phải dịch vụ tư vấn thương mại.

## Bối cảnh đồ án

Đây là **Project 2** trong lộ trình nghiên cứu bốn giai đoạn hướng tới Đồ án Tốt nghiệp chương trình Kỹ sư Công nghệ Thông tin tại Đại học Bách khoa Hà Nội (HUST), 2025-2027:

| Giai đoạn | Thời gian | Phạm vi |
|---|---|---|
| Project 1 — MVP | 04-05/2025 | Minimum-variance optimizer 29 mã VN30, SQLite, scipy baseline ([v1.0.0 released](https://github.com/MCTGiang/vn-portfolio-optimizer)) |
| **Project 2 — Nền tảng (repo này)** | 09-11/2026 | Full Markowitz efficient frontier + auto-rebalancing + structured news signal corpus + Hexagonal architecture |
| Project 3 — Platform | 12/2026-02/2027 | FastAPI backend, 3-tier auth, Agentic RAG prototype, live prediction tracker |
| Đồ án Tốt nghiệp — Trợ lý AI | 03-06/2027 | Trợ lý giáo dục full-stack với usability study và đánh giá empirical |

Project 2 **không phải** sản phẩm end-user hoàn chỉnh. Đây là một nền tảng nghiên cứu đã validate với các outputs (dịch vụ tối ưu, mô phỏng rebalance, kho tin tức có nhãn) phục vụ các giai đoạn tiếp theo.

## Milestones gần đây

- `v2.0-sprint12-adr019` (02/11/2026) — Live Prediction Tracking (ADR-019) production go-live
- `v2.0-phase2-ux` (06/11/2026) — Phase 2 UX refactor workflow tuyến tính (Bước 1 → 2 → 3 stepper)
- Phase C sentiment audit hoàn thành (09/11/2026) — 200 mẫu review độc lập, Sentiment Cohen's κ = 0,967 ("almost perfect"), 2/4 hypothesis đạt ngưỡng

---

## Tính năng

Trạng thái: ✅ Đã hoàn thành · 🚧 Đang làm · 📋 Kế hoạch (giai đoạn tiếp theo)

### Project 2 (repository này)

- ✅ **Đường biên hiệu quả (F1)** — Full Markowitz efficient frontier với 3 danh mục tham chiếu (Minimum Variance, Max Sharpe, Risk Parity) và đường cong 20 điểm cho người dùng chọn theo khẩu vị rủi ro. Triển khai qua `scipy.optimize` SLSQP (xem ADR-017).
- ✅ **Mô phỏng tái cân bằng tự động (F2)** — Ba chiến lược tái cân bằng (Threshold Band 500 bps mặc định, Calendar Monthly, Fixed Window 90 ngày) với mô hình chi phí đặc thù Việt Nam (thuế TT 111/2013, lot size HSX theo QĐ 496, phí môi giới nhập liệu). Strategy Pattern (GoF) cho phép mở rộng chiến lược mới mà không sửa engine backtest (ADR-015).
- ✅ **Kho tín hiệu có cấu trúc từ tin tức (F3)** — Dataset có nhãn 699 bài tin tức tài chính Việt Nam với schema 11-trường (`ticker`, `event_type`, `sentiment`, `magnitude`, `entities`, ...) trích xuất qua Claude Sonnet 5-5 teacher model. **Phase C audit** (200 mẫu phân tầng, human review độc lập) hoàn thành 09/11/2026: Sentiment Cohen's κ = 0,967 ("almost perfect" per Landis-Koch 1977), Relevance accuracy = 96,5%. Định vị là nền tảng evidence base cho Agentic Retrieval-Augmented Generation (RAG) ở các giai đoạn tiếp theo, không phải sentiment classifier độc lập.
- ✅ **Theo dõi dự đoán trực tiếp** — Logger dự đoán hàng ngày (ADR-019) chạy từ 02/11/2026 để tích lũy 155+ quan sát giao dịch phục vụ đánh giá empirical ở giai đoạn thesis.
- ✅ **Hexagonal Architecture** — Phân tách bốn lớp (Domain / Application / Infrastructure / Interface) theo Cockburn (2005) với Protocol-based ports. Đã được validate bởi hai case study thực tế: scipy fallback khi `vnstock_quant` khóa auth (ADR-017), và Task Scheduler bypass cho `vnstock` device-lock (ADR-018).
- ✅ **Xuất báo cáo** — Tải kết quả backtest dưới dạng PDF (executive summary) hoặc Excel (4 sheet: Config, KPIs, Decisions, DailyValues) để chia sẻ với stakeholders hoặc lưu hồ sơ phân tích. Hỗ trợ font tiếng Việt với fallback theo platform (Arial Windows → DejaVu Linux → Helvetica).

### Xem trước giai đoạn tiếp theo (không triển khai trong Project 2)

- 📋 **FastAPI REST backend** (Project 3) — Expose F1 và F2 dưới dạng REST endpoints cho Agentic chatbot tool consumption.
- 📋 **Trợ lý AI tác tử** (Thesis) — LangGraph orchestration với 5-7 tool, hybrid RAG retrieval trên kho tin tức có nhãn, 3-tier authentication (định vị giáo dục, không bán tư vấn live).
- 📋 **Báo cáo đánh giá empirical** (Thesis) — Phân tích MDA, IC, Jensen's Alpha, Sharpe từ 7+ tháng dữ liệu dự đoán trực tiếp.

## Stack công nghệ

| Lớp | Lựa chọn | Lý do |
|-----|---------|------|
| Ngôn ngữ | Python 3.11-3.13 (matrix test trong CI) | pandas 3.0+ yêu cầu 3.11+ |
| Database | Neon Cloud PostgreSQL (Singapore) | Managed service, 0.5 GB free tier đủ cho ~215K dòng ở phạm vi Project 2 |
| Tối ưu danh mục | scipy SLSQP (ADR-017) | Chuẩn ngành (LEAN, zipline, backtrader); không phụ thuộc vendor |
| Gán nhãn tin tức | Claude Sonnet 5-5 teacher model | Chất lượng tiếng Việt tốt; schema 11-trường (ADR-006) |
| Kiến trúc retrieval | Agentic RAG (Project 3+) | Linh hoạt hơn fine-tuned classifier ở corpus size <1000 (ADR-008 resolution 02/11/2026) |
| Frontend | Streamlit (nội bộ / admin), Next.js kế hoạch (Project 3+ end-user) | Streamlit cho research prototype; Next.js cho Agentic chatbot UI |
| Orchestration | Windows Task Scheduler (ADR-018) | Bắt buộc do vnstock Silver device-lock |
| CI/CD | GitHub Actions matrix Python 3.11/3.12/3.13 + pip-audit | 1,4 phút/run |

## Cài đặt

Chi tiết đầy đủ trong [README.md tiếng Anh](./README.md#getting-started). Tóm tắt:

```bash
git clone https://github.com/MCTGiang/vn-portfolio-frontier.git
cd vn-portfolio-frontier
python -m venv .venv && source .venv/Scripts/activate
pip install -e ".[dev,data]"
cp .env.example .env  # điền Neon connection string + vnstock API key vào .env
```

**Không commit `.env`** — đã git-ignore.

## Nguồn dữ liệu

| Nguồn | Phạm vi | Tần suất | Truy cập |
|-------|---------|---------|---------|
| OHLCV VN30 | 30 mã, từ 04/01/2021 | Daily close | vnstock Silver tier |
| Sự kiện VN30 membership | 11 rebalance 2021-2026 | Semi-annual | YAML seed + script (event-sourcing theo ADR-013) |
| Fundamentals | VN30 constituents | Quý | vnstock Silver (bronze/silver schema ADR-014) |
| Lãi suất tham chiếu | TPCP 1Y, SBV refi, VCB 13M | Daily | vnstock Macro API |
| Tin tức tài chính | 18 nguồn tiếng Việt | Daily | vnstock_news Silver tier |

Dữ liệu lịch sử bắt đầu từ **04/01/2021** — ngày HSX đổi lot size từ 10 lên 100 cổ/lot (Quyết định 496/QĐ-SGDHCM). Backtest trước mốc này đòi hỏi xử lý rule split lot, defer sang giai đoạn thesis.

## Tài liệu

- **Architecture Decision Records**: [`docs/architecture.md`](./docs/architecture.md) — 19 ADR document các quyết định
- **Nygard format**: [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- **Meta-process lessons**: `docs/decisions-and-learnings.md` — 38 bài học rút ra trong quá trình phát triển

## Đóng góp

Pull requests cho bug fixes, cải thiện tài liệu, hoặc thảo luận methodology được chào đón. Pull requests triển khai feature mới sẽ được review trong bối cảnh phạm vi nghiên cứu của đồ án. Xem [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## License

MIT — xem [`LICENSE`](./LICENSE). License MIT áp dụng cho source code. Mọi derived use cho tư vấn đầu tư thương mại cần tuân thủ Luật Chứng khoán 54/2019/QH14 và được cấp phép bởi tổ chức có nghiệp vụ tư vấn chứng khoán.

## Thông báo pháp lý

Đồ án này là **tạo tác nghiên cứu** được phát triển trong khuôn khổ một đồ án tốt nghiệp đại học tại Đại học Bách khoa Hà Nội. Nó không phải dịch vụ tư vấn đầu tư được cấp phép và không đưa ra khuyến nghị đầu tư cho các mã chứng khoán cụ thể theo định nghĩa tại Điều 72 và Điều 86 Luật Chứng khoán 54/2019/QH14. Người dùng chịu trách nhiệm hoàn toàn cho mọi quyết định đầu tư. Để được tư vấn đầu tư thực sự, hãy liên hệ chuyên gia có giấy phép thuộc công ty chứng khoán có giấy phép UBCKNN hợp lệ.

## Lời cảm ơn

- **VinAI Research** cho mô hình PhoBERT (dùng cho phân tích exploratory trong giai đoạn thiết kế ban đầu; kiến trúc F3 cuối cùng pivot sang Agentic RAG theo ADR-008 resolution 02/11/2026).
- **Neon** cho managed PostgreSQL với free tier phù hợp phần cứng dev 8 GB RAM.
- **Anthropic** cho Claude Sonnet 5-5 teacher model.
- **vnstock team** cho quyền truy cập Silver tier dữ liệu thị trường Việt Nam.

---

Phát triển trong khuôn khổ **Project 2** chương trình Kỹ sư Công nghệ Thông tin bằng 2 tại HUST (2025-2027). Hạn nộp Project 2: **17/11/2026**. Bảo vệ Đồ án Tốt nghiệp: **06/2027**.
