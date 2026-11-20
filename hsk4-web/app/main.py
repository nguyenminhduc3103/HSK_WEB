from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from . import models
from .db import initialize_database
from .deps import get_session, require_admin
from .routes_exam import router as exam_router
from .routes_review import router as review_router
from .routes_vocab import router as vocab_router
from .routes_review import review_items
from .grading import PASS_TOTAL


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="HSK 4 luyện đề", lifespan=lifespan)
app.include_router(vocab_router)
app.include_router(exam_router)
app.include_router(review_router)

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    n_words = len(session.exec(select(models.Word)).all())
    attempts = session.exec(
        select(models.Attempt).where(models.Attempt.submitted_at.is_not(None))
        .order_by(models.Attempt.id.desc()).limit(10)
    ).all()
    exams = session.exec(
        select(models.Exam).where(models.Exam.status != "failed")
        .order_by(models.Exam.id.desc()).limit(30)
    ).all()
    exam_rows = []
    for exam in exams:
        latest_attempt = session.exec(
            select(models.Attempt).where(models.Attempt.exam_id == exam.id)
            .order_by(models.Attempt.id.desc())
        ).first()
        draft_count = 0
        if latest_attempt and latest_attempt.submitted_at is None:
            draft_count = len(session.exec(
                select(models.DraftAnswer).where(
                    models.DraftAnswer.attempt_id == latest_attempt.id)
            ).all())
        exam_rows.append({
            "exam": exam,
            "attempt": latest_attempt,
            "draft_count": draft_count,
            "label_no": exam.id,
        })
    n_wrong = len(review_items(session, limit=10000))
    return templates.TemplateResponse(
        request, "index.html",
        {"n_words": n_words, "n_attempts": len(attempts),
         "n_wrong": n_wrong, "history": attempts, "exams": exam_rows,
         "pass_total": PASS_TOTAL},
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_index(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/index.html")
