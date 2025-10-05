"""
Migration: Add E*TRADE credential fields to user_credentials table.

This migration adds support for E*TRADE OAuth1 credentials:
- encrypted_consumer_key: E*TRADE consumer key
- encrypted_consumer_secret: E*TRADE consumer secret  
- encrypted_access_token_secret: E*TRADE access token secret

These fields are nullable to maintain backward compatibility with existing Tradier/Schwab credentials.
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
    """Add E*TRADE credential fields to user_credentials table."""
    
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
                # Add E*TRADE credential fields
                print("Adding E*TRADE credential fields...")
                
                # Add encrypted_consumer_key column
                conn.execute(text("""
                    ALTER TABLE user_credentials 
                    ADD COLUMN IF NOT EXISTS encrypted_consumer_key BYTEA
                """))
                
                # Add encrypted_consumer_secret column  
                conn.execute(text("""
                    ALTER TABLE user_credentials 
                    ADD COLUMN IF NOT EXISTS encrypted_consumer_secret BYTEA
                """))
                
                # Add encrypted_access_token_secret column
                conn.execute(text("""
                    ALTER TABLE user_credentials 
                    ADD COLUMN IF NOT EXISTS encrypted_access_token_secret BYTEA
                """))
                
                # Update platform comment to include E*TRADE
                conn.execute(text("""
                    COMMENT ON COLUMN user_credentials.platform IS 'tradier, tradier_paper, schwab, etrade, etrade_sandbox'
                """))
                
                # Commit transaction
                trans.commit()
                
                print("✅ Successfully added E*TRADE credential fields")
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
    print("🔄 Running migration: Add E*TRADE credential fields")
    success = run_migration()
    if success:
        print("✅ Migration completed successfully")
    else:
        print("❌ Migration failed")
        sys.exit(1)
