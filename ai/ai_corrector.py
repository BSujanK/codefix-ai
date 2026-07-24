"""
ai/ai_corrector.py
------------------
Provider chain:
  1. Groq  (primary  — fast, llama-3.3-70b-versatile)
  2. OpenAI (fallback — gpt-4o-mini)
  3. Local autopep8  (Python only, last resort)

Returns: (corrected_code, issues_list, used_ai, provider_name)
"""

import logging
import os
import time

from analyzer.local_fixer import local_fix

logger = logging.getLogger(__name__)

GROQ_MODEL    = os.environ.get("GROQ_MODEL",   "llama-3.3-70b-versatile")
OPENAI_MODEL  = os.environ.get("OPENAI_MODEL",  "gpt-4o-mini")

_FATAL_CODES   = {401, 403}
_RETRY_CODES   = {429, 500, 502, 503}

SYSTEM_PROMPT = (
    "You are an expert code reviewer and fixer. "
    "The user provides source code in a specific programming language. "
    "Return ONLY the corrected code — no markdown fences, no commentary, "
    "no explanations inside the code block. "
    "After the corrected code, append a line that says exactly 'ISSUES:' "
    "followed by a newline-separated list of issues found (one per line). "
    "If there are no issues write 'ISSUES:\\nNone'."
)


def _parse_response(raw: str):
    """Split AI response into (corrected_code, issues_list)."""
    if "ISSUES:" in raw:
        code_part, issues_part = raw.split("ISSUES:", 1)
        issues = [
            ln.strip()
            for ln in issues_part.strip().splitlines()
            if ln.strip() and ln.strip().lower() != "none"
        ]
        return code_part.strip(), issues
    return raw.strip(), []


# ── Groq ───────────────────────────────────────────────────────────────────────
def _try_groq(code: str, language: str, api_key: str):
    try:
        from groq import Groq, APIStatusError
    except ImportError:
        logger.warning('"groq package not installed"')
        return code, [], False

    client = Groq(api_key=api_key)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": f"Language: {language}\n\nCode:\n{code}"},
                ],
                max_tokens=4096,
                temperature=0,
            )
            raw = response.choices[0].message.content or ""
            corrected, issues = _parse_response(raw)
            return corrected, issues, True

        except APIStatusError as exc:
            status = exc.status_code
            if status in _FATAL_CODES:
                logger.error('"Groq fatal error %s: %s"', status, exc.message)
                return code, [], False
            if status in _RETRY_CODES and attempt == 0:
                logger.warning('"Groq transient %s, retrying..."', status)
                time.sleep(2)
                continue
            logger.error('"Groq error %s: %s"', status, exc.message)
            return code, [], False
        except Exception as exc:
            logger.error('"Groq unexpected: %s"', exc)
            return code, [], False

    return code, [], False


# ── OpenAI ─────────────────────────────────────────────────────────────────────
def _try_openai(code: str, language: str, api_key: str):
    try:
        from openai import OpenAI, APIStatusError
    except ImportError:
        logger.warning('"openai package not installed"')
        return code, [], False

    client = OpenAI(api_key=api_key)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": f"Language: {language}\n\nCode:\n{code}"},
                ],
                max_tokens=4096,
                temperature=0,
            )
            raw = response.choices[0].message.content or ""
            corrected, issues = _parse_response(raw)
            return corrected, issues, True

        except APIStatusError as exc:
            status = exc.status_code
            if status in _FATAL_CODES:
                logger.error('"OpenAI fatal error %s: %s"', status, exc.message)
                return code, [], False
            if status in _RETRY_CODES and attempt == 0:
                logger.warning('"OpenAI transient %s, retrying..."', status)
                time.sleep(2)
                continue
            logger.error('"OpenAI error %s: %s"', status, exc.message)
            return code, [], False
        except Exception as exc:
            logger.error('"OpenAI unexpected: %s"', exc)
            return code, [], False

    return code, [], False


# ── Public entry point ─────────────────────────────────────────────────────────
def correct_code(
    code: str,
    language: str,
    groq_key: str = "",
    openai_key: str = "",
) -> tuple[str, list, bool, str | None]:
    """
    Returns (corrected_code, issues, used_ai, provider_name).
    provider_name is 'Groq', 'OpenAI', or None.
    """
    # 1. Groq (primary)
    if groq_key:
        corrected, issues, ok = _try_groq(code, language, groq_key)
        if ok:
            logger.info('"Correction successful via Groq"')
            return corrected, issues, True, "Groq"
        logger.warning('"Groq failed — falling back to OpenAI"')

    # 2. OpenAI (fallback)
    if openai_key:
        corrected, issues, ok = _try_openai(code, language, openai_key)
        if ok:
            logger.info('"Correction successful via OpenAI"')
            return corrected, issues, True, "OpenAI"
        logger.warning('"OpenAI also failed — using local fixer"')

    # 3. Local fallback (Python only)
    if language.lower() == "python":
        logger.info('"Using local Python fixer"')
        return local_fix(code), [], False, None

    return code, [], False, None
