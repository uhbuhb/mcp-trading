# Schwab OAuth Setup Guide

This guide explains how to set up Schwab trading integration on your Railway deployment.

## Prerequisites

1. **Schwab Developer Account**: Register at https://developer.schwab.com
2. **Schwab App**: Create an app in the Schwab developer portal
3. **Railway Deployment**: Your MCP trading server deployed on Railway

## Step 1: Register Schwab OAuth Callback URL

In your Schwab developer portal:

1. Go to your app settings
2. Add callback URL: `https://your-railway-domain.railway.app/setup/schwab/callback`
   - Replace `your-railway-domain` with your actual Railway domain
3. Save the app settings
4. Note your App Key and App Secret

## Step 2: Set Railway Environment Variables

In your Railway project settings, add these environment variables:

```bash
SCHWAB_APP_KEY=your_schwab_app_key_here
SCHWAB_APP_SECRET=your_schwab_app_secret_here
SCHWAB_CALLBACK_URL=https://your-railway-domain.railway.app/setup/schwab/callback
```

**Note**: `SCHWAB_CALLBACK_URL` is optional - it will default to `{SERVER_URL}/setup/schwab/callback` if not set.

## Step 3: Deploy Updated Code

1. Push the updated code to your Railway deployment
2. Wait for the deployment to complete
3. Check logs to ensure the database migration completed (new `SchwabOAuthState` table)

## Step 4: Connect Your Schwab Account

1. Navigate to `https://your-railway-domain.railway.app/setup`
2. Fill in your email (and password if creating a new account)
3. Select "Schwab" from the platform dropdown
4. Select platform (tradier, tradier_paper, or schwab)
5. Click "Connect to Schwab"
6. You'll be redirected to Schwab to authorize access
7. After authorization, you'll be redirected back with your credentials stored

## How It Works

### OAuth Flow

1. **Initiate** (`/setup/schwab/initiate`):
   - Generates OAuth state and PKCE code verifier
   - Stores state in database (expires in 10 minutes)
   - Redirects to Schwab authorization page

2. **Callback** (`/setup/schwab/callback`):
   - Validates state parameter
   - Exchanges authorization code for access/refresh tokens
   - Fetches account hashes from Schwab API
   - Creates/updates user and stores encrypted credentials

3. **Storage**:
   - Access token (encrypted)
   - Refresh token (encrypted)
   - Account hash (encrypted)
   - Token expiration time
   - Platform: "schwab"
   - Environment: "sandbox" or "production"

### Stored Data

The following data is encrypted and stored in the `user_credentials` table:

- `encrypted_access_token` - Schwab OAuth access token
- `encrypted_refresh_token` - Schwab OAuth refresh token
- `encrypted_account_hash` - Schwab account hash (used instead of account number)
- `token_expires_at` - When the access token expires
- `encrypted_account_number` - Account display number (for reference)

### Token Refresh

The `SchwabClient` automatically handles token refresh using the `schwab-py` library. When tokens expire:

1. Client detects expired token
2. Uses refresh token to get new access token
3. Updates stored credentials in database
4. Continues operation seamlessly

## Security Notes

- All credentials are encrypted using Fernet symmetric encryption
- OAuth state uses PKCE (Proof Key for Code Exchange) for additional security
- State parameters expire after 10 minutes
- HTTPS required in production
- Passwords are hashed with bcrypt

## Troubleshooting

**"Server misconfigured" error:**
- Ensure `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` are set in Railway environment variables
- Redeploy after setting environment variables

**"Invalid or expired OAuth state":**
- The OAuth flow timed out (10 minute limit)
- Start the flow again from `/setup`

**"Failed to exchange code for tokens":**
- Verify callback URL matches what's registered in Schwab developer portal
- Check `SCHWAB_CALLBACK_URL` environment variable
- Ensure your Railway domain is correct

**"No Schwab accounts found":**
- Your Schwab account may not have any trading accounts
- Contact Schwab support to verify account status

## Testing

To test the integration:

1. Complete the setup flow above
2. Use an MCP client to call Schwab trading tools
3. Example tools: `get_positions`, `get_balance`, `get_quote`
4. Check logs for successful API calls to Schwab

## Support

For issues with:
- **Schwab API**: Contact Schwab developer support
- **Railway deployment**: Check Railway logs and documentation
- **MCP server**: Check server logs for detailed error messages
