#!/usr/bin/env python3
"""
Setup script for OAuth-enabled MCP Trading Server.

Run this to:
1. Generate encryption key
2. Initialize database
3. Create initial OAuth clients (optional)

Usage:
    uv run python setup_oauth.py
"""
import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists)
load_dotenv()

def main():
    print("=" * 70)
    print(" MCP TRADING SERVER - OAuth 2.1 Setup")
    print("=" * 70)
    print()
    
    # Step 1: Generate encryption key
    print("Step 1: Encryption Key")
    print("-" * 70)
    
    if os.getenv("ENCRYPTION_KEY"):
        print("✅ ENCRYPTION_KEY already set in environment")
    else:
        print("⚠️  ENCRYPTION_KEY not found in environment")
        print()
        from encryption import generate_encryption_key
        key = generate_encryption_key()
        print()
        print("📋 Add this to your .env file:")
        print(f"   ENCRYPTION_KEY={key}")
        print()
    
    # Step 2: Generate JWT secret
    print()
    print("Step 2: JWT Secret Key")
    print("-" * 70)
    
    if os.getenv("JWT_SECRET_KEY"):
        print("✅ JWT_SECRET_KEY already set in environment")
    else:
        print("⚠️  JWT_SECRET_KEY not found in environment")
        import secrets
        jwt_secret = secrets.token_urlsafe(32)
        print()
        print("📋 Add this to your .env file:")
        print(f"   JWT_SECRET_KEY={jwt_secret}")
        print()
    
    # Step 3: Set server URL
    print()
    print("Step 3: Server URL Configuration")
    print("-" * 70)
    
    server_url = os.getenv("SERVER_URL")
    if server_url:
        print(f"✅ SERVER_URL set to: {server_url}")
    else:
        print("⚠️  SERVER_URL not set, using default: http://localhost:8000")
        print()
        print("📋 For production, add to .env file:")
        print("   SERVER_URL=https://your-app.up.railway.app")
        print()
    
    # Step 4: Database URL
    print()
    print("Step 4: Database Configuration")
    print("-" * 70)
    
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        print(f"✅ DATABASE_URL configured (Railway PostgreSQL)")
    else:
        print("⚠️  DATABASE_URL not set, will use SQLite for development")
        print()
        print("📋 For production (Railway):")
        print("   1. Add PostgreSQL plugin to your Railway project")
        print("   2. DATABASE_URL will be set automatically")
        print()
    
    # Step 5: Initialize database
    print()
    print("Step 5: Initialize Database")
    print("-" * 70)
    
    try:
        from database import init_database
        engine = init_database()
        print("✅ Database tables created successfully")
        print(f"   Using: {engine.url}")
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        return 1
    
    # Step 6: Create test client
    print()
    print("Step 6: Create Test OAuth Client (Optional)")
    print("-" * 70)
    
    response = input("Create a test OAuth client for development? (y/n): ")
    if response.lower() == 'y':
        from database import OAuthClient, get_session_maker
        Session = get_session_maker(engine)
        db = Session()
        
        # Check if test client exists
        existing = db.query(OAuthClient).filter(
            OAuthClient.client_id == "test-client"
        ).first()
        
        if existing:
            print("✅ Test client already exists")
            print(f"   Client ID: {existing.client_id}")
        else:
            test_client = OAuthClient(
                client_id="test-client",
                client_name="Development Test Client",
                redirect_uris=["http://localhost:3000/callback"],
                is_confidential=False
            )
            db.add(test_client)
            db.commit()
            print("✅ Test client created")
            print(f"   Client ID: test-client")
            print(f"   Redirect URIs: http://localhost:3000/callback")
        
        db.close()
    
    # Summary
    print()
    print("=" * 70)
    print(" ✅ SETUP COMPLETE!")
    print("=" * 70)
    print()
    print("Next steps:")
    print()
    print("1. Make sure all environment variables are set in .env")
    print()
    print("2. Start the server:")
    print("   python app.py")
    print()
    print("3. Register your Tradier credentials:")
    print(f"   Visit: {server_url or 'http://localhost:8000'}/setup")
    print()
    print("4. Configure your MCP client:")
    print('   {')
    print('     "mcpServers": {')
    print('       "trading": {')
    print('         "command": "npx",')
    print(f'         "args": ["-y", "mcp-remote", "{server_url or "http://localhost:8000"}/mcp"],')
    print('         "icon": "📈"')
    print('       }')
    print('     }')
    print('   }')
    print()
    print("=" * 70)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

