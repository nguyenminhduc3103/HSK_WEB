import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient với SQLite trong thư mục tạm + admin password 'secret'.

    deps.get_session / require_admin đọc app.db.engine và app.config.settings
    LỚN TRONG HÀM, nên patch đúng chỗ đó (module-level attribute).
    """
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import app.db as db_mod
    import app.config as config_mod
    from app import models

    engine = create_engine(
        f"sqlite:///{db_file}",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    old_engine = db_mod.engine
    old_settings = config_mod.settings
    db_mod.engine = engine  # models.create_all() đọc engine từ app.db
    models.create_all()
    new_settings = config_mod.Settings()
    new_settings.admin_password = "secret"
    new_settings.admin_enabled = True
    config_mod.settings = new_settings
    try:
        import app.main as main_mod

        yield TestClient(main_mod.app)
    finally:
        db_mod.engine = old_engine
        config_mod.settings = old_settings
