"""
Database migration: Add OAuth token fields to user_credentials table

This migration adds support for OAuth-based platforms like Schwab by adding:
- encrypted_refresh_token: For storing OAuth refresh tokens
- encrypted_account_hash: For platforms using account hashes instead of numbers
- token_expires_at: For tracking OAuth token expiration

Run this migration against your PostgreSQL database.
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def get_database_url() -> str:
    """Get database URL from environment."""
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        # Railway uses postgres:// but SQLAlchemy needs postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    # Local development fallback
    return "sqlite:///./trading_oauth.db"


def run_migration():
    """Run the migration to add new columns."""
    database_url = get_database_url()
    engine = create_engine(database_url)

    print(f"Running migration on database: {database_url}")

    with engine.connect() as conn:
        # Add new columns to user_credentials table
        print("Adding encrypted_refresh_token column...")
        conn.execute(text("""
            ALTER TABLE user_credentials
            ADD COLUMN IF NOT EXISTS encrypted_refresh_token BYTEA
        """))

        print("Adding encrypted_account_hash column...")
        conn.execute(text("""
            ALTER TABLE user_credentials
            ADD COLUMN IF NOT EXISTS encrypted_account_hash BYTEA
        """))

        print("Adding token_expires_at column...")
        conn.execute(text("""
            ALTER TABLE user_credentials
            ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP
        """))

        conn.commit()
        print("Migration completed successfully!")


def rollback_migration():
    """Rollback the migration (remove the added columns)."""
    database_url = get_database_url()
    engine = create_engine(database_url)

    print(f"Rolling back migration on database: {database_url}")

    with engine.connect() as conn:
        print("Removing encrypted_refresh_token column...")
        conn.execute(text("""
            ALTER TABLE user_credentials
            DROP COLUMN IF EXISTS encrypted_refresh_token
        """))

        print("Removing encrypted_account_hash column...")
        conn.execute(text("""
            ALTER TABLE user_credentials
            DROP COLUMN IF EXISTS encrypted_account_hash
        """))

        print("Removing token_expires_at column...")
        conn.execute(text("""
            ALTER TABLE user_credentials
            DROP COLUMN IF EXISTS token_expires_at
        """))

        conn.commit()
        print("Rollback completed successfully!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback_migration()
    else:
        run_migration()
