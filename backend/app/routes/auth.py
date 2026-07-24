# ─────────────────────────────────────────
# routes/auth.py
# User authentication endpoints
#
# POST   /auth/signup         — create new account
# POST   /auth/login          — sign in
# POST   /auth/logout         — sign out
# DELETE /auth/delete-account — delete account + all data
# ─────────────────────────────────────────

import os
import re
import urllib.request
import json as _json
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.services import database
from app.config import create_auth_client
from app.services.app_logger import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


class AuthRequest(BaseModel):
    email:    str
    password: str
    name:     str = ""


class ForgotPasswordRequest(BaseModel):
    email: str


class RefreshSessionRequest(BaseModel):
    refresh_token: str


class ResetPasswordRequest(BaseModel):
    access_token: str
    new_password: str


def validate_password(password: str) -> str | None:
    """
    Validate password strength.
    Returns error message if invalid, None if valid.

    Rules:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 special character (. , ? ! @ # $ % & * _ - +)
    """
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r'[A-Z]', password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r'[.,?!@#$%&*_\-+]', password):
        return "Password must contain at least one special character (. , ? ! @ # $ % & * _ - +)."
    return None


@router.post("/signup")
def signup(req: AuthRequest):
    """
    Create a new user account and return a usable session token when possible.
    This allows the mobile app to scan immediately after signup.
    """
    if not req.email.strip():
        raise HTTPException(status_code=400, detail="Email is required.")

    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', req.email.strip()):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")

    password_error = validate_password(req.password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    email = req.email.strip().lower()

    try:
        auth_client = create_auth_client()
        response = auth_client.auth.sign_up({
            "email": email,
            "password": req.password,
            "options": {
                "data": {
                    "name": req.name.strip(),
                    "full_name": req.name.strip(),
                }
            }
        })

        if not response.user:
            raise HTTPException(status_code=400, detail="Could not create account. Email may already be registered.")

        # Supabase may or may not return a session on sign_up depending on email confirmation settings.
        session = response.session

        # If session is missing, try signing in immediately so frontend gets an access token.
        if not session:
            try:
                login_response = auth_client.auth.sign_in_with_password({
                    "email": email,
                    "password": req.password,
                })
                session = login_response.session
            except Exception as sign_in_error:
                logger.warning("Account created but immediate sign-in failed: %s", sign_in_error)

        return {
            "success": True,
            "message": "Account created successfully!",
            "user": {
                "id": str(response.user.id),
                "email": response.user.email,
                "name": req.name.strip(),
                "created_at": str(response.user.created_at),
            },
            "session": {
                "access_token": session.access_token if session else None,
                "refresh_token": session.refresh_token if session else None,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        msg = str(e).lower()
        if "already registered" in msg or "already exists" in msg:
            raise HTTPException(status_code=400, detail="An account with this email already exists. Please sign in instead.")
        if "rate limit" in msg:
            raise HTTPException(status_code=429, detail="Signup email rate limit exceeded. Please wait and try again.")
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")


@router.post("/login")
def login(req: AuthRequest):
    """
    Sign in to existing account.
    Returns user info and session tokens.
    """
    if not req.email.strip() or not req.password:
        raise HTTPException(status_code=400, detail="Email and password are required.")

    try:
        auth_client = create_auth_client()
        response = auth_client.auth.sign_in_with_password({
            "email":    req.email.strip().lower(),
            "password": req.password,
        })

        if response.user:
            name = (
                response.user.user_metadata.get("name") or
                response.user.user_metadata.get("full_name") or
                req.email.split("@")[0]
            )
            return {
                "success": True,
                "message": "Signed in successfully!",
                "user": {
                    "id":         str(response.user.id),
                    "email":      response.user.email,
                    "name":       name,
                    "created_at": str(response.user.created_at),
                },
                "session": {
                    "access_token":  response.session.access_token  if response.session else None,
                    "refresh_token": response.session.refresh_token if response.session else None,
                }
            }

        raise HTTPException(status_code=401, detail="Invalid email or password.")

    except HTTPException:
        raise
    except Exception as e:
        msg = str(e).lower()
        if "invalid" in msg or "credentials" in msg or "wrong" in msg:
            raise HTTPException(status_code=401, detail="Invalid email or password. Please try again.")
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@router.post("/refresh")
def refresh_session(req: RefreshSessionRequest):
    """Exchange a stored refresh token for a fresh Supabase session."""
    token = req.refresh_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Refresh token is required.")
    try:
        response = create_auth_client().auth.refresh_session(token)
        if not response.session or not response.user:
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
        name = (
            response.user.user_metadata.get("name")
            or response.user.user_metadata.get("full_name")
            or (response.user.email or "user").split("@")[0]
        )
        return {
            "success": True,
            "user": {
                "id": str(response.user.id),
                "email": response.user.email,
                "name": name,
                "created_at": str(response.user.created_at),
            },
            "session": {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Session refresh failed: %s", e)
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request):
    """Send a Supabase password recovery email."""
    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.environ.get("SUPABASE_KEY", "")
    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Password reset is not configured.")

    try:
        payload_data = {"email": email}
        reset_redirect_url = os.environ.get("PASSWORD_RESET_REDIRECT_URL", "").strip()
        if not reset_redirect_url:
            reset_redirect_url = f"{str(request.base_url).rstrip('/')}/reset-password/"
        payload_data["redirect_to"] = reset_redirect_url
        payload = _json.dumps(payload_data).encode()
        reset_req = urllib.request.Request(
            f"{supabase_url}/auth/v1/recover",
            data=payload,
            method="POST",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(reset_req, timeout=12):
            pass

        return {
            "success": True,
            "message": "If an account exists for this email, a password reset link has been sent."
        }
    except Exception as e:
        msg = str(e).lower()
        if "rate" in msg or "429" in msg:
            raise HTTPException(status_code=429, detail="Too many reset attempts. Please wait and try again.")
        raise HTTPException(status_code=500, detail=f"Could not send password reset email: {str(e)}")


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest):
    """Set a new password after Supabase validates the recovery access token."""
    password_error = validate_password(req.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)
    token = req.access_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Recovery token is required.")
    try:
        verified = database.supabase.auth.get_user(token)
        if not verified or not verified.user:
            raise HTTPException(status_code=401, detail="This recovery link is invalid or expired.")
        database.supabase.auth.admin.update_user_by_id(str(verified.user.id), {"password": req.new_password})
        return {"success": True, "message": "Password updated. You can now sign in."}
    except HTTPException:
        raise
    except Exception as error:
        logger.warning("Password recovery token verification failed: %s", error)
        raise HTTPException(status_code=401, detail="This recovery link is invalid or expired.")


@router.post("/logout")
def logout():
    """Sign out current user."""
    # Sessions are bearer tokens owned by each client. The dashboard/mobile app
    # deletes its token locally; there is intentionally no shared server auth
    # session to mutate here.
    return {"success": True, "message": "Signed out successfully."}


@router.delete("/delete-account")
def delete_account(req: AuthRequest):
    """
    Permanently delete user account and ALL their data.

    Steps:
    1. Verify credentials (re-authenticate)
    2. Delete all receipts belonging to this user
    3. Delete the user account from Supabase Auth

    This cannot be undone.
    """
    try:
        # ── Step 1: Re-authenticate to verify it's really them ──
        auth_response = create_auth_client().auth.sign_in_with_password({
            "email":    req.email.strip().lower(),
            "password": req.password,
        })

        if not auth_response.user:
            raise HTTPException(status_code=401, detail="Invalid credentials. Cannot delete account.")

        user_id = str(auth_response.user.id)

        import os
        service_key = (
            os.environ.get("SUPABASE_SERVICE_KEY", "")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        )
        supabase_url = os.environ.get("SUPABASE_URL", "")
        if not service_key or not supabase_url:
            logger.error("Account deletion unavailable because service-role configuration is missing")
            raise HTTPException(status_code=503, detail="Account deletion is temporarily unavailable.")

        # Remove owner-scoped learning and conversation data as part of the
        # same deletion request. Missing optional tables mean their migrations
        # were never installed and therefore contain no user data.
        for table_name in ("agent_conversation_messages", "agent_feedback", "receipt_item_aliases"):
            try:
                database.supabase.table(table_name).delete().eq("user_id", user_id).execute()
            except Exception as table_error:
                message = str(table_error).lower()
                if "pgrst205" in message or "could not find the table" in message or "does not exist" in message:
                    continue
                logger.exception("Could not delete account data from %s", table_name)
                raise HTTPException(status_code=503, detail="Account data could not be fully deleted. Please try again.")

        # ── Step 2: Delete all receipts for this user ──
        try:
            database.supabase.table("receipts")\
                .delete()\
                .eq("user_id", user_id)\
                .execute()
            logger.info("Deleted receipts during account deletion", extra={"user_id": user_id})
        except Exception as e:
            logger.exception("Could not delete receipts during account deletion", extra={"user_id": user_id})
            raise HTTPException(status_code=503, detail="Account data could not be fully deleted. Please try again.")
            # Continue anyway — try to delete the account

        # ── Step 3: Delete user from Supabase Auth ──
        # Requires service role key
        if service_key and supabase_url:
            import urllib.request, json as _json
            req_data = _json.dumps({}).encode()
            delete_req = urllib.request.Request(
                f"{supabase_url}/auth/v1/admin/users/{user_id}",
                data=req_data,
                method="DELETE",
                headers={
                    "apikey":        service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type":  "application/json",
                }
            )
            with urllib.request.urlopen(delete_req, timeout=10) as r:
                logger.info(
                    "Deleted authentication account",
                    extra={"user_id": user_id, "status_code": r.status},
                )
        else:
            logger.error("Account deletion reached an invalid missing-service-key state")

        return {
            "success": True,
            "message": "Account and all associated data have been permanently deleted."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected account deletion failure")
        raise HTTPException(status_code=500, detail="Account deletion failed. Please try again.")
