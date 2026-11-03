# ADR-020: Thesis scope lock — Agentic AI advisor for Vietnamese retail investors

**Status:** Proposed
**Date:** 2026-11-02 (draft) · lock target 2026-11-30
**Deciders:** Mai Công Trà Giang (Ginny) · Pending GVHD TS. Nguyễn Đức Anh sign-off
**Sprint:** Sprint 12 continuation · Pre-Project 3 planning
**Supersedes:** None (original thesis scope "Microservices platform tích hợp P1+P2+P3" pivoted per GVHD feedback 30/10/2026)
**Related:** ADR-015 (Hexagonal), ADR-019 (Live Prediction Tracking), ADR-022 (Educational positioning — proposed)

---

## 1. Context

### 1.1 Original thesis scope and problems

Scope ban đầu của Đồ án Tốt nghiệp (ĐATN), đặt tại Sprint 1 Project 1 (04/2025) và carried forward đến tháng 10/2026, là:

> *"Microservices platform tích hợp Project 1 (vn-portfolio-optimizer) + Project 2 (vn-portfolio-frontier) + Project 3 (ensemble ML + VaR/CVaR + Backtest) thành SaaS production với Docker + CI/CD"*

Scope này tập trung vào **engineering infrastructure** (microservices + Docker + CI/CD + API gateway) hơn là research contribution. Trong buổi gặp Giảng viên hướng dẫn (GVHD) TS. Nguyễn Đức Anh ngày 30/10/2026 và 02/11/2026, bốn phản hồi phương pháp luận quan trọng được đưa ra:

1. Scope hiện tại là **engineering scope**, chưa có research question định lượng để bảo vệ bằng dữ liệu thực nghiệm.
2. Realtime trading data pipeline **không khả thi** trong bối cảnh thị trường Việt Nam (news lag 1-6 giờ, archive sạch chỉ 5-6 năm, API realtime quốc tế vượt ngân sách sinh viên).
3. Phương pháp binary sentiment classification **lỗi thời** (paradigm 2015-2020), đã được thay thế bởi structured event extraction + multi-dimensional signal modeling trong literature NLP finance post-2022.
4. Tác động tin tức đến giá có **cấu trúc phân cấp 3 tier** (micro / meso / macro), không thể modeling bằng một mô hình đơn.

GVHD gợi ý pivot sang: **"Web/app platform với chat bot agentic AI + authentication + 3-tier free/paid + evaluation protocol vs real market."**

### 1.2 Opportunity

Ba yếu tố làm pivot này thành chiến lược thắng:

1. **Nền tảng P2 đã tích hợp sẵn**: Hexagonal Architecture (ADR-015) + 213+ unit tests + 19 ADRs + Live Prediction Tracking pipeline (ADR-019 go-live 02/11/2026) đã validate kiến trúc và chuẩn bị dữ liệu empirical.
2. **Tác giả có credentials phù hợp**: 16 năm kinh nghiệm ngành chứng khoán tại VCBS + Chứng chỉ hành nghề Phân tích chứng khoán (CKPT) do UBCKNN cấp → defendable positioning cho financial advisor system.
3. **Thời điểm công nghệ chín muồi**: Agentic AI frameworks (LangGraph, CrewAI) stabilize 2025-2026; Claude Sonnet 5-5 + PhoBERT family support Vietnamese; pgvector + bge-m3 enable hybrid RAG at pricing phù hợp sinh viên.

---

## 2. Decision

Lock scope Đồ án Tốt nghiệp theo research question tổng quát và 3 câu hỏi phụ:

### 2.1 Research question tổng quát

> **"Hệ thống trợ lý AI tác tử (Agentic AI advisor) có cải thiện được chất lượng ra quyết định đầu tư dài hạn (horizon 6 tháng - 2 năm) của nhà đầu tư cá nhân Việt Nam so với baseline tự ra quyết định (self-directed) hay không?"**

### 2.2 Ba câu hỏi phụ

- **RQ1 (Methodology)**: Kiến trúc Agentic Retrieval-Augmented Generation (RAG) có hiệu quả trong việc trích xuất tín hiệu có ý nghĩa từ corpus tin tức tài chính tiếng Việt không? Đánh giá qua ablation study các component (retriever, reranker, LLM reasoner).
- **RQ2 (Empirical)**: Độ chính xác dự đoán long-term của hệ thống đạt mức nào khi đo bằng các metric chuẩn ngành — Mean Directional Accuracy (MDA), Information Coefficient (IC), Information Coefficient Information Ratio (ICIR), Jensen's Alpha, Sharpe Ratio, Hit rate top-5?
- **RQ3 (UX)**: Người dùng cuối (nhà đầu tư cá nhân) có cảm nhận hệ thống hữu ích hơn so với tự nghiên cứu không? Đánh giá qua usability study (10 user × 2 tuần, Net Promoter Score, retention rate).

### 2.3 Scope boundary

**IN scope:**
- Universe: VN30 (kế thừa P2) + 5 ngành chính mở rộng (Bank, Real-estate, IT, Consumer, Securities) qua `equity.list_by_industry(ICB)`
- Horizon: long-term 6M-2Y
- News impact tiers: Micro (ticker-specific) + Meso (sector) — Phase 1
- Dataset: Agentic RAG trên labeled corpus (reuse 699 labels P2, mở rộng 5000 ở P3)
- Testing period: 03/11/2026 → 15/06/2027 (155+ trading days, N ≥ 125 obs cho p<0.05)
- Positioning: *"Educational self-directed investing platform"*, không "advisory service" (ADR-022 enforcement)

**OUT of scope (defer post-thesis hoặc phiên bản 2):**
- Realtime trading (not feasible, không có value với VN news lag)
- News macro tier (vĩ mô toàn cầu — vượt ngân sách Reuters/Bloomberg)
- Payment real integration (legal exposure UBCKNN; mock đủ cho defense)
- Multi-asset (bond, ETF, futures) — scope VN30 cổ phiếu
- Mobile native app (PWA đủ cho thesis)

### 2.4 Architecture (5 component mới trên nền P2)

| Component | Technology | Rationale |
|---|---|---|
| Backend API | FastAPI | Reuse P2 Python stack, auto OpenAPI, async, Hexagonal Driving Adapter mới |
| Frontend | Next.js 15 + TypeScript + shadcn/ui + Tailwind + TradingView Lightweight Charts | SEO-friendly, Vercel deploy free, modern CV signal |
| Agentic chatbot | LangGraph + Claude Sonnet 5-5 (teacher) + Haiku (fallback) | State machine chặt chẽ, Vietnamese capable, structured output reliable |
| Hybrid RAG | pgvector in Neon + bge-m3 multilingual embeddings + Claude reranker | BM25 + dense + rerank state-of-art 2026 |
| Auth + tier | Clerk hoặc Supabase + 3-tier RBAC | Free (10 câu/ngày + F1 basic) / Pro (199k/tháng unlimited) / Enterprise (999k custom) |

### 2.5 Deliverable milestones

**Project 3 (12/2026 — 02/2027): Platform foundation**

| Sprint | Thời gian | Deliverable |
|---|---|---|
| 1 | 01-15/12/2026 | FastAPI backend + migrate F1/F2 → REST endpoints + Streamlit admin tool kept |
| 2 | 16-31/12/2026 | Authentication (Clerk) + user model + 3-tier RBAC feature flag middleware |
| 3 | 01-15/01/2027 | Prediction logger production (đã khởi động 02/11/2026 — ADR-019) + monitoring dashboard |
| 4 | 16-31/01/2027 | News crawler scale-up (18 → 30+ sources) + corpus labeling 699 → 5000 |
| 5 | 01-15/02/2027 | pgvector + bge-m3 embedding pipeline + hybrid search BM25+dense+rerank prototype |
| 6 | 16-28/02/2027 | Agentic workflow prototype 1-3 tools + internal demo |

**Đồ án Tốt nghiệp (03-06/2027): Full system + evaluation**

| Sprint | Thời gian | Deliverable |
|---|---|---|
| 1 | Tháng 03/2027 | Next.js frontend MVP + chat interface + tích hợp FastAPI |
| 2 | Tháng 03-04/2027 | Agentic workflow 5-7 tool full + multi-turn conversation + memory layer |
| 3 | Tháng 04/2027 | Payment flow mock + 3-tier go-live + onboarding 10 beta user |
| 4 | Tháng 04-05/2027 | Usability study 10 user × 2 tuần + feedback collection + NPS |
| 5 | Tháng 05/2027 | Evaluation analysis: MDA / IC / Alpha từ 7+ tháng live data |
| 6 | Tháng 05-06/2027 | Thesis writing + defense prep + pilot deployment |

---

## 3. Alternatives considered

### 3.1 Giữ nguyên scope cũ (microservices platform)
Rejected vì các lý do ở Section 1.1 (engineering vs research scope, GVHD feedback explicit).

### 3.2 Scope hẹp: Chỉ ensemble ML + VaR/CVaR không user-facing
Rejected vì:
- Thiếu user-centric evaluation (không có RQ3 UX)
- Không chứng minh được architecture value qua integration
- Thesis defense panel kỳ vọng working system, không chỉ model + metrics

### 3.3 Scope rộng: Full fintech platform multi-feature (robo-advisor + trading + analytics)
Rejected vì:
- Vượt timeline 4 tháng ĐATN
- Legal exposure UBCKNN tăng (trading = môi giới license requirement)
- Risk scope creep → không hoàn thành

### 3.4 Giữ realtime trading theo gợi ý original P1→Thesis
Rejected per GVHD feedback point 2 (VN news lag + archive limits + API cost realtime quốc tế).

### 3.5 PhoBERT fine-tune focus thay vì RAG
Rejected per ADR-008 Resolution 02/11/2026 (corpus size 699 ở biên dưới PhoBERT threshold; RAG flexibility + modern paradigm phù hợp long-term advisor horizon).

---

## 4. Consequences

### 4.1 Positive

- **Clear research question** với 3 sub-RQ có thể defendable bằng empirical evidence (ADR-019 live data) + ablation study (RQ1) + usability metrics (RQ3).
- **Reuse 100% P2 foundation** — zero sunk cost, Hexagonal architecture + 19 ADRs + corpus + live tracking all carry forward.
- **Novel contribution**: Agentic RAG cho Vietnamese financial advisor — chưa có công trình tương đương trong literature VN đến 11/2026.
- **Career signal mạnh**: Full-stack SaaS với auth + payment + Agentic AI → match target "Data Leader positioning by mid-2027".
- **Legal defensibility**: Educational positioning + 5 defensive patterns (ADR-022) + CKPT credential tăng credibility.
- **Alignment GVHD feedback**: 5/5 gợi ý được tiếp thu đầy đủ.

### 4.2 Negative

- **Technology risk**: Agentic AI frameworks (LangGraph) chín muồi nhưng còn churn API. Mitigation: lock version tại thesis start Mar 2027.
- **Cost risk**: Claude API cost ở scale thesis ~$30-60/tháng × 4 tháng = $120-240 budget. Mitigation: aggressive caching + Haiku fallback.
- **Timeline tight**: Chỉ 4 tháng ĐATN cho 6 sprint deliverable. Mitigation: milestone binding, hard stop features nếu Sprint 3 chưa xong 50%.
- **UX study logistics**: 10 beta user × 2 tuần cần tuyển dụng + onboarding effort. Mitigation: tuyển qua nhóm Zalo đầu tư cá nhân Ginny đã network.

### 4.3 Risks accepted

- **MDA < 55% / Alpha không ý nghĩa thống kê**: Thesis vẫn defendable dưới dạng "negative result" nếu methodology rigor được chứng minh. Negative result trong empirical research là valid contribution per statistical convention.
- **Legal exposure UBCKNN**: Educational positioning (ADR-022) + no "advisor" wording + 5 defensive patterns giảm risk nhưng không eliminate. Compliance VCBS cần notify trước public demo (May 2027).

---

## 5. Reversibility

ADR-020 là scope lock chính cho ĐATN, reversibility rất hạn chế — thay đổi scope sau Sprint 1 (Mar 2027) sẽ risk thesis deadline. Tuy nhiên các component có thể adjust:

- **Horizon**: Có thể shift 6M-2Y → 3M-1Y nếu data trong Sprint 5 cho thấy signal mạnh hơn ở short horizon
- **News tiers**: Macro tier có thể promote từ "defer" lên "included" nếu Project 3 Sprint 5 có data macro VN (SBV policy + CPI + GDP) sẵn
- **Payment**: Mock → real có thể swap post-thesis theo PaymentProcessor Protocol port

Fundamental changes (research question, universe, methodology) require GVHD approval + new ADR.

---

## 6. Implementation plan

| Date | Milestone |
|---|---|
| 02/11/2026 | ADR-020 draft shipped (this document) |
| 15/11/2026 | GVHD review session (prep slide deck summary) |
| 30/11/2026 | **ADR-020 lock** với GVHD sign-off |
| 01/12/2026 | Project 3 Sprint 1 kickoff |
| 15/06/2027 | Final live tracking data pull cho thesis evaluation |
| 30/06/2027 | **Thesis defense** |

---

## 7. References

- GVHD feedback meeting notes: `claude/p2_gvhd_feedback_strategic_review.md`
- Research question development: `claude/p2_action_pack_02112026.md`
- ADR-015 Hexagonal (architectural foundation)
- ADR-019 Live Prediction Tracking (empirical infrastructure)
- ADR-022 Educational positioning (legal strategy — proposed, deadline 15/01/2027)
- Grinold, R. C., & Kahn, R. N. (2000). *Active Portfolio Management* — statistical methodology
- Research track overview: `/projects/019f4064-ba1b-73d7-935b-e8cdbc21feb1/areas/vn-thesis-platform.md`
