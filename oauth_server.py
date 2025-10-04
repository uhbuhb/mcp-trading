"""
OAuth 2.1 Authorization Server implementation following MCP specification.

This implements:
- RFC 6749 (OAuth 2.0) with OAuth 2.1 security best practices
- RFC 7636 (PKCE) - REQUIRED by MCP spec
- RFC 8707 (Resource Indicators) - REQUIRED by MCP spec
- RFC 8414 (Authorization Server Metadata) - REQUIRED by MCP spec
- RFC 9728 (Protected Resource Metadata) - REQUIRED by MCP spec
"""
import os
import logging
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import bcrypt
from slowapi import Limiter
from slowapi.util import get_remote_address

from database import (
    get_db, User, UserCredential, OAuthClient, OAuthCode, OAuthToken
)
from encryption import get_encryption_service

logger = logging.getLogger("oauth_server")

# Rate limiter configuration
limiter = Limiter(key_func=get_remote_address)

# Template configuration
templates = Jinja2Templates(directory="templates")

# Password hashing functions using bcrypt directly (Python 3.13 compatible)
def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    # Truncate to 72 bytes if needed (bcrypt limitation)
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a bcrypt hash."""
    password_bytes = plain_password.encode('utf-8')[:72]
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)

# JWT configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15  # Reduced from 60 to 15 for better security (OAuth 2.1 best practice)
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Server configuration
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
MCP_ENDPOINT = f"{SERVER_URL}/mcp/"  # Trailing slash required to match FastAPI mount

router = APIRouter()

# ============================================================================
# OAUTH METADATA ENDPOINTS (Required by MCP spec)
# ============================================================================

@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata():
    """
    OAuth 2.0 Authorization Server Metadata (RFC 8414).
    
    Required by MCP spec for client discovery of OAuth endpoints.
    """
    return JSONResponse({
        "issuer": SERVER_URL,
        "authorization_endpoint": f"{SERVER_URL}/authorize",
        "token_endpoint": f"{SERVER_URL}/token",
        "revocation_endpoint": f"{SERVER_URL}/revoke",  # RFC 7009
        "registration_endpoint": f"{SERVER_URL}/register",  # Optional but recommended
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],  # REQUIRED: PKCE support
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "revocation_endpoint_auth_methods_supported": ["none"],  # RFC 7009
        "scopes_supported": ["trading"],
        "service_documentation": f"{SERVER_URL}/docs"
    })

@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata():
    """
    OAuth 2.0 Protected Resource Metadata (RFC 9728).
    
    Required by MCP spec for clients to discover the authorization server.
    The resource MUST be the MCP endpoint URL per MCP spec.
    """
    return JSONResponse({
        "resource": MCP_ENDPOINT,  # Changed from SERVER_URL to MCP_ENDPOINT
        "authorization_servers": [SERVER_URL],
        "scopes_supported": ["trading"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{SERVER_URL}/docs"
    })

# ============================================================================
# USER REGISTRATION & CREDENTIAL MANAGEMENT
# ============================================================================

@router.get("/setup")
async def setup_form(request: Request):
    """Credential submission form for users to register their trading platform credentials."""
    # Check if user is authenticated via OAuth
    auth_header = request.headers.get("Authorization")
    user_email = None
    is_authenticated = False
    active_sessions = []

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
            user_id = payload["sub"]
            is_authenticated = True
            # Get user email and active sessions from database
            from database import get_db
            db = next(get_db())
            try:
                user = db.query(User).filter(User.user_id == user_id).first()
                if user:
                    user_email = user.email
                    
                # Get active sessions for this user
                from database import OAuthToken
                from datetime import datetime, timezone
                current_time = datetime.now(timezone.utc)
                
                sessions = db.query(OAuthToken).filter(
                    OAuthToken.user_id == user_id,
                    OAuthToken.revoked == False,
                    OAuthToken.expires_at > current_time
                ).all()
                
                active_sessions = [
                    {
                        "token_id": str(session.id) if hasattr(session, 'id') else session.token_hash[:8],
                        "client_id": session.client_id,
                        "created_at": session.created_at.isoformat(),
                        "expires_at": session.expires_at.isoformat()
                    }
                    for session in sessions
                ]
            finally:
                db.close()
        except Exception:
            pass  # Not authenticated, show full form

    return templates.TemplateResponse("setup.html", {
        "request": request,
        "user_email": user_email,
        "is_authenticated": is_authenticated,
        "active_sessions": active_sessions
    })

@router.post("/setup")
async def setup_credentials(
    request: Request,
    email: str = Form(...),
    password: Optional[str] = Form(None),
    platform: str = Form(...),
    access_token: str = Form(...),
    account_number: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Register user and encrypt their trading credentials.
    
    Two modes:
    1. Authenticated (has OAuth token): Adds credentials to authenticated user
    2. Unauthenticated: Creates new user with email/password
    
    Security:
    - Passwords are hashed with bcrypt
    - Trading credentials are encrypted with Fernet
    - HTTPS required in production
    """
    logger.info(f"Setting up credentials for {email} on {platform}")
    
    # Validate platform
    if platform not in ["tradier", "tradier_paper", "schwab"]:
        raise HTTPException(400, "Unsupported platform")
    
    # Check if user is authenticated via OAuth
    auth_header = request.headers.get("Authorization")
    user = None
    
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
            user_id = payload["sub"]
            # Get user from database
            user = db.query(User).filter(User.user_id == user_id).first()
            if user:
                logger.info(f"Using authenticated user: {user.user_id} ({user.email})")
                # Update email if it was set during OAuth without email
                if not user.email or user.email != email:
                    user.email = email
                    db.commit()
        except Exception as e:
            logger.warning(f"OAuth token validation failed during setup: {e}")
            # Fall through to email/password flow
    
    # If not authenticated via OAuth, use email/password
    if user is None:
        if not password:
            raise HTTPException(400, "Password required when not authenticated via OAuth")
        
        # Check if user exists
        user = db.query(User).filter(User.email == email).first()
        
        if user is None:
            # Create new user
            password_hash = hash_password(password)
            user = User(email=email, password_hash=password_hash)
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Created new user: {user.user_id}")
        else:
            # Verify password for existing user
            if not verify_password(password, user.password_hash):
                raise HTTPException(401, "Invalid credentials")
            logger.info(f"User already exists: {user.user_id}")
    
    # Store credentials using auth_utils
    from auth_utils import store_user_trading_credentials
    store_user_trading_credentials(
        user_id=str(user.user_id),
        platform=platform,
        access_token=access_token,
        account_number=account_number,
        db=db
    )
    
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Setup Complete</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
            .success {{ background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 4px; }}
            .info {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 4px; margin: 20px 0; }}
            code {{ background: #f8f9fa; padding: 2px 6px; border-radius: 3px; }}
        </style>
    </head>
    <body>
        <div class="success">
            <h2>✅ Credentials Registered Successfully!</h2>
            <p>Your {platform} credentials have been encrypted and stored.</p>
        </div>
        
        <div class="info">
            <h3>Next Steps:</h3>
            <ol>
                <li>Your User ID: <code>{user.user_id}</code></li>
                <li>You can now configure your MCP client to connect to this server</li>
                <li>The client will handle OAuth authentication automatically</li>
            </ol>
        </div>
        
        <p><a href="/setup">Register another credential →</a></p>
    </body>
    </html>
    """)

# ============================================================================
# SESSION MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/setup/sessions")
async def list_user_sessions(request: Request, db: Session = Depends(get_db)):
    """
    List active sessions for the authenticated user.
    """
    # Check if user is authenticated
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    
    token = auth_header.split(" ")[1]
    try:
        payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
        user_id = payload["sub"]
        
        # Get all active tokens for the user
        from database import OAuthToken
        from datetime import datetime, timezone
        
        active_tokens = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.revoked == False
        ).all()
        
        sessions = []
        current_time = datetime.now(timezone.utc)
        
        for token_obj in active_tokens:
            expires_at_utc = token_obj.expires_at.replace(tzinfo=timezone.utc) if token_obj.expires_at.tzinfo is None else token_obj.expires_at
            is_expired = expires_at_utc < current_time
            
            sessions.append({
                "client_id": token_obj.client_id,
                "created_at": token_obj.created_at.isoformat(),
                "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
                "is_expired": is_expired,
                "scope": token_obj.scope,
                "token_id": token_obj.id
            })
        
        return JSONResponse({
            "status": "success",
            "user_id": user_id,
            "sessions": sessions,
            "active_count": len([s for s in sessions if not s["is_expired"]]),
            "expired_count": len([s for s in sessions if s["is_expired"]])
        })
        
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/setup/revoke-current")
async def revoke_current_session(request: Request, db: Session = Depends(get_db)):
    """
    Revoke the current session token.
    """
    # Check if user is authenticated
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    
    token = auth_header.split(" ")[1]
    try:
        payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
        user_id = payload["sub"]
        
        # Hash the token to find it in the database
        import hashlib
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        # Find and revoke the token
        from database import OAuthToken
        oauth_token = db.query(OAuthToken).filter(
            OAuthToken.token_hash == token_hash,
            OAuthToken.revoked == False
        ).first()
        
        if not oauth_token:
            return JSONResponse({"error": "Current token not found"}, status_code=404)
        
        # Mark as revoked
        oauth_token.revoked = True
        db.commit()
        
        logger.info(f"Current session revoked for user {user_id}")
        
        return JSONResponse({
            "status": "success",
            "message": "Current session revoked successfully",
            "user_id": user_id
        })
        
    except Exception as e:
        logger.error(f"Failed to revoke current session: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/setup/revoke-all")
async def revoke_all_sessions(request: Request, db: Session = Depends(get_db)):
    """
    Revoke all active sessions for the authenticated user.
    """
    # Check if user is authenticated
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    
    token = auth_header.split(" ")[1]
    try:
        payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
        user_id = payload["sub"]
        
        # Get all active tokens for the user
        from database import OAuthToken
        active_tokens = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.revoked == False
        ).all()
        
        if not active_tokens:
            return JSONResponse({
                "status": "success",
                "message": "No active sessions found",
                "revoked_count": 0
            })
        
        # Revoke all tokens
        revoked_count = 0
        for token_obj in active_tokens:
            token_obj.revoked = True
            revoked_count += 1
        
        db.commit()
        
        logger.info(f"Revoked {revoked_count} sessions for user {user_id}")
        
        return JSONResponse({
            "status": "success",
            "message": f"Successfully revoked {revoked_count} sessions",
            "revoked_count": revoked_count
        })
        
    except Exception as e:
        logger.error(f"Failed to revoke all sessions: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ============================================================================
# SCHWAB OAUTH SETUP FLOW
# ============================================================================

@router.get("/setup/schwab/initiate")
async def schwab_oauth_initiate(
    email: str,
    environment: str,
    password: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Initiate Schwab OAuth flow for credential setup.

    This endpoint:
    1. Validates environment variables (SCHWAB_APP_KEY, etc.)
    2. Generates OAuth state and PKCE code verifier
    3. Stores state in database for callback verification
    4. Redirects user to Schwab authorization page
    """
    logger.info(f"Initiating Schwab OAuth for {email} ({environment})")

    # Validate environment
    # Environment validation removed - now using platform-only approach

    # Validate required environment variables
    app_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    callback_url = os.getenv("SCHWAB_CALLBACK_URL")

    if not app_key or not app_secret:
        raise HTTPException(
            500,
            "Server misconfigured: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set"
        )

    if not callback_url:
        # Default to SERVER_URL + /setup/schwab/callback
        callback_url = f"{SERVER_URL}/setup/schwab/callback"

    # Generate OAuth state and PKCE code verifier
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(32)

    # Calculate code challenge (SHA256 of verifier)
    code_challenge = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge_b64 = code_challenge.hex()

    # Store state in database (expires in 10 minutes)
    from database import SchwabOAuthState
    oauth_state = SchwabOAuthState(
        state=state,
        email=email,
        password=password,
        code_verifier=code_verifier,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
    )
    db.add(oauth_state)
    db.commit()

    # Build Schwab authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": app_key,
        "redirect_uri": callback_url,
        "state": state,
        "code_challenge": code_challenge_b64,
        "code_challenge_method": "S256"
    }

    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urlencode(auth_params)}"

    logger.info(f"Redirecting to Schwab OAuth: {auth_url}")
    return RedirectResponse(auth_url)

@router.get("/setup/schwab/callback")
async def schwab_oauth_callback(
    code: str,
    state: str,
    session: Optional[str] = None,  # Schwab also sends a session parameter
    db: Session = Depends(get_db)
):
    """
    Handle OAuth callback from Schwab.

    This endpoint:
    1. Validates state parameter
    2. Exchanges authorization code for tokens
    3. Fetches user's Schwab account hashes
    4. Creates/updates user and stores encrypted credentials
    """
    logger.info(f"Received Schwab OAuth callback - code: {code}, state: {state}, session: {session}")
    logger.info(f"Code length: {len(code)}, State length: {len(state)}")
    logger.info(f"Code first 50 chars: {code[:50]}...")
    logger.info(f"State first 50 chars: {state[:50]}...")

    # Retrieve and validate state
    from database import SchwabOAuthState
    oauth_state = db.query(SchwabOAuthState).filter(SchwabOAuthState.state == state).first()

    if not oauth_state:
        raise HTTPException(400, "Invalid or expired OAuth state")

    # Handle timezone-aware comparison - ensure both datetimes are timezone-aware
    current_time = datetime.now(timezone.utc)
    expires_at = oauth_state.expires_at
    
    # If expires_at is naive, assume it's UTC
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    if expires_at < current_time:
        db.delete(oauth_state)
        db.commit()
        raise HTTPException(400, "OAuth state expired - please try again")

    # Get environment variables
    app_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", f"{SERVER_URL}/setup/schwab/callback")

    try:
        # Debug logging for environment variables and request details
        logger.info(f"SERVER_URL: {SERVER_URL}")
        logger.info(f"app_key: {app_key}")
        logger.info(f"app_secret: {'***' if app_secret else 'None'}")
        logger.info(f"callback_url: {callback_url}")
        logger.info(f"code: {code}")
        logger.info(f"code_verifier: {oauth_state.code_verifier}")

        # Exchange authorization code for tokens via HTTP request
        import httpx

        # Prepare token exchange request
        token_url = "https://api.schwabapi.com/v1/oauth/token"
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url,
            "code_verifier": oauth_state.code_verifier,
            "client_id": app_key,
            "client_secret": app_secret
        }

        logger.info(f"Token URL: {token_url}")
        logger.info(f"Token data: {dict(token_data, client_secret='***' if token_data.get('client_secret') else None)}")

        # Exchange code for tokens using Basic Authentication
        import base64
        
        # Create Basic Auth header (client_id:client_secret base64 encoded)
        credentials = f"{app_key}:{app_secret}"
        basic_auth = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        # Remove client_id and client_secret from body since they're in the header
        token_data_auth = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url,
            "code_verifier": oauth_state.code_verifier
        }
        
        logger.info(f"Using Basic Auth header: Authorization: Basic {basic_auth[:20]}...")
        logger.info(f"Token data (without credentials): {token_data_auth}")

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=token_data_auth, headers=headers)
            
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response headers: {dict(response.headers)}")
            logger.info(f"Response text: {response.text}")

            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                raise HTTPException(500, f"Failed to exchange code for tokens: {response.text}")

            token_response = response.json()

        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        expires_in = token_response.get("expires_in", 1800)  # Default 30 minutes

        if not access_token or not refresh_token:
            raise HTTPException(500, "Missing tokens in Schwab response")

        # Fetch account hashes
        async with httpx.AsyncClient() as client:
            accounts_response = await client.get(
                "https://api.schwabapi.com/trader/v1/accounts/accountNumbers",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            logger.info(f"Accounts response status: {accounts_response.status_code}")
            logger.info(f"Accounts response text: {accounts_response.text}")

            if accounts_response.status_code != 200:
                logger.error(f"Failed to fetch accounts: {accounts_response.text}")
                raise HTTPException(500, "Failed to fetch Schwab accounts")

            accounts = accounts_response.json()

        # For now, use the first account (we can add account selection UI later)
        if not accounts or len(accounts) == 0:
            raise HTTPException(500, "No Schwab accounts found")

        account_hash = accounts[0].get("hashValue")
        account_number = accounts[0].get("accountNumber", "N/A")

        if not account_hash:
            raise HTTPException(500, "Account hash missing from Schwab response")

        # Create or authenticate user
        user = db.query(User).filter(User.email == oauth_state.email).first()

        if user is None:
            if not oauth_state.password:
                raise HTTPException(400, "Password required for new user")

            # Create new user
            password_hash = hash_password(oauth_state.password)
            user = User(email=oauth_state.email, password_hash=password_hash)
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Created new user: {user.user_id}")
        else:
            if oauth_state.password:
                # Verify password for existing user
                if not verify_password(oauth_state.password, user.password_hash):
                    raise HTTPException(401, "Invalid credentials")
            logger.info(f"Using existing user: {user.user_id}")

        # Store credentials using auth_utils
        from auth_utils import store_user_trading_credentials
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        store_user_trading_credentials(
            user_id=str(user.user_id),
            platform="schwab",
            access_token=access_token,
            account_number=account_number,
            db=db,
            refresh_token=refresh_token,
            account_hash=account_hash,
            token_expires_at=token_expires_at
        )

        # Clean up OAuth state
        db.delete(oauth_state)
        db.commit()

        logger.info(f"Successfully stored Schwab credentials for user {user.user_id}")

        # Return success page
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Schwab Setup Complete</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                .success {{ background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 4px; }}
                .info {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 4px; margin: 20px 0; }}
                code {{ background: #f8f9fa; padding: 2px 6px; border-radius: 3px; }}
            </style>
        </head>
        <body>
            <div class="success">
                <h2>✅ Schwab Credentials Registered Successfully!</h2>
                <p>Your Schwab credentials have been encrypted and stored.</p>
            </div>

            <div class="info">
                <h3>Next Steps:</h3>
                <ol>
                    <li>Your User ID: <code>{user.user_id}</code></li>
                    <li>Account Hash: <code>{account_hash}</code></li>
                    <li>You can now configure your MCP client to connect to this server</li>
                    <li>The client will handle OAuth authentication automatically</li>
                </ol>
            </div>

            <p><a href="/setup">Register another credential →</a></p>
        </body>
        </html>
        """)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Schwab OAuth callback failed: {e}")

        # Clean up OAuth state on error
        try:
            db.delete(oauth_state)
            db.commit()
        except:
            pass

        raise HTTPException(500, f"Schwab OAuth failed: {str(e)}")

# ============================================================================
# OAUTH AUTHORIZATION FLOW
# ============================================================================

@router.get("/authorize")
@limiter.limit("20/minute")  # Prevent authorization endpoint abuse
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,  # REQUIRED by MCP spec (RFC 8707)
    scope: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    OAuth 2.1 Authorization Endpoint with PKCE (RFC 7636) and Resource Indicators (RFC 8707).
    
    Required by MCP spec. Clients redirect users here to obtain authorization.
    
    Security:
    - PKCE (code_challenge) is REQUIRED per MCP spec
    - Resource parameter is REQUIRED per MCP spec
    - Must validate redirect_uri against registered clients
    """
    logger.info(f"Authorization request from client: {client_id}")
    
    # Validate response_type
    if response_type != "code":
        raise HTTPException(400, "Unsupported response_type. Only 'code' is supported.")
    
    # Validate PKCE
    if code_challenge_method != "S256":
        raise HTTPException(400, "code_challenge_method must be S256 per MCP spec")
    
    if not code_challenge:
        raise HTTPException(400, "code_challenge is required (PKCE)")
    
    # Validate resource parameter (RFC 8707 - required by MCP spec)
    if not resource:
        raise HTTPException(400, "resource parameter is required per MCP spec (RFC 8707)")

    # Validate and normalize scope
    requested_scope = scope or "trading"  # Default to "trading" if not provided
    requested_scopes = set(requested_scope.split())
    allowed_scopes = {"trading"}  # Currently only "trading" scope supported

    # Check if requested scopes are valid
    if not requested_scopes.issubset(allowed_scopes):
        invalid_scopes = requested_scopes - allowed_scopes
        raise HTTPException(400, f"Invalid scope(s): {', '.join(invalid_scopes)}. Supported scopes: {', '.join(allowed_scopes)}")

    # Normalize scope (space-separated string)
    normalized_scope = " ".join(sorted(requested_scopes))

    # Validate client
    client = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).first()
    if not client:
        logger.error(f"Unknown client_id: {client_id}")
        logger.error(f"This usually happens when the database was cleared but the client cached the registration.")
        logger.error(f"Available clients in DB: {[c.client_id for c in db.query(OAuthClient).all()]}")
        
        # Return HTML error page with helpful instructions
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Client Not Found</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                    .error {{ background: #f8d7da; border: 1px solid #f5c6cb; padding: 20px; border-radius: 4px; }}
                    .solution {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 4px; margin: 20px 0; }}
                    code {{ background: #f8f9fa; padding: 2px 6px; border-radius: 3px; }}
                    ol {{ margin: 10px 0; padding-left: 20px; }}
                </style>
            </head>
            <body>
                <div class="error">
                    <h2>❌ Unknown Client</h2>
                    <p>Client ID: <code>{client_id}</code></p>
                    <p>This client is not registered with the server.</p>
                </div>
                
                <div class="solution">
                    <h3>🔧 How to Fix This:</h3>
                    <p>This usually happens when the server database was reset but your MCP client cached the old registration.</p>
                    
                    <ol>
                        <li>Close Claude Desktop completely</li>
                        <li>Clear the MCP server from your config (or just restart Claude)</li>
                        <li>Re-add the MCP server to your config</li>
                        <li>Restart Claude Desktop</li>
                        <li>The client will automatically re-register and get a new client_id</li>
                    </ol>
                    
                    <p><strong>Note:</strong> The server will remember your client registration in the future, 
                    so you won't need to do this again unless the database is cleared.</p>
                </div>
            </body>
            </html>
            """,
            status_code=400
        )
    
    # Validate redirect_uri
    if redirect_uri not in client.redirect_uris:
        logger.warning(f"Invalid redirect_uri for client {client_id}: {redirect_uri}")
        raise HTTPException(400, "Invalid redirect_uri")
    
    # Show login form (simplified for now - in production, check existing session)
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorize Access</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }}
            h1 {{ color: #333; }}
            .client-info {{ background: #f8f9fa; padding: 15px; border-radius: 4px; margin: 20px 0; }}
            .form-group {{ margin: 15px 0; }}
            label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            input {{ width: 100%; padding: 10px; font-size: 16px; border: 1px solid #ddd; border-radius: 4px; }}
            button {{ background: #28a745; color: white; padding: 12px 24px; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; width: 100%; margin-top: 10px; }}
            button:hover {{ background: #218838; }}
            .cancel {{ background: #dc3545; }}
            .cancel:hover {{ background: #c82333; }}
        </style>
    </head>
    <body>
        <h1>🔐 Authorize Access</h1>
        
        <div class="client-info">
            <p><strong>Client:</strong> {client.client_name}</p>
            <p><strong>Requesting access to:</strong> Trading operations</p>
            <p><strong>Resource:</strong> {resource}</p>
        </div>
        
        <div class="warning" style="background: #d1ecf1; border: 1px solid #bee5eb; padding: 10px; border-radius: 4px; margin: 20px 0;">
            <strong>ℹ️ First time?</strong> Enter your email and create a password. This will create your account.
            <br><strong>Returning?</strong> Enter your existing email and password to log in.
        </div>
        
        <form method="post" action="/authorize/login">
            <input type="hidden" name="client_id" value="{client_id}">
            <input type="hidden" name="redirect_uri" value="{redirect_uri}">
            <input type="hidden" name="state" value="{state}">
            <input type="hidden" name="code_challenge" value="{code_challenge}">
            <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
            <input type="hidden" name="resource" value="{resource}">
            <input type="hidden" name="scope" value="{normalized_scope}">
            
            <div class="form-group">
                <label for="email">Email:</label>
                <input type="email" id="email" name="email" required placeholder="your.email@example.com">
            </div>
            
            <div class="form-group">
                <label for="password">Password (min 8 characters):</label>
                <input type="password" id="password" name="password" required minlength="8" placeholder="Create or enter your password">
            </div>
            
            <button type="submit">Authorize</button>
            <button type="button" class="cancel" onclick="window.close()">Cancel</button>
        </form>
    </body>
    </html>
    """)

@router.post("/authorize/login")
@limiter.limit("10/minute")  # Stricter limit for login attempts (brute force protection)
async def authorize_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
    resource: str = Form(...),
    scope: str = Form(default="trading"),
    db: Session = Depends(get_db)
):
    """
    Process login and generate authorization code.
    
    Creates user if they don't exist, or authenticates existing user.
    
    Security:
    - Verifies user credentials for existing users
    - Creates new users with hashed passwords
    - Generates cryptographically secure authorization code
    - Stores code with PKCE challenge for later verification
    """
    logger.info(f"Login attempt for {email}")
    
    # Check if user exists
    user = db.query(User).filter(User.email == email).first()
    
    if user is None:
        # Create new user during OAuth flow
        password_hash = hash_password(password)
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"Created new user during OAuth: {user.user_id}")
    else:
        # Authenticate existing user
        if not verify_password(password, user.password_hash):
            raise HTTPException(401, "Invalid password")
        logger.info(f"User authenticated: {user.user_id}")
    
    # Validate client again
    client = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).first()
    if not client or redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "Invalid client or redirect_uri")
    
    # Generate authorization code
    auth_code = secrets.token_urlsafe(32)
    
    # Store authorization code with PKCE challenge
    oauth_code = OAuthCode(
        code=auth_code,
        user_id=user.user_id,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        resource_parameter=resource,  # Store resource for token validation
        scope=scope,  # Store approved scope
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)  # Short-lived
    )
    db.add(oauth_code)
    db.commit()
    
    logger.info(f"Generated authorization code for user {user.user_id}, client {client_id}")
    
    # Redirect back to client with authorization code
    # Use 303 See Other to ensure browser switches from POST to GET
    params = {"code": auth_code, "state": state}
    redirect_url = f"{redirect_uri}?{urlencode(params)}"
    
    return RedirectResponse(redirect_url, status_code=303)

@router.post("/token")
@limiter.limit("30/minute")  # Limit token requests
async def token_exchange(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    resource: Optional[str] = Form(None),  # REQUIRED by MCP spec
    db: Session = Depends(get_db)
):
    """
    OAuth 2.1 Token Endpoint.
    
    Supports:
    - authorization_code grant with PKCE verification (RFC 7636)
    - refresh_token grant
    - Resource parameter validation (RFC 8707)
    
    Returns JWT access tokens with audience claim set to resource parameter.
    """
    logger.info(f"Token request: grant_type={grant_type}")
    
    if grant_type == "authorization_code":
        return await _handle_authorization_code_grant(
            code, redirect_uri, code_verifier, client_id, resource, db
        )
    elif grant_type == "refresh_token":
        return await _handle_refresh_token_grant(refresh_token, client_id, resource, db)
    else:
        raise HTTPException(400, f"Unsupported grant_type: {grant_type}")

async def _handle_authorization_code_grant(
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_id: str,
    resource: str,
    db: Session
) -> Dict[str, Any]:
    """Handle authorization code grant with PKCE verification."""
    
    if not all([code, redirect_uri, code_verifier, client_id, resource]):
        raise HTTPException(400, "Missing required parameters")
    
    # Retrieve authorization code
    oauth_code = db.query(OAuthCode).filter(
        OAuthCode.code == code,
        OAuthCode.client_id == client_id,
        OAuthCode.used == False
    ).first()
    
    if not oauth_code:
        logger.warning(f"Invalid or expired authorization code: {code}")
        raise HTTPException(400, "Invalid authorization code")
    
    # Check expiration
    # Convert timezone-naive datetime from DB to UTC for comparison
    expires_at_utc = oauth_code.expires_at.replace(tzinfo=timezone.utc) if oauth_code.expires_at.tzinfo is None else oauth_code.expires_at
    if expires_at_utc < datetime.now(timezone.utc):
        logger.warning(f"Expired authorization code: {code}")
        raise HTTPException(400, "Authorization code expired")
    
    # Validate redirect_uri matches
    if oauth_code.redirect_uri != redirect_uri:
        raise HTTPException(400, "redirect_uri mismatch")
    
    # REQUIRED: Verify PKCE code_verifier (RFC 7636)
    # Compute the challenge from the verifier using SHA256
    import base64
    computed_challenge = hashlib.sha256(code_verifier.encode('ascii')).digest()
    # Base64url encode (without padding)
    computed_challenge_b64 = base64.urlsafe_b64encode(computed_challenge).decode('ascii').rstrip('=')

    # Compare with stored challenge
    if computed_challenge_b64 != oauth_code.code_challenge:
        logger.warning(f"PKCE verification failed for code {code}")
        raise HTTPException(400, "Invalid code_verifier")
    
    # Verify resource parameter matches (RFC 8707)
    if resource != oauth_code.resource_parameter:
        logger.warning(f"Resource parameter mismatch: {resource} != {oauth_code.resource_parameter}")
        raise HTTPException(400, "resource parameter mismatch")
    
    # Mark code as used
    oauth_code.used = True
    db.commit()
    
    logger.info(f"Authorization code validated for user {oauth_code.user_id}")
    
    # Generate access token (JWT with audience claim and scope)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(oauth_code.user_id),
            "aud": resource,  # REQUIRED: Token audience must match resource parameter
            "client_id": client_id,
            "scope": oauth_code.scope  # Include approved scope in token
        },
        expires_delta=access_token_expires
    )

    # Generate refresh token
    refresh_token_value = secrets.token_urlsafe(32)
    refresh_token_hash = hashlib.sha256(refresh_token_value.encode()).hexdigest()

    # Store token with scope
    token_hash = hashlib.sha256(access_token.encode()).hexdigest()
    oauth_token = OAuthToken(
        token_hash=token_hash,
        user_id=oauth_code.user_id,
        client_id=client_id,
        resource_parameter=resource,
        scope=oauth_code.scope,  # Store approved scope
        expires_at=datetime.now(timezone.utc) + access_token_expires,
        refresh_token_hash=refresh_token_hash,
        refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(oauth_token)
    db.commit()
    
    logger.info(f"Generated tokens for user {oauth_code.user_id}")
    
    return JSONResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "refresh_token": refresh_token_value,
        "scope": oauth_code.scope  # Return the approved scope
    })

async def _handle_refresh_token_grant(
    refresh_token: str,
    client_id: str,
    resource: str,
    db: Session
) -> Dict[str, Any]:
    """Handle refresh token grant."""
    
    if not all([refresh_token, client_id, resource]):
        raise HTTPException(400, "Missing required parameters")
    
    # Find token by refresh_token hash
    refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    oauth_token = db.query(OAuthToken).filter(
        OAuthToken.refresh_token_hash == refresh_hash,
        OAuthToken.client_id == client_id,
        OAuthToken.revoked == False
    ).first()
    
    if not oauth_token:
        raise HTTPException(400, "Invalid refresh token")
    
    # Check expiration
    # Convert timezone-naive datetime from DB to UTC for comparison
    refresh_expires_at_utc = oauth_token.refresh_expires_at.replace(tzinfo=timezone.utc) if oauth_token.refresh_expires_at.tzinfo is None else oauth_token.refresh_expires_at
    if refresh_expires_at_utc < datetime.now(timezone.utc):
        raise HTTPException(400, "Refresh token expired")
    
    # Validate resource matches
    if resource != oauth_token.resource_parameter:
        raise HTTPException(400, "resource parameter mismatch")
    
    # Generate new access token with scope
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(oauth_token.user_id),
            "aud": resource,
            "client_id": client_id,
            "scope": oauth_token.scope  # Include scope from stored token
        },
        expires_delta=access_token_expires
    )

    # Rotate refresh token (best practice for public clients per OAuth 2.1)
    new_refresh_token = secrets.token_urlsafe(32)
    new_refresh_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()

    # Update token
    oauth_token.token_hash = hashlib.sha256(access_token.encode()).hexdigest()
    oauth_token.refresh_token_hash = new_refresh_hash
    oauth_token.expires_at = datetime.now(timezone.utc) + access_token_expires
    oauth_token.refresh_expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    db.commit()

    logger.info(f"Refreshed token for user {oauth_token.user_id}")

    return JSONResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "refresh_token": new_refresh_token,
        "scope": oauth_token.scope  # Return the scope from stored token
    })

# ============================================================================
# TOKEN REVOCATION (RFC 7009)
# ============================================================================

@router.post("/revoke")
async def revoke_token(
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Token Revocation Endpoint (RFC 7009).

    Allows clients to revoke access tokens or refresh tokens.

    Args:
        token: The token to revoke (access_token or refresh_token)
        token_type_hint: Optional hint about token type ("access_token" or "refresh_token")
        client_id: Optional client_id for validation

    Returns:
        200 OK (even if token doesn't exist per RFC 7009)

    Security:
    - Per RFC 7009, always returns 200 to prevent token scanning
    - Validates client_id if provided
    - Supports both access tokens and refresh tokens
    """
    logger.info(f"Token revocation request (hint: {token_type_hint})")

    # Hash the token to search database
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Try to find as access token first (or if hint says access_token)
    if token_type_hint != "refresh_token":
        oauth_token = db.query(OAuthToken).filter(
            OAuthToken.token_hash == token_hash
        ).first()

        if oauth_token:
            # Validate client_id if provided
            if client_id and oauth_token.client_id != client_id:
                logger.warning(f"Client ID mismatch on revocation: {client_id}")
                # Per RFC 7009, still return 200 but don't revoke
                return JSONResponse({"success": True})

            # Mark as revoked
            oauth_token.revoked = True
            db.commit()
            logger.info(f"Access token revoked for user {oauth_token.user_id}")
            return JSONResponse({"success": True})

    # Try as refresh token (or if hint says refresh_token)
    if token_type_hint != "access_token":
        refresh_hash = hashlib.sha256(token.encode()).hexdigest()
        oauth_token = db.query(OAuthToken).filter(
            OAuthToken.refresh_token_hash == refresh_hash
        ).first()

        if oauth_token:
            # Validate client_id if provided
            if client_id and oauth_token.client_id != client_id:
                logger.warning(f"Client ID mismatch on revocation: {client_id}")
                return JSONResponse({"success": True})

            # Mark as revoked (revokes both access and refresh)
            oauth_token.revoked = True
            db.commit()
            logger.info(f"Refresh token revoked for user {oauth_token.user_id}")
            return JSONResponse({"success": True})

    # Token not found - still return 200 per RFC 7009
    logger.debug("Token not found for revocation (returning 200 per RFC 7009)")
    return JSONResponse({"success": True})

# ============================================================================
# CLIENT REGISTRATION (Optional but recommended)
# ============================================================================

@router.post("/register")
async def register_client(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Dynamic Client Registration (RFC 7591).
    
    Optional but recommended by MCP spec. Allows MCP clients to self-register.
    """
    data = await request.json()
    
    client_name = data.get("client_name", "Unknown Client")
    redirect_uris = data.get("redirect_uris", [])
    
    if not redirect_uris:
        raise HTTPException(400, "redirect_uris are required")
    
    # Validate redirect URIs (must be localhost or HTTPS per OAuth 2.1)
    for uri in redirect_uris:
        parsed = urlparse(uri)
        if parsed.scheme not in ["https"] and parsed.hostname not in ["localhost", "127.0.0.1"]:
            raise HTTPException(400, f"Invalid redirect_uri: {uri}. Must be HTTPS or localhost.")
    
    # Generate client credentials
    client_id = f"mcp-{secrets.token_urlsafe(16)}"
    
    # For public clients (like Claude Desktop), no client_secret needed (PKCE only)
    client = OAuthClient(
        client_id=client_id,
        client_name=client_name,
        redirect_uris=redirect_uris,
        is_confidential=False  # Public client - uses PKCE
    )
    
    db.add(client)
    db.commit()
    
    logger.info(f"Registered new client: {client_id}")
    
    return JSONResponse({
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none"  # Public client
    })

# ============================================================================
# JWT UTILITIES
# ============================================================================

def create_access_token(data: Dict[str, Any], expires_delta: timedelta) -> str:
    """
    Create JWT access token with audience claim.
    
    Per MCP spec, the token MUST include the resource parameter in the audience claim.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "iss": SERVER_URL
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_access_token(token: str, expected_audience: str) -> Dict[str, Any]:
    """
    Verify and decode JWT access token.
    
    CRITICAL: Must validate audience claim matches expected resource per MCP spec.
    This prevents tokens issued for other servers from being accepted.
    
    Args:
        token: JWT access token
        expected_audience: Expected audience (resource URL)
    
    Returns:
        Decoded token payload
    
    Raises:
        HTTPException: If token is invalid or audience doesn't match
    """
    try:
        # Decode and verify
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=expected_audience,  # REQUIRED: Audience validation
            issuer=SERVER_URL
        )
        
        # Additional validation
        if "sub" not in payload:
            raise HTTPException(401, "Invalid token: missing subject")
        
        if "aud" not in payload or payload["aud"] != expected_audience:
            logger.warning(
                f"Token audience mismatch: got '{payload.get('aud')}', "
                f"expected '{expected_audience}'"
            )
            raise HTTPException(403, "Token not valid for this resource")
        
        return payload
        
    except JWTError as e:
        logger.warning(f"Token verification failed: {e}")
        raise HTTPException(401, f"Invalid token: {e}")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def get_current_user_id(
    request: Request,
    db: Session = Depends(get_db)
) -> str:
    """
    Extract and validate user ID from Bearer token.
    
    This is used by MCP endpoints to authenticate requests.
    
    Per MCP spec:
    - Validates token signature
    - Validates token audience matches server URL
    - Returns user_id for credential lookup
    """
    # Extract Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            401,
            "Missing or invalid Authorization header",
            headers={"WWW-Authenticate": f'Bearer realm="MCP Trading", resource_metadata="{SERVER_URL}/.well-known/oauth-protected-resource"'}
        )
    
    token = auth_header.split(" ")[1]
    
    # Verify token with audience validation
    # Token audience must match the MCP endpoint URL
    payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
    
    # Check if token is revoked
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    oauth_token = db.query(OAuthToken).filter(
        OAuthToken.token_hash == token_hash,
        OAuthToken.revoked == False
    ).first()
    
    if not oauth_token:
        logger.warning(f"Token not found or revoked: {token_hash[:16]}...")
        raise HTTPException(401, "Token revoked or invalid")
    
    # Check expiration
    # Convert timezone-naive datetime from DB to UTC for comparison
    expires_at_utc = oauth_token.expires_at.replace(tzinfo=timezone.utc) if oauth_token.expires_at.tzinfo is None else oauth_token.expires_at
    if expires_at_utc < datetime.now(timezone.utc):
        logger.warning(f"Token expired for user {oauth_token.user_id}")
        raise HTTPException(401, "Token expired")
    
    user_id = payload["sub"]
    
    # SECURITY: Verify user still exists in database
    # If user was deleted, token should be invalid
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        logger.warning(f"Token references non-existent user: {user_id}")
        # Revoke the token since user no longer exists
        oauth_token.revoked = True
        db.commit()
        raise HTTPException(
            401, 
            "User account no longer exists. Please authenticate again.",
            headers={"WWW-Authenticate": f'Bearer realm="MCP Trading", error="invalid_token"'}
        )
    
    logger.debug(f"Authenticated user: {user_id}")
    
    return user_id

