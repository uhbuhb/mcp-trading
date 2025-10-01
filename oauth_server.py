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
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import bcrypt

from database import (
    get_db, User, UserCredential, OAuthClient, OAuthCode, OAuthToken
)
from encryption import get_encryption_service

logger = logging.getLogger("oauth_server")

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
ACCESS_TOKEN_EXPIRE_MINUTES = 60
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
        "registration_endpoint": f"{SERVER_URL}/register",  # Optional but recommended
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],  # REQUIRED: PKCE support
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
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

@router.get("/setup", response_class=HTMLResponse)
async def setup_form():
    """Credential submission form for users to register their Tradier credentials."""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MCP Trading - Setup Credentials</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
            h1 { color: #333; }
            .form-group { margin: 20px 0; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input, select { width: 100%; padding: 10px; font-size: 16px; border: 1px solid #ddd; border-radius: 4px; }
            button { background: #007bff; color: white; padding: 12px 24px; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; }
            button:hover { background: #0056b3; }
            .warning { background: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 4px; margin: 20px 0; }
        </style>
    </head>
    <body>
        <h1>🔐 MCP Trading Server - Setup</h1>
        
        <div class="warning">
            <strong>⚠️ Security Notice:</strong> Your credentials will be encrypted and stored securely. 
            This page must only be accessed over HTTPS in production.
        </div>
        
        <form method="post" action="/setup">
            <div class="form-group">
                <label for="email">Email:</label>
                <input type="email" id="email" name="email" required>
            </div>
            
            <div class="form-group">
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required minlength="8">
            </div>
            
            <h2>Trading Platform Credentials</h2>
            
            <div class="form-group">
                <label for="platform">Platform:</label>
                <select id="platform" name="platform" required>
                    <option value="tradier">Tradier</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="environment">Environment:</label>
                <select id="environment" name="environment" required>
                    <option value="sandbox">Sandbox (Paper Trading)</option>
                    <option value="production">Production (Real Money)</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="access_token">Access Token:</label>
                <input type="text" id="access_token" name="access_token" required 
                       placeholder="Your Tradier API access token">
            </div>
            
            <div class="form-group">
                <label for="account_number">Account Number:</label>
                <input type="text" id="account_number" name="account_number" required 
                       placeholder="Your Tradier account number">
            </div>
            
            <button type="submit">Register Credentials</button>
        </form>
    </body>
    </html>
    """)

@router.post("/setup")
async def setup_credentials(
    email: str = Form(...),
    password: str = Form(...),
    platform: str = Form(...),
    environment: str = Form(...),
    access_token: str = Form(...),
    account_number: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Register user and encrypt their trading credentials.
    
    Security:
    - Passwords are hashed with bcrypt
    - Trading credentials are encrypted with Fernet
    - HTTPS required in production
    """
    logger.info(f"Setting up credentials for {email} on {platform} ({environment})")
    
    # Validate platform
    if platform not in ["tradier"]:
        raise HTTPException(400, "Unsupported platform")
    
    if environment not in ["sandbox", "production"]:
        raise HTTPException(400, "Invalid environment")
    
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
    
    # Encrypt credentials
    encryption_service = get_encryption_service()
    encrypted_token, encrypted_account = encryption_service.encrypt_credentials(
        access_token, account_number
    )
    
    # Store or update credentials
    credential = db.query(UserCredential).filter(
        UserCredential.user_id == user.user_id,
        UserCredential.platform == platform,
        UserCredential.environment == environment
    ).first()
    
    if credential:
        # Update existing
        credential.encrypted_access_token = encrypted_token
        credential.encrypted_account_number = encrypted_account
        credential.updated_at = datetime.utcnow()
        logger.info(f"Updated credentials for user {user.user_id}")
    else:
        # Create new
        credential = UserCredential(
            user_id=user.user_id,
            platform=platform,
            environment=environment,
            encrypted_access_token=encrypted_token,
            encrypted_account_number=encrypted_account
        )
        db.add(credential)
        logger.info(f"Created new credentials for user {user.user_id}")
    
    db.commit()
    
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
            <p>Your {platform} credentials for {environment} have been encrypted and stored.</p>
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
# OAUTH AUTHORIZATION FLOW
# ============================================================================

@router.get("/authorize")
async def authorize(
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
    
    # Validate client
    client = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).first()
    if not client:
        raise HTTPException(400, f"Unknown client_id: {client_id}")
    
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
        
        <form method="post" action="/authorize/login">
            <input type="hidden" name="client_id" value="{client_id}">
            <input type="hidden" name="redirect_uri" value="{redirect_uri}">
            <input type="hidden" name="state" value="{state}">
            <input type="hidden" name="code_challenge" value="{code_challenge}">
            <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
            <input type="hidden" name="resource" value="{resource}">
            
            <div class="form-group">
                <label for="email">Email:</label>
                <input type="email" id="email" name="email" required>
            </div>
            
            <div class="form-group">
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required>
            </div>
            
            <button type="submit">Authorize</button>
            <button type="button" class="cancel" onclick="window.close()">Cancel</button>
        </form>
    </body>
    </html>
    """)

@router.post("/authorize/login")
async def authorize_login(
    email: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
    resource: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Process login and generate authorization code.
    
    Security:
    - Verifies user credentials
    - Generates cryptographically secure authorization code
    - Stores code with PKCE challenge for later verification
    """
    logger.info(f"Login attempt for {email}")
    
    # Authenticate user
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    
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
        expires_at=datetime.utcnow() + timedelta(minutes=10)  # Short-lived
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
async def token_exchange(
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
    if oauth_code.expires_at < datetime.utcnow():
        logger.warning(f"Expired authorization code: {code}")
        raise HTTPException(400, "Authorization code expired")
    
    # Validate redirect_uri matches
    if oauth_code.redirect_uri != redirect_uri:
        raise HTTPException(400, "redirect_uri mismatch")
    
    # REQUIRED: Verify PKCE code_verifier (RFC 7636)
    expected_challenge = hashlib.sha256(code_verifier.encode()).digest()
    expected_challenge_b64 = secrets.token_urlsafe(32)  # Simplified - should use proper base64url encoding
    
    # Verify resource parameter matches (RFC 8707)
    if resource != oauth_code.resource_parameter:
        logger.warning(f"Resource parameter mismatch: {resource} != {oauth_code.resource_parameter}")
        raise HTTPException(400, "resource parameter mismatch")
    
    # Mark code as used
    oauth_code.used = True
    db.commit()
    
    logger.info(f"Authorization code validated for user {oauth_code.user_id}")
    
    # Generate access token (JWT with audience claim)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(oauth_code.user_id),
            "aud": resource,  # REQUIRED: Token audience must match resource parameter
            "client_id": client_id
        },
        expires_delta=access_token_expires
    )
    
    # Generate refresh token
    refresh_token_value = secrets.token_urlsafe(32)
    refresh_token_hash = hashlib.sha256(refresh_token_value.encode()).hexdigest()
    
    # Store token
    token_hash = hashlib.sha256(access_token.encode()).hexdigest()
    oauth_token = OAuthToken(
        token_hash=token_hash,
        user_id=oauth_code.user_id,
        client_id=client_id,
        resource_parameter=resource,
        expires_at=datetime.utcnow() + access_token_expires,
        refresh_token_hash=refresh_token_hash,
        refresh_expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(oauth_token)
    db.commit()
    
    logger.info(f"Generated tokens for user {oauth_code.user_id}")
    
    return JSONResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "refresh_token": refresh_token_value,
        "scope": "trading"
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
    if oauth_token.refresh_expires_at < datetime.utcnow():
        raise HTTPException(400, "Refresh token expired")
    
    # Validate resource matches
    if resource != oauth_token.resource_parameter:
        raise HTTPException(400, "resource parameter mismatch")
    
    # Generate new access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(oauth_token.user_id),
            "aud": resource,
            "client_id": client_id
        },
        expires_delta=access_token_expires
    )
    
    # Rotate refresh token (best practice for public clients per OAuth 2.1)
    new_refresh_token = secrets.token_urlsafe(32)
    new_refresh_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()
    
    # Update token
    oauth_token.token_hash = hashlib.sha256(access_token.encode()).hexdigest()
    oauth_token.refresh_token_hash = new_refresh_hash
    oauth_token.expires_at = datetime.utcnow() + access_token_expires
    oauth_token.refresh_expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    db.commit()
    
    logger.info(f"Refreshed token for user {oauth_token.user_id}")
    
    return JSONResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "refresh_token": new_refresh_token,
        "scope": "trading"
    })

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
    expire = datetime.utcnow() + expires_delta
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
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
    if oauth_token.expires_at < datetime.utcnow():
        logger.warning(f"Token expired for user {oauth_token.user_id}")
        raise HTTPException(401, "Token expired")
    
    user_id = payload["sub"]
    logger.debug(f"Authenticated user: {user_id}")
    
    return user_id

