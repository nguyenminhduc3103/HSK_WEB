"""M2: kiểm tra logic THUẦN của các bộ sinh (không gọi LLM).

Dùng sample JSON/pydantic + DB tạm (fixture `session` mới) để chạy:
- validate_order / validate_reading / validate_build / fill_blank._validate_one
- plan_targets (từ sai được ưu tiên vào đọc 1 + viết 2)
- make_sentence.gen (không LLM)
"""
import pytest
from datetime import datetime, timezone
from sqlmodel import Session, create_engine, select
from sqlalchemy.pool import StaticPool

from app import models


@pytest.fixture()
def session(tmp_path):
    db_file = tmp_path / "t.db"
    e = create_engine(
        f"sqlite:///{db_file}", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    from app import models

    # Tạo bảng trên engine tạm (không dùng models.create_all() — nó dùng engine global)
    models.SQLModel.metadata.create_all(e)
    with Session(e) as s:
        for i, h in enumerate("测试汉字词汇语"):
            s.add(models.Word(hanzi=h, pinyin=f"p{i}", meaning_vi=f"nghĩa{i}"))
        s.commit()
        yield s


# ---- Đọc 2 ---------------------------------------------------------------
def test_order_validate_ok(session):
    from app.gen.order import _Item, validate_order
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    it = _Item(segments=["B", "A", "C"], correct_order="BAC", explanation_vi="x")
    # A="B", B="A" (vế mở đầu = segments[0]=B->'A'?) — cấu trúc:
    # idx: A->0, B->1, C->2; order "BAC" => segments[1]+segments[0]+segments[2]
    it.segments = ["x", "测试y", "z"]  # vế mở đầu = segments[1] chứa từ
    assert validate_order(it, w, set()) is None


def test_order_rejects_non_pernutation(session):
    from app.gen.order import _Item, validate_order
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    it = _Item(segments=["a测试", "b", "c"], correct_order="AAB", explanation_vi="x")
    assert validate_order(it, w, set()) is not None


def test_order_rejects_connective_opener(session):
    from app.gen.order import _Item, validate_order
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    # vế mở đầu bắt đầu bằng 所以 -> sai
    it = _Item(segments=["所以测试", "b", "c"], correct_order="ABC", explanation_vi="x")
    assert validate_order(it, w, set()) is not None


# ---- Đọc 3 ---------------------------------------------------------------
def test_reading_validate_ok(session):
    from app.gen.reading import _Item, _Q, validate_reading
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    passage = "测试" + "是" * 60  # >40 chữ
    it = _Item(passage=passage, questions=[
        _Q(question="q", options=["a", "b", "c", "d"], answer_index=2, explanation_vi="x")])
    assert validate_reading(it, w, 1) is None


def test_reading_rejects_duplicate_options(session):
    from app.gen.reading import _Item, _Q, validate_reading
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    passage = "测试" + "是" * 60
    it = _Item(passage=passage, questions=[
        _Q(question="q", options=["a", "a", "c", "d"], answer_index=0, explanation_vi="x")])
    assert validate_reading(it, w, 1) is not None


# ---- Viết 1 ---------------------------------------------------------------
def test_build_validate_ok(session):
    from app.gen.build_sentence import _Item, validate_build
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    it = _Item(sentence="我们测试了系统",
               chunks=["我们", "测试", "了", "系统"], explanation_vi="x")
    assert validate_build(it, w) is None


def test_build_rejects_mismatch(session):
    from app.gen.build_sentence import _Item, validate_build
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    # nối chunks != sentence
    it = _Item(sentence="我们测试了系统",
               chunks=["我们", "测试", "了", "别", "系统"], explanation_vi="x")
    assert validate_build(it, w) is not None


# ---- Đọc 1 ----------------------------------------------------------------
def test_fill_validate_one(session):
    from app.gen.fill_blank import _validate_one, _Item
    w = models.Word(hanzi="测试", pinyin="cèshì", meaning_vi="thử")
    session.add(w)
    session.commit()
    session.refresh(w)
    it = _Item(sentence="我们（ ）了系统", answer="测试", explanation_vi="x")
    assert _validate_one(it, w, set()) is None
    bad = _Item(sentence="我们测试了系统（ ）", answer="别的", explanation_vi="x")
    assert _validate_one(bad, w, set()) is not None


# ---- plan_targets ----------------------------------------------------------
def test_plan_targets_prefers_wrong(session):
    from app.exam import plan_targets, MINI_SPEC
    # đánh dấu 2 từ đang sai
    ws = [w for w in session.exec(
        select(models.Word)).all()][:2]
    for w in ws:
        session.add(models.WordStat(word_id=w.id, wrong=1, correct_streak=0,
                                    last_wrong_at=datetime.now(timezone.utc)))
    session.commit()
    spec = {"fill_blank_groups": 1, "order": 2, "reading": [1],
            "build_sentence": 2, "make_sentence": 1}
    t = plan_targets(session, spec)
    wrong_ids = {w.id for w in ws}
    in_fb = any(w.id in wrong_ids for w in t["fill_blank"])
    assert in_fb, "từ sai phải được ưu tiên đưa vào Đọc 1 (điền từ)"
    # tổng số từ >= tổng slot (có thể dùng lại nếu DB nhỏ)
    total_slots = sum([5 * spec["fill_blank_groups"], spec["order"], len(spec["reading"]),
                       spec["build_sentence"], spec["make_sentence"]])
    assert sum(len(v) for v in t.values()) >= total_slots


# ---- M5: từ sai đề 1 → đề 2 ------------------------------------------------
def test_m5_wrong_word_surfaces_next_exam(session):
    """Từ X sai ở đề 1 (word_stats.wrong>0) phải được ưu tiên vào đề 2."""
    from app.exam import plan_targets
    from sqlmodel import select as _sel

    w = [w for w in session.exec(_sel(models.Word)).all()][0]
    session.add(models.WordStat(word_id=w.id, wrong=1, correct_streak=0,
                                last_wrong_at=datetime.now(timezone.utc)))
    session.commit()

    spec = {"fill_blank_groups": 1, "order": 2, "reading": [1],
            "build_sentence": 2, "make_sentence": 1}
    t = plan_targets(session, spec)
    assert w.id in [x.id for x in t["fill_blank"]], \
        "từ sai (3 từ đầu) phải được ưu tiên vào Đọc 1"

    # Sau khi làm đúng 2 liên tiếp + seen cao -> không bị ưu tiên nữa (mục 8)
    ws = session.get(models.WordStat, w.id)
    ws.correct_streak = 2
    ws.seen = 99  # đứng cuối hàng "từ mới nhất" để không bị take() nhặt
    session.add(ws)
    session.commit()
    t2 = plan_targets(session, spec)
    assert w.id not in [x.id for x in t2["fill_blank"]], \
        "từ đã nhớ (streak>=2) không được ưu tiên vào Đọc 1"
    assert w.id not in [x.id for x in t2["make_sentence"]], \
        "từ đã nhớ (streak>=2) không được ưu tiên vào Viết 2"


# ---- make_sentence ---------------------------------------------------------
def test_make_sentence_no_llm(session):
    from app.gen import make_sentence
    from app.gen.common import GenStats
    ws = [w for w in session.exec(
        select(models.Word)).all()][:3]
    stats = GenStats()
    qs = make_sentence.gen(session, ws, stats)
    assert len(qs) == 3
    assert all(q["part"] == "make_sentence" for q in qs)
    assert stats.calls == 0  # không gọi LLM
    assert all(q["answer"] is None for q in qs)


