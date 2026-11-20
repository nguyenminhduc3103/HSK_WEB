# hsk4-web

Web app luyện đề HSK 4 (Đọc + Viết), AI tự ra đề từ bộ từ vựng của bạn.
Chi tiết đặc tả: `../PLAN.md`.

## Các trang

| Đường dẫn | Việc |
|---|---|
| `/` | Trang chủ: nút làm đề mới (full/mini), lịch sử điểm, số từ cần ôn |
| `/exams` (POST) | Sinh đề bằng AI (~20–60s) |
| `/exams/{id}` | Làm bài (đáp án KHÔNG được gửi ra trang làm bài) |
| `/exams/{id}/submit` (POST) | Chấm: code chấm ngay phần trắc nghiệm; AI chấm phần viết + giải thích |
| `/attempts/{id}` | Kết quả: điểm /200, đúng ≥120 là ĐẠT; từng câu đúng/sai + giải thích; "Báo câu lỗi"; "Thử chấm lại" |
| `/review` | Từ cần ôn (từ sai gần đây) + nút Đã nhớ / Ôn lại |
| `/admin/vocab` | (khoá mật khẩu) danh sách từ + nhập Excel |

## Chạy local

```bash
cd hsk4-web
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows (Linux/mac: .venv/bin/pip)

# Tạo .env từ mẫu rồi sửa giá trị
copy .env.example .env   # Windows; Linux/mac: cp .env.example .env

.venv/Scripts/uvicorn app.main:app --reload   # Windows
# Linux/mac: .venv/bin/uvicorn app.main:app --reload
```

Mở <http://127.0.0.1:8000>.

Thứ tự sử dụng:
1. Mở `/admin/vocab` (đăng nhập Basic: user bất kỳ, password = `ADMIN_PASSWORD`), upload file Excel từ vựng → xem trước → Confirm.
2. Về `/` bấm **Làm đề đầy đủ** (hoặc mini) → làm bài → Nộp → xem kết quả.
3. Về `/review` xem các từ đang sai, đánh dấu Đã nhớ / Ôn lại.

Sinh thử nhiều đề (kiểm tra tỉ lệ sinh lại, không cần mở trình duyệt):

```bash
.venv/Scripts/python -m app.gen.try_exam --n 10
```

## Cấu hình (`.env`)

| Biến | Ý nghĩa | Mặc định |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/hsk4.db` (local); Postgres/Neon khi deploy | SQLite |
| `LLM_BASE_URL` | Endpoint OpenAI-compatible | Gemini (Google AI Studio) |
| `LLM_API_KEY` | Key của provider | — |
| `LLM_MODEL` | Model sinh đề + chấm | `gemini-2.5-flash` |
| `LLM_MODEL_GRADE` | Model chấm/giải thích; trống = dùng `LLM_MODEL` | — |
| `ADMIN_PASSWORD` | Mật khẩu `/admin`; trống thì `/admin` trả 503 | — |

## Test

```bash
.venv/Scripts/python -m pytest tests/ -q
```

(Các test chỉ kiểm tra logic thuần: validate bộ sinh, chọn từ mục tiêu, chấm code — không gọi AI thật.)

## Deploy (Render + Neon)

Render free không giữ file trên đĩa, nên **bắt buộc dùng Postgres (Neon)** qua `DATABASE_URL`
— SQLite chỉ dùng trên máy local.

1. Tạo DB Neon (free) → lấy string kết nối (đổi scheme thành `postgresql+psycopg://`).
2. Tạo repo GitHub (private) với thư mục này, đẩy `render.yaml`.
3. Render → New → Web Service → chọn repo → nó đọc `render.yaml`; điền giá trị thật
   vào `DATABASE_URL`, `LLM_API_KEY`, `ADMIN_PASSWORD`.
4. Lệnh start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

App tạo bảng tự động khi khởi động. Render free ngủ sau ~15 phút — lần mở đầu chờ 30–60s.
