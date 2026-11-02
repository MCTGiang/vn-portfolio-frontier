# Legal Positioning Update — CKPT/CKQLQ Advantage

## 1. Giải thích chứng chỉ hành nghề chứng khoán (CCHN)

Theo Thông tư 197/2015 (sửa đổi bởi TT 97/2020) và Luật Chứng khoán 2019, UBCKNN cấp 3 loại CCHN cho cá nhân:

| CCHN | Số môn thi | Nghiệp vụ hành nghề | Mức độ |
|---|---|---|---|
| **CKMG** (Môi giới) | 3 | Môi giới chứng khoán tại CTCK | Cơ bản |
| **CKPT** (Phân tích tài chính) | 6 | Môi giới + Tự doanh + Phân tích + Bảo lãnh phát hành + **Tư vấn đầu tư** | Nâng cao |
| **CKQLQ** (Quản lý quỹ) | 7 | Toàn bộ nghiệp vụ CTCK + Quản lý quỹ đầu tư | Cao nhất |

---

## 2. Legal implications với dự án Agentic AI advisor

### 2.1 Những gì CCHN cho phép

| Hoạt động | Không có CCHN | Có CKPT/CKQLQ |
|---|---|---|
| Phân tích thị trường public (blog, video) | OK (không khuyến nghị cụ thể) | OK |
| Khuyến nghị MUA/BÁN cho khách hàng cá nhân | **Vi phạm Luật CK Đ.86** | **OK nếu làm với tư cách CTV/nhân viên CTCK** |
| Mở app tư vấn độc lập thu phí | Vi phạm | Vẫn vi phạm (app phải thuộc tổ chức có license) |
| Hợp tác với CTCK dưới dạng CTV | — | **OK** — chatbot có thể là tool nội bộ cho CTV |
| Thesis / nghiên cứu học thuật | OK | OK (có credential chuyên môn tăng credibility) |

### 2.2 Những gì CCHN KHÔNG tự động cho phép

- **Mở app tư vấn độc lập**: license tư vấn phải thuộc **tổ chức** (CTCK, CTQLQ), không phải cá nhân
- **Thu phí tư vấn trực tiếp từ user**: vẫn cần cơ chế bao bọc qua tổ chức có license
- **Public khuyến nghị cổ phiếu trên MXH với tư cách cá nhân**: xem thông báo UBCKNN 2026 — kể cả nhân viên CTCK CÓ CCHN vẫn bị cấm khuyến nghị trên MXH **ngoài kênh chính thức của công ty**

### 2.3 3 pathway hợp pháp cho thesis + hậu thesis

#### Pathway A — Academic positioning (safest, chọn cho thesis)

- Thesis demo = **research artifact**, không phải sản phẩm thương mại
- Vẫn giữ disclaimer "educational, not advisory" ở UI
- Audit log đầy đủ, user ToS mandatory
- **MCTGiang đã có Chứng chỉ hành nghề phân tích tài chính tăng credibility academic** mà không change legal exposure
- Thesis report có thể viết: *"Author là chuyên gia tài chính được UBCKNN cấp chứng chỉ hành nghề phân tích tài chính (CKPT), do đó thiết kế hệ thống phản ánh đúng chuẩn thực tiễn ngành."*

#### Pathway B — CTV của CTCK (post-thesis, nếu muốn commercialize)

- CTCK "bao" chatbot như internal tool cho CTV
- Doanh thu split theo thỏa thuận
- **Advantage**: MCTGiang có CKPT → **đủ điều kiện**, không như sinh viên bình thường

#### Pathway C — CTCK Internal product (optimal cho career)

- Pitch chatbot thành **Smart Advisor** nội bộ hoặc semi-public
- MCTGiang là product owner / technical lead
- CTCK cung cấp license + legal cover + user base
- **Advantage**: Zero legal risk cá nhân + career signal cực mạnh ("Launched AI product line at CTCK")
- **Risk**: Nội bộ chính trị, phê duyệt chậm, có thể không được approve

---

## 3. Updated ADR-022 draft (defensive positioning)

Trước đây dự định ADR-022 là "positioning + disclaimer + output filter". Giờ bổ sung:

### ADR-022: Legal Compliance & Positioning Strategy

**Decision:**

1. **Pathway A (Academic) cho thesis** — không change positioning
2. **Pathway C (VCBS internal) là mục tiêu post-thesis chính** — bắt đầu scoping với compliance team từ Q1/2027
3. **Pathway B (CTV CTCK)** là fallback nếu Pathway C bị block

4. Dù pathway nào, chatbot vẫn implement **5 defensive patterns**:
   - System prompt banning MUA/BÁN/NẮM GIỮ cụ thể
   - Output filter regex + Claude rewrite
   - Positioning "Educational" / "Research tool"
   - User ToS mandatory
   - Full audit trail

5. **Thesis report explicit** về CKPT credential:
   - Chapter 1 Introduction: tác giả là chuyên gia 16 năm ngành CK + CCHN CKPT
   - Chapter 2 Related Work: cite các robo-advisor VN hiện tại và pháp lý
   - Chapter 6 Future Work: pathway commercialization qua CTCK partnership

**Trade-offs:**

- Giữ positioning "educational" trong thesis mất đi **monetization narrative** cho defense panel, nhưng **giảm legal risk** về 0
- Pathway C đẹp nhất nhưng phụ thuộc approval VCBS, không controllable
- Vẫn phải implement 5 defensive patterns dù có CCHN — CCHN giảm *individual* risk, không giảm *product* risk

---

## 4. Impact lên checklist tuần này

Không thay đổi gì về triển khai live tracking (ADR-019). Chỉ thêm vào Chapter 1 Introduction báo cáo P2:

> *"Tác giả đồ án có 16 năm công tác trong ngành chứng khoán Việt Nam (VCBS từ 2010) và được Ủy ban Chứng khoán Nhà nước cấp Chứng chỉ hành nghề Phân tích tài chính (CKPT) — chứng chỉ cho phép hành nghề các nghiệp vụ môi giới, tự doanh, phân tích đầu tư, bảo lãnh phát hành và tư vấn đầu tư chứng khoán. Nền tảng chuyên môn này định hình các quyết định thiết kế hệ thống trong Project 2, đặc biệt về cost model (TT 111/2013), lot size compliance (QĐ 496), VN30 event-sourcing, và framework đánh giá dự đoán."*

Câu này **tăng credibility** academic + **mitigate** câu hỏi "sinh viên IT biết gì về tài chính" từ defense panel.

---
