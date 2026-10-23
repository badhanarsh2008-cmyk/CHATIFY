"""Small PostgreSQL data layer for Chatify (using psycopg2 directly)."""

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


def connect():
    """Open a PostgreSQL connection using environment variables or .env values."""
    # Import here so the app can still show a useful error if dotenv is not installed.
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except ImportError:
        pass

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "chatify_app"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "Arsh@2008"),
        connect_timeout=5,
    )


@contextmanager
def get_cursor():
    """Commit successful work and always close the cursor and connection."""
    connection = connect()
    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def init_db():
    """Create the initial tables; safe to call every time the app starts."""
    with get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                username VARCHAR(30) NOT NULL UNIQUE,
                username_normalized VARCHAR(30) NOT NULL UNIQUE,
                display_name VARCHAR(80) NOT NULL DEFAULT '',
                email VARCHAR(254) NOT NULL UNIQUE,
                email_normalized VARCHAR(254) NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                avatar_data BYTEA,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(80) NOT NULL DEFAULT '';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data BYTEA;
            UPDATE users SET display_name = username WHERE display_name = '';
            CREATE TABLE IF NOT EXISTS sessions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash CHAR(64) NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS friendship_requests (
                id BIGSERIAL PRIMARY KEY,
                sender_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                receiver_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status VARCHAR(12) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'rejected')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (sender_id <> receiver_id),
                UNIQUE (sender_id, receiver_id)
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS conversation_members (
                conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (conversation_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                sender_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 5000),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS messages_conversation_time_idx
                ON messages (conversation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);
        """)


def create_user(username, email, password_hash, display_name):
    with get_cursor() as cur:
        cur.execute("""INSERT INTO users
            (username, username_normalized, display_name, email, email_normalized, password_hash)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (username, username.lower(), display_name, email, email.lower(), password_hash))
        return cur.fetchone()["id"]


def find_user(identifier):
    with get_cursor() as cur:
        cur.execute("""SELECT id, username, display_name, email, password_hash FROM users
            WHERE username_normalized = %s OR email_normalized = %s""",
            (identifier.lower(), identifier.lower()))
        return cur.fetchone()


def create_session(user_id, token_hash, expires_at):
    with get_cursor() as cur:
        cur.execute("INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                    (user_id, token_hash, expires_at))


def get_session_user(token_hash):
    with get_cursor() as cur:
        cur.execute("""SELECT u.id, u.username, u.display_name, u.email,
            (u.avatar_data IS NOT NULL) AS has_avatar FROM users u
            JOIN sessions s ON s.user_id = u.id
            WHERE s.token_hash = %s AND s.expires_at > NOW()""", (token_hash,))
        return cur.fetchone()


def delete_session(token_hash):
    with get_cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))


def list_friends(user_id, search=""):
    with get_cursor() as cur:
        cur.execute("""SELECT u.id, u.username, u.display_name,
            (u.avatar_data IS NOT NULL) AS has_avatar FROM friendship_requests f
            JOIN users u ON u.id = CASE WHEN f.sender_id = %s THEN f.receiver_id ELSE f.sender_id END
            WHERE f.status = 'accepted' AND (f.sender_id = %s OR f.receiver_id = %s)
            AND u.username ILIKE %s ORDER BY u.username""",
            (user_id, user_id, user_id, f"%{search}%"))
        return cur.fetchall()


def list_pending_requests(user_id):
    with get_cursor() as cur:
        cur.execute("""SELECT f.id, u.id AS sender_id, u.username, u.display_name,
            (u.avatar_data IS NOT NULL) AS has_avatar FROM friendship_requests f
            JOIN users u ON u.id = f.sender_id
            WHERE f.receiver_id = %s AND f.status = 'pending' ORDER BY f.created_at""", (user_id,))
        return cur.fetchall()


def send_friend_request(sender_id, username):
    with get_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username_normalized = %s", (username.lower(),))
        target = cur.fetchone()
        if not target or target["id"] == sender_id:
            return False, None, None, None
        receiver_id = target["id"]
        # If the other user already requested us, accept that request instead.
        cur.execute("""UPDATE friendship_requests SET status='accepted', updated_at=NOW()
            WHERE sender_id=%s AND receiver_id=%s AND status='pending' RETURNING id""",
            (receiver_id, sender_id))
        if cur.fetchone():
            return True, receiver_id, "accepted", None
        cur.execute("""INSERT INTO friendship_requests (sender_id, receiver_id)
            VALUES (%s, %s) ON CONFLICT (sender_id, receiver_id) DO NOTHING RETURNING id""",
            (sender_id, receiver_id))
        inserted = cur.fetchone()
        if inserted:
            return True, receiver_id, "request", inserted["id"]
        return False, receiver_id, "request", None


def answer_friend_request(user_id, request_id, accept):
    with get_cursor() as cur:
        cur.execute("""UPDATE friendship_requests SET status=%s, updated_at=NOW()
            WHERE id=%s AND receiver_id=%s AND status='pending'""",
            ("accepted" if accept else "rejected", request_id, user_id))
        return cur.rowcount == 1


def open_direct_chat(user_id, friend_id):
    """Return an existing private chat or create one for two accepted friends."""
    with get_cursor() as cur:
        cur.execute("""SELECT id FROM friendship_requests WHERE status='accepted'
            AND ((sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s))""",
            (user_id, friend_id, friend_id, user_id))
        if not cur.fetchone():
            return None
        cur.execute("""SELECT c.id FROM conversations c
            JOIN conversation_members a ON a.conversation_id=c.id AND a.user_id=%s
            JOIN conversation_members b ON b.conversation_id=c.id AND b.user_id=%s
            WHERE (SELECT COUNT(*) FROM conversation_members m WHERE m.conversation_id=c.id)=2
            ORDER BY c.id LIMIT 1""", (user_id, friend_id))
        existing = cur.fetchone()
        if existing:
            return existing["id"]
        cur.execute("INSERT INTO conversations DEFAULT VALUES RETURNING id")
        conversation_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (%s, %s), (%s, %s)",
                    (conversation_id, user_id, conversation_id, friend_id))
        return conversation_id


def list_user_chats(user_id):
    with get_cursor() as cur:
        cur.execute("""SELECT c.id, u.id AS friend_id, u.username, u.display_name,
            (u.avatar_data IS NOT NULL) AS has_avatar,
            (SELECT body FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_message
            FROM conversations c
            JOIN conversation_members mine ON mine.conversation_id=c.id AND mine.user_id=%s
            JOIN conversation_members theirs ON theirs.conversation_id=c.id AND theirs.user_id<>%s
            JOIN users u ON u.id=theirs.user_id
            ORDER BY c.id DESC""", (user_id, user_id))
        return cur.fetchall()


def read_chat(user_id, conversation_id):
    """Only return messages when this user belongs to the conversation."""
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM conversation_members WHERE conversation_id=%s AND user_id=%s",
                    (conversation_id, user_id))
        if not cur.fetchone():
            return None
        # Select the newest page first, then display those messages oldest to newest.
        cur.execute("""SELECT recent.id, recent.body, recent.created_at, recent.username, recent.display_name
            FROM (
                SELECT m.id, m.body, m.created_at, u.username, u.display_name
                FROM messages m JOIN users u ON u.id=m.sender_id
                WHERE m.conversation_id=%s
                ORDER BY m.created_at DESC LIMIT 100
            ) AS recent
            ORDER BY recent.created_at ASC""", (conversation_id,))
        return cur.fetchall()


def save_message(user_id, conversation_id, body):
    """Membership check and insert happen together in one database transaction."""
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM conversation_members WHERE conversation_id=%s AND user_id=%s",
                    (conversation_id, user_id))
        if not cur.fetchone():
            return False
        cur.execute("""INSERT INTO messages (conversation_id, sender_id, body)
            VALUES (%s, %s, %s) RETURNING id, created_at""", (conversation_id, user_id, body))
        return cur.fetchone()


def pending_request_count(user_id):
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM friendship_requests WHERE receiver_id=%s AND status='pending'",
                    (user_id,))
        return cur.fetchone()["count"]


def save_avatar(user_id, image_bytes):
    with get_cursor() as cur:
        cur.execute("UPDATE users SET avatar_data=%s WHERE id=%s", (psycopg2.Binary(image_bytes), user_id))


def update_display_name(user_id, display_name):
    with get_cursor() as cur:
        cur.execute("UPDATE users SET display_name=%s WHERE id=%s", (display_name, user_id))


def get_avatar(user_id):
    with get_cursor() as cur:
        cur.execute("SELECT avatar_data FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
        return bytes(row["avatar_data"]) if row and row["avatar_data"] else None
