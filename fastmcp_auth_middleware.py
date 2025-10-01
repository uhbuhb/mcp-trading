"""
FastMCP Middleware for OAuth 2.1 authentication and user context injection.

This middleware:
1. Validates OAuth Bearer tokens on every MCP request
2. Extracts user_id from validated token
3. Injects user_id and db session into FastMCP Context state
4. Makes user_id and db available in tools via ctx.get_state()

Based on FastMCP middleware pattern from:
https://gofastmcp.com/servers/context
"""
import logging
from typing import Any, Callable, Awaitable
from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import get_db, init_session_local
from oauth_server import verify_access_token, SERVER_URL, MCP_ENDPOINT
import hashlib
from datetime import datetime

logger = logging.getLogger("fastmcp_auth")

class OAuthAuthMiddleware:
    """
    FastMCP middleware for OAuth token validation and user context injection.
    
    This is a FastMCP-native middleware that integrates with FastMCP's
    Context system using set_state() and get_state().
    """
    
    def __init__(self):
        """Initialize the OAuth middleware."""
        # Initialize database session maker
        init_session_local()
        logger.info("OAuth middleware initialized")
    
    async def on_call_tool(self, context, call_next: Callable[[], Awaitable[Any]]):
        """
        Intercept tool calls to inject user context.
        
        This method is called by FastMCP before every tool execution.
        
        Args:
            context: FastMCP MiddlewareContext object
            call_next: Function to call next middleware or tool
        
        Returns:
            Result from next middleware or tool
        """
        logger.debug("OAuth middleware: validating token")
        
        try:
            # Access the underlying HTTP request
            # FastMCP provides access to the Starlette request
            request = context.request  # This is the Starlette request object
            
            # Extract Authorization header
            auth_header = request.headers.get("Authorization")
            
            if not auth_header or not auth_header.startswith("Bearer "):
                logger.warning("Missing or invalid Authorization header")
                raise HTTPException(
                    status_code=401,
                    detail="Bearer token required",
                    headers={
                        "WWW-Authenticate": f'Bearer realm="MCP Trading", resource_metadata="{SERVER_URL}/.well-known/oauth-protected-resource"'
                    }
                )
            
            # Extract token
            token = auth_header.split(" ")[1]
            
            # Verify token with audience validation (per MCP spec)
            # Token audience must match the MCP endpoint URL
            try:
                payload = verify_access_token(token, expected_audience=MCP_ENDPOINT)
                user_id = payload["sub"]
                logger.info(f"Token validated for user: {user_id}")
            except Exception as e:
                logger.warning(f"Token validation failed: {e}")
                raise HTTPException(
                    status_code=401,
                    detail=f"Invalid token: {e}",
                    headers={
                        "WWW-Authenticate": f'Bearer realm="MCP Trading", error="invalid_token"'
                    }
                )
            
            # Get database session
            db_generator = get_db()
            db = next(db_generator)
            
            try:
                # Verify token in database (check not revoked, not expired)
                from database import OAuthToken
                token_hash = hashlib.sha256(token.encode()).hexdigest()
                oauth_token = db.query(OAuthToken).filter(
                    OAuthToken.token_hash == token_hash,
                    OAuthToken.revoked == False
                ).first()
                
                if not oauth_token:
                    logger.warning(f"Token not found in database or revoked")
                    raise HTTPException(401, "Token revoked or invalid")
                
                if oauth_token.expires_at < datetime.utcnow():
                    logger.warning(f"Token expired for user {user_id}")
                    raise HTTPException(401, "Token expired")
                
                # ✅ INJECT USER CONTEXT INTO FASTMCP STATE
                # This is the key! FastMCP tools can access this via ctx.get_state()
                context.fastmcp_context.set_state("user_id", user_id)
                context.fastmcp_context.set_state("db", db)
                context.fastmcp_context.set_state("authenticated", True)
                
                logger.debug(f"Injected user context into FastMCP state: {user_id}")
                
                # Call the tool with injected context
                result = await call_next()
                
                return result
                
            finally:
                # Clean up database session
                db.close()
        
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error in OAuth middleware: {e}", exc_info=True)
            raise HTTPException(500, f"Authentication error: {e}")
    
    async def on_list_tools(self, context, call_next: Callable[[], Awaitable[Any]]):
        """
        Tools list doesn't require authentication.
        
        Clients need to discover tools before authenticating.
        """
        logger.debug("OAuth middleware: tools/list (no auth required)")
        return await call_next()
    
    async def on_list_resources(self, context, call_next: Callable[[], Awaitable[Any]]):
        """
        Resources list doesn't require authentication.
        
        Clients need to discover resources before authenticating.
        """
        logger.debug("OAuth middleware: resources/list (no auth required)")
        return await call_next()
    
    async def on_list_prompts(self, context, call_next: Callable[[], Awaitable[Any]]):
        """
        Prompts list doesn't require authentication.
        
        Clients need to discover prompts before authenticating.
        """
        logger.debug("OAuth middleware: prompts/list (no auth required)")
        return await call_next()

# Helper function to extract user context from FastMCP Context in tools
def get_user_context_from_ctx(ctx) -> tuple[str, Session]:
    """
    Extract user_id and database session from FastMCP Context.
    
    Usage in tools:
        @mcp.tool()
        async def my_tool(ctx: Context, symbol: str) -> str:
            user_id, db = get_user_context_from_ctx(ctx)
            # Now use user_id and db
    
    Args:
        ctx: FastMCP Context object
    
    Returns:
        Tuple of (user_id, db_session)
    
    Raises:
        ValueError: If context not authenticated
    """
    user_id = ctx.get_state("user_id")
    db = ctx.get_state("db")
    authenticated = ctx.get_state("authenticated")
    
    if not authenticated or not user_id or not db:
        logger.error("Attempted to use tool without authentication")
        raise ValueError("Request not authenticated. This tool requires OAuth authentication.")
    
    return user_id, db

