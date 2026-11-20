"""Test M1: nhập Excel tách pinyin [Hán Việt], nhận diện cột, upsert."""
import openpyxl

from sqlmodel import Session, select

from app import vocab_import as vi
from app.models import Word, create_all


def make_xlsx(tmp_path, with_level=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ["STT", "Từ mới", "Phiên âm", "Giải thích",
               "Ví dụ (chữ hán)", "Phiên âm", "Dịch"]
    if with_level:
        headers.append("Cấp")
    ws.append(headers)
    base_rows = [
        [1, "爱情", "ài qíng [ái tình]", "tình yêu",
         "他们的爱情很美好。", "Tāmen de àiqíng hěn měihǎo.", "Tình yêu của họ rất đẹp."],
        [2, "安排", "ān pái [an bài]", "sắp xếp",
         "我已经安排好了行程。", "Wǒ yǐjīng ānpái hǎo le xíngchéng.", "Tôi đã sắp xếp xong hành trình."],
        [3, "按时", "àn shí", "đúng hạn",
         "我们必须按时完成任务。", "Wǒmen bìxū ànshí wánchéng rènwù.", "Chúng ta phải hoàn thành nhiệm vụ đúng giờ."],
        [4, "按时", "àn shí", "DUPLICATE", "", "", ""],
    ]
    if with_level:
        for r in base_rows:
            r.append(3)
        base_rows.append([5, "保护", "bǎo hù [bảo hộ]", "bảo vệ", "", "", "", 4])
    for r in base_rows:
        ws.append(r)
    path = tmp_path / "vocab.xlsx"
    wb.save(str(path))
    return str(path), headers


def test_split_pinyin():
    assert vi.split_pinyin("ài qíng [ái tình]") == ("ài qíng", "ái tình")
    assert vi.split_pinyin("àn shí") == ("àn shí", None)
    assert vi.split_pinyin(None) == ("", None)
    assert vi.split_pinyin("  ān pái [an bài]  ") == ("ān pái", "an bài")


def test_detect_columns_position_based(tmp_path):
    _, headers = make_xlsx(tmp_path)
    mapping = vi.detect_columns(headers)
    assert mapping["hanzi"] == 1
    assert mapping["pinyin"] == 2          # cột "Phiên âm" thứ nhất
    assert mapping["meaning_vi"] == 3
    assert mapping["example_zh"] == 4
    assert mapping["example_pinyin"] == 5  # cột "Phiên âm" thứ hai
    assert mapping["example_vi"] == 6
    assert "level" not in mapping


def test_parse_rows_split_han_viet(tmp_path):
    path, headers = make_xlsx(tmp_path)
    mapping = vi.detect_columns(headers)
    _, data = vi.read_excel(path)
    items = vi.parse_rows(headers, data, mapping)
    assert len(items) == 4
    assert items[0] == {
        "hanzi": "爱情",
        "pinyin": "ài qíng",
        "han_viet": "ái tình",
        "meaning_vi": "tình yêu",
        "level": None,
        "example_zh": "他们的爱情很美好。",
        "example_pinyin": "Tāmen de àiqíng hěn měihǎo.",
        "example_vi": "Tình yêu của họ rất đẹp.",
    }
    assert items[2]["han_viet"] is None   # "àn shí" không có [..]


def test_level_column(tmp_path):
    path, headers = make_xlsx(tmp_path, with_level=True)
    mapping = vi.detect_columns(headers)
    assert mapping["level"] == 7
    _, data = vi.read_excel(path)
    items = vi.parse_rows(headers, data, mapping)
    assert len(items) == 5
    assert items[0]["level"] == 3
    assert items[-1] == {
        "hanzi": "保护", "pinyin": "bǎo hù", "han_viet": "bảo hộ",
        "meaning_vi": "bảo vệ", "level": 4,
        "example_zh": None, "example_pinyin": None, "example_vi": None,
    }


def test_upsert_words(tmp_path, monkeypatch):
    db_file = tmp_path / "upsert.db"
    from sqlalchemy.pool import StaticPool
    from sqlmodel import create_engine

    import app.db as db_mod

    eng = create_engine(
        f"sqlite:///{db_file}", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    old_engine = db_mod.engine
    db_mod.engine = eng
    try:
        create_all()
        path, headers = make_xlsx(tmp_path)
        mapping = vi.detect_columns(headers)
        _, data = vi.read_excel(path)
        items = vi.parse_rows(headers, data, mapping)
        with Session(eng) as s:
            r1 = vi.upsert_words(s, items)
            assert r1 == {"added": 3, "updated": 0, "skipped": 1}
            items2 = vi.parse_rows(headers, data, mapping)
            r2 = vi.upsert_words(s, items2)
            assert r2 == {"added": 0, "updated": 3, "skipped": 1}
            assert len(s.exec(select(Word)).all()) == 3
    finally:
        db_mod.engine = old_engine


def test_import_http_flow(client, tmp_path):
    """Upload -> preview (token) -> confirm -> từ vào DB của client."""
    path, _ = make_xlsx(tmp_path)
    with open(path, "rb") as f:
        r = client.post(
            "/admin/vocab/import",
            auth=("x", "secret"),
            files={"file": ("vocab.xlsx", f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert r.status_code == 200, r.text
    assert "Xem trước" in r.text
    assert "ái tình" in r.text  # Hán Việt đã tách ra
    token = r.text.split('name="token" value="')[1].split('"')[0]

    r = client.post(
        "/admin/vocab/import/confirm",
        auth=("x", "secret"),
        data={"token": token},
    )
    assert r.status_code == 200, r.text
    assert "Thêm:</b> 3" in r.text
    assert "Bỏ (trùng):</b> 1" in r.text

    import app.db as db_mod
    with Session(db_mod.engine) as s:
        words = s.exec(select(Word)).all()
    assert len(words) == 3
    w = s.exec(select(Word).where(Word.hanzi == "爱情")).one()
    assert w.pinyin == "ài qíng" and w.han_viet == "ái tình"
