# Authentication & User Data API Documentation

App email/password authentication with **email OTP verification (Brevo)**, JWT, bookmarks, and history.

Interactive docs: `/docs`

---

## Overview

| Feature | Supported |
|---------|-----------|
| Signup with email + password | Yes |
| Email OTP verification (Brevo, free tier) | Yes |
| Login (only after email verified) | Yes |
| Forgot / reset password (OTP via Brevo) | Yes |
| Bookmarks / History | Yes |
| Login with Google | Removed |

Flow:

```text
1. POST /auth/signup      → OTP emailed
2. POST /auth/verify-email → JWT returned
3. Later: POST /auth/login → JWT

Forgot password:
1. POST /auth/forgot-password → OTP emailed
2. POST /auth/reset-password  → new password + JWT
```

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

# Brevo (recommended free production OTP provider)
BREVO_API_KEY=your-brevo-api-key
BREVO_SENDER_EMAIL=noreply@yourdomain.com
BREVO_SENDER_NAME=GS App
OTP_EXPIRE_MINUTES=10
OTP_RESEND_COOLDOWN_SECONDS=60

# Local/dev only: log OTP to server logs if Brevo is not set
EMAIL_OTP_DEBUG=false
```

### Brevo free setup (production)

1. Create account at [brevo.com](https://www.brevo.com/)
2. Verify your sender domain / sender email
3. Create an API key (SMTP & API → API Keys)
4. Put key + sender email in `.env`
5. Free plan is enough for OTP (~300 emails/day)

---

## Auth endpoints

### `POST /auth/signup`

Creates an **unverified** user and emails a 6-digit OTP. No JWT yet.

```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "full_name": "John Doe"
}
```

Response:

```json
{
  "status_code": 200,
  "success": true,
  "message": "Signup successful. Enter the OTP sent to your email to verify your account.",
  "email": "user@example.com",
  "email_verified": false,
  "requires_verification": true,
  "otp_expires_in": 600
}
```

### `POST /auth/verify-email`

```json
{
  "email": "user@example.com",
  "otp_code": "123456"
}
```

Returns JWT + user (same shape as login).

### `POST /auth/resend-otp`

```json
{
  "email": "user@example.com"
}
```

Cooldown-limited by `OTP_RESEND_COOLDOWN_SECONDS`.

### `POST /auth/login`

Requires verified email.

```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

If unverified → `403` with message to verify / resend OTP.

### `POST /auth/forgot-password`

Sends a password-reset OTP (same Brevo setup). Response is always generic so emails cannot be enumerated.

```json
{
  "email": "user@example.com"
}
```

Response:

```json
{
  "status_code": 200,
  "success": true,
  "message": "If an account exists for this email, a password reset code has been sent.",
  "email": "user@example.com",
  "email_verified": true,
  "requires_verification": true,
  "otp_expires_in": 600
}
```

### `POST /auth/reset-password`

```json
{
  "email": "user@example.com",
  "otp_code": "123456",
  "new_password": "newsecurepass123"
}
```

Returns JWT + user (same shape as login).

### Auth success response (verify-email / login / reset-password)

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
    "email_verified": true,
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
| `GET` | `/auth/bookmarks` | List bookmarks |
| `POST` | `/auth/bookmarks` | Save bookmark |
| `DELETE` | `/auth/bookmarks/{id}` | Delete bookmark |

---

## History

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/history` | List history |
| `POST` | `/auth/history` | Record a visit |
| `DELETE` | `/auth/history/{id}` | Delete one entry |
| `DELETE` | `/auth/history/clear` | Clear all history |

---

## Endpoint quick reference

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/auth/signup` | Public |
| `POST` | `/auth/verify-email` | Public |
| `POST` | `/auth/resend-otp` | Public |
| `POST` | `/auth/login` | Public |
| `POST` | `/auth/forgot-password` | Public |
| `POST` | `/auth/reset-password` | Public |
| `GET` | `/auth/me` | Bearer |
| `GET/POST/DELETE` | `/auth/bookmarks...` | Bearer |
| `GET/POST/DELETE` | `/auth/history...` | Bearer |

---

## Related files

| File | Purpose |
|------|---------|
| `auth_routes.py` | HTTP endpoints |
| `auth_service.py` | JWT, passwords, OTP logic |
| `email_service.py` | Brevo OTP email sender |
| `auth_db.py` | Table creation / migration |
| `models.py` | Request/response models |
| `config.py` | JWT + Brevo settings |
