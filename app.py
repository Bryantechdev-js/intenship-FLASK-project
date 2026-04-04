import os
import re
import secrets
import sqlite3
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instance" / "datasecure.db"

load_dotenv(BASE_DIR / ".env")

LOGIN_ATTEMPT_WINDOW_SECONDS = 300
LOGIN_ATTEMPT_LIMIT = 5
REGISTER_ATTEMPT_WINDOW_SECONDS = 900
REGISTER_ATTEMPT_LIMIT = 4
RATE_LIMIT_BUCKETS = {}
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,30}$")
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$")
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z '\-.,]{1,79}$")
DEPARTMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/\-]{1,79}$")
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,128}$")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["DATABASE"] = str(DB_PATH)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV") == "production"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["FORMSUBMIT_EMAIL"] = os.getenv("FORMSUBMIT_EMAIL", "support@ttsetglobal.com")


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            department TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'worker')),
            password_hash TEXT NOT NULL
        )
        """
    )
    db.commit()
    seed_demo_users()


def seed_demo_users():
    db = get_db()
    users = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    if users == 0:
        demo_users = [
            {
                "username": "admin",
                "email": "admin@ttsetglobal.local",
                "full_name": "TTSET System Administrator",
                "department": "Administration",
                "role": "admin",
                "password": "Admin@12345",
            },
            {
                "username": "worker",
                "email": "worker@ttsetglobal.local",
                "full_name": "TTSET Staff Member",
                "department": "ICT Support",
                "role": "worker",
                "password": "Worker@12345",
            },
        ]
        for user in demo_users:
            db.execute(
                """
                INSERT INTO users (username, email, full_name, department, role, password_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user["username"],
                    user["email"],
                    user["full_name"],
                    user["department"],
                    user["role"],
                    generate_password_hash(user["password"]),
                ),
            )
        db.commit()


def get_client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit_key(action, identifier=""):
    return f"{action}:{get_client_ip()}:{identifier or 'default'}"


def prune_attempts(key, window_seconds):
    now = time.time()
    attempts = RATE_LIMIT_BUCKETS.get(key, [])
    attempts = [timestamp for timestamp in attempts if now - timestamp < window_seconds]
    RATE_LIMIT_BUCKETS[key] = attempts
    return attempts


def is_rate_limited(action, limit, window_seconds, identifier=""):
    key = rate_limit_key(action, identifier)
    attempts = prune_attempts(key, window_seconds)
    if len(attempts) >= limit:
        retry_after_seconds = window_seconds - (time.time() - attempts[0])
        return True, max(1, int(retry_after_seconds))
    return False, 0


def record_rate_limit_attempt(action, window_seconds, identifier=""):
    key = rate_limit_key(action, identifier)
    attempts = prune_attempts(key, window_seconds)
    attempts.append(time.time())
    RATE_LIMIT_BUCKETS[key] = attempts


def clear_rate_limit_attempts(action, identifier=""):
    RATE_LIMIT_BUCKETS.pop(rate_limit_key(action, identifier), None)


def sanitize_text(value, max_len=120):
    cleaned = " ".join((value or "").strip().split())
    cleaned = cleaned.replace("<", "").replace(">", "")
    return cleaned[:max_len]


def generate_csrf_token():
    token = session.get("_csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf_token(form_token):
    session_token = session.get("_csrf_token")
    if not form_token or not session_token:
        return False
    return secrets.compare_digest(form_token, session_token)


@app.context_processor
def inject_template_globals():
    return {
        "csrf_token": generate_csrf_token,
        "formsubmit_email": app.config["FORMSUBMIT_EMAIL"],
    }


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if session.get("role") not in allowed_roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


@app.before_request
def load_logged_in_user():
    g.user = None
    session.permanent = True
    user_id = session.get("user_id")

    if user_id:
        now = int(time.time())
        last_seen = session.get("last_seen", now)
        timeout_seconds = int(app.config["PERMANENT_SESSION_LIFETIME"].total_seconds())

        if now - last_seen > timeout_seconds:
            session.clear()
            flash("Your session timed out. Please log in again.", "warning")
            if request.endpoint not in ("login", "register", "index", "static"):
                return redirect(url_for("login"))
            return None

        session["last_seen"] = now

    if user_id:
        g.user = (
            get_db()
            .execute("SELECT * FROM users WHERE id = ?", (user_id,))
            .fetchone()
        )


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "media-src 'self' https:; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self' https://formsubmit.co; "
        "frame-ancestors 'none'"
    )
    return response


@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """
    For TTSET GLOBAL LTD demo purposes, registration creates worker accounts only.
    Admin accounts should be created by the system owner.
    """
    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token", "")):
            flash("Your secure form session expired. Please submit again.", "warning")
            return render_template("register.html"), 400

        full_name = sanitize_text(request.form.get("full_name", ""), max_len=80)
        username = sanitize_text(request.form.get("username", ""), max_len=30).lower()
        email = sanitize_text(request.form.get("email", ""), max_len=120).lower()
        department = sanitize_text(request.form.get("department", ""), max_len=80)
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        rate_id = email or username or "unknown"

        limited, retry_after = is_rate_limited(
            action="register",
            limit=REGISTER_ATTEMPT_LIMIT,
            window_seconds=REGISTER_ATTEMPT_WINDOW_SECONDS,
            identifier=rate_id,
        )
        if limited:
            retry_minutes = max(1, (retry_after + 59) // 60)
            flash(
                f"Too many registration attempts. Try again in {retry_minutes} minute(s).",
                "warning",
            )
            return render_template("register.html"), 429

        error = None
        if not all([full_name, username, email, department, password, confirm_password]):
            error = "All fields are required."
        elif not FULL_NAME_PATTERN.fullmatch(full_name):
            error = "Enter a valid full name using letters and standard punctuation."
        elif not USERNAME_PATTERN.fullmatch(username):
            error = "Username must be 3-30 characters and contain only lowercase letters, numbers, dot, underscore, or dash."
        elif not EMAIL_PATTERN.fullmatch(email):
            error = "Enter a valid email address."
        elif not DEPARTMENT_PATTERN.fullmatch(department):
            error = "Enter a valid department name."
        elif len(password) < 8:
            error = "Password must be at least 8 characters long."
        elif not PASSWORD_PATTERN.fullmatch(password):
            error = "Password must include letters, numbers, and at least one special character."
        elif password != confirm_password:
            error = "Passwords do not match."

        db = get_db()
        existing_user = db.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (username, email),
        ).fetchone()
        if not error and existing_user:
            error = "Username or email already exists."

        if error:
            record_rate_limit_attempt(
                action="register",
                window_seconds=REGISTER_ATTEMPT_WINDOW_SECONDS,
                identifier=rate_id,
            )
            flash(error, "danger")
            return render_template("register.html")

        db.execute(
            """
            INSERT INTO users (username, email, full_name, department, role, password_hash)
            VALUES (?, ?, ?, ?, 'worker', ?)
            """,
            (username, email, full_name, department, generate_password_hash(password)),
        )
        db.commit()
        clear_rate_limit_attempts("register", rate_id)
        flash("Staff account created successfully. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token", "")):
            flash("Your secure form session expired. Please submit again.", "warning")
            return render_template("login.html"), 400

        username = sanitize_text(request.form.get("username", ""), max_len=30).lower()
        password = request.form.get("password", "")
        rate_id = username or "unknown"

        limited, retry_after = is_rate_limited(
            action="login",
            limit=LOGIN_ATTEMPT_LIMIT,
            window_seconds=LOGIN_ATTEMPT_WINDOW_SECONDS,
            identifier=rate_id,
        )
        if limited:
            retry_minutes = max(1, (retry_after + 59) // 60)
            flash(
                f"Too many login attempts. Try again in {retry_minutes} minute(s).",
                "warning",
            )
            return render_template("login.html"), 429

        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not USERNAME_PATTERN.fullmatch(username):
            record_rate_limit_attempt(
                action="login",
                window_seconds=LOGIN_ATTEMPT_WINDOW_SECONDS,
                identifier=rate_id,
            )
            flash("Invalid username or password.", "danger")
            return render_template("login.html")

        if not user or not check_password_hash(user["password_hash"], password):
            record_rate_limit_attempt(
                action="login",
                window_seconds=LOGIN_ATTEMPT_WINDOW_SECONDS,
                identifier=rate_id,
            )
            flash("Invalid username or password.", "danger")
            return render_template("login.html")

        clear_rate_limit_attempts("login", rate_id)
        session.clear()
        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["username"] = user["username"]
        session["last_seen"] = int(time.time())
        session.permanent = True

        flash(f"Welcome back, {user['full_name']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("worker_dashboard"))


@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    db = get_db()

    users = db.execute(
        """
        SELECT id, username, email, full_name, department, role
        FROM users
        ORDER BY role ASC, username ASC
        """
    ).fetchall()

    total_users = db.execute(
        "SELECT COUNT(*) AS total FROM users"
    ).fetchone()["total"]

    total_workers = db.execute(
        "SELECT COUNT(*) AS total FROM users WHERE role = 'worker'"
    ).fetchone()["total"]

    total_admins = db.execute(
        "SELECT COUNT(*) AS total FROM users WHERE role = 'admin'"
    ).fetchone()["total"]

    latest_user = db.execute(
        """
        SELECT id, username, full_name, department, role
        FROM users
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    return render_template(
        "admin_dashboard.html",
        users=users,
        total_users=total_users,
        total_workers=total_workers,
        total_admins=total_admins,
        latest_user=latest_user,
    )


@app.route("/worker/dashboard")
@role_required("worker")
def worker_dashboard():
    announcements = [
        "Upcoming staff training",
        "System maintenance notice",
        "New internal policy",
    ]
    return render_template(
        "worker_dashboard.html",
        user=g.user,
        announcements=announcements,
    )


@app.route("/worker/profile")
@role_required("worker")
def worker_profile():
    return render_template("worker_profile.html", user=g.user)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("login"))


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
