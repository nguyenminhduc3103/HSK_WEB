"""M4: kiểm tra logic chấm THUẦN CODE (không gọi LLM)."""
import json
import pytest
from sqlmodel import Session

from app import models
from app.grading import grade_code


def _q(part: str, answer_json: str = None, payload_json: str = "") -> models.Question:
    return models.Question(
        exam_id=1, part=part, number=1,
        payload_json=payload_json or "{}",
        answer_json=answer_json or "{}",
        target_word_ids_json="[]",
    )


def test_grade_code_reading_label():
    q = _q("reading", json.dumps({"label": "B"}))
    assert grade_code(q, "b")["is_correct"] is True
    assert grade_code(q, "C")["is_correct"] is False


def test_grade_code_order():
    q = _q("order", json.dumps({"order": "BAC"}))
    assert grade_code(q, "bac")["is_correct"] is True
    assert grade_code(q, "ACB")["is_correct"] is False


def test_grade_code_fill_blank():
    q = _q("fill_blank", json.dumps({"label": "E"}))
    assert grade_code(q, "E")["is_correct"] is True
    assert grade_code(q, "A")["is_correct"] is False


def test_grade_code_build_sentence():
    payload = json.dumps({"chunks": ["我们", "测试", "系统"]})
    answer = json.dumps({"chunks": ["我们", "测试", "系统"]})
    q = _q("build_sentence", answer, payload)
    assert grade_code(q, "我们|测试|系统")["is_correct"] is True

    # đủ cụm nhưng trật tự khác -> chờ LLM
    r = grade_code(q, "测试|我们|系统")
    assert r["is_correct"] is None and r["needs_llm"] is True

    # thiếu cụm -> sai
    assert grade_code(q, "我们|测试")["is_correct"] is False

    # bỏ trống -> sai
    assert grade_code(q, "")["is_correct"] is False


def test_grade_code_make_sentence():
    q = _q("make_sentence", "null")
    assert grade_code(q, "")["is_correct"] is False  # trống = 0 điểm
    r = grade_code(q, "我测试了")
    assert r["is_correct"] is None and r["needs_llm"] is True
