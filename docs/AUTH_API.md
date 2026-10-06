# Authentication & User Data API Documentation

Passwordless **email OTP sign-in** (Brevo), long-lived JWT (until logout), bookmarks, and history.

Interactive docs: `/docs`

---

## Overview

| Feature | Supported |
|---------|-----------|
| Sign in with email only (OTP) | Yes |
| Auto-create account on first email | Yes |
| Stay signed in until logout | Yes (JWT ~365 days + logout invalidation) |
| Bookmarks / History per email | Yes |
| Password signup/login | Removed |

Flow:

```text
0. If you already have access_token → GET /auth/me (do not call signin)
1. POST /auth/signin       → OTP emailed (creates user if new)
2. POST /auth/verify-otp   → JWT returned
3. Use Bearer token for bookmarks/history
4. POST /auth/logout       → session invalidated
```

If `POST /auth/signin` is called **with a valid Bearer token for the same email**, API returns `409` and does **not** send OTP:

```json
{
  "detail": {
    "already_signed_in": true,
    "email": "user@example.com",
    "message": "You are already signed in. Use GET /auth/me with your existing access token instead of requesting a new OTP.",
    "use_endpoint": "/auth/me"
  }
}
```

Protected routes require:

```http
Authorization: Bearer <access_token>
```

Store the token on the client until the user taps Sign out.

---

## Environment

```env
JWT_SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=525600

BREVO_API_KEY=your-brevo-api-key
BREVO_SENDER_EMAIL=noreply@yourdomain.com
BREVO_SENDER_NAME=GS App
OTP_EXPIRE_MINUTES=10
OTP_RESEND_COOLDOWN_SECONDS=60
EMAIL_OTP_DEBUG=false
```

---

## Auth endpoints

### `POST /auth/signin`

Email only. Creates the user if needed and sends OTP.

```json
{ "email": "user@example.com" }
```

Response:

```json
{
  "status_code": 200,
  "success": true,
  "message": "Sign-in code sent to your email.",
  "email": "user@example.com",
  "email_verified": false,
  "requires_verification": true,
  "otp_expires_in": 600
}
```

### `POST /auth/verify-otp`

```json
{
  "email": "user@example.com",
  "otp_code": "123456"
}
```

Returns JWT + user + bookmarks + history.

### `POST /auth/resend-otp`

```json
{ "email": "user@example.com" }
```

### `POST /auth/logout`

Requires Bearer token. Invalidates that session (and all prior tokens for the user).

### `GET /auth/me`

Current profile + bookmarks + history.

### Auth success response (verify-otp / me)

```json
{
  "status_code": 200,
  "success": true,
  "message": "Signed in successfully",
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 31536000,
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": null,
    "profile_picture": null,
    "auth_provider": "app",
    "email_verified": true,
    "created_at": "2026-09-25T10:00:00"
  },
  "bookmarks": [],
  "history": []
}
```

---

## Bookmarks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/bookmarks` | List **all** bookmarks (no pagination); includes `favicon` |
| `POST` | `/auth/bookmarks` | Save one bookmark (`title`, `url`, optional `favicon`, optional `folder`) |
| `POST` | `/auth/bookmarks/bulk` | Bulk save bookmarks (each item = one row; supports `favicon`) |
| `DELETE` | `/auth/bookmarks/{id}` | Delete bookmark |

```json
{
  "title": "Example",
  "url": "https://example.com",
  "favicon": "https://example.com/favicon.ico",
  "folder": "Work"
}
```

## History

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/history` | List **all** history (no pagination); includes `favicon` |
| `POST` | `/auth/history` | Record one visit (`title`, `url`, optional `favicon`, optional `visited_at`) |
| `POST` | `/auth/history/bulk` | Bulk save history (each item = one row; supports `favicon`) |
| `DELETE` | `/auth/history/{id}` | Delete one entry |
| `DELETE` | `/auth/history/clear` | Clear all history |
| `DELETE` | `/auth/history/range?from_epoch=<unix>` | Delete history from epoch → now |

```json
{
  "title": "Example visit",
  "url": "https://example.com",
  "favicon": "https://example.com/favicon.ico",
  "visited_at": "2026-10-01T10:00:00Z"
}
```

---

## Trending (ScrapingDog)

`GET /trending?geo=US&limit=4`

- Calls ScrapingDog `google_trends/trending_now` when cache is missing or older than **24 hours**
- Saves **top 10** trends per `geo` in DB (`google_trending_cache`)
- Returns **4 random** items from that cached top 10 (override with `limit`)
- Concurrent requests for the same geo share one refresh (no stampede)

```env
TRENDING_CACHE_HOURS=24
TRENDING_STORE_COUNT=10
TRENDING_SERVE_COUNT=4
TRENDING_DEFAULT_GEO=US
```

---

## Endpoint quick reference

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/auth/signin` | Public |
| `POST` | `/auth/verify-otp` | Public |
| `POST` | `/auth/resend-otp` | Public |
| `POST` | `/auth/logout` | Bearer |
| `GET` | `/auth/me` | Bearer |
| `GET/POST/DELETE` | `/auth/bookmarks...` | Bearer |
| `GET/POST/DELETE` | `/auth/history...` | Bearer |

Aliases (hidden from docs, still work): `/auth/signup`, `/auth/login` → same as `/auth/signin`; `/auth/verify-email` → same as `/auth/verify-otp`.

---

## Related files

| File | Purpose |
|------|---------|
| `app/auth/routes.py` | HTTP endpoints |
| `app/auth/service.py` | OTP + JWT + logout |
| `app/email_service.py` | Brevo OTP email |
| `app/auth/db.py` | Tables / migrations |
| `app/models.py` | Request/response models |
| `app/config.py` | JWT + Brevo settings |
| `app/trending/` | Google trending cache API |
