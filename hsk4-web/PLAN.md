# Kế hoạch: Không nuốt lỗi chấm AI

## Context

Route nộp bài và route “Thử chấm lại” hiện bắt mọi exception từ `llm_grade()` rồi thay bằng `{}`. Vì vậy câu Viết 2 vẫn có `is_correct=None`, giao diện chỉ hiện “chưa chấm (AI)”, còn log không có traceback và người dùng không biết nguyên nhân thật. Cần giữ trạng thái pending an toàn nhưng ghi lỗi đầy đủ ở backend và đưa thông báo rõ ràng về trang kết quả.

## Approach

1. **Ghi log có ngữ cảnh trong `app/routes_exam.py`**
   - Thêm logger chuẩn của Python ở đầu module.
   - Trong `_grade_and_save()` và `regrade()`, log bằng `logger.exception(...)` khi `llm_grade()` thất bại, kèm attempt/exam và số lượng câu theo từng nhóm; không log API key hoặc toàn bộ prompt/câu trả lời nhạy cảm.
   - Không re-raise lỗi LLM ở hai điểm này để các câu code-chấm vẫn được lưu và câu LLM vẫn giữ trạng thái pending.

2. **Truyền trạng thái lỗi ra trang kết quả**
   - Route regrade redirect về `/attempts/{id}` với query parameter thông báo ngắn, không chứa exception/raw credential.
   - Route `attempt_page()` đọc thông báo và truyền vào template.
   - Template `attempt.html` hiển thị banner cảnh báo khi regrade thất bại, hướng dẫn xem log backend hoặc thử lại sau; vẫn giữ nút “Thử chấm lại”.
   - Với lần submit ban đầu, không làm hỏng redirect/chấm các phần khác; ghi log để người vận hành biết có câu pending.

3. **Cải thiện lỗi ở lớp LLM nếu cần**
   - Kiểm tra `app/llm.py` để bảo đảm exception cuối cùng vẫn giữ loại lỗi/status code hữu ích (`LLMError` có nguyên nhân), nhưng không đưa thông tin bí mật vào UI.
   - Không đổi provider/API contract hiện tại; code đang dùng OpenAI-compatible client/Gemini nên không chuyển SDK.

4. **Kiểm thử**
   - Bổ sung test route hoặc test helper để mô phỏng `llm_grade` ném exception, xác nhận: answer vẫn pending, redirect có cảnh báo, logger được gọi, không lộ secret.
   - Chạy `python -m pytest tests/ -q` và kiểm tra syntax/import.
   - Xác nhận log thực tế khi regrade attempt 2: phải có traceback và nguyên nhân API/timeout/validation thay vì chỉ các dòng 302/200.

## Critical files

- `app/routes_exam.py`: logging, xử lý lỗi submit/regrade, truyền thông báo.
- `app/templates/attempt.html`: banner lỗi chấm AI.
- `app/llm.py`: kiểm tra/chuẩn hóa thông tin exception nếu cần.
- `tests/`: regression test cho lỗi LLM bị nuốt.

## Verification

Sau khi triển khai, chạy toàn bộ test suite, sau đó bấm “Thử chấm lại” một lần. Log phải xuất hiện traceback có attempt/question-group context; trang kết quả phải báo chấm AI thất bại và vẫn cho phép thử lại, trong khi không hiển thị API key hay prompt đầy đủ.
