"""
Migration: Remove environment column from schwab_oauth_states table

This migration removes the unused environment column from the schwab_oauth_states table.
The environment field was only used for display purposes and is not functionally required.
"""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Add parent directory to path to import from database module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv()

def get_database_url() -> str:
    """Get database URL from environment or use local SQLite for development."""
    # Railway provides DATABASE_URL automatically
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url
    
    # For local development, use SQLite
    return "sqlite:///./trading_oauth.db"

def run_migration():
    """Run the migration to remove environment column."""
    print("=" * 70)
    print(" MIGRATION: Remove environment column from schwab_oauth_states")
    print("=" * 70)
    
    database_url = get_database_url()
    print(f"Database URL: {database_url}")
    
    # Create engine
    engine = create_engine(database_url)
    
    try:
        with engine.connect() as conn:
            # Check if the table exists
            if "postgresql" in database_url:
                # PostgreSQL
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'schwab_oauth_states'
                    );
                """))
                table_exists = result.scalar()
            else:
                # SQLite
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='schwab_oauth_states';
                """))
                table_exists = result.fetchone() is not None
            
            if not table_exists:
                print("❌ Table 'schwab_oauth_states' does not exist. Skipping migration.")
                return
            
            # Check if environment column exists
            if "postgresql" in database_url:
                # PostgreSQL
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'schwab_oauth_states' 
                        AND column_name = 'environment'
                    );
                """))
                column_exists = result.scalar()
            else:
                # SQLite
                result = conn.execute(text("PRAGMA table_info(schwab_oauth_states);"))
                columns = result.fetchall()
                column_exists = any(col[1] == 'environment' for col in columns)
            
            if not column_exists:
                print("✅ Column 'environment' does not exist in 'schwab_oauth_states'. Nothing to migrate.")
                return
            
            print("✅ Found environment column in schwab_oauth_states table")
            
            # Drop the environment column
            if "postgresql" in database_url:
                # PostgreSQL
                conn.execute(text("ALTER TABLE schwab_oauth_states DROP COLUMN environment;"))
            else:
                # SQLite - need to recreate table without environment column
                print("📝 SQLite detected - recreating table without environment column...")
                
                # Get current table structure
                result = conn.execute(text("PRAGMA table_info(schwab_oauth_states);"))
                columns = result.fetchall()
                
                # Create new table without environment column
                create_sql = """
                CREATE TABLE schwab_oauth_states_new (
                    state VARCHAR NOT NULL PRIMARY KEY,
                    email VARCHAR NOT NULL,
                    password VARCHAR,
                    code_verifier VARCHAR NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
                conn.execute(text(create_sql))
                
                # Copy data (excluding environment column)
                conn.execute(text("""
                    INSERT INTO schwab_oauth_states_new (state, email, password, code_verifier, expires_at, created_at)
                    SELECT state, email, password, code_verifier, expires_at, created_at
                    FROM schwab_oauth_states;
                """))
                
                # Drop old table and rename new one
                conn.execute(text("DROP TABLE schwab_oauth_states;"))
                conn.execute(text("ALTER TABLE schwab_oauth_states_new RENAME TO schwab_oauth_states;"))
            
            conn.commit()
            print("✅ Successfully removed environment column from schwab_oauth_states table")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise
    
    print("=" * 70)
    print(" ✅ MIGRATION COMPLETED SUCCESSFULLY!")
    print("=" * 70)

def rollback_migration():
    """Rollback the migration by adding the environment column back."""
    print("=" * 70)
    print(" ROLLBACK: Add environment column back to schwab_oauth_states")
    print("=" * 70)
    
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    try:
        with engine.connect() as conn:
            if "postgresql" in database_url:
                # PostgreSQL
                conn.execute(text("ALTER TABLE schwab_oauth_states ADD COLUMN environment VARCHAR;"))
            else:
                # SQLite - need to recreate table with environment column
                print("📝 SQLite detected - recreating table with environment column...")
                
                # Create new table with environment column
                create_sql = """
                CREATE TABLE schwab_oauth_states_new (
                    state VARCHAR NOT NULL PRIMARY KEY,
                    email VARCHAR NOT NULL,
                    password VARCHAR,
                    environment VARCHAR,
                    code_verifier VARCHAR NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
                conn.execute(text(create_sql))
                
                # Copy data
                conn.execute(text("""
                    INSERT INTO schwab_oauth_states_new (state, email, password, code_verifier, expires_at, created_at)
                    SELECT state, email, password, code_verifier, expires_at, created_at
                    FROM schwab_oauth_states;
                """))
                
                # Drop old table and rename new one
                conn.execute(text("DROP TABLE schwab_oauth_states;"))
                conn.execute(text("ALTER TABLE schwab_oauth_states_new RENAME TO schwab_oauth_states;"))
            
            conn.commit()
            print("✅ Successfully added environment column back to schwab_oauth_states table")
            
    except Exception as e:
        print(f"❌ Rollback failed: {e}")
        raise

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback_migration()
    else:
        run_migration()
