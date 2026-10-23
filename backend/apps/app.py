"""Chatify web routes. Keep page rendering here and SQL in backend/storage."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import psycopg2
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.storage import main as storage

PROJECT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_DIR / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"

app = FastAPI(title="Chatify")
app.mount("/CHATIFY/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
SESSION_COOKIE = "chatify_session"


@app.on_event("startup")
def prepare_database():
    # Tables are created once if missing; set DB_* values before starting the server.
    storage.init_db()


def hash_password(password, salt=None):
    """Hash a password with Python's built-in scrypt implementation."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password, encoded_hash):
    try:
        algorithm, salt_hex, digest_hex = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)),
                                   f"scrypt${salt_hex}${digest_hex}")
    except (ValueError, TypeError):
        return False


def current_user(request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return storage.get_session_user(hashlib.sha256(token.encode()).hexdigest())


def page(request, name, **context):
    return templates.TemplateResponse(request=request, name=name, context=context)


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    return page(request, "landing_page.html")


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return page(request, "about.html")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return page(request, "terms.html")


@app.get("/register", response_class=HTMLResponse)
@app.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup(request: Request):
    return page(request, "signup.html")


@app.post("/register", response_class=HTMLResponse)
async def register(request: Request, username: str = Form(...), email: str = Form(...),
                   password: str = Form(...), password_confirmation: str = Form(...)):
    username, email = username.strip(), email.strip()
    error = None
    if not (3 <= len(username) <= 30) or not all(c.isascii() and (c.isalnum() or c == "_") for c in username):
        error = "Username 3–30 letters, numbers, ya underscores ka hona chahiye."
    elif "@" not in email or len(email) > 254:
        error = "Valid email address enter karo."
    elif not 12 <= len(password) <= 128:
        error = "Password 12 se 128 characters ka hona chahiye."
    elif password != password_confirmation:
        error = "Dono passwords match nahi karte."
    if error:
        return page(request, "signup.html", error=error)
    try:
        storage.create_user(username, email, hash_password(password))
    except psycopg2.errors.UniqueViolation:
        return page(request, "signup.html", error="Username ya email pehle se registered hai.")
    return RedirectResponse("/login?registered=1", status_code=303)


@app.get("/login", response_class=HTMLResponse)
@app.get("/signin", response_class=HTMLResponse, include_in_schema=False)
async def signin(request: Request):
    if current_user(request):
        return RedirectResponse("/friends", status_code=303)
    notice = "Account ban gaya. Ab sign in karo." if request.query_params.get("registered") else None
    return page(request, "signin.html", notice=notice)


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, identifier: str = Form(...), password: str = Form(...)):
    user = storage.find_user(identifier.strip())
    if not user or not password_matches(password, user["password_hash"]):
        return page(request, "signin.html", error="Username/email ya password sahi nahi hai.")
    token = secrets.token_urlsafe(32)
    storage.create_session(user["id"], hashlib.sha256(token.encode()).hexdigest(),
                           datetime.now(timezone.utc) + timedelta(days=14))
    response = RedirectResponse("/friends", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", max_age=14 * 24 * 60 * 60,
                        path="/")
    return response


@app.get("/inbox")
@app.get("/friends")
async def friends_page(request: Request, search: str = "", message: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return page(request, "friends.html", user=user,
                friends=storage.list_friends(user["id"], search.strip()),
                requests=storage.list_pending_requests(user["id"]), search=search,
                notice=message)


@app.post("/friends/add")
async def add_friend(request: Request, username: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    added = storage.send_friend_request(user["id"], username.strip().lstrip("@"))
    message = "Request bhej di." if added else "User nahi mila, ya request pehle se hai."
    return RedirectResponse(f"/friends?message={quote(message)}", status_code=303)


@app.post("/friends/request/{request_id}")
async def respond_to_request(request: Request, request_id: int, action: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    storage.answer_friend_request(user["id"], request_id, action == "accept")
    return RedirectResponse("/friends", status_code=303)


@app.get("/chats", response_class=HTMLResponse)
async def chats_page(request: Request, with_user: int = 0, conversation: int = 0):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    # A friend id opens the corresponding private chat, creating it if needed.
    if with_user:
        conversation_id = storage.open_direct_chat(user["id"], with_user)
        if conversation_id:
            return RedirectResponse(f"/chats?conversation={conversation_id}", status_code=303)
    messages = storage.read_chat(user["id"], conversation) if conversation else []
    return page(request, "chats.html", user=user, chats=storage.list_user_chats(user["id"]),
                active_id=conversation, messages=messages,
                notice="" if messages is not None else "Chat access nahi hai.")


@app.post("/chats/{conversation_id}/send")
async def send_chat_message(request: Request, conversation_id: int, body: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    body = body.strip()
    if body and len(body) <= 5000:
        storage.save_message(user["id"], conversation_id, body)
    return RedirectResponse(f"/chats?conversation={conversation_id}", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        storage.delete_session(hashlib.sha256(token.encode()).hexdigest())
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
