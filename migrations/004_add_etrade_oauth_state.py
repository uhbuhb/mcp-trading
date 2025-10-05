"""
Migration: Add E*TRADE OAuth state table.

This migration creates the etrade_oauth_states table for storing temporary
OAuth1 state during the E*TRADE authorization flow.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Add the parent directory to the path so we can import shared modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv()

def run_migration():
    """Create E*TRADE OAuth state table."""
    
    # Get database URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL not found in environment variables")
        return False
    
    try:
        # Create engine
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                # Create etrade_oauth_states table
                print("Creating E*TRADE OAuth state table...")
                
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS etrade_oauth_states (
                        state VARCHAR PRIMARY KEY,
                        email VARCHAR NOT NULL,
                        platform VARCHAR NOT NULL,
                        request_token VARCHAR NOT NULL,
                        request_token_secret VARCHAR NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                
                # Commit transaction
                trans.commit()
                
                print("✅ Successfully created E*TRADE OAuth state table")
                return True
                
            except Exception as e:
                # Rollback on error
                trans.rollback()
                print(f"❌ Migration failed: {e}")
                return False
                
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

if __name__ == "__main__":
    print("🔄 Running migration: Add E*TRADE OAuth state table")
    success = run_migration()
    if success:
        print("✅ Migration completed successfully")
    else:
        print("❌ Migration failed")
        sys.exit(1)
