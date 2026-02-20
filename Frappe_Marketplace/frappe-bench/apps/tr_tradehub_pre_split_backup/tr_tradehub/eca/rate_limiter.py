# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
ECA Rate Limiter

This module provides Redis-based rate limiting for ECA rules to prevent
excessive rule triggering and protect system resources.

Uses atomic Redis INCR operations with TTL for automatic cleanup.
Key format: eca_rate:{rule_name}:{doc_name}:{window_start}
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import frappe
from frappe import _


# =============================================================================
# RATE LIMITER RESULT
# =============================================================================

@dataclass
class RateLimitResult:
    """
    Result of a rate limit check.

    Attributes:
        allowed: Whether the request is allowed
        current_count: Current number of executions in the window
        limit: Maximum allowed executions
        remaining: Number of remaining executions allowed
        reset_at: Unix timestamp when the window resets
        window_seconds: Duration of the rate limit window
        reason: Human-readable reason if not allowed
    """
    allowed: bool
    current_count: int
    limit: int
    remaining: int
    reset_at: float
    window_seconds: int
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "allowed": self.allowed,
            "current_count": self.current_count,
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "window_seconds": self.window_seconds,
            "reason": self.reason,
        }


# =============================================================================
# RATE LIMITER CLASS
# =============================================================================

class ECARateLimiter:
    """
    Redis-based rate limiter for ECA rules.

    Uses a sliding window approach with atomic Redis operations.
    Keys are automatically expired using TTL for cleanup.

    Usage:
        limiter = ECARateLimiter()
        result = limiter.check_rate_limit(rule, doc)
        if result.allowed:
            # Execute the rule
            pass
        else:
            # Skip due to rate limit
            pass

    Key Format:
        eca_rate:{rule_name}:{doctype}:{doc_name}:{window_start}
    """

    # Key prefix for all rate limit keys
    KEY_PREFIX = "eca_rate"

    def __init__(self):
        """Initialize the rate limiter."""
        self._redis = None

    @property
    def redis(self):
        """
        Get Redis connection lazily.

        Returns:
            Redis connection from frappe.cache()
        """
        if self._redis is None:
            try:
                self._redis = frappe.cache().get_redis()
            except Exception as e:
                frappe.log_error(
                    f"Failed to get Redis connection: {str(e)}",
                    "ECA Rate Limiter Error"
                )
                self._redis = None
        return self._redis

    def check_rate_limit(
        self,
        rule: "frappe.model.document.Document",
        doc: "frappe.model.document.Document"
    ) -> RateLimitResult:
        """
        Check if a rule execution is allowed under rate limits.

        This method:
        1. Checks if rate limiting is enabled for the rule
        2. Calculates the current window based on rate_limit_seconds
        3. Uses atomic INCR to count and check in one operation
        4. Sets TTL on the key for automatic cleanup

        Args:
            rule: The ECA Rule document
            doc: The document that triggered the rule

        Returns:
            RateLimitResult indicating if execution is allowed
        """
        # Check if rate limiting is enabled
        if not rule.get("enable_rate_limit"):
            return RateLimitResult(
                allowed=True,
                current_count=0,
                limit=0,
                remaining=0,
                reset_at=0,
                window_seconds=0,
                reason="Rate limiting disabled"
            )

        # Get rate limit parameters (explicitly handle 0 vs None)
        rate_limit_count_value = rule.get("rate_limit_count")
        limit_count = rate_limit_count_value if rate_limit_count_value is not None else 10
        rate_limit_seconds_value = rule.get("rate_limit_seconds")
        limit_seconds = rate_limit_seconds_value if rate_limit_seconds_value is not None else 60

        # Handle rate_limit_count = 0 (block all requests)
        if limit_count == 0:
            return RateLimitResult(
                allowed=False,
                current_count=0,
                limit=0,
                remaining=0,
                reset_at=0,
                window_seconds=limit_seconds,
                reason=_("Rate limit count set to 0 - all requests blocked")
            )

        # Calculate window start (floor to nearest window boundary)
        current_time = frappe.utils.now_datetime().timestamp()
        window_start = int(current_time // limit_seconds) * limit_seconds
        window_end = window_start + limit_seconds

        # Build the rate limit key
        key = self._build_key(rule.name, doc.doctype, doc.name, window_start)

        # Check if Redis is available
        if not self.redis:
            # Redis unavailable - fail open (allow execution)
            frappe.log_error(
                "Redis unavailable for rate limiting - allowing execution",
                "ECA Rate Limiter Warning"
            )
            return RateLimitResult(
                allowed=True,
                current_count=0,
                limit=limit_count,
                remaining=limit_count,
                reset_at=window_end,
                window_seconds=limit_seconds,
                reason="Redis unavailable - rate limit bypassed"
            )

        try:
            # Atomic increment and get
            current_count = self._increment_count(key, limit_seconds)

            # Check if within limit
            allowed = current_count <= limit_count
            remaining = max(0, limit_count - current_count)

            reason = None
            if not allowed:
                reason = _(
                    "Rate limit exceeded: {current}/{limit} executions in {window}s window"
                ).format(
                    current=current_count,
                    limit=limit_count,
                    window=limit_seconds
                )

            return RateLimitResult(
                allowed=allowed,
                current_count=current_count,
                limit=limit_count,
                remaining=remaining,
                reset_at=window_end,
                window_seconds=limit_seconds,
                reason=reason
            )

        except Exception as e:
            # On error, fail open (allow execution)
            frappe.log_error(
                f"Rate limit check failed: {str(e)}",
                "ECA Rate Limiter Error"
            )
            return RateLimitResult(
                allowed=True,
                current_count=0,
                limit=limit_count,
                remaining=limit_count,
                reset_at=window_end,
                window_seconds=limit_seconds,
                reason=f"Rate limit check error - allowing execution: {str(e)}"
            )

    def _build_key(
        self,
        rule_name: str,
        doctype: str,
        doc_name: str,
        window_start: int
    ) -> str:
        """
        Build the Redis key for rate limiting.

        Format: eca_rate:{rule_name}:{doctype}:{doc_name}:{window_start}

        Args:
            rule_name: The ECA Rule name
            doctype: The document type
            doc_name: The document name
            window_start: Unix timestamp of window start

        Returns:
            The Redis key string
        """
        # Sanitize components to avoid key injection
        safe_rule = rule_name.replace(":", "_")
        safe_doctype = doctype.replace(":", "_")
        safe_doc = doc_name.replace(":", "_")

        return f"{self.KEY_PREFIX}:{safe_rule}:{safe_doctype}:{safe_doc}:{window_start}"

    def _increment_count(self, key: str, ttl_seconds: int) -> int:
        """
        Atomically increment the counter and set TTL.

        Uses Redis INCR for atomic increment, then EXPIRE if new key.

        Args:
            key: The Redis key
            ttl_seconds: TTL in seconds for automatic cleanup

        Returns:
            The new counter value
        """
        # INCR is atomic - increments or creates with value 1
        new_count = self.redis.incr(key)

        # Set TTL only on new keys (count == 1)
        # This ensures we don't reset TTL on each request
        if new_count == 1:
            # Add extra buffer to TTL to handle clock skew
            self.redis.expire(key, ttl_seconds + 10)

        return new_count

    def get_current_count(
        self,
        rule: "frappe.model.document.Document",
        doc: "frappe.model.document.Document"
    ) -> int:
        """
        Get the current execution count without incrementing.

        Args:
            rule: The ECA Rule document
            doc: The document

        Returns:
            Current count, or 0 if not found
        """
        if not self.redis:
            return 0

        limit_seconds = rule.get("rate_limit_seconds") or 60
        current_time = frappe.utils.now_datetime().timestamp()
        window_start = int(current_time // limit_seconds) * limit_seconds

        key = self._build_key(rule.name, doc.doctype, doc.name, window_start)

        try:
            count = self.redis.get(key)
            return int(count) if count else 0
        except Exception:
            return 0

    def reset_limit(
        self,
        rule_name: str,
        doctype: str,
        doc_name: str
    ) -> bool:
        """
        Reset the rate limit counter for a specific rule/document.

        This can be used for manual overrides or testing.

        Args:
            rule_name: The ECA Rule name
            doctype: The document type
            doc_name: The document name

        Returns:
            True if reset successful, False otherwise
        """
        if not self.redis:
            return False

        try:
            # Delete all keys matching the pattern
            pattern = f"{self.KEY_PREFIX}:{rule_name}:{doctype}:{doc_name}:*"
            cursor = 0

            while True:
                cursor, keys = self.redis.scan(cursor, match=pattern)
                if keys:
                    self.redis.delete(*keys)
                if cursor == 0:
                    break

            return True
        except Exception as e:
            frappe.log_error(
                f"Failed to reset rate limit: {str(e)}",
                "ECA Rate Limiter Error"
            )
            return False

    def cleanup_expired_keys(self) -> int:
        """
        Clean up expired rate limit keys.

        Note: With proper TTL usage, this should rarely be needed
        as Redis automatically expires keys. This is a safety net.

        Returns:
            Number of keys cleaned up
        """
        if not self.redis:
            return 0

        # Keys with TTL should auto-expire, but scan for any stuck keys
        try:
            pattern = f"{self.KEY_PREFIX}:*"
            deleted = 0
            cursor = 0

            while True:
                cursor, keys = self.redis.scan(cursor, match=pattern)
                for key in keys:
                    # Check if key has TTL, if not set one
                    ttl = self.redis.ttl(key)
                    if ttl == -1:  # No TTL set
                        # Set a default TTL of 1 hour for stuck keys
                        self.redis.expire(key, 3600)
                        deleted += 1

                if cursor == 0:
                    break

            return deleted
        except Exception as e:
            frappe.log_error(
                f"Failed to cleanup rate limit keys: {str(e)}",
                "ECA Rate Limiter Error"
            )
            return 0


# =============================================================================
# GLOBAL RATE LIMITER INSTANCE
# =============================================================================

# Singleton instance for convenience
_rate_limiter: Optional[ECARateLimiter] = None


def get_rate_limiter() -> ECARateLimiter:
    """
    Get the global rate limiter instance.

    Returns:
        The singleton ECARateLimiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = ECARateLimiter()
    return _rate_limiter


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def check_rate_limit(
    rule: "frappe.model.document.Document",
    doc: "frappe.model.document.Document"
) -> RateLimitResult:
    """
    Check if rule execution is allowed under rate limits.

    Convenience function that uses the global rate limiter.

    Args:
        rule: The ECA Rule document
        doc: The document that triggered the rule

    Returns:
        RateLimitResult indicating if execution is allowed
    """
    return get_rate_limiter().check_rate_limit(rule, doc)


def reset_rule_limit(rule_name: str, doctype: str, doc_name: str) -> bool:
    """
    Reset the rate limit for a specific rule/document combination.

    Args:
        rule_name: The ECA Rule name
        doctype: The document type
        doc_name: The document name

    Returns:
        True if successful
    """
    return get_rate_limiter().reset_limit(rule_name, doctype, doc_name)


def is_rate_limited(
    rule: "frappe.model.document.Document",
    doc: "frappe.model.document.Document"
) -> bool:
    """
    Quick check if a rule execution would be rate limited.

    Does NOT increment the counter - use check_rate_limit for that.

    Args:
        rule: The ECA Rule document
        doc: The document

    Returns:
        True if rate limited, False if allowed
    """
    if not rule.get("enable_rate_limit"):
        return False

    limiter = get_rate_limiter()
    current_count = limiter.get_current_count(rule, doc)
    limit_count = rule.get("rate_limit_count") or 10

    return current_count >= limit_count


# =============================================================================
# API ENDPOINTS
# =============================================================================

@frappe.whitelist()
def get_rate_limit_status(rule_name: str, doctype: str, doc_name: str) -> dict:
    """
    Get the current rate limit status for a rule/document.

    API endpoint for checking rate limit status.

    Args:
        rule_name: The ECA Rule name
        doctype: The document type
        doc_name: The document name

    Returns:
        Dictionary with rate limit status
    """
    try:
        rule = frappe.get_doc("ECA Rule", rule_name)
        doc = frappe.get_doc(doctype, doc_name)

        limiter = get_rate_limiter()
        result = limiter.check_rate_limit(rule, doc)

        # Don't return the incremented result - just get current count
        return {
            "enabled": rule.get("enable_rate_limit"),
            "current_count": result.current_count - 1,  # Subtract the increment
            "limit": result.limit,
            "remaining": result.remaining,
            "window_seconds": result.window_seconds,
        }
    except Exception as e:
        frappe.log_error(
            f"Failed to get rate limit status: {str(e)}",
            "ECA Rate Limiter Error"
        )
        return {
            "error": str(e)
        }


@frappe.whitelist()
def reset_rate_limit(rule_name: str, doctype: str, doc_name: str) -> dict:
    """
    Reset the rate limit for a rule/document combination.

    API endpoint for resetting rate limits (admin only).

    Args:
        rule_name: The ECA Rule name
        doctype: The document type
        doc_name: The document name

    Returns:
        Dictionary with success status
    """
    # Check permissions
    if not frappe.has_permission("ECA Rule", "write"):
        frappe.throw(_("Insufficient permissions to reset rate limit"))

    success = reset_rule_limit(rule_name, doctype, doc_name)

    return {
        "success": success,
        "message": _("Rate limit reset successfully") if success else _("Failed to reset rate limit")
    }
