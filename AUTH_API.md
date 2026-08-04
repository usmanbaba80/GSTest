# Authentication & User Data API Documentation

This document describes the authentication APIs for **App (email/password)** login and **Google Account** login, plus endpoints for **bookmarks** and **browsing history**.

Interactive OpenAPI docs are also available at `/docs` when the server is running.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Base URL & Authentication](#2-base-url--authentication)
3. [Environment Setup](#3-environment-setup)
4. [App Signup & Login](#4-app-signup--login)
5. [Google Account Login](#5-google-account-login)
6. [User Profile](#6-user-profile)
7. [Bookmarks API](#7-bookmarks-api)
8. [History API](#8-history-api)
9. [Common Response Models](#9-common-response-models)
10. [Error Codes](#10-error-codes)
11. [Frontend Integration Flows](#11-frontend-integration-flows)
12. [Endpoint Quick Reference](#12-endpoint-quick-reference)

---

## 1. Overview

Users can authenticate in two ways:

| Method | Signup required? | Bookmarks / History source |
|--------|------------------|----------------------------|
| **App login** | Yes (`/auth/signup` first) | Stored in your app via API (`source=app`) |
| **Google login** | No (auto-created on first Google login) | Exported from Chrome via Google Data Portability API (`source=google`) |

After successful authentication, the API returns a **JWT** (`access_token`). Use this token for all protected endpoints.

---

## 2. Base URL & Authentication

### Base path

```
/auth
```

Example (local):

```
http://localhost:8000/auth
```

### Protected endpoints

Send the JWT in the request header:

```http
Authorization: Bearer <access_token>
```

### Public endpoints (no JWT required)

- `POST /auth/signup`
- `POST /auth/login`
- `GET /auth/google/url`
- `GET /auth/google/callback` (HTML redirect page)
- `POST /auth/google/callback`

---

## 3. Environment Setup

Add these variables to your `.env` file:

```env
# JWT
JWT_SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080

# Google OAuth (required for Google login)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

> Use the backend callback page URL above (same host as this API).  
> Example for production: `https://your-api-domain.com/auth/google/callback`

### Google Cloud Console checklist

1. Create a Google Cloud project
2. Enable **Data Portability API**
3. Configure OAuth consent screen
4. Create OAuth 2.0 Client ID (Web application)
5. Add your redirect URI — must match `GOOGLE_REDIRECT_URI` exactly
6. Add test users while the app is in **Testing** mode

### Install dependencies

```bash
pip install -r requirements.txt
```

Auth-related packages include: `PyJWT`, `passlib[bcrypt]`, `bcrypt`.

---

## 4. App Signup & Login

### 4.1 Signup

Create a new app account. Password must be at least 8 characters.

**Endpoint**

```http
POST /auth/signup
Content-Type: application/json
```

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Valid email address |
| `password` | string | Yes | Min 8 characters |
| `full_name` | string | No | Display name |

**Example**

```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "full_name": "John Doe"
}
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "Signup successful",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 604800,
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "John Doe",
    "profile_picture": null,
    "auth_provider": "app",
    "created_at": "2026-07-28T10:00:00"
  },
  "bookmarks": [],
  "history": [],
  "google_sync": null
}
```

**Errors**

| Status | When |
|--------|------|
| `409` | Email already registered |
| `422` | Invalid email/password format |
| `500` | Server error |

---

### 4.2 Login

Login with an existing app account. Signup is required first.

**Endpoint**

```http
POST /auth/login
Content-Type: application/json
```

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Registered email |
| `password` | string | Yes | Account password |

**Example**

```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

**Success response (`200`)**

Same shape as signup. Includes the user's saved `bookmarks` and `history`.

**Errors**

| Status | When |
|--------|------|
| `401` | Invalid email or password |
| `500` | Server error |

---

## 5. Google Account Login

Google login uses OAuth 2.0. After login, the backend exports Chrome **bookmarks** and **history** using Google's Data Portability API and stores them in MySQL.

> **Note:** Sync is a snapshot export (not real-time). Re-sync with `POST /auth/google/sync`.

### 5.1 Get Google authorization URL

**Endpoint**

```http
GET /auth/google/url
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "Open this URL in a browser to authenticate with Google",
  "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=...",
  "state": "random-csrf-token"
}
```

**Client steps**

1. Call this endpoint
2. Open `authorization_url` in a browser / WebView
3. User signs in and grants consent
4. Google redirects to your `GOOGLE_REDIRECT_URI` with `?code=...&state=...`
5. Send `code` to `/auth/google/callback`

**Errors**

| Status | When |
|--------|------|
| `503` | Google OAuth env vars not configured |

---

### 5.2 Google redirect page (browser)

This is the simple HTML page Google redirects to after the user signs in.

**Endpoint**

```http
GET /auth/google/callback?code=...&state=...
```

**What it does**

1. Receives `code` from Google in the query string
2. Calls `POST /auth/google/callback` automatically
3. Shows login result (email, bookmark/history counts)
4. Saves JWT to `localStorage` as `access_token`

**Setup**

```env
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

Add the same URL in Google Cloud Console → OAuth client → Authorized redirect URIs.

---

### 5.3 Complete Google login (API callback)

Used by the redirect page (and by mobile/web clients) to finish login.

**Endpoint**

```http
POST /auth/google/callback
Content-Type: application/json
```

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | Yes | Authorization code from Google redirect |
| `state` | string | No | CSRF state token |

**Example**

```json
{
  "code": "4/0AeanS...",
  "state": "optional-state-token"
}
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "Google login successful",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 604800,
  "user": {
    "id": 2,
    "email": "user@gmail.com",
    "full_name": "John Doe",
    "profile_picture": "https://lh3.googleusercontent.com/...",
    "auth_provider": "google",
    "created_at": "2026-07-28T10:05:00"
  },
  "bookmarks": [
    {
      "id": 10,
      "title": "GitHub",
      "url": "https://github.com",
      "folder": "Dev",
      "source": "google"
    }
  ],
  "history": [
    {
      "id": 20,
      "title": "Google",
      "url": "https://www.google.com",
      "visited_at": "2026-07-27T15:30:00+00:00",
      "source": "google"
    }
  ],
  "google_sync": {
    "bookmarks_count": 42,
    "history_count": 150,
    "status": "complete",
    "message": "Google bookmarks and history synced successfully"
  }
}
```

> This endpoint may take **30–60+ seconds** because Google export jobs are polled until complete. Show a loading state in the UI.

**Errors**

| Status | When |
|--------|------|
| `400` | Google profile missing email/sub |
| `503` | Google OAuth not configured |
| `500` | Token exchange / sync failure |

---

### 5.4 Re-sync Google bookmarks & history

Re-export Chrome data and replace previously stored Google rows for the user.

**Endpoint**

```http
POST /auth/google/sync
Authorization: Bearer <access_token>
```

No request body.

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "Google bookmarks and history synced successfully",
  "google_sync": {
    "bookmarks_count": 45,
    "history_count": 160,
    "status": "complete",
    "message": "Google bookmarks and history synced successfully"
  },
  "bookmarks": [],
  "history": []
}
```

**Errors**

| Status | When |
|--------|------|
| `400` | User is not a Google login user, or no stored OAuth tokens |
| `401` | Missing/invalid JWT |
| `500` | Sync failed |

---

## 6. User Profile

### 6.1 Get current user

**Endpoint**

```http
GET /auth/me
Authorization: Bearer <access_token>
```

**Success response (`200`)**

Same shape as login/signup (`AuthResponse`), including current `bookmarks` and `history`.

---

## 7. Bookmarks API

Bookmarks can come from:

- `source=app` — saved by your app
- `source=google` — synced from Chrome

### 7.1 List bookmarks

**Endpoint**

```http
GET /auth/bookmarks
Authorization: Bearer <access_token>
```

**Query parameters**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source` | string | No | all | Filter: `app` or `google` |
| `limit` | int | No | `100` | Max items (1–500) |

**Examples**

```http
GET /auth/bookmarks
GET /auth/bookmarks?source=app
GET /auth/bookmarks?source=google&limit=50
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "Bookmarks retrieved",
  "data": [
    {
      "id": 1,
      "title": "FastAPI Docs",
      "url": "https://fastapi.tiangolo.com",
      "folder": "Dev",
      "source": "app"
    }
  ]
}
```

---

### 7.2 Create / upsert bookmark (app)

Saves a bookmark with `source=app`. If the same URL already exists for the user as an app bookmark, it is updated.

**Endpoint**

```http
POST /auth/bookmarks
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | Must start with `http://` or `https://` |
| `title` | string | No | Page title |
| `folder` | string | No | Folder / category |

**Example**

```json
{
  "title": "FastAPI Docs",
  "url": "https://fastapi.tiangolo.com",
  "folder": "Dev"
}
```

**Success response (`201`)**

```json
{
  "status_code": 201,
  "success": true,
  "message": "Bookmark saved",
  "data": {
    "id": 1,
    "title": "FastAPI Docs",
    "url": "https://fastapi.tiangolo.com",
    "folder": "Dev",
    "source": "app"
  }
}
```

---

### 7.3 Delete bookmark (app only)

Deletes only bookmarks with `source=app` owned by the authenticated user. Google-synced bookmarks are not deleted through this endpoint.

**Endpoint**

```http
DELETE /auth/bookmarks/{bookmark_id}
Authorization: Bearer <access_token>
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "Bookmark deleted"
}
```

**Errors**

| Status | When |
|--------|------|
| `404` | Bookmark not found or not deletable |

---

## 8. History API

History can come from:

- `source=app` — recorded by your app
- `source=google` — synced from Chrome

### 8.1 List history

**Endpoint**

```http
GET /auth/history
Authorization: Bearer <access_token>
```

**Query parameters**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source` | string | No | all | Filter: `app` or `google` |
| `limit` | int | No | `100` | Max items (1–500) |

**Examples**

```http
GET /auth/history
GET /auth/history?source=google
GET /auth/history?source=app&limit=200
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "History retrieved",
  "data": [
    {
      "id": 1,
      "title": "Google Search",
      "url": "https://www.google.com",
      "visited_at": "2026-07-28T15:30:00+00:00",
      "source": "app"
    }
  ]
}
```

---

### 8.2 Record history entry (app)

**Endpoint**

```http
POST /auth/history
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | Must start with `http://` or `https://` |
| `title` | string | No | Page title |
| `visited_at` | string | No | ISO 8601 timestamp; defaults to now |

**Example**

```json
{
  "title": "Google Search",
  "url": "https://www.google.com",
  "visited_at": "2026-07-28T15:30:00Z"
}
```

**Success response (`201`)**

```json
{
  "status_code": 201,
  "success": true,
  "message": "History entry recorded",
  "data": {
    "id": 1,
    "title": "Google Search",
    "url": "https://www.google.com",
    "visited_at": "2026-07-28T15:30:00+00:00",
    "source": "app"
  }
}
```

---

### 8.3 Delete one history entry (app only)

**Endpoint**

```http
DELETE /auth/history/{history_id}
Authorization: Bearer <access_token>
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "History entry deleted"
}
```

---

### 8.4 Clear all app history

Deletes all history rows with `source=app` for the authenticated user. Google history is not cleared.

**Endpoint**

```http
DELETE /auth/history/clear
Authorization: Bearer <access_token>
```

**Success response (`200`)**

```json
{
  "status_code": 200,
  "success": true,
  "message": "App history cleared",
  "deleted_count": 12
}
```

---

## 9. Common Response Models

### User object

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | User ID |
| `email` | string | Email address |
| `full_name` | string \| null | Display name |
| `profile_picture` | string \| null | Profile image URL |
| `auth_provider` | string | `app` or `google` |
| `created_at` | string \| null | ISO timestamp |

### Bookmark object

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Bookmark ID |
| `title` | string \| null | Title |
| `url` | string | URL |
| `folder` | string \| null | Folder / category |
| `source` | string | `app` or `google` |

### History object

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | History ID |
| `title` | string \| null | Title |
| `url` | string | URL |
| `visited_at` | string \| null | Visit time (ISO) |
| `source` | string | `app` or `google` |

---

## 10. Error Codes

| Status | Meaning |
|--------|---------|
| `400` | Bad request / invalid input / wrong auth provider for Google sync |
| `401` | Missing, invalid, or expired JWT; invalid login credentials |
| `404` | Resource not found |
| `409` | Email already registered |
| `422` | Validation error (Pydantic) |
| `500` | Internal server error |
| `503` | Google OAuth not configured |

Example error body (FastAPI):

```json
{
  "detail": "Invalid email or password"
}
```

---

## 11. Frontend Integration Flows

### App login flow

```
1. POST /auth/signup   (first time)
   or
   POST /auth/login    (returning user)
2. Store access_token securely
3. Use Authorization: Bearer <token> for later calls
4. Optionally call GET /auth/bookmarks and GET /auth/history
```

### Google login flow

```
1. GET  /auth/google/url
2. Open authorization_url in browser
3. Google redirects to GET /auth/google/callback?code=...
4. The HTML page automatically calls POST /auth/google/callback
5. Page stores access_token in localStorage and shows sync result
6. Later refresh with POST /auth/google/sync
```

### Recommended client storage

- Store JWT in secure storage (mobile Keychain / Keystore, or httpOnly cookie for web)
- On `401`, clear token and redirect to login
- For Google sync, show a loading indicator (export can take time)

---

## 12. Endpoint Quick Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/auth/signup` | Public | Register app user |
| `POST` | `/auth/login` | Public | Login app user |
| `GET` | `/auth/google/url` | Public | Get Google OAuth URL |
| `GET` | `/auth/google/callback` | Public | Browser redirect page (HTML) |
| `POST` | `/auth/google/callback` | Public | Complete Google login + sync |
| `POST` | `/auth/google/sync` | Bearer | Re-sync Chrome bookmarks/history |
| `GET` | `/auth/me` | Bearer | Get current profile + data |
| `GET` | `/auth/bookmarks` | Bearer | List bookmarks |
| `POST` | `/auth/bookmarks` | Bearer | Save app bookmark |
| `DELETE` | `/auth/bookmarks/{id}` | Bearer | Delete app bookmark |
| `GET` | `/auth/history` | Bearer | List history |
| `POST` | `/auth/history` | Bearer | Record app history |
| `DELETE` | `/auth/history/{id}` | Bearer | Delete app history entry |
| `DELETE` | `/auth/history/clear` | Bearer | Clear all app history |

---

## Related Files

| File | Purpose |
|------|---------|
| `auth_routes.py` | HTTP endpoints |
| `auth_service.py` | JWT, password hashing, DB operations |
| `google_service.py` | Google OAuth + Data Portability sync |
| `auth_db.py` | MySQL table creation |
| `models.py` | Request/response models |
| `config.py` | JWT and Google OAuth settings |

---

## Notes & Limitations

1. Google Chrome data is a **snapshot**, not a live sync.
2. Google sync replaces previous `source=google` rows for that user.
3. App data (`source=app`) is independent of Google sync.
4. Data Portability Chrome scopes are **restricted** by Google; production use requires Google Cloud setup and OAuth verification.
5. While the OAuth app is in **Testing** mode, only added test users can log in with Google.
6. If Chrome sync data is encrypted on the user's Google account, export may return empty/unreadable data.
