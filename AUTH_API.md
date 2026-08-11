# Authentication & User Data API Documentation

App email/password authentication with JWT, plus bookmarks and browsing history APIs.

Interactive docs: `/docs`

---

## Overview

| Feature | Supported |
|---------|-----------|
| Signup / login with email + password | Yes |
| Bookmarks (create / list / delete) | Yes |
| History (record / list / delete / clear) | Yes |
| Login with Google | Removed |

Protected routes require:

```http
Authorization: Bearer <access_token>
```

---

## Environment

```env
JWT_SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080
```

---

## Auth endpoints

### `POST /auth/signup`

```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "full_name": "John Doe"
}
```

Password: 8–72 characters.

### `POST /auth/login`

```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

### Auth response

```json
{
  "status_code": 200,
  "success": true,
  "message": "Login successful",
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 604800,
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "John Doe",
    "profile_picture": null,
    "auth_provider": "app",
    "created_at": "2026-08-05T10:00:00"
  },
  "bookmarks": [],
  "history": []
}
```

### `GET /auth/me`

Returns current user profile + bookmarks + history.

---

## Bookmarks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/bookmarks` | List bookmarks (`limit` optional, default 100) |
| `POST` | `/auth/bookmarks` | Save bookmark |
| `DELETE` | `/auth/bookmarks/{id}` | Delete bookmark |

### Create bookmark

```json
{
  "title": "FastAPI Docs",
  "url": "https://fastapi.tiangolo.com",
  "folder": "Dev"
}
```

---

## History

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/history` | List history (`limit` optional) |
| `POST` | `/auth/history` | Record a visit |
| `DELETE` | `/auth/history/{id}` | Delete one entry |
| `DELETE` | `/auth/history/clear` | Clear all history |

### Record history

```json
{
  "title": "Google Search",
  "url": "https://www.google.com",
  "visited_at": "2026-08-05T15:30:00Z"
}
```

`visited_at` is optional (defaults to now).

---

## Endpoint quick reference

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/auth/signup` | Public |
| `POST` | `/auth/login` | Public |
| `GET` | `/auth/me` | Bearer |
| `GET` | `/auth/bookmarks` | Bearer |
| `POST` | `/auth/bookmarks` | Bearer |
| `DELETE` | `/auth/bookmarks/{id}` | Bearer |
| `GET` | `/auth/history` | Bearer |
| `POST` | `/auth/history` | Bearer |
| `DELETE` | `/auth/history/{id}` | Bearer |
| `DELETE` | `/auth/history/clear` | Bearer |

---

## Related files

| File | Purpose |
|------|---------|
| `auth_routes.py` | HTTP endpoints |
| `auth_service.py` | JWT, passwords, DB access |
| `auth_db.py` | Table creation |
| `models.py` | Request/response models |
| `config.py` | JWT settings |
