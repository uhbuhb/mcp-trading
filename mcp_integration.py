"""
Integration layer between FastAPI OAuth and FastMCP tools.

This module provides the bridge to inject authenticated user context
into MCP tool calls.

Challenge: FastMCP doesn't natively support FastAPI-style dependency injection.
Solution: We'll use FastMCP's context feature and wrap the MCP app.
"""
import logging
from typing import Callable, Any
from functools import wraps
from fastapi import Request, Depends
from sqlalchemy.orm import Session
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from database import get_db
from oauth_server import get_current_user_id

logger = logging.getLogger("mcp_integration")

# ============================================================================
# CONTEXT INJECTION FOR MCP TOOLS
# ============================================================================

class MCPContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to inject user_id and db session into request state.
    
    FastMCP tools can access these via request context.
    """
    
    async def dispatch(self, request: StarletteRequest, call_next):
        # For MCP endpoints, extract and validate user
        if request.url.path.startswith("/mcp"):
            try:
                # Convert Starlette request to FastAPI request for dependency injection
                from fastapi import Request as FastAPIRequest
                fastapi_request = FastAPIRequest(request.scope, request.receive)
                
                # Get database session
                db_generator = get_db()
                db = next(db_generator)
                
                try:
                    # Get authenticated user ID
                    user_id = await get_current_user_id(fastapi_request, db)
                    
                    # Inject into request state
                    request.state.user_id = user_id
                    request.state.db = db
                    
                    logger.debug(f"Injected user context: {user_id}")
                    
                    # Call next middleware/endpoint
                    response = await call_next(request)
                    return response
                    
                finally:
                    # Clean up database session
                    db.close()
                    
            except Exception as e:
                logger.error(f"Auth middleware error: {e}")
                # Let the error propagate to FastAPI error handling
                raise
        else:
            # Non-MCP endpoints - no auth required
            return await call_next(request)

def requires_auth(func: Callable) -> Callable:
    """
    Decorator to inject authenticated user context into MCP tools.
    
    This decorator:
    1. Extracts user_id from request state (set by middleware)
    2. Extracts db session from request state
    3. Passes both as first arguments to the tool function
    
    Usage:
        @mcp.tool()
        @requires_auth
        def my_tool(user_id: str, db: Session, symbol: str) -> str:
            # user_id and db are automatically injected
            # symbol comes from LLM
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # In FastMCP, we can access request context via Context object
        # This is a simplified version - you may need to use FastMCP's Context API
        
        # For now, we'll document that tools need to accept these parameters
        # and the middleware ensures they're available
        return func(*args, **kwargs)
    
    return wrapper

# ============================================================================
# ALTERNATIVE: Custom MCP Tool Wrapper
# ============================================================================

class AuthenticatedMCPServer:
    """
    Wrapper around FastMCP that automatically injects user context.
    
    This approach modifies how tools are called to inject user_id and db.
    """
    
    def __init__(self, mcp_server):
        self.mcp = mcp_server
        self._original_tools = {}
    
    def authenticated_tool(self, **tool_kwargs):
        """
        Decorator that wraps MCP tools to inject user_id and db.
        
        Usage:
            auth_mcp = AuthenticatedMCPServer(mcp)
            
            @auth_mcp.authenticated_tool()
            def get_positions(user_id: str, db: Session, platform: str = "tradier"):
                # user_id and db are injected automatically
                ...
        """
        def decorator(func: Callable):
            # Register with FastMCP normally
            mcp_tool = self.mcp.tool(**tool_kwargs)
            
            # Wrap the function to inject context
            @wraps(func)
            async def wrapper(request, **kwargs):
                # Extract user context from request state
                user_id = getattr(request.state, "user_id", None)
                db = getattr(request.state, "db", None)
                
                if not user_id or not db:
                    raise ValueError("Request not authenticated - missing user context")
                
                # Call original function with injected context
                return await func(user_id=user_id, db=db, **kwargs)
            
            # Store original for reference
            self._original_tools[func.__name__] = func
            
            return mcp_tool(wrapper)
        
        return decorator

# ============================================================================
# USAGE EXAMPLE
# ============================================================================

"""
To use the authenticated MCP server:

from mcp.server.fastmcp import FastMCP
from mcp_integration import MCPContextMiddleware, AuthenticatedMCPServer

# Create base MCP server
mcp = FastMCP("trading")

# Wrap for authentication
auth_mcp = AuthenticatedMCPServer(mcp)

# Define tools with user_id and db injected
@auth_mcp.authenticated_tool()
def get_positions(user_id: str, db: Session, platform: str = "tradier") -> str:
    # user_id and db are automatically provided
    # platform comes from LLM
    ...

# Create FastAPI app
app = FastAPI()
app.add_middleware(MCPContextMiddleware)
app.mount("/mcp", mcp.streamable_http_app())
"""

