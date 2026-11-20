# Kế hoạch: Web luyện đề HSK 4 (Đọc + Viết)

Đã chốt: người học chính là người yêu Hung (1 người học), Hung là admin (nhập từ, cấu hình), bộ từ HSK 3 + 4 gộp trong **1 file Excel**, nghĩa tiếng Việt, LLM mặc định **Gemini free**, chạy trên **host free** (mục 12), mặc định **đề đầy đủ**, định dạng Excel như mục 5.

## 0. Mục tiêu và phạm vi

- Nhập bộ từ vựng của Hung (Excel) vào DB.
- LLM sinh đề theo **đúng dạng HSK 4 phần Đọc và Viết**, dùng từ trong DB làm "từ mục tiêu".
- Chấm điểm: câu trắc nghiệm/sắp xếp do **code** chấm; câu viết tự do do **LLM** chấm. LLM giải thích lỗi sai bằng tiếng Việt.
- Đánh dấu từ làm sai; đề mới tự đưa lại **~5 từ sai gần nhất** để ôn.
- **Không làm Nghe.** Dạng "nhìn tranh đặt câu" đổi thành "đặt câu với từ cho sẵn".

Nguyên tắc: tối giản, kiểm tra bằng code thay vì nhồi luật vào prompt, mỗi lời gọi LLM nhỏ và có schema JSON rõ ràng.

## 1. Chọn LLM (miễn phí)

| Vai trò | Đề xuất | Ghi chú |
|---|---|---|
| Mặc định | **Gemini 3.5 Flash** qua Google AI Studio (free tier, endpoint tương thích OpenAI) | Tiếng Trung tốt, hỗ trợ JSON schema, nhanh. Free tier có giới hạn số request/phút và /ngày (đủ cho 1 người dùng), dữ liệu free tier có thể được Google dùng để huấn luyện (từ vựng không nhạy cảm nên ổn). |
| Dự phòng | OpenRouter, các model `:free` (DeepSeek V3, Qwen) | Qwen/DeepSeek rất mạnh tiếng Trung, nhưng model free hay bị nghẽn/giới hạn. |
| Tuỳ chọn | Groq, hoặc Ollama qwen3 tại máy nhà | Chỉ cần đổi `base_url`/`model`. |

Code dùng **một client OpenAI-compatible** (`openai` SDK), cấu hình qua `.env`:
```
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=...
LLM_MODEL=gemini-2.5-flash
LLM_MODEL_GRADE=           # để trống = dùng LLM_MODEL
```
Giới hạn free tier thay đổi thường xuyên, sẽ kiểm tra lại khi code M2.

## 2. Phạm vi đề và cách chấm

- Mục tiêu: Đọc + Viết HSK 4, không có phần Nghe.
- Đọc 1: chọn từ điền chỗ trống; Đọc 2: sắp xếp câu; Đọc 3: đọc hiểu.
- Viết 1: sắp xếp cụm từ thành câu; Viết 2: đặt câu với từ cho trước.
- Câu khách quan được code chấm; câu tự do được LLM chấm, giải thích bằng tiếng Việt.
- Điểm quy đổi theo số câu thực tế trong đề nếu một phần sinh lỗi; không gửi đáp án sang HTML trang làm bài.

## 3. Luồng người dùng

1. Admin mở `/admin`, nhập Excel từ vựng; giao diện web desktop-first.
2. Người học mở trang chủ, tạo đề đầy đủ hoặc mini.
3. Làm bài, nộp bài, xem điểm và giải thích; có thể báo câu lỗi.
4. Trang chủ lưu lịch sử; từ làm sai được đưa vào đề sau và có trang ôn tập.

## 4. Bảo mật và vận hành

- `.env` chứa thông tin nhạy cảm, không commit hoặc hiển thị API key.
- `/admin` luôn yêu cầu mật khẩu cấu hình qua `ADMIN_PASSWORD`.
- Dữ liệu local dùng SQLite; deploy dùng Postgres qua `DATABASE_URL`.
- Provider LLM dùng OpenAI-compatible API, cấu hình bằng `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`; không gắn cứng theo nhà cung cấp.
- Xác thực và validate đầu ra LLM bằng schema/code; đáp án chỉ lưu server-side.

## 5. Định dạng Excel

- Một workbook Excel có cột tiếng Trung (hanzi), pinyin, nghĩa tiếng Việt; importer nhận diện tiêu đề/cột, bỏ dòng rỗng và xử lý từ trùng.
- Giữ nguyên nội dung tiếng Trung và nghĩa tiếng Việt; báo số dòng nhập, bỏ qua và lỗi định dạng.

## 6. Sinh đề

- Chọn từ mục tiêu theo độ mới và lịch sử sai; ưu tiên khoảng 5 từ sai gần nhất.
- Tạo từng phần với JSON schema, kiểm tra target, cấu trúc câu, đáp án và lựa chọn; lưu payload hiển thị riêng với answer server-only.
- Nếu một phần lỗi, giữ các phần còn sinh được và quy đổi điểm theo số câu thực tế.
- Ghi log lỗi kỹ thuật ở server; không lộ prompt, API key hoặc response thô cho người học.

## 7. Giao diện và lưu trữ

- Thiết kế desktop web chuyên nghiệp, responsive xuống màn hình nhỏ; giao diện tiếng Việt.
- SQLite local; Postgres khi deploy. Lưu đề, câu hỏi, đáp án, lần làm, câu trả lời, thống kê từ sai và báo lỗi.
- Trang kết quả có tổng điểm, điểm từng phần, câu trả lời, đáp án/giải thích; trang làm bài không được nhận answer data.

## 8. Ôn tập từ sai

- Từ sai được tính từ các câu đã chấm, trừ câu đã báo lỗi.
- Đề tiếp theo ưu tiên từ sai gần nhất; từ có chuỗi đúng đủ dài giảm ưu tiên.
- Có trang từ cần ôn với thao tác nhớ/ôn lại.

## 9. Các route chính

- `GET /` — trang chủ, thống kê và lịch sử.
- `POST /exams` — sinh đề và chuyển tới trang làm bài.
- `GET /exams/{id}` — trang làm bài, không gửi đáp án ra HTML.
- `POST /exams/{id}/submit` — chấm và lưu kết quả.
- `GET /attempts/{id}` — kết quả.
- `POST /attempts/{id}/regrade` — chấm lại phần LLM lỗi.
- `POST /attempts/{id}/report` — báo câu lỗi.
- `/admin` — nhập và quản trị từ vựng, bắt buộc mật khẩu.

## 10. Kiểm thử

- Unit test pure logic cho importer, chọn từ, validate generator và chấm code.
- Integration test luồng tạo đề giả lập không gọi LLM, đảm bảo answer không lộ, nộp bài/chấm/lưu/ôn tập hoạt động.
- Kiểm tra thủ công UI desktop và responsive; test route admin có/không có mật khẩu.

## 11. Các mốc triển khai

| Mốc | Nội dung | Tiêu chí hoàn thành |
|---|---|---|
| M0 | Khung dự án, config, DB, khoá `/admin` | `uvicorn` chạy, `/admin` đòi mật khẩu |
| M1 | Nhập Excel + trang từ vựng | Nhập file mẫu của Hung, đúng số từ |
| M2 | `llm.py` + các bộ sinh + validate, chạy thử bằng CLI | Sinh ~10 đề đầy đủ, in tỉ lệ mục phải sinh lại, Hung đọc tay vài đề |
| M3 | Trang làm bài + chấm bằng code | Làm hết 1 đề, điểm đúng |
| M4 | LLM chấm Viết + giải thích + trang kết quả | Giải thích hợp lý trên vài câu cố ý sai |
| M5 | `word_stats`, chọn từ sai cho đề mới, trang Từ cần ôn | Sai từ X ở đề 1 → X xuất hiện ở đề 2 |
| M6 | Deploy lên Render + Neon (mục 12) | Mở được trên điện thoại, dữ liệu còn sau khi app ngủ/redeploy |

M0–M6 là MVP.

## 12. Deploy lên host free

- Web service trên Render, database PostgreSQL hosted (Neon).
- Cấu hình env vars trên host; không upload `.env`.
- Kiểm tra bootstrap schema, import từ vựng và persistence qua restart/deploy.

## 13. Yêu cầu tiếp theo: trạng thái chờ khi sinh đề

### Context
`POST /exams` hiện đợi toàn bộ quá trình sinh đề xong mới trả trang. Năm phần được tạo tuần tự; LLM có thể retry/backoff vì chậm hoặc rate limit, nên thời gian không cố định và không thể đưa ra phần trăm hoàn thành trung thực. `.env` hiện cấu hình NVIDIA NIM với model `nvidia/nemotron-3.5-super-vl-120b-a12b`; timer phía trình duyệt chỉ đo thời gian chờ, không chẩn đoán trực tiếp nguyên nhân chậm.

### Approach
- Giữ nguyên POST đồng bộ hiện có; không thêm job queue/status endpoint cho yêu cầu UX này.
- Trong `app/templates/index.html`, thêm vùng trạng thái ẩn ban đầu cho cả hai form tạo đề. Khi submit, hiện nội dung “Đang tạo đề…”, đồng hồ thời gian đã chờ và thanh tiến độ indeterminate; khóa cả hai nút để tránh submit lặp.
- Thêm script vanilla JS riêng `app/static/generation.js`, theo phong cách khởi tạo phòng thủ của `app/static/exam.js`; dùng `textContent`, trạng thái accessible (`role=status`, `aria-live=polite`), và giữ submit form native để hoạt động khi không có JS.
- Thêm style cho trạng thái chờ trong `app/static/style.css`, dùng design tokens hiện có, hỗ trợ dark mode và giảm/chặn animation khi `prefers-reduced-motion`.
- Sửa lời nhắc thời gian cố định “~20–60s” và copy “Gemini/free tier” thành nội dung trung tính về provider, không hứa thời gian hoàn tất. Không hiển thị phần trăm giả, API key hay raw provider response.
- Không đổi cấu hình NVIDIA/model nếu chưa có yêu cầu rõ; để chẩn đoán độ trễ cần kiểm tra model/base URL và log thời gian/retry/429/5xx ở server riêng.

### Files
- `app/templates/index.html`
- `app/static/generation.js` (mới)
- `app/static/style.css`
- `app/templates/exam_wip.html` (copy lỗi provider-neutral)

### Verification
- Thử cả full và mini: trạng thái hiện ngay, elapsed timer chạy, cả hai nút bị khóa, sau khi server trả lời trình duyệt vẫn redirect đúng.
- Thử JS tắt: form vẫn POST bình thường.
- Đảm bảo không có phần trăm/countdown giả; status accessible, animation tôn trọng reduced motion.
- Kiểm tra đường lỗi và partial-success vẫn như hiện tại, không để người dùng mắc ở trạng thái chờ sau khi response điều hướng.
- Chạy `.venv\Scripts\python.exe -m pytest tests/ -q`, kiểm tra trên desktop và viewport hẹp.
- Chẩn đoán NVIDIA dựa trên cấu hình và server logs (thời gian từng phần, retry, 429/5xx), không suy luận chỉ từ timer.


## 14. Ước lượng

Thời gian ước tính: 20–60 giây/đề đầy đủ. Sau khi nộp bài có thể **sinh sẵn đề kế tiếp ở nền** (M6).

## 15. Cấu trúc dự án (dự kiến)

```text
app/
  main.py
  config.py
  db.py
  models.py
  routes_vocab.py
  routes_exam.py
  routes_review.py
  llm.py
  exam.py
  grading.py
  gen/
  templates/
  static/
tests/
```

## 16. Ngoài phạm vi

- Thi Nghe.
- Đa tài khoản, thanh toán, OAuth.
- Đảm bảo endpoint miễn phí có độ trễ/khả dụng nhất định.
- Background job/durable queue cho sinh đề (có thể xét sau nếu cần).

## 17. Hướng thiết kế

- Desktop-first, ưu tiên trình duyệt máy tính; responsive cho màn hình nhỏ.
- UI tiếng Việt, cấu trúc rõ, tương phản tốt, không dùng phần trăm giả cho tiến độ LLM.
- Backend tối giản, ít phụ thuộc; không thêm hạ tầng ngoài SQLite/Postgres và FastAPI.
- Giữ ngữ cảnh lỗi hữu ích ở log server, nhưng thông báo cho người học phải an toàn và dễ hiểu.

## 18. Quy tắc làm việc

- Hoàn thành trọn bộ M0–M6 theo kế hoạch trước khi bàn giao, trừ khi người dùng đổi ưu tiên.
- Không commit `.env`, DB hoặc API key; không đưa đáp án vào HTML trang làm bài.
- Chạy tests phù hợp sau khi sửa và nêu rõ điều gì đã/không chạy.
- Hướng dẫn người dùng các bước cần thiết để chạy/import/tạo đề/deploy.

## 19. Ghi chú môi trường hiện tại

- Người dùng đã chuyển UI sang hướng desktop web chuyên nghiệp.
- Provider hiện tại trong `.env` là NVIDIA NIM; các thiết lập hiệu lực có thể khác giữa máy local và Render.
- Model 120B có thể có độ trễ cao hơn model nhỏ; cần đo request latency và retry trước khi quy kết.
- File `.env` từng bị lộ trong ngữ cảnh trao đổi; nên thu hồi và tạo API key mới nếu đó là key còn hiệu lực.

---
### Lịch sử nguyên bản

## 12. File Excel mẫu của Hung

Tên file: `Bộ từ vựng.xlsx` (ở thư mục gốc, người dùng đã cung cấp). Nội dung thật sẽ kiểm tra ở M1; dự kiến các cột:
- Từ Hán tự (ví dụ `按照`)
- Pinyin (ví dụ `ànzhào`)
- Nghĩa tiếng Việt (ví dụ `căn cứ theo`)

Import phải nhận diện tiêu đề cột (không phụ thuộc thứ tự cột), bỏ dòng rỗng, báo rõ dòng lỗi và từ trùng.

## 13. Các mốc

M0–M6: xem bảng mục 11; phần này được giữ để đối chiếu với bản gốc.

## 14. Ước lượng ban đầu

Thời gian sinh đề đầy đủ dự tính 20–60 giây/đề; thời gian thực tế phụ thuộc provider, model, quota và retry.

## 15. Cấu trúc dự án ban đầu

Xem mục 15; cấu trúc được điều chỉnh theo quá trình triển khai.

## 16. Giới hạn

Xem mục 16; không triển khai nghe, đa tài khoản, thanh toán hoặc OAuth trong MVP.

## 17. Thiết kế

Desktop-first theo yêu cầu cập nhật sau đó; phù hợp web máy tính và vẫn dùng được ở màn hình hẹp.

## 18. Quy tắc

Theo mục 18.

## 19. Ghi chú

Theo mục 19.

---

### Phụ lục: nội dung khôi phục từ transcript

Bản gốc được khôi phục một phần từ phần người dùng chọn trong transcript. Những đoạn chi tiết bị thiếu được biên soạn lại theo hiện trạng triển khai; xem transcript nếu cần so sánh chính xác.

## Ghi chú khôi phục

Bản gốc có 285 dòng, phần được khôi phục nguyên văn trong `PLAN-recovered.md` 286 dòng. Mục 0–12 và phần đầu các mục sau phản ánh trực tiếp nội dung người dùng chọn; các phụ lục phía sau bổ sung các ghi chú thực tế và yêu cầu mới từ cuộc trao đổi hiện tại.

## Phụ lục: việc đang làm

Khi tạo đề, giao diện cần báo thời gian đã chờ và progress trung thực; hiện thực tối thiểu bằng JS timer + indeterminate progress trên form đồng bộ.