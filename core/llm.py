"""LINER Platform API Router(/api/v1/chat/completions) LLM 호출 모듈. 키는 .env 의 LINER_API_KEY 에서만 읽는다."""
import json
import os
import re
import requests
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(_ENV_PATH)

LINER_CHAT_URL = "https://platform.liner.com/api/v1/chat/completions"
DEFAULT_MODEL = "liner-gpt-router"
FALLBACK_MODEL = "liner-claude-router"

_GLOBAL_STATS = {
    "router_calls": 0,
    "router_success": 0,
    "router_fallback": 0,
}


def get_llm_stats() -> dict[str, int]:
    return dict(_GLOBAL_STATS)


def reset_llm_stats() -> None:
    for k in _GLOBAL_STATS:
        _GLOBAL_STATS[k] = 0


def _key() -> str:
    k = os.getenv("LINER_API_KEY", "").strip()
    if not k or k.startswith("your_"):
        return ""
    return k


def llm_available() -> bool:
    return bool(_key())


def call_llm(
    prompt: str,
    system: str = "",
    model: str | None = None,
    timeout: int = 30,
    post=requests.post,
) -> str | None:
    """LINER Router로 텍스트 응답을 반환. 실패/타임아웃 시 None을 반환해 호출측 폴백을 보장한다."""
    k = _key()
    if not k or prompt is None or not str(prompt).strip():
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": str(prompt)})

    if model:
        candidates = [model]
    else:
        primary = os.getenv("LINER_LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        candidates = [primary] if primary == FALLBACK_MODEL else [primary, FALLBACK_MODEL]

    headers = {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}
    for idx_c, m in enumerate(candidates):
        _GLOBAL_STATS["router_calls"] += 1
        try:
            # response_format={"type":"json_object"} 는 user 메시지에 'json' 영문 단어가 없으면 HTTP 400을 유발하므로 생략한다.
            r = post(
                LINER_CHAT_URL,
                headers=headers,
                json={"model": m, "messages": messages, "temperature": 0, "max_tokens": 2048},
                timeout=timeout,
            )
            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                txt = (content or "").strip()
                if txt:
                    _GLOBAL_STATS["router_success"] += 1
                    if idx_c > 0:
                        _GLOBAL_STATS["router_fallback"] += 1
                    return txt
        except (requests.Timeout, requests.ConnectionError, TimeoutError):
            return None
        except Exception:
            return None
    return None


def llm_json(
    system: str,
    user: str,
    timeout: int = 45,
    post=requests.post,
) -> dict | None:
    """JSON 객체를 반환. 실패하면 None (호출측이 결정론적 폴백 또는 '확인 불가'로 처리)."""
    txt = call_llm(
        user,
        system=system + "\n반드시 코드블록 없이 순수 JSON 객체만 출력.",
        timeout=timeout,
        post=post,
    )
    if not txt:
        return None

    decoder = json.JSONDecoder()
    for i, ch in enumerate(txt):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(txt[i:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None
