"""Routes /admin/vocab: danh sách từ + nhập Excel (mục 5 PLAN)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .deps import require_admin
from .models import Word
from . import vocab_import as vi

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin/vocab")


@router.get("/", response_class=HTMLResponse)
def vocab_list(
    request: Request,
    session: Session = Depends(require_admin),
    q: str = "",
):
    stmt = select(Word).order_by(Word.hanzi)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (Word.hanzi.like(like))
            | (Word.pinyin.like(like))
            | (Word.meaning_vi.like(like))
            | (Word.han_viet.like(like))
        )
    words = session.exec(stmt).all()
    return templates.TemplateResponse(
        request,
        "admin/vocab.html",
        {"words": words, "q": q, "count": len(words)},
    )


@router.post("/import", response_class=HTMLResponse)
def vocab_import(
    request: Request,
    file: Annotated[UploadFile, ...],
    session: Session = Depends(require_admin),
):
    content = file.file.read()
    import io

    buf = io.BytesIO(content)
    buf.name = file.filename or "upload.xlsx"
    headers, rows = vi.read_excel(buf)
    if not rows:
        return templates.TemplateResponse(
            request,
            "admin/vocab_import.html",
            {"error": "File rỗng hoặc không đọc được."},
        )

    mapping = vi.detect_columns(headers)
    # Cột bắt buộc tối thiểu
    missing = [k for k in ("hanzi", "meaning_vi") if k not in mapping]
    if missing:
        return templates.TemplateResponse(
            request,
            "admin/vocab_import.html",
            {
                "error": f"Không nhận diện được cột bắt buộc: {missing}. "
                         "Vui lòng kiểm tra file (dòng 1 phải là tiêu đề).",
                "headers": headers,
            },
        )

    token = vi.store_preview(headers, rows, mapping)
    preview = vi.preview_rows(headers, rows, mapping, limit=10)
    return templates.TemplateResponse(
        request,
        "admin/vocab_import.html",
        {
            "headers": headers,
            "mapping": mapping,
            "preview": preview,
            "total_rows": len(rows),
            "token": token,
        },
    )


@router.post("/import/confirm")
async def vocab_import_confirm(
    request: Request,
    session: Session = Depends(require_admin),
):
    form = await request.form()
    token = form.get("token", "")
    pending = vi.pop_preview(token)
    if not pending:
        return templates.TemplateResponse(
            request, "admin/vocab_import.html",
            {"error": "Phiên làm việc xem trước không hợp lệ hoặc đã hết hạn, vui lòng upload lại."},
        )
    # Cho phép user chỉnh mapping qua dropdown (giá trị = index cột)
    headers = pending["headers"]
    rows = pending["rows"]
    mapping = dict(pending["mapping"])
    for key in ("hanzi", "pinyin", "meaning_vi", "example_zh", "example_pinyin", "example_vi", "level"):
        val = form.get(f"col_{key}")
        if val == "":
            mapping.pop(key, None)
        elif val is not None:
            mapping[key] = int(val)
    if "hanzi" not in mapping:
        return templates.TemplateResponse(
            request, "admin/vocab_import.html",
            {"error": "Cần chọn cột 'Từ mới'."},
        )
    items = vi.parse_rows(headers, rows, mapping)
    report = vi.upsert_words(session, items)
    return templates.TemplateResponse(
        request, "admin/vocab_import_done.html",
        {"report": report, "total": len(items)},
    )
