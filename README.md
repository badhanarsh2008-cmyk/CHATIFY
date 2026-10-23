# Chatify

Chatify is a FastAPI app with PostgreSQL backed accounts, friend requests, and private text conversations. The code intentionally uses plain `psycopg2` cursors in `backend/storage/main.py` so the database queries stay visible and easy to learn from.

## Local setup

1. Install PostgreSQL and create a database named `chatify` (or choose another name in `.env`).
2. Copy `.env.example` to `.env`, then set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` to your PostgreSQL connection details. Keep `.env` private; Git ignores it.
3. From the `CHATIFY` directory, install packages and start the app:

   ```powershell
   python -m pip install -r requirements.txt
   python -m uvicorn backend.apps.app:app --reload --port 8000
   ```

4. Open `http://127.0.0.1:8000`, register an account, then sign in. The first start creates or updates the database tables automatically. If Windows blocks port 8000, use `--port 8001` and open `http://127.0.0.1:8001`.

The web app listens on port **8000**. `DB_PORT` is the PostgreSQL server port (usually **5432**); those ports are for different services.

## What the tables do

- `users` stores usernames, display names, profile photo bytes, emails, and scrypt password hashes.
- `sessions` stores only the hash of a random browser session token.
- `friendship_requests` records requests and their pending/accepted/rejected state. An accepted request represents the friendship.
- `conversations` is the container for a private chat.
- `conversation_members` joins users to conversations.
- `messages` stores text and sender/time details. The app checks membership before reading or saving chat messages.

When somebody sends a request, a `friendship_requests` row is added. The recipient accepts it; the Friends page then shows that connection. Selecting Message creates (or reuses) one conversation and inserts both people in `conversation_members`. The Python Socket.IO server authenticates a connecting client with the existing session cookie, keeps connected socket sessions in an in-memory dictionary, checks conversation membership, saves each message in PostgreSQL, then broadcasts it to the chat room. The browser connects to Socket.IO for live chat and friend request updates. If Socket.IO disconnects, message sending falls back to HTTP without reloading the chat page. Profile photos are cropped and resized to 256×256 pixels before storage.

## Current scope

Signup, sign-in, persistent sessions, editable display names, profile photo updates, friend requests, a searchable Friends list, and persisted one-to-one chats are implemented. Python Socket.IO events are available for a future client connection. The visual online/offline status from the reference is not backed by presence tracking yet. Email verification, password reset, group chats, and Aryaki provider integration still need their own implementation and configuration.
