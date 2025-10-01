"""
Thread-safe request context for passing user info from middleware to tools.

Uses Python's contextvars to safely pass user_id and db session
from FastAPI middleware to FastMCP tools.
"""
from contextvars import ContextVar
from typing import Optional
from sqlalchemy.orm import Session

# Context variables for request-scoped data
_user_id: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
_db_session: ContextVar[Optional[Session]] = ContextVar("db_session", default=None)
_authenticated: ContextVar[bool] = ContextVar("authenticated", default=False)

def set_request_context(user_id: str, db: Session):
    """
    Store user context for the current request.
    
    Called by middleware after OAuth validation.
    
    Args:
        user_id: Authenticated user ID
        db: Database session for this request
    """
    _user_id.set(user_id)
    _db_session.set(db)
    _authenticated.set(True)

def get_request_context() -> tuple[str, Session]:
    """
    Retrieve user context for the current request.
    
    Called by MCP tools to get authenticated user info.
    
    Returns:
        Tuple of (user_id, db_session)
    
    Raises:
        ValueError: If not authenticated
    """
    user_id = _user_id.get()
    db = _db_session.get()
    authenticated = _authenticated.get()
    
    if not authenticated or not user_id or not db:
        raise ValueError(
            "Request not authenticated. This tool requires OAuth authentication. "
            "Please make sure you've completed the OAuth flow."
        )
    
    return user_id, db

def clear_request_context():
    """
    Clear request context.
    
    Called by middleware after request completes.
    """
    _user_id.set(None)
    _db_session.set(None)
    _authenticated.set(False)

