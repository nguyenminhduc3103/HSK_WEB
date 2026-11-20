"""Dependencies dùng chung (session, auth admin).

Đọc `engine`/`settings` trễ (trong hàm) để test đổi giá trị module-level dễ.
"""
import base64
import secrets

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session


def get_session():
    from .db import engine

    with Session(engine) as session:
        yield session


def require_admin(request: Request, session: Session = Depends(get_session)):
    """HTTP Basic auth cho /admin. Không có ADMIN_PASSWORD thì /admin trả 503."""
    from .config import settings

    if not settings.admin_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_PASSWORD chưa được cấu hình trong .env",
        )
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
            detail="Cần đăng nhập admin",
        )
    try:
        password = base64.b64decode(auth[6:]).decode().partition(":")[2]
    except Exception:
        password = ""
    if not secrets.compare_digest(password, settings.admin_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
            detail="Mật khẩu sai",
        )
    return session
