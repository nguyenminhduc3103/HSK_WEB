"""Lifecycle integration tests: generated exams, server drafts, and submit."""
import json

from sqlmodel import select

from app import models


def _seed_exam(session):
    exam = models.Exam(mode="mini", model="test-model", status="ready")
    session.add(exam)
    session.commit()
    session.refresh(exam)
    q = models.Question(
        exam_id=exam.id,
        part="reading",
        number=1,
        group_no=1,
        payload_json=json.dumps({
            "passage": "测试文章。",
            "question": "问题？",
            "options": [["A", "选项一"], ["B", "选项二"]],
        }, ensure_ascii=False),
        answer_json=json.dumps({"label": "A", "explanation_vi": "Đúng."}),
        target_word_ids_json="[]",
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return exam.id, q.id


def _db_session():
    from app.db import engine
    from sqlmodel import Session
    return Session(engine)


def test_generated_exam_redirects_to_dashboard(client, monkeypatch):
    import app.routes_exam as routes

    async def fake_gen(session, mode):
        exam_id, _qid = _seed_exam(session)
        return exam_id, {}, 1, []

    monkeypatch.setattr(routes.exam_mod, "generate_exam", fake_gen)
    response = client.post("/exams", data={"mode": "mini"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert "Đề" in client.get("/").text


def test_draft_restored_and_submitted_from_draft(client):
    session = _db_session()
    try:
        exam_id, qid = _seed_exam(session)
    finally:
        session.close()

    page = client.get(f"/exams/{exam_id}")
    assert page.status_code == 200
    assert 'name="attempt_id"' in page.text
    assert "explanation_vi" not in page.text

    saved = client.post(f"/exams/{exam_id}/draft", json={"answers": {str(qid): "A"}})
    assert saved.status_code == 200
    data = saved.json()
    assert data["ok"] is True

    restored = client.get(f"/exams/{exam_id}")
    assert 'value="A" checked' in restored.text
    assert "Đã khôi phục 1 câu bạn làm dở." in restored.text

    submitted = client.post(
        f"/exams/{exam_id}/submit",
        data={"attempt_id": str(data["attempt_id"])},
        follow_redirects=False,
    )
    assert submitted.status_code == 302
    location = submitted.headers["location"]
    assert location.startswith("/attempts/")
    result_id = int(location.rsplit("/", 1)[1])

    session = _db_session()
    try:
        saved_exam = session.get(models.Exam, exam_id)
        assert saved_exam.status == "done"
        attempt = session.get(models.Attempt, result_id)
        assert attempt.submitted_at is not None
        assert not session.exec(select(models.DraftAnswer)).all()
        user_rows = session.exec(select(models.Answer)).all()
        assert any(a.user_answer_json == json.dumps("A") for a in user_rows)
    finally:
        session.close()


def test_draft_rejects_question_from_other_exam(client):
    session = _db_session()
    try:
        exam_a, _qid_a = _seed_exam(session)
        _exam_b, _qid_b = _seed_exam(session)
    finally:
        session.close()

    response = client.post(
        f"/exams/{exam_a}/draft", json={"answers": {"99999": "A"}}
    )
    assert response.status_code == 200
    assert response.json()["answered"] == 0


def test_exam_list_status_flows(client):
    session = _db_session()
    try:
        exam_id, _qid = _seed_exam(session)
        assert session.get(models.Exam, exam_id).status == "ready"
    finally:
        session.close()

    home = client.get("/")
    assert "Sẵn sàng" in home.text

    client.get(f"/exams/{exam_id}")
    home = client.get("/")
    assert "Đang làm" in home.text
    assert "Tiếp tục" in home.text

    r = client.post(f"/exams/{exam_id}/submit", data={}, follow_redirects=False)
    assert r.status_code == 302
    home = client.get("/")
    assert "Đã hoàn thành" in home.text
    assert "Xem kết quả" in home.text
