"""
Thread-safe request context for passing user info from middleware to tools.

Uses Python's contextvars to safely pass user_id from FastAPI middleware to FastMCP tools.
Each tool creates its own database session to avoid session conflicts.
"""
from contextvars import ContextVar
from typing import Optional

# Context variables for request-scoped data
_user_id: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
_authenticated: ContextVar[bool] = ContextVar("authenticated", default=False)

def set_user_id(user_id: str):
    """
    Store user_id for the current request.

    Called by middleware after OAuth validation.

    Args:
        user_id: Authenticated user ID
    """
    _user_id.set(user_id)
    _authenticated.set(True)

def get_user_id() -> str:
    """
    Retrieve user_id for the current request.

    Called by MCP tools to get authenticated user info.

    Returns:
        user_id string

    Raises:
        ValueError: If not authenticated
    """
    user_id = _user_id.get()
    authenticated = _authenticated.get()

    if not authenticated or not user_id:
        raise ValueError(
            "Request not authenticated. This tool requires OAuth authentication. "
            "Please make sure you've completed the OAuth flow."
        )

    return user_id

def clear_user_id():
    """
    Clear user context.

    Called by middleware after request completes.
    """
    _user_id.set(None)
    _authenticated.set(False)

# Expose context vars for direct access if needed (backward compatibility)
__all__ = ['set_user_id', 'get_user_id', 'clear_user_id', '_user_id', '_authenticated']

