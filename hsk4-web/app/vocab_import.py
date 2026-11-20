"""Đọc file Excel từ vựng, nhận diện cột, tách pinyin/Hán Việt, upsert vào DB.

Định dạng (mục 5 PLAN.md):
    STT | Từ mới | Phiên âm | Giải thích | Ví dụ (chữ hán) | Phiên âm | Dịch
Ánh xạ theo VỊ TRÍ vì có 2 cột cùng tên "Phiên âm".
"""
import re
import uuid
from typing import Any

import openpyxl
from sqlmodel import Session, select

from .models import Word

# "ài qíng [ái tình]" -> ("ài qíng", "ái tình"); không có [..] -> (pinyin, None)
_PINYIN_RE = re.compile(r"^(.*?)\s*\[(.*?)\]\s*$")


def split_pinyin(cell: str | None) -> tuple[str, str | None]:
    """Tách cột Phiên âm thành (pinyin, han_viet)."""
    s = (cell or "").strip()
    m = _PINYIN_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s, None


def read_excel(source) -> tuple[list[str], list[list]]:
    """Trả về (headers, data_rows). Đọc sheet đầu tiên, dòng 1 là tiêu đề.

    `source` là đường dẫn str hoặc file-like (BytesIO).
    """
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append(list(row))
    wb.close()
    if not rows:
        return [], []
    headers = [("" if c is None else str(c)).strip() for c in rows[0]]
    data = rows[1:]
    return headers, data


def _norm(h: str) -> str:
    return (h or "").strip().lower()


def detect_columns(headers: list[str]) -> dict[str, int]:
    """Trả về {trường DB: index cột}. Nhận diện theo từ khoá + vị trí.

    Hai cột "Phiên âm": cái trước → pinyin, cái sau → example_pinyin.
    """
    norm = [_norm(h) for h in headers]
    mapping: dict[str, int] = {}
    pinyin_seen = 0
    for i, h in enumerate(norm):
        if h in ("", "stt", " "):
            continue
        if "từ mới" in h or h == "từ" or "từ vựng" in h:
            mapping.setdefault("hanzi", i)
        elif "phiên âm" in h:
            if pinyin_seen == 0:
                mapping.setdefault("pinyin", i)
            else:
                mapping.setdefault("example_pinyin", i)
            pinyin_seen += 1
        elif "giải thích" in h or "nghĩa" in h:
            mapping.setdefault("meaning_vi", i)
        elif "ví dụ" in h:
            mapping.setdefault("example_zh", i)
        elif h == "dịch" or "dịch" in h:
            mapping.setdefault("example_vi", i)
        elif "cấp" in h:
            mapping.setdefault("level", i)
    return mapping


def parse_rows(headers: list[str], rows: list[list], mapping: dict[str, int]) -> list[dict]:
    """Biến đổi data raw thành list dict theo schema DB.

    `mapping` cho phép override cột (từ dropdown trang xem trước).
    """
    def cell(row: list, key: str) -> str | None:
        i = mapping.get(key)
        if i is None or i >= len(row):
            return None
        v = row[i]
        if v is None:
            return None
        return str(v).strip()

    out: list[dict] = []
    for row in rows:
        hanzi = cell(row, "hanzi")
        if not hanzi:
            continue  # bỏ dòng trống / thiếu từ
        pinyin_raw = cell(row, "pinyin") or ""
        pinyin, han_viet = split_pinyin(pinyin_raw)
        level_raw = cell(row, "level")
        level: int | None = None
        if level_raw:
            try:
                level = int(float(level_raw))
            except ValueError:
                level = None
        out.append(
            {
                "hanzi": hanzi,
                "pinyin": pinyin,
                "han_viet": han_viet,
                "meaning_vi": cell(row, "meaning_vi") or "",
                "level": level,
                "example_zh": cell(row, "example_zh"),
                "example_pinyin": cell(row, "example_pinyin"),
                "example_vi": cell(row, "example_vi"),
            }
        )
    return out


def upsert_words(session: Session, items: list[dict]) -> dict:
    """Upsert theo `hanzi` (trùng trong file → bỏ dòng sau).

    Trả về {"added": x, "updated": y, "skipped": z}.
    """
    added = updated = skipped = 0
    seen: set[str] = set()
    for it in items:
        if it["hanzi"] in seen:
            skipped += 1
            continue
        seen.add(it["hanzi"])
        existing = session.exec(select(Word).where(Word.hanzi == it["hanzi"])).first()
        if existing:
            existing.pinyin = it["pinyin"]
            existing.han_viet = it["han_viet"]
            existing.meaning_vi = it["meaning_vi"]
            existing.level = it["level"]
            existing.example_zh = it["example_zh"]
            existing.example_pinyin = it["example_pinyin"]
            existing.example_vi = it["example_vi"]
            updated += 1
        else:
            session.add(Word(**it))
            added += 1
    session.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


# Kho chứa import đang chờ xác nhận (1 người dùng, in-memory là đủ)
_PENDING: dict[str, dict] = {}


def store_preview(headers: list[str], rows: list[list], mapping: dict[str, int]) -> str:
    token = uuid.uuid4().hex
    _PENDING[token] = {"headers": headers, "rows": rows, "mapping": mapping}
    return token


def pop_preview(token: str) -> dict | None:
    return _PENDING.pop(token, None)


def preview_rows(headers: list[str], rows: list[list], mapping: dict[str, int], limit: int = 10) -> list[dict]:
    """Trả về `limit` dòng đầu đã parse (gồm pinyin tách Hán Việt)."""
    return parse_rows(headers, rows, mapping)[:limit]
