# Chatify plan

## Product goal

Chatify is a place to find friends, have private conversations, and invite Aryaki, a fine-tuned AI assistant, to help with ideas or join a conversation.

## Stack

- Python and FastAPI for the web app and API.
- PostgreSQL for durable user, friendship, conversation, and message data.
- SQLAlchemy for database access and Alembic for schema migrations.
- HTML templates and separate CSS files for the initial web interface.
- A hosted PostgreSQL service, HTTPS, and managed secrets for production.

## Current status

- [x] Landing page created.
- [x] Signup and sign-in form interfaces created.
- [x] FastAPI GET routes serve the landing, signup, and sign-in pages.
- [ ] Signup and sign-in POST handlers are not implemented yet.
- [ ] PostgreSQL is not connected yet; account data must not be stored in an in-memory dictionary.
- [ ] Authentication, email verification, the Inbox, and chat are not implemented yet.

## Build phases

### Phase 1 — Local app foundation

- [x] Serve the landing page from `/`.
- [x] Serve account pages from `/register` and `/login`.
- [ ] Confirm the frontend static files load through FastAPI.
- [ ] Keep local configuration and secrets out of Git.

### Phase 2 — Secure accounts

- [ ] Connect a local development PostgreSQL database.
- [ ] Create SQLAlchemy models and the first Alembic migration.
- [ ] Add `users` and `email_verification_tokens` tables with unique normalized username and email fields, foreign keys, and timestamps.
- [ ] Implement server-side validation for registration and sign-in.
- [ ] Hash passwords with Argon2id; never store or log raw passwords.
- [ ] Implement one-time, expiring email verification tokens; store token hashes, not raw tokens.
- [ ] Add rate limits for registration, sign-in, and verification requests.
- [ ] Add CSRF protection to browser form submissions.
- [ ] Create secure sessions with random opaque tokens, store only token hashes, and set `HttpOnly`, `Secure` (in HTTPS environments), and `SameSite` cookies.
- [ ] Use generic sign-in errors and avoid revealing whether an account exists.

### Phase 3 — Inbox

- [ ] Create `inbox.html` as the signed-in user's main page.
- [ ] Add an `/inbox` route that requires a valid session.
- [ ] Redirect successful sign-in to `/inbox` only after credentials are verified and the account is allowed to sign in.
- [ ] Add sign-out and session revocation.

### Phase 4 — Friends and messaging

- [ ] Add friendship requests and acceptance.
- [ ] Add `conversations`, `conversation_members`, and `messages` tables with appropriate foreign keys and unique constraints.
- [ ] Implement conversation membership checks for every message read and write.
- [ ] Build message history with cursor-based pagination and indexes for conversation/time lookups.
- [ ] Start with HTTP message endpoints; add WebSockets for live delivery after persistence works.
- [ ] Persist a message before broadcasting it to connected users.

### Phase 5 — Aryaki

- [ ] Add Aryaki as a conversation participant/type.
- [ ] Save the user's message before calling the AI provider.
- [ ] Call the AI provider outside database transactions and save its reply as a separate message.
- [ ] Add timeouts, failure handling, and usage limits; keep provider credentials server-side.

### Phase 6 — Production readiness

- [ ] Use a managed PostgreSQL instance with private networking, TLS, automated backups, and point-in-time recovery.
- [ ] Use separate runtime and migration database roles; the app role must not be a database superuser.
- [ ] Store secrets in the host's secret manager or environment configuration.
- [ ] Run Alembic migrations as a deployment step, not from every web worker.
- [ ] Deploy FastAPI behind HTTPS with a production server and reverse proxy.
- [ ] Configure structured logs, error reporting, health checks, database connection limits, and monitoring.
- [ ] Practice restoring a backup before launch.

## Initial routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Public landing page |
| GET | `/register` | Signup form |
| POST | `/register` | Validate and create an account (to implement) |
| GET | `/login` | Sign-in form |
| POST | `/login` | Authenticate and create a session (to implement) |
| POST | `/logout` | Revoke the current session (to implement) |
| GET | `/inbox` | Protected main page after sign-in (to implement) |

## First milestone

Complete the account flow locally: registration, email verification, sign-in, sign-out, and a protected Inbox backed by PostgreSQL. Do not treat the current HTML form validation as security; the server must repeat validation and enforce authentication and authorization.
