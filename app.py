"""
app.py — AutoCode: Self-Correcting Code Analyzer
- Groq  → primary AI provider  (fast, free tier available)
- OpenAI → secondary / fallback
- API keys entered at runtime via /setup page (stored in server session)
- No keys ever accepted as form fields on /analyze
"""

import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, render_template, redirect,
                   request, send_file, session, url_for, abort, after_this_request)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename

from analyzer.syntax_checker import check_syntax
from ai.ai_corrector import correct_code

# ── Env & logging ─────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}',
)
logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

secret = os.environ.get("SECRET_KEY", "dev-secret-change-in-production-12345")
app.secret_key = secret

# ── Config ────────────────────────────────────────────────────────────────────
UPLOAD_FOLDER   = Path("uploads")
CORRECTED_FOLDER = Path("corrected")
UPLOAD_FOLDER.mkdir(exist_ok=True)
CORRECTED_FOLDER.mkdir(exist_ok=True)

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 512 * 1024))  # 512 KB
MAX_CODE_CHARS   = int(os.environ.get("MAX_CODE_CHARS", 20_000))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".c", ".cpp", ".cs", ".go",
    ".rb", ".php", ".swift", ".kt", ".rs",
    ".html", ".css", ".sql", ".sh", ".txt",
}

# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(
    get_remote_address, app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def get_session_keys():
    """Return (groq_key, openai_key) from the user's session."""
    return (
        session.get("groq_api_key", "").strip(),
        session.get("openai_api_key", "").strip(),
    )

def keys_configured() -> bool:
    groq_key, openai_key = get_session_keys()
    return bool(groq_key or openai_key)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("index.html", keys_ok=keys_configured())


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Page where user enters their API keys at runtime."""
    error = None
    if request.method == "POST":
        groq_key   = request.form.get("groq_api_key", "").strip()
        openai_key = request.form.get("openai_api_key", "").strip()

        if not groq_key and not openai_key:
            error = "Please enter at least one API key (Groq or OpenAI)."
        else:
            # Store keys in the server-side session (never in the URL or localStorage)
            session["groq_api_key"]   = groq_key
            session["openai_api_key"] = openai_key
            session.permanent = False  # keys clear when browser closes
            return redirect(url_for("home"))

    return render_template("setup.html", error=error, keys_ok=keys_configured())


@app.route("/clear-keys")
def clear_keys():
    session.pop("groq_api_key", None)
    session.pop("openai_api_key", None)
    return redirect(url_for("setup"))


@app.route("/analyze", methods=["POST"])
@limiter.limit("10 per minute")
def analyze():
    if not keys_configured():
        return redirect(url_for("setup"))

    language    = request.form.get("language", "python").strip().lower()
    pasted_code = (request.form.get("code", "") or "").strip()
    uploaded_file = request.files.get("file")

    groq_key, openai_key = get_session_keys()
    code = ""
    upload_path = None

    # ── File upload ────────────────────────────────────────────────────────────
    if uploaded_file and uploaded_file.filename:
        filename = secure_filename(uploaded_file.filename)
        if not allowed_file(filename):
            return render_template(
                "result.html",
                language=language,
                original_code="", corrected_code="",
                errors=[f"File type not allowed. Accepted: "
                        f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"],
                explanation="", session_id=None, keys_ok=True,
            )
        upload_path = UPLOAD_FOLDER / filename
        uploaded_file.save(str(upload_path))
        try:
            code = upload_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return render_template(
                "result.html",
                language=language,
                original_code="", corrected_code="",
                errors=["Could not read file as UTF-8. Upload a plain-text source file."],
                explanation="", session_id=None, keys_ok=True,
            )
        finally:
            if upload_path and upload_path.exists():
                upload_path.unlink(missing_ok=True)

    # ── Pasted code ────────────────────────────────────────────────────────────
    elif pasted_code:
        if len(pasted_code) > MAX_CODE_CHARS:
            return render_template(
                "result.html",
                language=language,
                original_code="", corrected_code="",
                errors=[f"Code too long ({len(pasted_code):,} chars). "
                        f"Max: {MAX_CODE_CHARS:,}."],
                explanation="", session_id=None, keys_ok=True,
            )
        code = pasted_code
    else:
        return redirect(url_for("home"))

    # ── Syntax check (Python only, local) ─────────────────────────────────────
    syntax_errors = check_syntax(code) if language == "python" else []

    # ── AI correction ──────────────────────────────────────────────────────────
    try:
        corrected_code, ai_issues, used_ai, provider_used = correct_code(
            code, language,
            groq_key=groq_key,
            openai_key=openai_key,
        )
    except Exception as exc:
        logger.error('"Correction failed: %s"', exc)
        corrected_code = code
        ai_issues  = []
        used_ai    = False
        provider_used = None
        syntax_errors.append({
            "type": "Correction Error",
            "line": "-",
            "message": f"Could not correct code: {exc}",
        })

    # ── Build errors list ──────────────────────────────────────────────────────
    errors = [
        f"{e['type']} at Line {e['line']}: {e['message']}"
        for e in syntax_errors
    ]
    errors.extend(ai_issues)
    if not errors:
        errors.append("✅ No issues found — code looks clean.")

    # ── Explanation ────────────────────────────────────────────────────────────
    if used_ai:
        explanation = (
            f"Analyzed and corrected by {provider_used} — "
            f"supports all languages."
        )
    elif language == "python":
        explanation = (
            "AI providers unavailable. Used local Python linter (autopep8). "
            "Only common syntax issues are caught."
        )
    else:
        explanation = (
            f"AI providers unavailable. No offline corrector exists for "
            f"{language}. Add a valid Groq or OpenAI key to enable AI correction."
        )

    # ── Save per-session corrected file ───────────────────────────────────────
    session_id = uuid.uuid4().hex
    out_path = CORRECTED_FOLDER / f"corrected_{session_id}.txt"
    out_path.write_text(corrected_code, encoding="utf-8")

    return render_template(
        "result.html",
        language=language,
        original_code=code,
        corrected_code=corrected_code,
        errors=errors,
        explanation=explanation,
        session_id=session_id,
        keys_ok=True,
        provider_used=provider_used,
    )


@app.route("/download/<session_id>")
def download(session_id: str):
    if not session_id.isalnum() or len(session_id) != 32:
        abort(400, "Invalid session ID.")
    filepath = CORRECTED_FOLDER / f"corrected_{session_id}.txt"
    if not filepath.exists():
        abort(404, "File not found or already downloaded.")

    @after_this_request
    def cleanup(response):
        try:
            filepath.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning('"Could not delete corrected file: %s"', exc)
        return response

    return send_file(str(filepath), as_attachment=True,
                     download_name="corrected_code.txt")


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(413)
def file_too_large(_):
    return render_template(
        "result.html", language="", original_code="", corrected_code="",
        errors=[f"File too large. Max size: {MAX_UPLOAD_BYTES // 1024} KB."],
        explanation="", session_id=None, keys_ok=keys_configured(),
    ), 413

@app.errorhandler(429)
def rate_limited(_):
    return render_template(
        "result.html", language="", original_code="", corrected_code="",
        errors=["Too many requests. Wait a moment and try again."],
        explanation="", session_id=None, keys_ok=keys_configured(),
    ), 429


# ── Dev entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="127.0.0.1", port=5000)