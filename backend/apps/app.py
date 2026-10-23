"""Chatify web routes. Keep page rendering here and SQL in backend/storage."""

import asyncio
import hashlib
import hmac
import io
import secrets
from http.cookies import SimpleCookie
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import psycopg2
import socketio
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.storage import main as storage

PROJECT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_DIR / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"

fastapi_app = FastAPI(title="Chatify")
fastapi_app.mount("/CHATIFY/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
SESSION_COOKIE = "chatify_session"

# Socket.IO forwards ordinary HTTP routes to FastAPI and handles realtime events.
sio = socketio.AsyncServer(async_mode="asgi")
# Socket connection state lives only in this Python process, keyed by Socket.IO sid.
socket_sessions = {}


def user_is_online(user_id):
    return any(session["user_id"] == user_id for session in socket_sessions.values())


async def broadcast_presence(user_id, online):
    """Send presence only to users who are friends with the person changing state."""
    friends = await asyncio.to_thread(storage.list_friends, user_id)
    for friend in friends:
        await sio.emit("presence_update", {"user_id": user_id, "online": online},
                       room=f"user:{friend['id']}")


@fastapi_app.on_event("startup")
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


async def current_user(request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await asyncio.to_thread(storage.get_session_user, hashlib.sha256(token.encode()).hexdigest())


def page(request, name, **context):
    return templates.TemplateResponse(request=request, name=name, context=context)


@fastapi_app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    return page(request, "landing_page.html")


@fastapi_app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return page(request, "about.html")


@fastapi_app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return page(request, "terms.html")


@fastapi_app.get("/register", response_class=HTMLResponse)
@fastapi_app.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup(request: Request):
    return page(request, "signup.html")


@fastapi_app.post("/register", response_class=HTMLResponse)
async def register(request: Request, username: str = Form(...), display_name: str = Form(...), email: str = Form(...),
                   password: str = Form(...), password_confirmation: str = Form(...)):
    username, display_name, email = username.strip(), display_name.strip(), email.strip()
    error = None
    if not (3 <= len(username) <= 30) or not all(c.isascii() and (c.isalnum() or c == "_") for c in username):
        error = "Username 3–30 letters, numbers, only use underscore in username."
    elif "@" not in email or len(email) > 254:
        error = "please enter valid email address"
    elif not 1 <= len(display_name) <= 80:
        error = "Display name must be 1 to 80 characters."
    elif not 8 <= len(password) <= 128:
        error = "Password should only contain 8-128 characters."
    elif password != password_confirmation:
        error = "Passwords doesn't match."
    if error:
        return page(request, "signup.html", error=error)
    try:
        await asyncio.to_thread(storage.create_user, username, email, hash_password(password), display_name)
    except psycopg2.errors.UniqueViolation:
        return page(request, "signup.html", error="Username or email are already registered.")
    return RedirectResponse("/login?registered=1", status_code=303)


@fastapi_app.get("/login", response_class=HTMLResponse)
@fastapi_app.get("/signin", response_class=HTMLResponse, include_in_schema=False)
async def signin(request: Request):
    if await current_user(request):
        return RedirectResponse("/friends", status_code=303)
    notice = "Signup completed, Now please signin." if request.query_params.get("registered") else None
    return page(request, "signin.html", notice=notice)


@fastapi_app.post("/login", response_class=HTMLResponse)
async def login(request: Request, identifier: str = Form(...), password: str = Form(...)):
    user = await asyncio.to_thread(storage.find_user, identifier.strip())
    if not user or not password_matches(password, user["password_hash"]):
        return page(request, "signin.html", error="Username/email or password is wrong.")
    token = secrets.token_urlsafe(32)
    await asyncio.to_thread(storage.create_session, user["id"], hashlib.sha256(token.encode()).hexdigest(),
                            datetime.now(timezone.utc) + timedelta(days=14))
    response = RedirectResponse("/friends", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", max_age=14 * 24 * 60 * 60,
                        path="/")
    return response


@fastapi_app.get("/inbox")
@fastapi_app.get("/friends")
async def friends_page(request: Request, search: str = "", message: str = ""):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    friend_requests = await asyncio.to_thread(storage.list_pending_requests, user["id"])
    friends, unread_count = await asyncio.gather(
        asyncio.to_thread(storage.list_friends, user["id"], search.strip()),
        asyncio.to_thread(storage.unread_message_count, user["id"]),
    )
    return page(request, "friends.html", user=user,
                friends=friends,
                requests=friend_requests, has_requests=bool(friend_requests), search=search,
                has_unread_messages=unread_count > 0,
                notice=message)


@fastapi_app.post("/friends/add")
async def add_friend(request: Request, username: str = Form(...)):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    added, receiver_id, request_kind, request_id = await asyncio.to_thread(
        storage.send_friend_request, user["id"], username.strip().lstrip("@"))
    if added and request_kind == "request":
        await sio.emit("friend_request", {
            "request_id": request_id,
            "sender_id": user["id"],
            "name": user["display_name"],
            "username": user["username"],
            "has_avatar": user["has_avatar"],
        }, room=f"user:{receiver_id}")
    elif added and request_kind == "accepted":
        await sio.emit("friend_request_accepted", {"name": user["display_name"]}, room=f"user:{receiver_id}")
    message = "Request sent." if added else "User not found."
    return RedirectResponse(f"/friends?message={quote(message)}", status_code=303)


@fastapi_app.post("/friends/request/{request_id}")
async def respond_to_request(request: Request, request_id: int, action: str = Form(...)):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    await asyncio.to_thread(storage.answer_friend_request, user["id"], request_id, action == "accept")
    count = await asyncio.to_thread(storage.pending_request_count, user["id"])
    await sio.emit("friend_requests_count", {"count": count}, room=f"user:{user['id']}")
    return RedirectResponse("/friends", status_code=303)


@fastapi_app.get("/users/{user_id}/avatar")
async def user_avatar(user_id: int):
    image_bytes = await asyncio.to_thread(storage.get_avatar, user_id)
    if not image_bytes:
        return Response(status_code=404)
    return Response(image_bytes, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@fastapi_app.post("/profile/avatar")
async def change_avatar(request: Request, avatar: UploadFile = File(...)):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    # Limit upload size, crop to square, and store a predictable 256px avatar.
    raw_image = await avatar.read(5 * 1024 * 1024 + 1)
    if len(raw_image) > 5 * 1024 * 1024:
        return RedirectResponse("/friends?message=Image+must+be+under+5+MB", status_code=303)
    try:
        with Image.open(io.BytesIO(raw_image)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported image format")
            square_image = ImageOps.fit(source.convert("RGB"), (256, 256), method=Image.Resampling.LANCZOS)
            output = io.BytesIO()
            square_image.save(output, format="JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError):
        return RedirectResponse("/friends?message=Choose+a+valid+JPG+PNG+or+WEBP+image", status_code=303)
    await asyncio.to_thread(storage.save_avatar, user["id"], output.getvalue())
    return RedirectResponse("/friends?message=Profile+photo+updated", status_code=303)


@fastapi_app.post("/profile/name")
async def change_display_name(request: Request, display_name: str = Form(...)):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    display_name = display_name.strip()
    if 1 <= len(display_name) <= 80:
        await asyncio.to_thread(storage.update_display_name, user["id"], display_name)
        return RedirectResponse("/friends?message=Name+updated", status_code=303)
    return RedirectResponse("/friends?message=Name+must+be+1+to+80+characters", status_code=303)


@fastapi_app.get("/chats", response_class=HTMLResponse)
async def chats_page(request: Request, with_user: int = 0, conversation: int = 0):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    # A friend id opens the corresponding private chat, creating it if needed.
    if with_user:
        conversation_id = await asyncio.to_thread(storage.open_direct_chat, user["id"], with_user)
        if conversation_id:
            return RedirectResponse(f"/chats?conversation={conversation_id}", status_code=303)
    if conversation:
        messages, friend_requests, chats = await asyncio.gather(
            asyncio.to_thread(storage.read_chat, user["id"], conversation),
            asyncio.to_thread(storage.list_pending_requests, user["id"]),
            asyncio.to_thread(storage.list_user_chats, user["id"]),
        )
        if messages is not None:
            await asyncio.to_thread(storage.mark_chat_read, user["id"], conversation)
    else:
        messages = []
        friend_requests, chats = await asyncio.gather(
            asyncio.to_thread(storage.list_pending_requests, user["id"]),
            asyncio.to_thread(storage.list_user_chats, user["id"]),
        )
    active_partner = next((chat for chat in chats if chat["id"] == conversation), None)
    return page(request, "chats.html", user=user, chats=chats, active_partner=active_partner,
                has_requests=bool(friend_requests), active_id=conversation, messages=messages,
                has_unread_messages=any(chat["unread_count"] for chat in chats),
                notice="" if messages is not None else "Chat access nahi hai.")


@fastapi_app.post("/chats/{conversation_id}/send")
async def send_chat_message(request: Request, conversation_id: int, body: str = Form(...)):
    user = await current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    body = body.strip()
    if body and len(body) <= 5000:
        saved = await asyncio.to_thread(storage.save_message, user["id"], conversation_id, body)
        if saved:
            message = {
                "conversation_id": conversation_id,
                "id": saved["id"],
                "body": body,
                "sender_id": user["id"],
                "display_name": user["display_name"],
                "created_at": saved["created_at"].isoformat(),
            }
            await sio.emit("new_message", message, room=f"chat:{conversation_id}")
            recipients = await asyncio.to_thread(storage.conversation_recipient_ids, conversation_id, user["id"])
            for recipient_id in recipients:
                await sio.emit("unread_message", {"conversation_id": conversation_id, "body": body}, room=f"user:{recipient_id}")
    return RedirectResponse(f"/chats?conversation={conversation_id}", status_code=303)


async def publish_attachment_message(user, conversation_id, saved, kind):
    message = {
        "conversation_id": conversation_id,
        "id": saved["id"],
        "body": "[Image]" if kind == "image" else "[Voice note]",
        "attachment_kind": kind,
        "attachment_url": f"/chats/{conversation_id}/messages/{saved['id']}/attachment",
        "sender_id": user["id"],
        "display_name": user["display_name"],
        "created_at": saved["created_at"].isoformat(),
    }
    await sio.emit("new_message", message, room=f"chat:{conversation_id}")
    recipients = await asyncio.to_thread(storage.conversation_recipient_ids, conversation_id, user["id"])
    for recipient_id in recipients:
        await sio.emit("unread_message", {"conversation_id": conversation_id, "body": message["body"]},
                       room=f"user:{recipient_id}")
    return message


@fastapi_app.post("/chats/{conversation_id}/attachments")
async def send_chat_attachment(request: Request, conversation_id: int, attachment: UploadFile = File(...)):
    user = await current_user(request)
    if not user:
        return JSONResponse({"error": "Please sign in again."}, status_code=401)
    raw_data = await attachment.read(10 * 1024 * 1024 + 1)
    if not raw_data or len(raw_data) > 10 * 1024 * 1024:
        return JSONResponse({"error": "Attachments must be under 10 MB."}, status_code=413)

    mime_type = (attachment.content_type or "").split(";")[0].lower()
    if mime_type in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        try:
            with Image.open(io.BytesIO(raw_data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                    raise ValueError("Unsupported image format")
                if source.width * source.height > 40_000_000:
                    raise ValueError("Image dimensions are too large")
                image = source.convert("RGB")
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=85, optimize=True)
                raw_data, mime_type, kind = output.getvalue(), "image/jpeg", "image"
        except (UnidentifiedImageError, OSError, ValueError):
            return JSONResponse({"error": "Choose a valid JPG, PNG, WEBP, or GIF image."}, status_code=400)
    elif mime_type in {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav"}:
        if mime_type == "audio/x-wav":
            mime_type = "audio/wav"
        kind = "audio"
    else:
        return JSONResponse({"error": "Choose an image or record a supported voice note."}, status_code=400)

    saved = await asyncio.to_thread(storage.save_attachment, user["id"], conversation_id,
                                    "image" if kind == "image" else "audio", mime_type, raw_data)
    if not saved:
        return JSONResponse({"error": "This conversation is unavailable."}, status_code=403)
    message = await publish_attachment_message(user, conversation_id, saved, "image" if kind == "image" else "audio")
    return JSONResponse({"ok": True, "message": message})


@fastapi_app.get("/chats/{conversation_id}/messages/{message_id}/attachment")
async def chat_attachment(request: Request, conversation_id: int, message_id: int):
    user = await current_user(request)
    if not user:
        return Response(status_code=401)
    attachment = await asyncio.to_thread(storage.get_message_attachment, user["id"], conversation_id, message_id)
    if not attachment:
        return Response(status_code=404)
    mime_type, data = attachment
    return Response(data, media_type=mime_type,
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@fastapi_app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await asyncio.to_thread(storage.delete_session, token_hash)
        await sio.emit("session_revoked", room=f"session:{token_hash}")
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@sio.event
async def connect(sid, environ, auth=None):
    """Authenticate Socket.IO with the same opaque cookie as the HTTP pages."""
    cookies = SimpleCookie(environ.get("HTTP_COOKIE", ""))
    session_cookie = cookies.get(SESSION_COOKIE)
    if not session_cookie:
        return False
    token_hash = hashlib.sha256(session_cookie.value.encode()).hexdigest()
    user = await asyncio.to_thread(storage.get_session_user, token_hash)
    if not user:
        return False
    already_online = user_is_online(user["id"])
    socket_sessions[sid] = {"user_id": user["id"], "token_hash": token_hash}
    await sio.enter_room(sid, f"user:{user['id']}")
    await sio.enter_room(sid, f"session:{token_hash}")
    if not already_online:
        sio.start_background_task(broadcast_presence, user["id"], True)


@sio.on("sync_presence")
async def sync_presence(sid):
    """Load friend presence after the socket handshake is established."""
    session = socket_sessions.get(sid)
    if not session:
        return {"ok": False}
    friends = await asyncio.to_thread(storage.list_friends, session["user_id"])
    online_ids = {friend["id"] for friend in friends if user_is_online(friend["id"])}
    await sio.emit("presence_snapshot", {"online_user_ids": list(online_ids)}, to=sid)
    return {"ok": True}


@sio.on("join_chat")
async def join_chat(sid, data):
    """Join a chat room only if the current user is a member in PostgreSQL."""
    try:
        conversation_id = int(data["conversation_id"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False}
    session = socket_sessions.get(sid)
    if not session:
        return {"ok": False}
    user = await asyncio.to_thread(storage.get_session_user, session["token_hash"])
    if not user:
        return {"ok": False}
    messages = await asyncio.to_thread(storage.read_chat, user["id"], conversation_id)
    if messages is None:
        return {"ok": False}
    await sio.enter_room(sid, f"chat:{conversation_id}")
    unread_count = await asyncio.to_thread(storage.mark_chat_read, user["id"], conversation_id)
    await sio.emit("unread_count", {"count": unread_count or 0}, room=f"user:{user['id']}")
    return {"ok": True}


@sio.on("mark_read")
async def mark_read(sid, data):
    """Mark a chat read while it is open, so new-message dots clear live."""
    session = socket_sessions.get(sid)
    if not session:
        return {"ok": False}
    try:
        conversation_id = int(data["conversation_id"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False}
    unread_count = await asyncio.to_thread(storage.mark_chat_read, session["user_id"], conversation_id)
    if unread_count is None:
        return {"ok": False}
    await sio.emit("unread_count", {"count": unread_count}, room=f"user:{session['user_id']}")
    return {"ok": True, "count": unread_count}


@sio.on("send_message")
async def socket_send_message(sid, data):
    """Save first, then send the new message to all members in that chat room."""
    try:
        conversation_id = int(data["conversation_id"])
        body = str(data["body"]).strip()
    except (KeyError, TypeError, ValueError):
        return {"ok": False}
    if not body or len(body) > 5000:
        return {"ok": False}
    session = socket_sessions.get(sid)
    if not session:
        return {"ok": False}
    user = await asyncio.to_thread(storage.get_session_user, session["token_hash"])
    if not user:
        return {"ok": False}
    saved = await asyncio.to_thread(storage.save_message, user["id"], conversation_id, body)
    if not saved:
        return {"ok": False}
    await sio.emit("new_message", {
        "conversation_id": conversation_id,
        "id": saved["id"],
        "body": body,
        "sender_id": user["id"],
        "display_name": user["display_name"],
        "created_at": saved["created_at"].isoformat(),
    }, room=f"chat:{conversation_id}")
    recipients = await asyncio.to_thread(storage.conversation_recipient_ids, conversation_id, user["id"])
    for recipient_id in recipients:
        await sio.emit("unread_message", {"conversation_id": conversation_id, "body": body}, room=f"user:{recipient_id}")
    return {"ok": True}


@sio.event
async def disconnect(sid, reason=None):
    """Forget this socket's in-memory session when the connection closes."""
    session = socket_sessions.pop(sid, None)
    if session and not user_is_online(session["user_id"]):
        await broadcast_presence(session["user_id"], False)


# Export the wrapped app under the usual `app` name so `uvicorn ...:app` starts both.
app = socketio.ASGIApp(sio, fastapi_app)
# Keep the explicit name working for anyone already using the earlier command.
socket_app = app
