# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

An OAuth 2.1 secured MCP (Model Context Protocol) server that provides trading capabilities for brokerages. Currently supports Tradier and Schwab with extensible architecture for additional platforms. The server implements OAuth 2.1 with PKCE, resource indicators (RFC 8707), and dynamic client registration.

## Architecture

### Core Components

**FastAPI Application (`app.py`)**
- Main entry point integrating OAuth server and MCP server
- `MCPAuthMiddleware`: Validates Bearer tokens on all `/mcp` endpoints, stores user context in `request_context`
- Lifespan manager: Initializes database, encryption service, and cleanup job on startup
- **Critical**: MCP endpoint must be `/mcp/` (with trailing slash) to match OAuth resource metadata

**OAuth Server (`oauth_server.py`)**
- Implements OAuth 2.1 authorization server per MCP specification
- Endpoints: `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource`, `/authorize`, `/token`, `/revoke`, `/register`
- JWT tokens with audience claim set to `{SERVER_URL}/mcp/` (required by RFC 8707)
- PKCE verification using SHA256 code challenges (required by MCP spec)
- Rate limiting on authorization (`20/minute`) and login (`10/minute`) endpoints

**MCP Trading Server (`trading_server_oauth.py`)**
- FastMCP server in stateless HTTP mode (required for Railway deployment)
- All tools receive `ctx: Context` parameter (FastMCP convention)
- User context extracted via `get_request_context()` from context-local storage set by middleware
- Tools use `get_trading_client_for_user()` to fetch decrypted credentials and create platform clients

**Database Models (`database.py`)**
- SQLAlchemy models: `User`, `UserCredential`, `OAuthClient`, `OAuthCode`, `OAuthToken`
- Credentials encrypted with Fernet (symmetric encryption)
- Composite primary key on `UserCredential`: `(user_id, platform, environment)`

**Request Context (`request_context.py`)**
- Context-local storage using Python's `contextvars`
- Middleware sets `(user_id, db_session)` before tool execution
- Tools access via `get_request_context()`

**Platform Clients**
- `TradierClient` (`tradier_client.py`): Handles Tradier API interactions
  - Supports multiple platforms (tradier, tradier_paper, schwab)
  - Base URLs: tradier=`https://api.tradier.com`, tradier_paper=`https://sandbox.tradier.com`
  - Uses simple API token authentication
- `SchwabClient` (`schwab_client.py`): Handles Schwab API interactions
  - Uses OAuth 2.0 with access/refresh tokens
  - Requires `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` environment variables
  - Automatically handles token refresh via `schwab-py` library
  - Stores account hash instead of account number

**Encryption (`encryption.py`)**
- Fernet symmetric encryption for trading credentials
- `ENCRYPTION_KEY` must be set in environment (32-byte URL-safe base64)

**Background Jobs (`cleanup_job.py`)**
- Asynchronous cleanup of expired OAuth codes and tokens
- Runs every 1 hour, deletes codes older than 10 minutes and expired tokens

## Development Commands

**Install dependencies:**
```bash
uv sync
```

**Run server locally:**
```bash
uv run python app.py
# Or with auto-reload:
uvicorn app:app --reload --port 8000
```

**Environment setup:**
Create `.env` file with:
```bash
JWT_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">
ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
SERVER_URL=http://localhost:8000
DATABASE_URL=sqlite:///./trading_oauth.db  # Or PostgreSQL URL

# For Schwab support:
SCHWAB_APP_KEY=<your_schwab_app_key>
SCHWAB_APP_SECRET=<your_schwab_app_secret>
SCHWAB_CALLBACK_URL=http://localhost:8000/setup/schwab/callback  # Optional, defaults to {SERVER_URL}/setup/schwab/callback
```

**Database initialization:**
Database is auto-initialized on server startup via `init_database()` in `database.py`.

**Register user credentials:**

*Tradier (Token-based):*
Navigate to `/setup`, select "Tradier" platform, and enter:
- `email`, `password` (for new users)
- `platform` ('tradier', 'tradier_paper', or 'schwab')
- `access_token` (Tradier API token)
- `account_number`

*Schwab (OAuth-based):*
Navigate to `/setup`, select "Schwab" platform, click "Connect to Schwab":
1. User is redirected to Schwab authorization page
2. After authorization, Schwab redirects to `/setup/schwab/callback`
3. Server exchanges authorization code for access/refresh tokens
4. Server fetches account hashes and stores encrypted credentials
5. Flow uses PKCE for security, state stored in `SchwabOAuthState` table

## Critical Implementation Details

### OAuth Flow

1. **Client Registration**: MCP client POSTs to `/register` with `redirect_uris`, receives `client_id`
2. **Authorization Request**: Client redirects to `/authorize?response_type=code&client_id=...&redirect_uri=...&code_challenge=...&code_challenge_method=S256&resource={SERVER_URL}/mcp/&state=...`
3. **User Login**: Server shows login form, creates/authenticates user, generates authorization code with PKCE challenge
4. **Token Exchange**: Client POSTs to `/token` with `grant_type=authorization_code&code=...&redirect_uri=...&code_verifier=...&resource={SERVER_URL}/mcp/`
5. **Token Validation**: Server verifies PKCE, resource parameter, issues JWT with `aud={SERVER_URL}/mcp/`

### Token Validation in Middleware

`MCPAuthMiddleware` in `app.py`:
- Extracts Bearer token from `Authorization` header
- Verifies JWT signature and audience claim (`verify_access_token()` in `oauth_server.py`)
- Checks token not revoked and user exists in database
- Stores `user_id` and `db` in context-local storage via `set_request_context()`
- Returns 401 with `WWW-Authenticate` header if validation fails

### User Context Access in Tools

All MCP tools follow this pattern:
```python
@mcp.tool()
async def tool_name(ctx: Context, ...) -> str:
    user_id, db = get_user_context_from_ctx(ctx)
    client, account_number = get_trading_client_for_user(user_id, platform, db)
    # Use client to call platform API
```

### Security Best Practices

- **Never skip PKCE verification**: Always validate `code_verifier` matches `code_challenge` in token exchange
- **Always validate audience claim**: JWT must have `aud` claim matching `{SERVER_URL}/mcp/`
- **Always verify user exists**: Token valid doesn't mean user wasn't deleted
- **Never log sensitive data**: Access tokens, passwords, encryption keys must not appear in logs
- **Always use HTTPS in production**: OAuth requires HTTPS except for localhost
- **Token rotation**: Refresh tokens are rotated on use (OAuth 2.1 best practice)

## Common Patterns

**Adding a new MCP tool:**
1. Add tool function in `trading_server_oauth.py` with `@mcp.tool()` decorator
2. Accept `ctx: Context` as first parameter
3. Extract user context: `user_id, db = get_user_context_from_ctx(ctx)`
4. Get platform client: `client, account = get_trading_client_for_user(user_id, platform, environment, db)`
5. Call platform API via client
6. Return JSON string (all MCP tools return strings)

**Adding a new trading platform:**
1. Create client class in new file (e.g., `etrade_client.py`) following `TradierClient` pattern
2. Add platform name to `SUPPORTED_PLATFORMS` in `trading_server_oauth.py`
3. Add conditional in `get_trading_client_for_user()` to instantiate new client
4. Update `/setup` form to include new platform option

**Token refresh flow:**
Client POSTs to `/token` with `grant_type=refresh_token&refresh_token=...&resource={SERVER_URL}/mcp/`
- Server validates refresh token hash, checks not revoked/expired
- Issues new access token and new refresh token (rotation)
- Old refresh token becomes invalid

## Testing

**Test OAuth flow locally:**
```bash
# 1. Start server
uv run python app.py

# 2. Register a client (simulate MCP client)
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"client_name": "Test Client", "redirect_uris": ["http://localhost:3000/callback"]}'

# 3. Navigate to authorization URL in browser with client_id from step 2
# 4. Login/create account, authorize
# 5. Exchange code for token at /token endpoint
```

**Test MCP endpoints:**
```bash
# Get OAuth token first (via flow above), then:
curl -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "health_check", "arguments": {}}}'
```

## Claude Desktop Integration

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "trading-localhost": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp/"],
      "icon": "📈"
    }
  }
}
```

**Important**: URL must include trailing slash (`/mcp/`) to match OAuth resource metadata.

## Deployment Considerations

**Required Environment Variables:**
- `JWT_SECRET_KEY` - Secret key for signing JWT tokens
- `ENCRYPTION_KEY` - Fernet key for encrypting credentials
- `SERVER_URL` - Full server URL (e.g., `https://your-app.railway.app`)
- `DATABASE_URL` - PostgreSQL connection string (automatically set by Railway)

**Optional for Schwab:**
- `SCHWAB_APP_KEY` - Schwab application key
- `SCHWAB_APP_SECRET` - Schwab application secret
- `SCHWAB_CALLBACK_URL` - OAuth callback URL (defaults to `{SERVER_URL}/setup/schwab/callback`)

**Best Practices:**
- Use PostgreSQL for production (not SQLite) - set `DATABASE_URL`
- Generate production `JWT_SECRET_KEY` and `ENCRYPTION_KEY`, store securely
- Enable HTTPS (required by OAuth 2.1 for non-localhost)
- Rate limiting is enabled via `slowapi` middleware
- Database sessions are properly closed in middleware `finally` block
- For Schwab OAuth callback, register `{SERVER_URL}/setup/schwab/callback` in Schwab developer portal
