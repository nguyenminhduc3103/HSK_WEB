"""Client LLM dùng chung (OpenAI-compatible, mặc định Gemini qua Google AI Studio).

- call_json(): gọi model, parse kết quả qua model pydantic (không tin LLM).
- Ưu tiên response_format=json_schema; provider không hỗ trợ thì fallback json_object.
- Sai → gọi lại kèm thông báo lỗi (tối đa max_retries).
"""
import json
import asyncio
import random

import openai
from pydantic import BaseModel

from .config import settings

SYSTEM = "Bạn là người ra đề và chấm thi HSK (tiếng Trung) chuyên nghiệp. Trả lời ngắn gọn, đúng định dạng yêu cầu."


class LLMError(Exception):
    pass


def _client() -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "sk-none",
    )


def _strip_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


async def call_json(
    prompt: str,
    out_cls: type[BaseModel],
    model: str | None = None,
    system: str = SYSTEM,
    max_retries: int = 2,
) -> BaseModel:
    """Gọi LLM, trả về instance của out_cls.

    `out_cls` là pydantic model mô tả JSON mong muốn (schema gửi kèm).
    Lỗi (JSON hỏng / validate sai / lỗi network) → gọi lại kèm thông báo, tối đa max_retries lần.
    """
    model = model or settings.llm_model
    client = _client()
    last_err: Exception | None = None
    use_schema = True
    # One primary request plus max_retries retries. Respect provider Retry-After
    # when available; otherwise bounded exponential backoff for 429/5xx.
    total_attempts = max_retries + 1

    for attempt in range(1, total_attempts + 1):
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        content = prompt
        if attempt > 1 and last_err and not isinstance(
            last_err, (openai.RateLimitError, openai.APIStatusError)
        ):
            content = (
                f"{prompt}\n\n"
                f"[Lưu ý] Lần trước trả về không đúng định dạng / bị lỗi: {last_err}\n"
                f"Hãy trả lại đúng JSON theo schema, không kèm văn bản thừa."
            )
        msgs.append({"role": "user", "content": content})
        kwargs: dict = {"model": model, "messages": msgs, "temperature": 0.4}

        try:
            if use_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "exam",
                        "strict": True,
                        "schema": out_cls.model_json_schema(),
                    },
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}

            resp = await client.chat.completions.create(**kwargs)
            raw = resp.choices[0].message.content or ""
            data = json.loads(_strip_fence(raw))
            return out_cls.model_validate(data)

        except openai.RateLimitError as e:
            # 429 (hết hạn mức / bị giới hạn tần suất free tier): chờ rồi retry.
            last_err = e
            await _sleep_backoff(attempt, e)
            continue
        except openai.BadRequestError as e:
            msg = str(e).lower()
            if use_schema and ("json_schema" in msg or "response_format" in msg or "not supported" in msg):
                # Provider không hỗ trợ json_schema -> fallback json_object, thử lại ngay
                use_schema = False
                last_err = e
                continue
            last_err = e
        except json.JSONDecodeError as e:
            last_err = e
        except Exception as e:  # network, timeout, validate
            last_err = e
            await _sleep_backoff(attempt, e, retry_on_server_error=True)

    if isinstance(last_err, openai.RateLimitError):
        details = "429 provider rate/quota limit reached; wait for quota reset or check provider limits"
        raise LLMError(f"{details} ({last_err})")
    raise LLMError(f"Gọi LLM thất bại sau {total_attempts} lần: {last_err}")


async def _sleep_backoff(attempt: int, err: Exception, retry_on_server_error: bool = False) -> None:
    """Chờ giữa các lần retry. 429 luôn chờ; 5xx/server-error chờ theo retry_on_server_error."""
    code = getattr(err, "status_code", None)
    is_rate_limited = isinstance(err, openai.RateLimitError)
    if not (is_rate_limited or (retry_on_server_error and code in (500, 502, 503))):
        return
    base = 5.0
    delay = base * attempt + random.uniform(0, 1)
    await asyncio.sleep(delay)


async def call_text(
    prompt: str,
    model: str | None = None,
    system: str = SYSTEM,
) -> str:
    """Gọi LLM trả text thường (không JSON). Dùng khi cần nội dung tự do."""
    model = model or settings.llm_model
    client = _client()
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    resp = await client.chat.completions.create(model=model, messages=msgs, temperature=0.4)
    return (resp.choices[0].message.content or "").strip()
