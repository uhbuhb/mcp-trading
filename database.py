"""
Database models for OAuth 2.1 and credential storage following MCP spec.
"""
import os
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, ARRAY, ForeignKey, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

Base = declarative_base()

class User(Base):
    """User account for authentication."""
    __tablename__ = "users"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    credentials = relationship("UserCredential", back_populates="user", cascade="all, delete-orphan")
    oauth_codes = relationship("OAuthCode", back_populates="user", cascade="all, delete-orphan")
    oauth_tokens = relationship("OAuthToken", back_populates="user", cascade="all, delete-orphan")

class UserCredential(Base):
    """Encrypted trading platform credentials per user."""
    __tablename__ = "user_credentials"
    
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True)
    platform = Column(String, primary_key=True)  # 'tradier'
    environment = Column(String, primary_key=True)  # 'sandbox' or 'production'
    encrypted_access_token = Column(LargeBinary, nullable=False)
    encrypted_account_number = Column(LargeBinary, nullable=False)
    encryption_key_id = Column(String, nullable=False, default="default")  # For key rotation
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="credentials")

class OAuthClient(Base):
    """Registered OAuth clients (MCP clients like Claude Desktop)."""
    __tablename__ = "oauth_clients"
    
    client_id = Column(String, primary_key=True)
    client_secret = Column(String, nullable=True)  # NULL for public clients (PKCE-only)
    client_name = Column(String, nullable=False)
    redirect_uris = Column(ARRAY(String), nullable=False)
    is_confidential = Column(Boolean, default=False)  # False = public client (uses PKCE)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    oauth_codes = relationship("OAuthCode", back_populates="client", cascade="all, delete-orphan")
    oauth_tokens = relationship("OAuthToken", back_populates="client", cascade="all, delete-orphan")

class OAuthCode(Base):
    """Authorization codes for OAuth authorization code flow."""
    __tablename__ = "oauth_codes"

    code = Column(String, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    client_id = Column(String, ForeignKey("oauth_clients.client_id"), nullable=False)
    redirect_uri = Column(String, nullable=False)
    code_challenge = Column(String, nullable=False)  # REQUIRED for PKCE
    code_challenge_method = Column(String, nullable=False, default="S256")  # MUST be S256
    resource_parameter = Column(String, nullable=False)  # REQUIRED per MCP spec (RFC 8707)
    scope = Column(String, nullable=False, default="trading")  # OAuth 2.0 scope
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="oauth_codes")
    client = relationship("OAuthClient", back_populates="oauth_codes")

class OAuthToken(Base):
    """Access and refresh tokens."""
    __tablename__ = "oauth_tokens"

    token_hash = Column(String, primary_key=True)  # SHA256 hash of access token
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    client_id = Column(String, ForeignKey("oauth_clients.client_id"), nullable=False)
    resource_parameter = Column(String, nullable=False)  # Token audience (RFC 8707)
    scope = Column(String, nullable=False, default="trading")  # OAuth 2.0 scope
    expires_at = Column(DateTime, nullable=False)
    refresh_token_hash = Column(String, unique=True, nullable=True)
    refresh_expires_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="oauth_tokens")
    client = relationship("OAuthClient", back_populates="oauth_tokens")

# Database connection
def get_database_url() -> str:
    """Get database URL from environment or use local SQLite for development."""
    # Railway provides DATABASE_URL automatically
    database_url = os.getenv("DATABASE_URL")
    
    if database_url:
        # Railway uses postgres:// but SQLAlchemy needs postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    
    # Local development fallback
    return "sqlite:///./trading_oauth.db"

def init_database():
    """Initialize database and create all tables."""
    database_url = get_database_url()
    engine = create_engine(database_url, echo=True)
    Base.metadata.create_all(engine)
    return engine

def get_session_maker(engine=None):
    """Get SQLAlchemy session maker."""
    if engine is None:
        engine = create_engine(get_database_url())
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Session dependency for FastAPI
SessionLocal = None

def init_session_local():
    """Initialize the global SessionLocal."""
    global SessionLocal
    engine = init_database()
    SessionLocal = get_session_maker(engine)
    return SessionLocal

def get_db():
    """Dependency for getting database sessions in FastAPI."""
    if SessionLocal is None:
        init_session_local()
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

