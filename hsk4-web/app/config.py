import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.lower() in ("1", "true", "yes")


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.getenv(
            "DATABASE_URL", "sqlite:///data/hsk4.db"
        )
        self.llm_base_url: str = os.getenv(
            "LLM_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "")
        self.llm_model: str = os.getenv("LLM_MODEL", "gemini-2.5-flash")
        # Chấm/hiệu chỉnh: để trống = dùng llm_model
        self.llm_model_grade: str = os.getenv("LLM_MODEL_GRADE", "")

        admin_password = os.getenv("ADMIN_PASSWORD", "")
        self.admin_password: str = admin_password
        # Không cho phép chạy app không mật khẩu (đi ngược với mục 4 PLAN: /admin luôn khoá)
        self.admin_enabled: bool = admin_password != ""

        # Chỉ dùng khi database_url là sqlite
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.split("sqlite:///")[-1])
            if not db_path.is_absolute():
                db_path = BASE_DIR / db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.sqlite_path: str | None = str(db_path)
        else:
            self.sqlite_path = None


settings = Settings()
