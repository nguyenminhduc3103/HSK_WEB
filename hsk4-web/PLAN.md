# Kế hoạch: vòng đời đề + autosave + nâng cấp UI/UX

Thay thế bản plan timer-only trước đó. Phạm vi = (1) luồng tạo/chọn/làm/nộp đề, (2) lưu nháp trên server (user đã chốt "Lưu server (autosave)"), (3) làm mới giao diện (user đã chốt "Cac (fonts + icon, CDN)").

## 0. Luồng người dùng mới (đã chốt với user)

1. **Tạo đề** (nút trên trang chủ): form POST đồng bộ như hiện tại, nhưng thêm trạng thái chờ phía client (elapsed timer + thanh tiến độ indeterminate + khóa 2 nút). **Không hiển thị % giả** — sinh đề chạy tuần tự 5 phần LLM, thời gian không cố định (có thể bị 429/retry).
2. **Sinh xong → quay về trang chủ** (đổi redirect), không tự nhảy vào trang làm bài. Đề được lưu và hiển thị trong danh sách "Đề đã tạo".
3. **Danh sách đề trên trang chủ**: mỗi đề một hàng: nhãn **Đề {n}** (số thứ tự theo `id` tăng dần = thứ tự tạo) + chế độ (full/mini) + ngày giờ + **status có màu**.
4. **Bấm "Làm bài" → mới mở trang làm đề**. Khi mở lần đầu, tạo (hoặc dùng lại) attempt chưa nộp; đây là lúc chuyển status đề sang "in_progress".
5. **Autosave trên server**: mỗi khi trả lời/xoá, nháp được lưu về server (debounce). Thoát trang / F5 / quay lại → **phục hồi đúng chỗ đã làm**.
6. **Nộp** → chấm code + LLM (giữ nguyên logic hiện tại) → lưu kết quả → status đề = "done" (màu khác) → link xem kết quả. Nộp lại (retake) tạo attempt mới, đề vẫn "done".

## 1. Vòng đời đề (status) và dữ liệu

### 1.1 Trạng thái Exam

Giữ cột `Exam.status` string, mở rộng bộ giá trị:

| Status | Ý nghĩa | Màu (badge) |
|---|---|---|
| `ready` | đã sinh xong, chưa làm | xám/trắng (neutral) |
| `in_progress` | đang làm (có nháp chưa nộp) | tím/vàng |
| `done` | đã có ít nhất một bài nộp | xanh lá |
| `failed` | sinh thất bại (giữ nguyên) | đỏ |

**Migration cho DB cũ** (SQLite & Postgres):
- `create_all()` không ALTER bảng cũ → viết migration thủ công trong `app/db.py` (chạy sau `create_all()`): kiểm tra `PRAGMA table_info(exams)` (SQLite) / `information_schema` (Postgres); cột `status` đã tồn tại nên chỉ cần **backfill**: mọi `exam` có ≥1 `Attempt.submitted_at` (có điểm) → `status='done'`, giữ các status hiện có hợp lệ. Không thêm cột mới lên `exams`.
- Draft answers: **tạo bảng mới `ExamDraft`** (mới → `create_all()` tự tạo, không cần migration) — nhưng không đặt constraint uniqueness cố định; logic "mỗi đề 1 draft" quản lý bằng code (query theo attempt).

### 1.2 Bảng nháp (draft)

Mở rộng `Attempt`: thêm **một draft chưa chấm** mỗi đề, gắn vào attempt "đang làm":

```python
class DraftAnswer(SQLModel, table=True):   # bảng "draft_answers"
    id            PK
    attempt_id    FK attempts.id (index)
    question_id   FK questions.id (index)
    user_answer   str        # raw string, đúng định dạng submit (label "A", "BAC", "c1|c2", câu viết)
    updated_at    datetime
```

Quy tắc (code, không dùng unique constraint để tránh lỗi trên SQLite cũ):
- Mỗi `exam` chỉ có **1 attempt "đang làm"**: attempt có `submitted_at IS NULL`. Có nhiều → giữ attempt có `started_at` mới nhất, các attempt chưa nộp còn lại bị gộp xoá khi mở lại (hoặc đánh dấu bỏ). Cách đơn giản nhất: khi "Làm bài", tìm attempt `submitted_at IS NULL` của exam này; có thì dùng, không thì tạo mới.
- Submit hiện tại: thay `Attempt(exam_id=exam.id)` luôn-mới bằng: **gộp draft (nếu có) vào lần nộp đó** — attempt đang làm được chấm và đóng lại (`submitted_at`), sau đó trả về /attempts/{id}. **Không tạo thêm attempt mới cho cùng lần làm**.
- Retake: trên trang kết quả thêm nút "Làm lại đề này" → tạo attempt chưa nộp mới + status đề về `in_progress`. (Tuỳ chọn, phạm vi nhỏ.)

### 1.3 API (mới, trong `routes_exam.py`)

- `POST /exams/{id}/draft` (JSON: `{"answers": {qid: "raw"}, ...}`) → ghi `DraftAnswer` (upsert theo (attempt_id, question_id)), trả JSON `{"ok": true, "saved_at": ...}`. Endpoint này chỉ nhận raw answer — **không bao giờ gửi `answer_json` ra**.
- `GET /exams/{id}` (sửa): khi render trang làm đề, **nạp nháp** vào form (giá trị mặc định của input/textarea/chip) + render bộ counter đã-trả-lời.
- `GET /` (sửa, trong `main.py`): truyền thêm `exams` (mọi đề `status != 'failed'`, sort `id desc`) + bộ đếm.

### 1.4 Chấm vẫn như cũ

`_grade_and_save` không đổi hợp đồng: `a_<qid>` = label ("A"), build_sentence = "c1|c2|…". Draft lưu đúng raw này nên khi submit có thể submit thẳng từ form (giữ POST form hiện tại) — server đọc form trước, fallback đọc draft khi form thiếu field.

## 2. UI/UX — làm mới

**Nguyên tắc**: desktop-first (như hiện), không thêm framework/build step.

### 2.1 Thư viện (đã chốt CDN)

- **Google Fonts** `Inter` (Latin) + **Noto Sans SC** (chữ Hán, cân nặng nhẹ) → `<link>` trong template.
- **Lucide icon** (SVG, cùng style): kiểm tra xem `.venv` đã có `lucide-static` hay CDN; ưu tiên CDN `lucide` (script nhỏ, `lucide.createIcons()`). Nếu CDN không tải → icon biến mất nhưng layout vẫn đúng (fallback: không render icon, text label vẫn đủ). Không thay emoji quan trọng bằng icon rồi để trống.
- Font/CDN fail phải **graceful**: `font-family: Inter, "Noto Sans SC", system-ui` — app chạy không cần mạng vẫn đọc được.

### 2.2 Palette & typography (thay indigo hiện tại)

Cập nhật tokens trong `style.css` (cả light/dark):
- Accent chuyển sang **tím trầm**: `--accent: #6d5ae8 → dùng #5b4bc4 / dark: #8b7ce8`, `--accent-soft` tương ứng; giữ nền trung tính hiện có (`#f5f6f8`), card `#fff`, shadow giữ nguyên.
- Status colors dùng token: `--st-ready (muted)`, `--st-inprogress (#b45309/#fde68a)`, `--st-done (#15803d/#dcfce7)`, `--st-failed (#c2352f)`.
- Type scale rõ hơn: h1 28–32px/700, h2 18–20px/600, body 15–16px, `.zh` 18px, tracking -0.01em cho headings.

### 2.3 Trang chủ (`index.html` + CSS)

- Card mới **"Đề của bạn"** (đặt trên card Lịch sử): mỗi đề = một dòng/card nhỏ:
  - Nhãn: `Đề {n} · Full/Mini · 12/01 14:30` (n = số thứ tự tạo, filter template từ `exam.id` theo danh sách đã sort).
  - Badge status có màu (Sẵn sàng / Đang làm / Đã hoàn thành).
  - Nút hành động theo status: `Sẵn sàng` → "Làm bài"; `Đang làm` → "Tiếp tục" (hiện % câu đã nháp, vd 12/55); `Đã hoàn thành` → "Xem kết quả" (link attempt mới nhất) + "Làm lại".
- Giữ card tạo đề + trạng thái chờ (mục 0.1): elapsed timer (s), thanh tiến độ indeterminate, 2 nút disable, `role="status"` announce "Đang tạo đề… đã chờ 45s" (thông báo ~mỗi 5s, không每秒, tránh spam screen reader).
- Sửa copy "~20–60s" → "Tạo đề mất một lúc tuỳ nhà cung cấp AI".

### 2.4 Trang làm đề (`exam.html` + `exam.js` + CSS)

Giữ nguyên **hợp đồng chấm** (mục 1.4), chỉ đổi lớp vỏ:

- **Fill-blank (Đọc 1)**: bỏ `<select>`, dùng **chip bấm-điền**:
  - Word bank hiện có (`.choices`) → mỗi chip là `<button data-qid data-choice="A">`; bấm chip + bấm câu → hoặc bấm câu trước (highlight) rồi bấm chữ → auto điền. Đơn giản hoá: mỗi câu có ô trống `.blank` hiển thị chữ đã chọn; bấm chip = gán cho câu đang chọn (câu cuối cùng chưa chọn nếu không). **Định dạng an toàn nhất**: mỗi câu giữ hidden input `a_<qid>` = label "A" (đúng như grading); chip chỉ là UI bọc ngoài.
  - Thực hiện theo mẫu: chip bấm được, mỗi câu có 1 ô "slot" nhận chữ; chọn slot (bấm câu) → bấm chip → slot hiện chữ + hidden value cập nhật; bấm lại chip = gỡ.
- **Sentence builder (Viết 1)**: giữ cơ chế `.chunk` click + hidden pipe (đã đúng contract), làm mới visual: chunk button bo góc nhẹ, slot answer area rõ ràng (nền riêng, chiều cao cố định), chunk đã dùng mờ đi trong bank.
- **Đặt câu (Viết 2)**: textarea + **bộ đếm ký tự** (vd "0/100") cạnh mỗi câu; không enforce giới cứng — chỉ hiển thị (đề HSK thực không giới hạn, LLM chấm theo chất lượng).
- **Thanh sticky "submit bar" đáy màn hình** (thay nút cuối trang): progress "Đã trả lời 32/55" + điểm nháp đã lưu (icon check/x) + nút "Nộp bài" to. Sticky bằng `position: sticky`/fixed, nội dung scroll phía trên.
- **Timer**: giữ đồng hồ tham khảo; khi tới ngưỡng 65 phút (tham khảo 65p Đọc+Viết) chip timer đổi sang màu cam và hiện "Gần hết thời gian tham khảo"; không blocking.
- **Phục hồi nháp**: khi JS load, form render đã có giá trị draft (server-side), autosave resume.

### 2.5 Autosave phía client (`exam.js` mở rộng + script nhỏ)

- Lắng nghe `input`/`change` trên mọi field `a_*` + sự kiện build/fill → gom state → debounce 1.5s → `POST /exams/{id}/draft` (fetch, JSON).
- Hiện trạng thái: "Đang lưu… / Đã lưu lúc 14:32 / Lưu thất bại (sẽ thử lại)". Lỗi mạng → giữ queue, retry lần kế tiếp (mỗi lần state mới nhất thay cả bundle cũ).
- Trạng thái "đã trả lời" (progress 32/55) tính từ form hiện tại (không phụ thuộc mạng).

### 2.6 Copy lỗi & provider-neutral (vẫn còn từ bản plan cũ)

Thay các chuỗi hardcode Gemini/free-tier (provider hiện tại = NVIDIA NIM, .env đã đổi):
- `app/routes_exam.py` (n_q==0): `Kiểm tra hạn mức Gemini rồi thử lại.` → `Kiểm tra hạn mức / độ trễ của nhà cung cấp AI rồi thử lại.`
- `app/templates/exam_wip.html`: `AI free tier có thể bị giới hạn tần suất…` → `Nhà cung cấp AI có thể đang giới hạn tần suất hoặc trả lời chậm — chờ vài phút rồi thử lại.`
- `app/llm.py` (429 msg): `Gemini free-tier limit reached; … AI Studio limits` → `provider rate/quota limit reached; check provider limits`.
- `app/templates/index.html`: bỏ con số "~20–60s" cố định.

## 3. Files cần sửa / thêm

| File | Thay đổi |
|---|---|
| `app/models.py` | `DraftAnswer` (bảng mới); (không đổi cột Exam — status string giữ nguyên, chỉ thêm giá trị) |
| `app/db.py` | migration/backfill status sau `create_all()` (SQLite + Postgres) |
| `app/routes_exam.py` | POST /exams → redirect về `/`; GET /exams/{id} → tạo/dùng lại attempt + nạp draft; POST /exams/{id}/draft (mới); submit → gộp attempt đang làm thay vì luôn tạo mới |
| `app/main.py` | truyền `exams` list + counter vào index |
| `app/templates/index.html` | card "Đề của bạn" + loading state khi tạo đề + fix copy |
| `app/templates/exam_wip.html` | copy provider-neutral |
| `app/llm.py` | 429 message provider-neutral |
| `app/templates/exam.html` | chip fill-blank, counter, sticky bar, restore draft (server-side), fonts/Lucide |
| `app/static/exam.js` | chip logic, autosave, progress, timer warning |
| `app/static/style.css` | token tím/neutral, type scale, badge status, sticky bar, chip, reduced-motion + dark mode |
| `app/static/generation.js` (mới) | elapsed timer + indeterminate bar khi tạo đề |
| `tests/test_m3_lifecycle.py` (mới) | vòng đời + draft (xem mục 4) |

## 4. Kiểm thử

- **Test mới** (`tests/test_m3_lifecycle.py`, dùng conftest fake-LLM như test_m2):
  1. POST /exams (fake gen) → response 302 về `/`, đề `status='ready'` trong DB.
  2. GET /exams/{id} lần 1 → tạo attempt chưa nộp; đề `in_progress`; HTML chứa field draft rỗng, **không chứa** nội dung `answer_json`.
  3. POST /exams/{id}/draft (1 câu) → 200; GET lại → giá trị draft hiện trong form.
  4. POST /exams/{id}/submit (form rỗng nhưng có draft) → attempt được chấm từ draft, `submitted_at` set, đề `done`.
  5. Tạo đề thứ 2 → "Đề 2"; thứ tự trên trang chủ đúng id desc.
  6. Backfill: tạo attempt submitted cũ + exam status rỗng/ready → sau migration = `done`.
- Chạy: `.venv\Scripts\python.exe -m pytest tests/ -q` (toàn bộ, không chỉ file mới).
- **Thủ công**: tạo đề (đợi) → về trang chủ thấy "Đề N · Sẵn sàng" → Làm bài → trả lời vài câu → F5 → nháp còn → Nộp → điểm + "Đã hoàn thành" màu xanh → "Xem kết quả". Kịch bản thoát giữa chừng (đóng tab) rồi quay lại.

## 5. Thứ tự làm (khi được duyệt)

1. models + db migration + draft endpoint + route lifecycle (core, chạy tests).
2. index.html card "Đề của bạn" + generation.js (loading state).
3. Làm mới style.css (token/tím, type, badge, sticky) + fonts/Lucide.
4. exam.html chip/counter/sticky + exam.js autosave.
5. Copy provider-neutral (llm.py, exam_wip, index).
6. tests + chạy pytest + kiểm thử thủ công.

## 6. Không làm (trừ khi user yêu cầu)

- Background job queue cho sinh đề (giữ POST đồng bộ + client loading state).
- Đổi model/NVIDIA config.
- Đa tài khoản; autosave chỉ 1 user như hiện tại.
- Force giới hạn ký tự cho câu viết.
