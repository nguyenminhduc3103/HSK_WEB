from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine
from sqlalchemy.pool import StaticPool

from .config import settings

if settings.sqlite_path:
    # SQLite: StaticPool để mọi thread dùng cùng connection (app 1 người dùng)
    engine = create_engine(
        f"sqlite:///{settings.sqlite_path}",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(settings.database_url)


def migrate_exam_status() -> None:
    """Backfill lifecycle status for existing exams after metadata.create_all().

    Keep the migration idempotent and compatible with SQLite and PostgreSQL.
    """
    inspector = inspect(engine)
    if not inspector.has_table("exams") or not inspector.has_table("attempts"):
        return
    columns = {column["name"] for column in inspector.get_columns("exams")}
    if "status" not in columns:
        return
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE exams SET status = 'done' WHERE EXISTS ("
            "SELECT 1 FROM attempts WHERE attempts.exam_id = exams.id "
            "AND attempts.submitted_at IS NOT NULL)"
        ))
        connection.execute(text(
            "UPDATE exams SET status = 'ready' "
            "WHERE status IS NULL OR status NOT IN "
            "('ready', 'in_progress', 'done', 'failed')"
        ))
        # A previously in-progress attempt should be reflected as such unless
        # a completed submission takes precedence (handled above).
        connection.execute(text(
            "UPDATE exams SET status = 'in_progress' WHERE status = 'ready' "
            "AND EXISTS (SELECT 1 FROM attempts WHERE attempts.exam_id = exams.id "
            "AND attempts.submitted_at IS NULL)"
        ))


def initialize_database() -> None:
    from .models import create_all

    create_all()
    migrate_exam_status()

    # SQLModel metadata creates new tables, but for an existing DB the newly
    # introduced table will be created by create_all() without altering legacy tables.
    inspector = inspect(engine)
    if inspector.has_table("draft_answers"):
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_draft_answers_attempt_id "
                "ON draft_answers (attempt_id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_draft_answers_question_id "
                "ON draft_answers (question_id)"
            ))
