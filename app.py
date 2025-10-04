"""
Main FastAPI application integrating OAuth 2.1 server with MCP Trading server.

This application:
1. Serves OAuth metadata endpoints (/.well-known/*)
2. Handles OAuth authorization flow (/authorize, /token)
3. Serves MCP endpoints (/mcp) with Bearer token authentication
4. Provides user credential management (/setup)

Security:
- All MCP requests require valid Bearer tokens
- Tokens must have correct audience claim per MCP spec (RFC 8707)
- Session IDs are NOT used for authentication per MCP security best practices
"""
import os
import logging
from typing import Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Mount
from sqlalchemy.orm import Session

from shared.database import init_database, get_db
from auth.oauth_server import router as oauth_router, get_current_user_id, SERVER_URL, MCP_ENDPOINT, verify_access_token
from mcp_server.trading_server_oauth import mcp as trading_mcp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("app")

# ============================================================================
# TOKEN VALIDATION MIDDLEWARE FOR MCP ENDPOINTS
# ============================================================================

class MCPAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce OAuth token validation on MCP endpoints.
    
    Per MCP spec:
    - All requests to /mcp must include valid Bearer token
    - Token audience must match server URL
    - Returns 401 with WWW-Authenticate header if missing/invalid
    
    Also stores user_id and db in request.state for tool access.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Only protect /mcp endpoints
        if request.url.path.startswith("/mcp"):
            # Skip health check
            if request.url.path == "/mcp/health":
                return await call_next(request)
            
            # Check for Authorization header
            auth_header = request.headers.get("Authorization")
            
            if not auth_header or not auth_header.startswith("Bearer "):
                logger.warning(f"MCP request without valid Authorization header from {request.client.host}")
                
                # Return 401 with WWW-Authenticate header per MCP spec
                return JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized", "message": "Bearer token required"},
                    headers={
                        "WWW-Authenticate": f'Bearer realm="MCP Trading", resource_metadata="{SERVER_URL}/.well-known/oauth-protected-resource"'
                    }
                )
            
            # Extract and validate token
            token = auth_header.split(" ")[1]
            
            try:
                # Verify token with audience validation (per MCP spec RFC 8707)
                # Token audience must match the MCP endpoint URL
                payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
                user_id = payload["sub"]
                
                # Create a direct database session for middleware use
                from shared.database import SessionLocal
                if SessionLocal is None:
                    from shared.database import init_session_local
                    init_session_local()
                
                db = SessionLocal()
                try:
                    # SECURITY: Verify user still exists in database
                    from shared.database import User
                    user = db.query(User).filter(User.user_id == user_id).first()
                    if not user:
                        logger.warning(f"❌ Token references non-existent user: {user_id}")
                        return JSONResponse(
                            status_code=401,
                            content={
                                "error": "invalid_token", 
                                "message": "User account no longer exists. Please authenticate again."
                            },
                            headers={
                                "WWW-Authenticate": f'Bearer realm="MCP Trading", error="invalid_token"'
                            }
                        )
                    
                    # Store user_id and token in context-local storage for tools to access
                    # Tools will create their own database sessions
                    from shared.request_context import set_user_id
                    set_user_id(user_id, token)

                    logger.info(f"✅ Token validated for user: {user_id}")

                    # Continue to endpoint with context set
                    response = await call_next(request)
                    return response

                finally:
                    # Clean up context and close database session
                    from shared.request_context import clear_user_id
                    clear_user_id()
                    db.close()
                
            except Exception as e:
                logger.warning(f"❌ Token validation failed: {e}")
                return JSONResponse(
                    status_code=401,
                    content={"error": "invalid_token", "message": str(e)},
                    headers={
                        "WWW-Authenticate": f'Bearer realm="MCP Trading", error="invalid_token"'
                    }
                )
        
        # Non-MCP endpoints - just continue
        response = await call_next(request)
        return response

# ============================================================================
# APPLICATION SETUP
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - runs on startup and shutdown."""
    # Startup
    logger.info("🚀 Starting MCP Trading Server with OAuth 2.1")
    logger.info(f"Server URL: {SERVER_URL}")

    # Validate JWT_SECRET_KEY is set (critical for production)
    if not os.getenv("JWT_SECRET_KEY"):
        logger.error("❌ JWT_SECRET_KEY environment variable is not set!")
        logger.error("⚠️  This is CRITICAL for production - tokens will be invalid after restart")
        logger.error("📝 Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        raise ValueError("JWT_SECRET_KEY environment variable is required for production")

    # Initialize database
    try:
        init_database()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

    # Initialize encryption service
    try:
        from shared.encryption import get_encryption_service
        get_encryption_service()
        logger.info("✅ Encryption service initialized")
    except Exception as e:
        logger.error(f"❌ Encryption service initialization failed: {e}")
        logger.warning("⚠️  Make sure ENCRYPTION_KEY is set in environment!")
        raise

    # Start cleanup job for expired tokens/codes
    import asyncio
    from shared.cleanup_job import cleanup_loop
    cleanup_stop_event = asyncio.Event()
    cleanup_task = asyncio.create_task(cleanup_loop(cleanup_stop_event))
    logger.info("✅ OAuth cleanup job started")

    # Start FastMCP session manager (required for streamable HTTP)
    async with trading_mcp.session_manager.run():
        logger.info("✅ FastMCP session manager started")
        logger.info("✅ All startup checks passed - server ready")
        yield

    # Shutdown
    logger.info("🛑 Shutting down MCP Trading Server")
    cleanup_stop_event.set()
    await cleanup_task
    logger.info("✅ Cleanup job stopped")

# Create FastAPI app
app = FastAPI(
    title="MCP Trading Server",
    description="OAuth 2.1 secured trading server implementing Model Context Protocol",
    version="0.1.0",
    lifespan=lifespan
)

# Add CORS middleware for browser-based MCP clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],  # Required for MCP session management
)

# Add rate limiting middleware (must be before routes)
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from auth.oauth_server import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Add OAuth token validation for MCP endpoints
app.add_middleware(MCPAuthMiddleware)

# ============================================================================
# MOUNT OAUTH ROUTES
# ============================================================================

# Include OAuth server routes (/.well-known/*, /authorize, /token, /setup, /register)
app.include_router(oauth_router)

# ============================================================================
# MOUNT MCP SERVER
# ============================================================================

# Create MCP server app
mcp_app = trading_mcp.streamable_http_app()

logger.info("MCP app created (OAuth validation handled by MCPAuthMiddleware)")

@app.get("/mcp/health")
async def mcp_health():
    """
    Health check endpoint for MCP server.
    
    This endpoint is excluded from OAuth validation in the middleware
    to allow basic health checks without authentication.
    """
    return JSONResponse({
        "status": "ok",
        "message": "MCP Trading Server is running",
        "server_url": SERVER_URL
    })

# Mount the MCP app at /mcp/ (WITH trailing slash to prevent redirects!)
# FastAPI automatically redirects /mcp -> /mcp/ which breaks MCP protocol
# OAuth validation happens in MCPAuthMiddleware
# User context is stored in request.state and accessed by tools
app.router.routes.append(Mount("/mcp/", app=mcp_app))

# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint - redirect to login page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login", status_code=302)

# ============================================================================
# DEVELOPMENT HELPERS
# ============================================================================
# Note: Development endpoints have been removed for security.
# Use the /register endpoint to create OAuth clients in production.

if __name__ == "__main__":
    import uvicorn
    
    # Run the server
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting server on http://0.0.0.0:{port}")
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=True  # Enable auto-reload for development
    )

