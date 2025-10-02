"""
Background cleanup job for expired OAuth codes and tokens.

This module provides a scheduled task that periodically removes:
- Expired authorization codes (> 10 minutes old)
- Expired access tokens
- Expired refresh tokens
- Revoked tokens (after grace period)

Runs every hour to prevent database bloat.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import get_db, OAuthCode, OAuthToken

logger = logging.getLogger("cleanup_job")

# Cleanup configuration
CLEANUP_INTERVAL_MINUTES = 60  # Run cleanup every hour
REVOKED_TOKEN_GRACE_PERIOD_DAYS = 7  # Keep revoked tokens for 7 days for audit

async def cleanup_expired_codes():
    """
    Remove expired authorization codes from the database.

    Authorization codes expire after 10 minutes but may not be immediately
    cleaned up. This removes codes that have been expired for > 1 hour.
    """
    db_gen = get_db()
    db = next(db_gen)

    try:
        # Delete codes expired more than 1 hour ago
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)

        deleted_count = db.query(OAuthCode).filter(
            OAuthCode.expires_at < cutoff_time
        ).delete()

        db.commit()

        if deleted_count > 0:
            logger.info(f"🗑️  Cleaned up {deleted_count} expired authorization codes")

        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired codes: {e}")
        db.rollback()
        return 0
    finally:
        db.close()

async def cleanup_expired_tokens():
    """
    Remove expired access tokens and refresh tokens from the database.

    Removes tokens that have been expired for > 1 day to allow for clock skew
    and graceful degradation.
    """
    db_gen = get_db()
    db = next(db_gen)

    try:
        # Delete tokens expired more than 1 day ago
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=1)

        deleted_count = db.query(OAuthToken).filter(
            OAuthToken.expires_at < cutoff_time,
            OAuthToken.refresh_expires_at < cutoff_time
        ).delete()

        db.commit()

        if deleted_count > 0:
            logger.info(f"🗑️  Cleaned up {deleted_count} expired tokens")

        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired tokens: {e}")
        db.rollback()
        return 0
    finally:
        db.close()

async def cleanup_revoked_tokens():
    """
    Remove revoked tokens after grace period.

    Keeps revoked tokens for a grace period (default 7 days) for audit purposes,
    then removes them to prevent database bloat.
    """
    db_gen = get_db()
    db = next(db_gen)

    try:
        # Delete revoked tokens older than grace period
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=REVOKED_TOKEN_GRACE_PERIOD_DAYS)

        deleted_count = db.query(OAuthToken).filter(
            OAuthToken.revoked == True,
            OAuthToken.created_at < cutoff_time
        ).delete()

        db.commit()

        if deleted_count > 0:
            logger.info(f"🗑️  Cleaned up {deleted_count} revoked tokens (grace period expired)")

        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up revoked tokens: {e}")
        db.rollback()
        return 0
    finally:
        db.close()

async def run_cleanup():
    """
    Run all cleanup tasks.

    This is the main entry point for the cleanup job. It runs all cleanup
    tasks in sequence and logs the results.
    """
    logger.info("🧹 Starting OAuth database cleanup")

    start_time = datetime.now(timezone.utc)

    # Run all cleanup tasks
    codes_deleted = await cleanup_expired_codes()
    tokens_deleted = await cleanup_expired_tokens()
    revoked_deleted = await cleanup_revoked_tokens()

    total_deleted = codes_deleted + tokens_deleted + revoked_deleted
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()

    if total_deleted > 0:
        logger.info(f"✅ Cleanup complete: {total_deleted} records deleted in {duration:.2f}s")
    else:
        logger.debug(f"✅ Cleanup complete: no expired records found ({duration:.2f}s)")

async def cleanup_loop(stop_event: Optional[asyncio.Event] = None):
    """
    Background loop that runs cleanup periodically.

    Args:
        stop_event: Optional event to signal when to stop the loop

    This function runs indefinitely until stop_event is set. It runs cleanup
    every CLEANUP_INTERVAL_MINUTES and handles errors gracefully.
    """
    logger.info(f"🔄 Starting cleanup loop (interval: {CLEANUP_INTERVAL_MINUTES} minutes)")

    while True:
        try:
            # Run cleanup
            await run_cleanup()

            # Wait for next interval or stop event
            if stop_event:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=CLEANUP_INTERVAL_MINUTES * 60
                    )
                    # Stop event was set
                    logger.info("🛑 Cleanup loop stopped")
                    break
                except asyncio.TimeoutError:
                    # Timeout reached, continue loop
                    pass
            else:
                # No stop event, just sleep
                await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)

        except Exception as e:
            logger.error(f"Error in cleanup loop: {e}")
            # Wait before retrying
            await asyncio.sleep(60)

# Convenience function for manual cleanup
async def manual_cleanup():
    """Run cleanup manually (useful for testing or one-off maintenance)."""
    await run_cleanup()

if __name__ == "__main__":
    # Allow running cleanup manually for testing
    logging.basicConfig(level=logging.INFO)
    asyncio.run(manual_cleanup())
