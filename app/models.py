from pydantic import BaseModel, HttpUrl, Field, validator
from typing import Optional, Literal, List
import re

class ScreenshotRequest(BaseModel):
    """Request model for screenshot endpoint with proper validation."""
    
    url: HttpUrl = Field(..., description="Valid URL to take screenshot of")
    ux_type: int = Field(ge=0, le=10, description="UX type identifier (0-10)")
    ss_width: int = Field(ge=100, le=4000, description="Screenshot width in pixels")
    ss_height: int = Field(ge=100, le=4000, description="Screenshot height in pixels")
    output_base_path: str = Field(
        default='https://usc1.contabostorage.com/gsdatasync/',
        description="Base path for output files"
    )
    browser_type: Literal['chromium', 'firefox', 'webkit'] = Field(
        default='chromium',
        description="Browser type to use"
    )
    full_page: bool = Field(default=True, description="Take full page screenshot")
    executable_path: Optional[str] = Field(None, description="Custom browser executable path")

    @validator('url')
    def validate_url_scheme(cls, v):
        """Ensure URL has valid scheme."""
        if str(v).startswith(('http://', 'https://')):
            return v
        raise ValueError('URL must start with http:// or https://')

class SearchRequest(BaseModel):
    """Request model for search endpoint with proper validation."""
    
    query: str = Field(
        ..., 
        min_length=1, 
        max_length=500,
        description="Search query (1-500 characters)"
    )
    searchType: Literal['general', 'nws', 'isch', 'shop', 'videos', 'ai'] = Field(
        ...,
        description="Type of search: general, nws (news), isch (images), shop (shopping), videos (YouTube), ai (Google AI Mode)"
    )
    start: int = Field(
        default=0, 
        ge=0, 
        le=1000,
        description="Start index for pagination (0-1000)"
    )
    limit: int = Field(
        default=5, 
        ge=1, 
        le=100,
        description="Limit of results per page (1-100)"
    )

    @validator('query')
    def validate_query(cls, v):
        """Validate search query for basic safety."""
        # Remove potentially dangerous characters
        if re.search(r'[<>"\']', v):
            raise ValueError('Query contains invalid characters')
        return v.strip()

class LinkRequest(BaseModel):
    """Request model for links endpoint with proper validation."""
    
    url: HttpUrl = Field(..., description="Valid URL to extract links from")

    @validator('url')
    def validate_url_scheme(cls, v):
        """Ensure URL has valid scheme."""
        if str(v).startswith(('http://', 'https://')):
            return v
        raise ValueError('URL must start with http:// or https://')



# Response models for better API documentation
class SuccessResponse(BaseModel):
    """Standard success response model."""
    
    status_code: int = Field(200, description="HTTP status code")
    success: bool = Field(True, description="Operation success flag")
    message: str = Field(..., description="Success message")

class ErrorResponse(BaseModel):
    """Standard error response model."""
    
    status_code: int = Field(..., description="HTTP status code")
    success: bool = Field(False, description="Operation success flag")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")


# =====================================================================
# Authentication models
# =====================================================================

class EmailOnlyRequest(BaseModel):
    """Request model for passwordless sign-in / resend OTP (email only)."""

    email: str = Field(..., min_length=5, max_length=255, description="User email address")

    @validator('email')
    def validate_email(cls, v):
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email format')
        return v.lower().strip()


# Backwards-compatible aliases
SignupRequest = EmailOnlyRequest
LoginRequest = EmailOnlyRequest
ResendOtpRequest = EmailOnlyRequest
ForgotPasswordRequest = EmailOnlyRequest


class BookmarkItem(BaseModel):
    """A saved bookmark."""

    id: Optional[int] = None
    title: Optional[str] = None
    url: str
    folder: Optional[str] = None
    source: str = "app"


class HistoryItem(BaseModel):
    """A browsing history entry."""

    id: Optional[int] = None
    title: Optional[str] = None
    url: str
    visited_at: Optional[str] = None
    source: str = "app"


class UserProfile(BaseModel):
    """Authenticated user profile."""

    id: int
    email: str
    full_name: Optional[str] = None
    profile_picture: Optional[str] = None
    auth_provider: str
    email_verified: bool = False
    created_at: Optional[str] = None


class AuthResponse(BaseModel):
    """Login/verify response with JWT."""

    status_code: int = 200
    success: bool = True
    message: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile
    bookmarks: Optional[List[BookmarkItem]] = None
    history: Optional[List[HistoryItem]] = None


class SignupPendingResponse(BaseModel):
    """OTP sent; client must verify before receiving JWT."""

    status_code: int = 200
    success: bool = True
    message: str
    email: str
    email_verified: bool = False
    requires_verification: bool = True
    otp_expires_in: int


OtpPendingResponse = SignupPendingResponse


class VerifyOtpRequest(BaseModel):
    """Verify sign-in email with OTP code."""

    email: str = Field(..., description="Sign-in email address")
    otp_code: str = Field(..., min_length=4, max_length=8, description="OTP code from email")

    @validator('email')
    def normalize_email(cls, v):
        return v.lower().strip()

    @validator('otp_code')
    def normalize_otp(cls, v):
        return v.strip()


VerifyEmailRequest = VerifyOtpRequest


class CreateBookmarkRequest(BaseModel):
    """Request model for saving a bookmark."""

    title: Optional[str] = Field(None, max_length=512, description="Page title")
    url: str = Field(..., min_length=1, max_length=2048, description="Bookmark URL")
    folder: Optional[str] = Field(None, max_length=255, description="Folder or category name")

    @validator('url')
    def validate_url(cls, v):
        v = v.strip()
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v


class CreateHistoryRequest(BaseModel):
    """Request model for recording a history entry."""

    title: Optional[str] = Field(None, max_length=512, description="Page title")
    url: str = Field(..., min_length=1, max_length=2048, description="Visited page URL")
    visited_at: Optional[str] = Field(None, description="Visit timestamp (ISO 8601). Defaults to now.")

    @validator('url')
    def validate_url(cls, v):
        v = v.strip()
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v
