"""Trang "Từ cần ôn" (mục 8 + 9 PLAN).

- Từ đang sai: `wrong > 0` và `correct_streak < 2`, theo lần sai gần nhất.
- "Đã nhớ": đặt `correct_streak >= 2` → từ không bị kéo vào đề nữa (mục 8).
- "Ôn lại": đánh dấu lỗi mới nhất → bắt buộc ưu tiên vào đề sau (mục 8).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .deps import get_session
from .models import Word, WordStat

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def review_items(session: Session, limit: int = 100) -> list[dict]:
    rows = session.exec(
        select(WordStat)
        .where(WordStat.wrong > 0, WordStat.correct_streak < 2)
        .order_by(WordStat.last_wrong_at.desc())
        .limit(limit)
    ).all()
    out = []
    for r in rows:
        w = session.get(Word, r.word_id)
        if w:
            out.append({"word": w, "stat": r})
    return out


@router.get("/review", response_class=HTMLResponse)
def review_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "review.html", {"items": review_items(session)})


@router.post("/review/{word_id}")
def review_action(word_id: int, action: str = Form("remembered"),
                  session: Session = Depends(get_session)):
    """POST action="remembered" (Đã nhớ) hoặc "again" (Ôn lại)."""
    if session.get(Word, word_id) is None:
        return HTMLResponse("Không tìm thấy.", status_code=404)
    ws = session.get(WordStat, word_id)
    if ws is None:
        ws = WordStat(word_id=word_id)
        session.add(ws)
    now = datetime.now(timezone.utc)
    if action == "again":
        ws.wrong += 1
        ws.correct_streak = 0
        ws.last_wrong_at = now  # mới nhất → pick_wrong_words đưa vào đề sau
    else:
        ws.correct_streak = max(ws.correct_streak, 2)  # "đã nhớ" (mục 8)
    session.commit()
    return RedirectResponse("/review", status_code=302)
