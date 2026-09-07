# vn-portfolio-frontier

> Mở rộng Đường biên Hiệu quả và Tích hợp Phân tích Cảm xúc Thị trường cho Danh mục Chứng khoán Việt Nam.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

**Phiên bản tiếng Anh (đầy đủ hơn):** [README.md](./README.md)

---

## Giới thiệu

Kế thừa từ [`vn-portfolio-optimizer`](https://github.com/MCTGiang/vn-portfolio-optimizer) (Project 1 — MPT tối ưu portfolio VN30), dự án này mở rộng ba năng lực mới:

1. **Đường biên hiệu quả đầy đủ** — Không chỉ điểm biến động nhỏ nhất (MVP), người dùng chọn được portfolio ở bất kỳ mức rủi ro nào trên đường cong risk-return.
2. **Mô phỏng tái cân bằng tự động** — Tái tối ưu định kỳ với chi phí giao dịch, ràng buộc turnover, và tracking drift.
3. **Trích xuất tín hiệu từ tin tức tiếng Việt** — Structured extraction (loại sự kiện, mã CK, cường độ sentiment, entities) từ VnExpress, CafeF, VietStock. **Không** khẳng định "sentiment dự đoán được return" — positioning yếu và khó defense.

Đối tượng: Nhà đầu tư cá nhân Việt Nam và nghiên cứu viên định lượng làm việc với VN30.

## Tính năng

Trạng thái: ✅ Đã hoàn thành · 🚧 Đang làm · 📋 Kế hoạch

- 📋 Trực quan hoá đường biên hiệu quả (Streamlit)
- 📋 Mô phỏng tái cân bằng với chi phí giao dịch
- 📋 Sentiment tiếng Việt qua PhoBERT hoặc RAG
- 📋 Tích hợp dữ liệu fundamentals (nguồn dữ liệu thứ hai)

## Stack

| Lớp | Lựa chọn |
|-----|----------|
| Ngôn ngữ | Python 3.11+ |
| Database | Neon Cloud PostgreSQL (Singapore) |
| Orchestration | Prefect (dự kiến, chốt 2026-09-15) |
| Transformation | dbt |
| NLP | PhoBERT (fine-tune hoặc RAG, chốt 2026-10-20) |
| Frontend | Streamlit |
| CI/CD | GitHub Actions + pytest + black + ruff |

## Cài đặt

Chi tiết đầy đủ trong [README.md tiếng Anh](./README.md#getting-started). Tóm tắt:

```bash
git clone https://github.com/MCTGiang/vn-portfolio-frontier.git
cd vn-portfolio-frontier
cp .env.example .env  # điền connection string Neon vào .env
```

**Không commit `.env`** — đã git-ignore.

## Roadmap

- **Phase 1 (hiện tại):** Repo foundation, README, CI skeleton
- **Phase 2:** Setup Neon + thiết kế schema
- **Phase 3:** Prefect orchestration trong Docker
- **Phase 4:** dbt transformations
- **Phase 5:** Efficient frontier + rebalancing
- **Phase 6:** PhoBERT/RAG sentiment
- **Nộp:** 17/11/2026

## Dự án liên quan

- [`vn-portfolio-optimizer`](https://github.com/MCTGiang/vn-portfolio-optimizer) (Project 1) — Giảm **25.9% biến động** so với danh mục đều tay trên VN30 (v1.0.0, 15/08/2026).

## License

MIT — xem [LICENSE](./LICENSE).

---

Đồ án 2, chương trình kỹ sư IT bằng 2, HUST 2025-2027. Nộp **17/11/2026**.
