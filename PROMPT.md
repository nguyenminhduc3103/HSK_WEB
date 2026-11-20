## Prompt khởi động (dán 1 lần)

```
Bạn sẽ xây một web app luyện đề HSK 4 (chỉ phần Đọc và Viết) theo đặc tả trong file PLAN.md ở thư mục gốc. Đọc kỹ toàn bộ PLAN.md trước khi viết code. PLAN.md là nguồn sự thật; nếu có chỗ mâu thuẫn hoặc thiếu, hỏi tôi thay vì tự đoán.

Cách làm việc:
- Làm theo từng mốc ở mục 11 của PLAN.md (M0 → M6). Mỗi lần chỉ làm MỘT mốc. Xong mốc thì dừng lại, báo: đã làm gì, file nào, cách chạy/kiểm tra, và điều gì chưa chắc. Chờ tôi nói "tiếp" mới sang mốc sau.
- Bắt đầu bằng M0.

Nguyên tắc code (bắt buộc):
- Tối giản. Không thêm thư viện, lớp trừu tượng, pattern hay tính năng ngoài PLAN.md. Không làm SPA, không build frontend: FastAPI + Jinja2 + JS thuần.
- Thư viện cho phép: fastapi, uvicorn, jinja2, python-multipart, sqlmodel, openpyxl, openai, python-dotenv, pydantic, psycopg (cho Postgres khi deploy), pytest. Cần thêm gì thì hỏi trước.
- Kiểm tra bằng code thay vì nhồi luật vào prompt. Prompt LLM ngắn; ràng buộc nằm trong schema pydantic và hàm validate().
- Mọi output LLM phải parse qua model pydantic. Không tin min/max từ LLM: tự kẹp giá trị trong code.
- Code tự xáo vị trí đáp án, tự xáo các cụm từ, tự chọn từ nhiễu. Không để LLM làm việc này.
- Không bao giờ gửi đáp án ra HTML của trang làm bài.
- Cấu hình chỉ qua biến môi trường (.env): DATABASE_URL, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_MODEL_GRADE, ADMIN_PASSWORD. Tạo .env.example, không commit .env.
- LLM gọi qua openai SDK với base_url cấu hình được (mặc định Gemini OpenAI-compatible endpoint). Ưu tiên response_format json_schema; nếu provider báo lỗi thì fallback json_object + validate.
- Giao diện tiếng Việt, ưu tiên điện thoại (1 cột, nút to, chữ Hán cỡ lớn).
- Mỗi mốc có test pytest cho phần logic thuần (import Excel, validate, chấm điểm, chọn từ sai). Không test gọi LLM thật trong pytest; dùng dữ liệu JSON mẫu.
- Không sửa code của mốc trước trừ khi cần cho mốc hiện tại; nếu sửa thì nói rõ.
```

---

## Prompt từng mốc

### M0
```
Làm M0: khung dự án theo cấu trúc thư mục ở mục 2, config.py đọc .env, db.py tạo engine từ DATABASE_URL (mặc định sqlite:///data/hsk4.db), models.py theo đúng lược đồ mục 4, tạo bảng khi khởi động, trang chủ trống, và /admin khoá bằng HTTP Basic với ADMIN_PASSWORD. Thêm requirements.txt, .env.example, README.md ngắn (cách chạy local). Dừng lại khi xong.
```

### M1
```
Làm M1: nhập từ vựng từ Excel theo mục 5 của PLAN.md. Chú ý: có 2 cột cùng tên "Phiên âm" nên ánh xạ theo vị trí; tách "ài qíng [ái tình]" thành pinyin và han_viet; cột "Cấp" là tuỳ chọn. Có trang xem trước 10 dòng, dropdown chỉnh cột nếu nhận diện sai, upsert theo hanzi, báo cáo thêm/cập nhật/bỏ. Trang /admin/vocab liệt kê + tìm kiếm. Viết test với 1 file xlsx mẫu tạo trong test. Dừng lại khi xong.
```

### M2
```
Làm M2: llm.py (call_json(prompt, model_cls) + retry kèm thông báo lỗi), exam.py chọn từ mục tiêu theo mục 6.1, và các bộ sinh trong app/gen/ theo mục 6.2–6.3: mỗi dạng bài một file gồm prompt + schema + validate(). Validate theo từng mục; mục sai thì sinh lại riêng mục đó tối đa 2 lần, rồi đổi từ mục tiêu, cuối cùng mới bỏ câu. Các lời gọi chạy song song bằng asyncio.gather. Viết script CLI `python -m app.gen.try_exam --n 10` sinh đề đầy đủ, lưu vào DB, in ra tỉ lệ mục phải sinh lại và in 1 đề ra màn hình để tôi đọc. Dừng lại khi xong.
```

### M3
```
Làm M3: trang làm bài /exams/{id} theo mục 10 (tab Đọc/Viết, đồng hồ tham khảo, Viết 1 bấm cụm để ghép câu bằng JS thuần), POST /exams/{id}/submit chấm phần code chấm được theo mục 7.1, lưu attempts/answers, trang kết quả cơ bản. Điểm theo mục 3 (Đọc 100 + Viết 100, quy đổi theo số câu thực có). Nút "Làm đề mới" ở trang chủ. Dừng lại khi xong.
```

### M4
```
Làm M4: chấm/giải thích bằng LLM theo mục 7.2 (1 lời gọi gộp: chấm Viết 2, xét Viết 1 có trật tự khác, giải thích câu Đọc sai), lưu feedback_json, trang kết quả đầy đủ theo mục 7.3 (điểm từng phần, tỉ lệ đúng theo dạng, top grammar_tag hay sai, danh sách từ sai kèm câu ví dụ từ DB). Nút "Báo câu lỗi" ghi vào bảng reports, loại câu đó khỏi điểm và khỏi thống kê từ sai. LLM lỗi thì vẫn hiện điểm phần code chấm và nút "Thử chấm lại". Dừng lại khi xong.
```

### M5
```
Làm M5: cập nhật word_stats sau khi chấm theo mục 8, đề mới lấy ~5 từ sai và ưu tiên đặt vào Đọc 1 và Viết 2 theo mục 6.1, trang /review "Từ cần ôn" (hanzi, pinyin, Hán Việt, nghĩa, câu ví dụ, số lần sai) với nút "Đã nhớ"/"Ôn lại". Test: làm sai từ X ở đề 1 thì X có trong danh sách từ mục tiêu của đề 2. Dừng lại khi xong.
```

### M6
```
Làm M6: chuẩn bị deploy theo mục 12: hỗ trợ DATABASE_URL Postgres (Neon), render.yaml, lệnh start uvicorn với $PORT, hướng dẫn từng bước trong README (tạo DB Neon, tạo web service Render từ GitHub, đặt biến môi trường, nhập Excel lần đầu qua /admin). Không dùng SQLite trên Render. Dừng lại khi xong.
```

---