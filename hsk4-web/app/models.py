from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class Word(SQLModel, table=True):
    __tablename__ = "words"
    id: int | None = Field(default=None, primary_key=True)
    hanzi: str = Field(index=True, unique=True)
    pinyin: str
    han_viet: str | None = None
    meaning_vi: str
    level: int | None = None  # 3 hoặc 4, NULL nếu file không có cột "Cấp"
    example_zh: str | None = None
    example_pinyin: str | None = None
    example_vi: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Exam(SQLModel, table=True):
    __tablename__ = "exams"
    id: int | None = Field(default=None, primary_key=True)
    mode: str  # 'full' | 'mini'
    model: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ready"  # 'ready' | 'failed'


class Question(SQLModel, table=True):
    __tablename__ = "questions"
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True, foreign_key="exams.id")
    part: str  # 'fill_blank' | 'order' | 'reading' | 'build_sentence' | 'make_sentence'
    number: int
    group_no: int | None = None  # Đọc 1: nhóm 1/2; Đọc 3: nhóm đoạn hỏi 2 câu
    payload_json: str
    answer_json: str
    target_word_ids_json: str  # JSON list[int]


class Attempt(SQLModel, table=True):
    __tablename__ = "attempts"
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True, foreign_key="exams.id")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: datetime | None = None
    score_reading: float | None = None
    score_writing: float | None = None
    total: float | None = None


class Answer(SQLModel, table=True):
    __tablename__ = "answers"
    id: int | None = Field(default=None, primary_key=True)
    attempt_id: int = Field(index=True, foreign_key="attempts.id")
    question_id: int = Field(index=True, foreign_key="questions.id")
    user_answer_json: str
    is_correct: bool | None = None
    score: float | None = None
    feedback_json: str | None = None


class WordStat(SQLModel, table=True):
    __tablename__ = "word_stats"
    word_id: int = Field(primary_key=True, foreign_key="words.id")
    seen: int = 0
    wrong: int = 0
    correct_streak: int = 0
    last_wrong_at: datetime | None = None
    last_seen_at: datetime | None = None


class Report(SQLModel, table=True):
    __tablename__ = "reports"
    """Nút 'Báo câu lỗi' của người học."""

    id: int | None = Field(default=None, primary_key=True)
    question_id: int = Field(index=True, foreign_key="questions.id")
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DraftAnswer(SQLModel, table=True):
    """Nháp chưa nộp: câu đã làm của attempt đang làm (autosave, mục 1.2 PLAN).

    Không đặt unique constraint (để SQLite cũ không lỗi khi thêm bảng sau);
    "1 nháp mỗi câu" quản lý bằng code trong routes_exam.
    """

    __tablename__ = "draft_answers"
    id: int | None = Field(default=None, primary_key=True)
    attempt_id: int = Field(index=True, foreign_key="attempts.id")
    question_id: int = Field(index=True, foreign_key="questions.id")
    user_answer: str = ""  # raw, đúng định dạng submit (label "A", "BAC", "c1|c2", câu viết)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def create_all() -> None:
    from .db import engine

    SQLModel.metadata.create_all(engine)
