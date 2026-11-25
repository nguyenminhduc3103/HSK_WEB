"""Chấm điểm (mục 7 PLAN).

- grade_code(): chấm ngay các câu code chấm được (Đọc 1/2/3 so đáp án, Viết 1 so
  chuỗi chuẩn hoá). Câu viết tự do (Viết 2) và Viết 1 "trật tự khác" → trả về
  danh sách cần LLM chấm (llm_grade).
- llm_grade(): 1 lời gọi gộp (7.2): chấm Viết 2 (0–8), xét Viết 1 trật tự khác,
  giải thích ngắn các câu Đọc 2/3 sai. Code kẹp score vào [0, 8].
- recompute_scores(): quy đổi điểm theo số câu thực có + câu bị báo lỗi.
"""
import json
import unicodedata

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from . import llm
from .models import Answer, Attempt, Question, Report

# Trọng số điểm/câu của đề đầy đủ (mục 3 PLAN). Quy đổi: điểm phần = earned/available*100
POINTS = {"fill_blank": 2.5, "order": 2.5, "reading": 2.5, "build_sentence": 6.0, "make_sentence": 8.0}
READING_PARTS = ("fill_blank", "order", "reading")
WRITING_PARTS = ("build_sentence", "make_sentence")
PASS_TOTAL = 120.0  # ≥60% như ngưỡng HSK (180/300)

_PUNCT = "，。！？、；：…,.!?"


def _norm(s: str) -> str:
    """Chuẩn hoá so Viết 1: bỏ khoảng trắng + dấu câu, NFC."""
    s = unicodedata.normalize("NFC", s)
    return "".join(ch for ch in s if not ch.isspace() and ch not in _PUNCT)


def grade_code(q: Question, user_value: str) -> dict:
    """Chấm 1 câu bằng code.

    Trả dict: {"is_correct": bool|None, "needs_llm": bool}
    - needs_llm: Viết 2 (luôn), hoặc Viết 1 dùng đủ cụm nhưng trật tự khác.
    """
    import json

    ans = json.loads(q.answer_json) if q.answer_json else None
    if q.part == "make_sentence":
        # Không chấm được bằng code (trừ câu rỗng)
        if not user_value.strip():
            return {"is_correct": False, "needs_llm": False}
        return {"is_correct": None, "needs_llm": True}

    if q.part == "build_sentence":
        chunks = [c for c in user_value.split("|") if c]  # JS tách bằng "|"
        if not chunks:
            return {"is_correct": False, "needs_llm": False}
        correct = ans["chunks"]
        if _norm("|".join(chunks)) == _norm("|".join(correct)):
            return {"is_correct": True, "needs_llm": False}
        payload = json.loads(q.payload_json)
        shown = payload["chunks"]
        if sorted(chunks) == sorted(shown):
            # Dùng đủ các cụm nhưng trật tự khác → cho LLM xét (7.1)
            return {"is_correct": None, "needs_llm": True}
        return {"is_correct": False, "needs_llm": False}

    # Đọc 1/2/3: so đáp án trực tiếp
    if q.part == "fill_blank":
        ok = user_value.upper() == ans["label"]
    elif q.part == "order":
        ok = user_value.upper() == ans["order"]
    elif q.part == "reading":
        ok = user_value.upper() == ans["label"]
    else:
        ok = False
    return {"is_correct": ok, "needs_llm": False}


# ---------------------------------------------------------------------------
# LLM chấm + giải thích (7.2) — 1 lời gọi gộp
# ---------------------------------------------------------------------------
class _FS(BaseModel):
    qid: int
    score: int = Field(ge=0, le=8)
    corrected: str | None
    explanation_vi: str
    grammar_tag: str


class _ALT(BaseModel):
    qid: int
    accepted: bool
    explanation_vi: str
    grammar_tag: str


class _EXP(BaseModel):
    qid: int
    explanation_vi: str
    grammar_tag: str


class _GradeOut(BaseModel):
    fs: list[_FS] = Field(description="Chấm từng câu Viết 2")
    alt: list[_ALT] = Field(description="Xét Viết 1 trật tự khác")
    exp: list[_EXP] = Field(description="Giải thích câu Đọc 2/3 sai")


def _llm_grade_prompt(fs_items: list[dict], alt_items: list[dict],
                      exp_items: list[dict]) -> str:
    parts = ["Bạn là giám khảo HSK 4. Chấm và giải thích bằng tiếng Việt, ngắn gọn."]
    if fs_items:
        lines = []
        for it in fs_items:
            lines.append(
                f"qid={it['qid']} | từ: {it['hanzi']} ({it['meaning_vi']}) | câu HS đặt: {it['sentence']}"
            )
        parts.append(
            "## Viết 2 — chấm mỗi câu 0–8 (4 tiêu chí: dùng đúng từ, ngữ pháp, chính tả chữ Hán, độ đầy đủ), "
            "gợi câu sửa, tag ngữ pháp:\n" + "\n".join(lines)
        )
    if alt_items:
        lines = []
        for it in alt_items:
            lines.append(
                f"qid={it['qid']} | câu đúng: {it['correct']} | HS xắp: {it['user']}"
            )
        parts.append(
            "## Viết 1 (trật tự khác) — câu HS dùng đủ từ nhưng trật tự khác; xét có hợp lệ không:\n"
            + "\n".join(lines)
        )
    if exp_items:
        lines = []
        for it in exp_items:
            lines.append(
                f"qid={it['qid']} | đáp án: {it['correct']} | HS chọn: {it['user']} | "
                f"nội dung: {json.dumps(it['context'], ensure_ascii=False)[:200]}"
            )
        parts.append(
            "## Giải thích ngắn câu Đọc sai (1–2 câu, nêu lỗi chính, tag ngữ pháp):\n"
            + "\n".join(lines)
        )
    return "\n\n".join(parts) + """

Trả về JSON: {"fs": [qid, score, corrected, explanation_vi, grammar_tag],
"alt": [qid, accepted, explanation_vi, grammar_tag],
"exp": [qid, explanation_vi, grammar_tag]} — chỉ các qid cho ở trên."""


async def llm_grade(
    fs_items: list[dict],
    alt_items: list[dict],
    exp_items: list[dict],
) -> dict:
    """Gộp thành 1 call. Trả {qid: feedback_dict} đã kẹp điểm.

    fs_items: [{"qid","hanzi","meaning_vi","sentence"}]
    alt_items: [{"qid","correct","user"}]
    exp_items: [{"qid","correct","user","context"}]
    """
    if not (fs_items or alt_items or exp_items):
        return {}
    from .config import settings
    out = await llm.call_json(
        _llm_grade_prompt(fs_items, alt_items, exp_items), _GradeOut,
        model=settings.llm_model_grade or None, max_retries=2,
    )
    feedback: dict[int, dict] = {}
    for f in out.fs:
        feedback[f.qid] = {
            "score": max(0.0, min(8.0, float(f.score))),  # kẹp, không tin min/max
            "corrected": f.corrected,
            "explanation_vi": f.explanation_vi,
            "grammar_tag": f.grammar_tag,
        }
    for a in out.alt:
        feedback[a.qid] = {
            "accepted": a.accepted,
            "explanation_vi": a.explanation_vi,
            "grammar_tag": a.grammar_tag,
        }
    for e in out.exp:
        feedback[e.qid] = {
            "explanation_vi": e.explanation_vi,
            "grammar_tag": e.grammar_tag,
        }
    return feedback


# ---------------------------------------------------------------------------
# Quy đổi điểm (theo số câu thực có, bỏ câu bị báo lỗi)
# ---------------------------------------------------------------------------
def recompute_scores(session: Session, attempt_id: int) -> None:
    attempt = session.get(Attempt, attempt_id)
    answers = session.exec(select(Answer).where(Answer.attempt_id == attempt_id)).all()
    reported = {r.question_id for r in
                session.exec(select(Report).where(Report.question_id.in_([
                    a.question_id for a in answers]))).all()} if answers else set()

    earned: dict[str, float] = {}
    avail: dict[str, float] = {}
    for a in answers:
        q = session.get(Question, a.question_id)
        if q is None or a.question_id in reported:
            continue  # câu bị báo lỗi: không tính điểm, không tính vào từ sai
        if a.is_correct is None:  # câu LLM chưa chấm được
            continue
        p = POINTS[q.part]
        avail[q.part] = avail.get(q.part, 0.0) + p
        if q.part == "make_sentence":
            earned[q.part] = earned.get(q.part, 0.0) + (a.score or 0.0)
        elif a.is_correct:
            fb = None
            if a.feedback_json:
                import json
                fb = json.loads(a.feedback_json)
            if q.part == "build_sentence" and fb is not None and "accepted" in (fb or {}):
                earned[q.part] = earned.get(q.part, 0.0) + (p if fb["accepted"] else 0.0)
            else:
                earned[q.part] = earned.get(q.part, 0.0) + p

    def pct(parts):
        e, v = sum(earned.get(p, 0) for p in parts), sum(avail.get(p, 0) for p in parts)
        return round(e / v * 100, 1) if v else 0.0

    attempt.score_reading = pct(READING_PARTS)
    attempt.score_writing = pct(WRITING_PARTS)
    attempt.total = round(attempt.score_reading + attempt.score_writing, 1)
    session.add(attempt)
    session.commit()


def make_sentence_pending(a: Answer) -> bool:
    """Câu Viết 2 chưa có điểm (LLM lỗi) — nút 'Thử chấm lại'."""
    import json

    try:
        txt = json.loads(a.user_answer_json)
    except Exception:
        txt = a.user_answer_json
    return a.score is None and bool(txt and str(txt).strip())
