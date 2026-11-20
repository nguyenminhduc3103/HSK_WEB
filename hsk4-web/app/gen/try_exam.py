"""CLI sinh thử đề (mục M2 PLAN): `python -m app.gen.try_exam --n 10 [--mode full]`

- Sinh n đề (nối tiếp), lưu vào DB (exam + questions).
- In tỉ lệ mục phải sinh lại theo phần.
- In 1 đề ra màn hình (payload + đáp án) để đọc tay.

Cần: LLM_API_KEY trong .env. Chạy từ thư mục hsk4-web:
    python -m app.gen.try_exam --n 10
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..db import engine
from ..exam import generate_many
from ..models import Exam, Question, Word


def _print_exam(session: Session, exam_id: int) -> None:
    exam = session.get(Exam, exam_id)
    qs = session.exec(
        select(Question).where(Question.exam_id == exam_id).order_by(Question.part, Question.number)
    ).all()
    print(f"\n{'=' * 70}\nĐề {exam_id} ({exam.mode}, {exam.model}, {exam.status}) — {len(qs)} câu")
    part_no: dict[str, int] = {}
    for q in qs:
        part_no[q.part] = part_no.get(q.part, 0) + 1
        print(f"\n[{q.part} #{part_no[q.part]}] " + "-" * 40)
        payload = json.loads(q.payload_json)
        print("  PAYLOAD:", json.dumps(payload, ensure_ascii=False)[:300])
        ans = json.loads(q.answer_json)
        print("  ANSWER :", json.dumps(ans, ensure_ascii=False)[:300])
        ids = json.loads(q.target_word_ids_json)
        if ids:
            words = [session.get(Word, i) for i in ids]
            print("  TARGET :", ", ".join(w.hanzi + " " + w.meaning_vi for w in words if w))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--mode", choices=["full", "mini"], default="full")
    args = ap.parse_args()

    t0 = datetime.now(timezone.utc)
    with Session(engine) as session:
        results = asyncio.run(generate_many(session, args.n, args.mode))

    print(f"\nSinh {len(results)} đề trong {datetime.now(timezone.utc) - t0} "
          f"(mode={args.mode})")
    agg: dict[str, dict] = {}
    total_q = 0
    for exam_id, stats, n_q, errors in results:
        total_q += n_q
        if errors:
            print(f"  Đề {exam_id} lỗi: " + " | ".join(errors[:3]))
        else:
            print(f"  Đề {exam_id}: không có lỗi bộ sinh")

        for part, s in stats.items():
            agg.setdefault(part, {}).setdefault("regen", 0)
            agg[part]["regen"] += s.get("regenerated", 0)
    print("Tổng số câu:", total_q)
    if agg:
        print("Tỉ lệ mục phải sinh lại (bỏ qua đề, theo phần):")
        for part, d in agg.items():
            print(f"  {part}: regenerated tổng {d['regen']}")

    if results:
        print_exam_id = results[0][0]
        with Session(engine) as session:
            _print_exam(session, print_exam_id)


if __name__ == "__main__":
    main()
