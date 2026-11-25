"""Routes người học: làm đề + chấm (mục 9 + lifecycle mới PLAN).

POST /exams                 → sinh đề (LLM) → quay về trang chủ (đề vào danh sách)
GET  /exams/{id}            → trang làm bài: mở/tạo attempt đang làm, nạp nháp (KHÔNG gửi đáp án ra HTML)
POST /exams/{id}/draft      → autosave nháp (JSON {answers: {qid: raw}})
POST /exams/{id}/submit     → chấm code + LLM từ form (gộp nháp), lưu attempt/answers → /attempts/{id}
GET  /attempts/{id}         → trang kết quả
POST /attempts/{id}/regrade → 'Thử chấm lại' phần chấm bằng LLM (fallback khi LLM lỗi)
POST /attempts/{id}/report  → 'Báo câu lỗi' (loại khỏi điểm + không tính từ sai)

Vòng đời đề: ready → in_progress (khi mở làm) → done (sau khi nộp chấm thành công).
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete
from sqlmodel import Session, select

from . import exam as exam_mod
from .deps import get_session
from .grading import PASS_TOTAL, grade_code, llm_grade, recompute_scores
from .models import Answer, Attempt, DraftAnswer, Exam, Question, Report, Word, WordStat

router = APIRouter()
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")


def _open_attempt(session: Session, exam: Exam) -> Attempt | None:
    """Attempt 'đang làm': chưa nộp (submitted_at IS NULL), giữ attempt mới nhất."""
    return session.exec(
        select(Attempt).where(
            Attempt.exam_id == exam.id,
            Attempt.submitted_at.is_(None),
        ).order_by(Attempt.id.desc())
    ).first()


def _mark_in_progress(session: Session, exam: Exam) -> None:
    if exam.status != "in_progress":
        exam.status = "in_progress"
        session.add(exam)
        session.commit()
        session.refresh(exam)

PART_LABELS = {
    "fill_blank": "Đọc 1 — 选词填空",
    "order": "Đọc 2 — 排列顺序",
    "reading": "Đọc 3 — 阅读理解",
    "build_sentence": "Viết 1 — 完成句子",
    "make_sentence": "Viết 2 — 用词造句",
}


@router.post("/exams")
async def new_exam(request: Request, mode: str = Form("full"),
                  session: Session = Depends(get_session)):
    """Sinh đề mới (LLM, 20–60s) rồi chuyển sang trang làm bài."""
    if mode not in ("full", "mini"):
        mode = "full"
    try:
        exam_id, _stats, n_q, errors = await exam_mod.generate_exam(session, mode)
    except Exception as e:
        return templates.TemplateResponse(
            request, "exam_wip.html",
            {"error": f"Sinh đề thất bại: {type(e).__name__}: {e}"},
            status_code=502,
        )
    if n_q == 0:
        detail = " · ".join(errors[:3]) or "LLM lỗi / hết hạn mức"
        return templates.TemplateResponse(
            request, "exam_wip.html",
            {"error": (f"Không sinh được câu hỏi nào ({detail}). "
                       "Kiểm tra hạn mức / độ trễ của nhà cung cấp AI rồi thử lại.")},
            status_code=502,
        )
    # Có phần bị lỗi (vd 429) nhưng vẫn còn câu: đề dùng được phần còn lại,
    # điểm tự quy đổi theo số câu thực (mục 7 PLAN). Đề lưu vào danh sách trên
    # trang chủ — không tự nhảy vào trang làm bài (lifecycle PLAN).
    return RedirectResponse("/", status_code=302)


@router.get("/exams/{exam_id}", response_class=HTMLResponse)
def exam_page(exam_id: int, request: Request, session: Session = Depends(get_session)):
    exam = session.get(Exam, exam_id)
    if not exam:
        return HTMLResponse("Không tìm thấy đề.", status_code=404)
    if exam.status == "failed":
        return HTMLResponse("Đề này không có câu hỏi (sinh thất bại).", status_code=404)

    # "Làm lại" (đề đã done) hoặc lần mở đầu: không có attempt đang làm
    # nào → tạo attempt mới, đề chuyển in_progress. Nháp của attempt cũ
    # (đã xoá khi nộp) không còn, nên retake bắt đầu sạch.
    attempt = _open_attempt(session, exam)
    if attempt is None:
        attempt = Attempt(exam_id=exam.id)
        session.add(attempt)
    # A retake creates a new, clean attempt (no inherited draft answers).
    _mark_in_progress(session, exam)
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    # Nạp nháp đã lưu (chỉ attempt đang làm), phục hồi đúng chỗ đã làm.
    drafts = {
        d.question_id: d.user_answer
        for d in session.exec(
            select(DraftAnswer).where(DraftAnswer.attempt_id == attempt.id)
        ).all()
    }

    qs = session.exec(
        select(Question).where(Question.exam_id == exam_id)
        .order_by(Question.part, Question.group_no, Question.number)
    ).all()
    # parse payload (KHÔNG gửi answer_json ra trang làm bài)
    parsed = [{
        "id": q.id, "part": q.part, "group_no": q.group_no, "number": q.number,
        "payload": json.loads(q.payload_json),
        "draft": drafts.get(q.id, ""),
    } for q in qs]

    fill_groups: list[dict] = []
    for g in sorted({d["group_no"] for d in parsed if d["part"] == "fill_blank"},
                    key=lambda x: (x is None, x)):
        gq = [d for d in parsed if d["part"] == "fill_blank" and d["group_no"] == g]
        fill_groups.append({"group_no": g, "choices": gq[0]["payload"]["choices"],
                            "questions": gq})
    reading_passages: list[dict] = []
    for g in sorted({d["group_no"] for d in parsed if d["part"] == "reading"},
                    key=lambda x: (x is None, x)):
        gq = [d for d in parsed if d["part"] == "reading" and d["group_no"] == g]
        reading_passages.append({"passage": gq[0]["payload"]["passage"], "questions": gq})

    return templates.TemplateResponse(
        request, "exam.html",
        {"exam": exam, "part_labels": PART_LABELS,
         "attempt_id": attempt.id,
         "draft_count": len([d for d in parsed if d["draft"]]),
         "n_questions": len(parsed),
         "fill_groups": fill_groups,
         "order_qs": [d for d in parsed if d["part"] == "order"],
         "reading_passages": reading_passages,
         "build_qs": [d for d in parsed if d["part"] == "build_sentence"],
         "make_qs": [d for d in parsed if d["part"] == "make_sentence"],
         "generation_warnings": []},
    )


@router.post("/exams/{exam_id}/draft")
async def save_draft(exam_id: int, request: Request,
                     session: Session = Depends(get_session)):
    """Autosave nháp: JSON {"answers": {"<qid>": "raw"}} (mục 1.2–1.3 PLAN)."""
    exam = session.get(Exam, exam_id)
    if not exam:
        return JSONResponse({"ok": False, "error": "exam_not_found"}, status_code=404)
    if exam.status == "failed":
        return JSONResponse({"ok": False, "error": "exam_failed"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        body = {}
    raw_answers = body.get("answers", {}) if isinstance(body, dict) else {}

    attempt = _open_attempt(session, exam)
    if attempt is None:
        attempt = Attempt(exam_id=exam.id)
        session.add(attempt)
    _mark_in_progress(session, exam)
    session.add(attempt)
    session.flush()

    valid_qids = set(session.exec(
        select(Question.id).where(Question.exam_id == exam_id)
    ).all())
    existing = {
        d.question_id: d
        for d in session.exec(
            select(DraftAnswer).where(DraftAnswer.attempt_id == attempt.id)
        ).all()
    }

    # Upsert nháp: có value → ghi/sửa; value rỗng → xoá nháp câu đó.
    now = datetime.now(timezone.utc)
    answered = 0
    for key, value in raw_answers.items():
        try:
            qid = int(key)
        except (TypeError, ValueError):
            continue
        if qid not in valid_qids:
            continue
        value = str(value) if value is not None else ""
        if value == "":
            if qid in existing:
                session.delete(existing[qid])
        else:
            answered += 1
            if qid in existing:
                existing[qid].user_answer = value
                existing[qid].updated_at = now
                session.add(existing[qid])
            else:
                session.add(DraftAnswer(
                    attempt_id=attempt.id, question_id=qid,
                    user_answer=value, updated_at=now))
    session.commit()

    return JSONResponse({
        "ok": True,
        "attempt_id": attempt.id,
        "exam_status": exam.status,
        "answered": answered,
        "saved_at": now.isoformat(),
    })


def _collect_pending(qs: list[Question], answers: dict[int, str]) -> tuple:
    """Tách các câu cần LLM (7.2): fs (Viết 2), alt (Viết 1 trật tự khác), exp (Đọc sai)."""
    pending_fs, pending_alt, pending_exp = [], [], []
    for q in qs:
        raw = answers.get(q.id, "")
        res = grade_code(q, raw)
        if res["needs_llm"]:
            if q.part == "make_sentence":
                payload = json.loads(q.payload_json)
                pending_fs.append({"qid": q.id, "hanzi": payload["hanzi"],
                                   "meaning_vi": payload["meaning_vi"], "sentence": raw})
            else:  # build_sentence, dùng đủ cụm nhưng trật tự khác
                correct = json.loads(q.answer_json)["chunks"]
                pending_alt.append({"qid": q.id, "correct": "".join(correct),
                                    "user": "".join(raw.split("|"))})
        elif res["is_correct"] is False and q.part in ("order", "reading"):
            pending_exp.append({"qid": q.id, "correct": json.loads(q.answer_json),
                                "user": raw, "context": json.loads(q.payload_json)})
    return pending_fs, pending_alt, pending_exp, answers


async def _grade_and_save(session: Session, exam: Exam,
                          answers: dict[int, str], attempt: Attempt) -> None:
    """Chấm code (7.1) + 1 LLM call gộp (7.2), lưu attempt/answers + word_stats."""
    qs = session.exec(select(Question).where(Question.exam_id == exam.id)).all()
    pending_fs, pending_alt, pending_exp, _ = _collect_pending(qs, answers)

    for q in qs:
        raw = answers.get(q.id, "")
        res = grade_code(q, raw)
        a = Answer(attempt_id=attempt.id, question_id=q.id,
                   user_answer_json=json.dumps(raw))
        a.is_correct = res["is_correct"]
        session.add(a)
        session.flush()

    feedback: dict[int, dict] = {}
    if pending_fs or pending_alt or pending_exp:
        try:
            feedback = await llm_grade(pending_fs, pending_alt, pending_exp)
        except Exception:
            logger.exception(
                "LLM grading failed during submit: attempt_id=%s exam_id=%s "
                "make_sentence=%d build_sentence=%d explanation=%d",
                attempt.id, exam.id, len(pending_fs), len(pending_alt), len(pending_exp),
            )
            feedback = {}

    fs_ids = {i["qid"] for i in pending_fs}
    alt_ids = {i["qid"] for i in pending_alt}
    for qid, fb in feedback.items():
        a = session.exec(select(Answer).where(
            Answer.attempt_id == attempt.id, Answer.question_id == qid)).first()
        if a is None:
            continue
        if qid in fs_ids:
            a.score = fb.get("score")
            if a.score is not None:
                a.is_correct = a.score >= 5.0  # ≥5/8 = "đã làm được" (mục 8)
        elif qid in alt_ids:
            a.is_correct = bool(fb.get("accepted"))
        a.feedback_json = json.dumps(fb, ensure_ascii=False)
        session.add(a)

    attempt.submitted_at = datetime.now(timezone.utc)
    session.commit()
    recompute_scores(session, attempt.id)
    _update_word_stats(session, attempt.id)


def _update_word_stats(session: Session, attempt_id: int) -> None:
    """M5: cập nhật word_stats cho từ mục tiêu (mục 8 PLAN)."""
    answers = session.exec(select(Answer).where(Answer.attempt_id == attempt_id)).all()
    reported_qids = {r.question_id for r in session.exec(select(Report)).all()}
    now = datetime.now(timezone.utc)
    for a in answers:
        q = session.get(Question, a.question_id)
        if q is None or a.question_id in reported_qids:
            continue  # câu bị báo lỗi: không tính (mục 6.3)
        if a.is_correct is None:
            continue  # chưa chấm được (LLM lỗi) — không kết luận đúng/sai
        for wid in json.loads(q.target_word_ids_json):
            ws = session.get(WordStat, wid)
            if ws is None:
                ws = WordStat(word_id=wid)
                session.add(ws)
            ws.seen += 1
            ws.last_seen_at = now
            if a.is_correct:
                ws.correct_streak += 1
            else:
                ws.wrong += 1
                ws.correct_streak = 0
                ws.last_wrong_at = now
    session.commit()


@router.post("/exams/{exam_id}/submit")
async def submit_exam(exam_id: int, request: Request, session: Session = Depends(get_session)):
    exam = session.get(Exam, exam_id)
    if not exam:
        return HTMLResponse("Không tìm thấy đề.", status_code=404)
    if exam.status == "failed":
        return HTMLResponse("Đề này không có câu hỏi (sinh thất bại).", status_code=404)

    form = await request.form()
    answers = {}
    for key, value in form.items():
        if not key.startswith("a_"):
            continue
        try:
            answers[int(key[2:])] = value
        except ValueError:
            continue

    # Ưu tiên attempt_id form gửi kèm (đúng nháp đã load); fallback: attempt đang làm.
    attempt = None
    try:
        form_attempt_id = int(form.get("attempt_id") or 0)
    except ValueError:
        form_attempt_id = 0
    if form_attempt_id:
        candidate = session.get(Attempt, form_attempt_id)
        if candidate and candidate.exam_id == exam.id:
            if candidate.submitted_at is not None:
                # retry lần submit trước đã xong: đưa thẳng về kết quả.
                return RedirectResponse(f"/attempts/{candidate.id}", status_code=302)
            attempt = candidate
    if attempt is None:
        # Nếu submit xảy ra sau autosave/nav/network edge, merge draft values.
        attempt = _open_attempt(session, exam)
    if attempt is None:
        attempt = Attempt(exam_id=exam.id)
        session.add(attempt)
        session.commit()
        session.refresh(attempt)
    drafts = session.exec(
        select(DraftAnswer).where(DraftAnswer.attempt_id == attempt.id)
    ).all()
    for draft in drafts:
        # Form includes empty fields: only use draft where the user did not send one.
        answers.setdefault(draft.question_id, draft.user_answer)
    # A full form with empty fields can still override drafts; only substitute when
    # the field is absent (e.g. transport fallback), not when explicitly empty.
    if not any(k.startswith("a_") for k in form.keys()):
        answers = {d.question_id: d.user_answer for d in drafts}

    # Idempotent submit: if browser retries after a successful commit, return
    # to the existing result instead of creating/processing another attempt.
    if attempt.submitted_at is not None:
        return RedirectResponse(f"/attempts/{attempt.id}", status_code=302)

    try:
        await _grade_and_save(session, exam, answers, attempt)
    except Exception:
        session.rollback()
        raise
    exam.status = "done"
    session.add(exam)
    session.exec(delete(DraftAnswer).where(DraftAnswer.attempt_id == attempt.id))
    session.commit()
    return RedirectResponse(f"/attempts/{attempt.id}", status_code=302)


@router.post("/attempts/{attempt_id}/regrade")
async def regrade(attempt_id: int, session: Session = Depends(get_session)):
    """'Thử chấm lại': chấm lại các câu LLM đang lỗi (score/correct = None)."""
    attempt = session.get(Attempt, attempt_id)
    if not attempt:
        return HTMLResponse("Không tìm thấy.", status_code=404)
    exam = session.get(Exam, attempt.exam_id)
    answers = session.exec(select(Answer).where(Answer.attempt_id == attempt.id)).all()
    raw_by_q = {a.question_id: json.loads(a.user_answer_json) for a in answers}

    # chỉ gom các câu LLM đang "chờ" (chưa có kết luận)
    pending_fs, pending_alt, pending_exp = [], [], []
    for a in answers:
        q = session.get(Question, a.question_id)
        raw = raw_by_q.get(q.id, "")
        if q.part == "make_sentence" and a.is_correct is None and raw:
            payload = json.loads(q.payload_json)
            pending_fs.append({"qid": q.id, "hanzi": payload["hanzi"],
                               "meaning_vi": payload["meaning_vi"], "sentence": raw})
        elif q.part == "build_sentence" and a.is_correct is None and raw:
            if sorted(raw.split("|")) == sorted(json.loads(q.payload_json)["chunks"]):
                correct = json.loads(q.answer_json)["chunks"]
                pending_alt.append({"qid": q.id, "correct": "".join(correct),
                                    "user": "".join(raw.split("|"))})
        elif a.is_correct is False and q.part in ("order", "reading") and not a.feedback_json:
            pending_exp.append({"qid": q.id, "correct": json.loads(q.answer_json),
                                "user": raw, "context": json.loads(q.payload_json)})

    regrade_error = False
    if pending_fs or pending_alt or pending_exp:
        try:
            feedback = await llm_grade(pending_fs, pending_alt, pending_exp)
        except Exception:
            logger.exception(
                "LLM grading failed during regrade: attempt_id=%s exam_id=%s "
                "make_sentence=%d build_sentence=%d explanation=%d",
                attempt.id, exam.id, len(pending_fs), len(pending_alt), len(pending_exp),
            )
            feedback = {}
            regrade_error = True
        fs_ids = {i["qid"] for i in pending_fs}
        alt_ids = {i["qid"] for i in pending_alt}
        for a in answers:
            fb = feedback.get(a.question_id)
            if not fb:
                continue
            q = session.get(Question, a.question_id)
            if a.question_id in fs_ids:
                a.score = fb.get("score")
                if a.score is not None:
                    a.is_correct = a.score >= 5.0
            elif a.question_id in alt_ids:
                a.is_correct = bool(fb.get("accepted"))
            a.feedback_json = json.dumps(fb, ensure_ascii=False)
            session.add(a)
        session.commit()
        recompute_scores(session, attempt.id)
        _update_word_stats(session, attempt.id)
    if regrade_error:
        return RedirectResponse(f"/attempts/{attempt_id}?regrade_error=1", status_code=302)
    return RedirectResponse(f"/attempts/{attempt_id}", status_code=302)


@router.post("/attempts/{attempt_id}/report")
async def report_question(attempt_id: int, qid: int = Form(...),
                          note: str = Form(""), session: Session = Depends(get_session)):
    attempt = session.get(Attempt, attempt_id)
    if not attempt:
        return HTMLResponse("Không tìm thấy.", status_code=404)
    session.add(Report(question_id=qid, note=note or None))
    session.commit()
    recompute_scores(session, attempt.id)  # câu mới báo → loại khỏi điểm
    _update_word_stats(session, attempt.id)
    return RedirectResponse(f"/attempts/{attempt_id}", status_code=302)


@router.get("/attempts/{attempt_id}", response_class=HTMLResponse)
def attempt_page(attempt_id: int, request: Request, regrade_error: int = 0,
                 session: Session = Depends(get_session)):
    attempt = session.get(Attempt, attempt_id)
    if not attempt:
        return HTMLResponse("Không tìm thấy.", status_code=404)
    exam = session.get(Exam, attempt.exam_id)
    qs = session.exec(select(Question).where(Question.exam_id == exam.id)).all()
    answers = {a.question_id: a for a in session.exec(
        select(Answer).where(Answer.attempt_id == attempt_id)).all()}
    reported_qids = {r.question_id for r in session.exec(select(Report)).all()}
    words = {w.id: w for w in session.exec(select(Word)).all()}

    def user_display(q: Question, a: Answer | None) -> str:
        if a is None:
            return ""
        raw = json.loads(a.user_answer_json)
        raw = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        if q.part == "build_sentence":
            return " ".join(c for c in raw.split("|") if c)
        return raw

    rows = []
    for q in sorted(qs, key=lambda x: (x.part, x.group_no or 0, x.number)):
        a = answers.get(q.id)
        fb = json.loads(a.feedback_json) if (a and a.feedback_json) else None
        ans = json.loads(q.answer_json) if q.answer_json else None
        rows.append({
            "q": q, "a": a, "fb": fb,
            "user": user_display(q, a),
            "reported": q.id in reported_qids,
            "pending": bool(a and a.is_correct is None),
            "wrong_words": ([words[i] for i in json.loads(q.target_word_ids_json)
                             if i in words] if (a and a.is_correct is False) else []),
        })
    n_pending = sum(1 for r in rows if r["pending"] and r["user"])
    parts = []
    for part, label in PART_LABELS.items():
        prows = [r for r in rows if r["q"].part == part]
        if not prows:
            continue
        parts.append({
            "part": part, "label": label, "rows": prows,
            "n_ok": sum(1 for r in prows if r["a"] and r["a"].is_correct),
        })
    return templates.TemplateResponse(
        request, "attempt.html",
        {"attempt": attempt, "exam": exam, "rows": rows, "parts": parts,
         "pass_total": PASS_TOTAL, "n_pending": n_pending,
         "regrade_error": bool(regrade_error),
         "ans_by_q": {q.id: (json.loads(q.answer_json) if q.answer_json else None)
                      for q in qs}},
    )
