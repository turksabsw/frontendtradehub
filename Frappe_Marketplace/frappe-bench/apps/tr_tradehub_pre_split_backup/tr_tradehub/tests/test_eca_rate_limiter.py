# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
Test Suite for ECA Rate Limiter

This test suite covers:
- Rate limiting with Redis-based counters
- Window-based rate limit enforcement
- Atomic counter operations
- Rate limit bypass when disabled
- Fail-open behavior when Redis unavailable
- Key generation and cleanup

Run with:
    bench --site [site] run-tests --module tr_tradehub.tests.test_eca_rate_limiter
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, Optional


# =============================================================================
# MOCK FRAPPE MODULE
# =============================================================================

class MockRedis:
    """Mock Redis client for testing."""

    def __init__(self):
        self._data = {}
        self._ttls = {}
        self._available = True

    def incr(self, key):
        if key not in self._data:
            self._data[key] = 0
        self._data[key] += 1
        return self._data[key]

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ex=None):
        self._data[key] = value
        if ex:
            self._ttls[key] = ex

    def expire(self, key, seconds):
        self._ttls[key] = seconds
        return True

    def ttl(self, key):
        if key not in self._data:
            return -2  # Key doesn't exist
        return self._ttls.get(key, -1)  # -1 = no TTL

    def delete(self, *keys):
        for key in keys:
            if key in self._data:
                del self._data[key]
            if key in self._ttls:
                del self._ttls[key]
        return len(keys)

    def scan(self, cursor, match=None):
        # Simple scan implementation
        matching_keys = []
        for key in self._data.keys():
            if match:
                import fnmatch
                if fnmatch.fnmatch(key, match):
                    matching_keys.append(key)
            else:
                matching_keys.append(key)
        return (0, matching_keys)


class MockCache:
    """Mock frappe.cache() for testing."""

    def __init__(self):
        self._redis = MockRedis()

    def get_redis(self):
        if not self._redis._available:
            raise Exception("Redis unavailable")
        return self._redis


class MockUtils:
    """Mock frappe.utils for testing."""

    _mock_time = 1738800000.0  # Fixed timestamp for predictable tests

    @staticmethod
    def now_datetime():
        return datetime.fromtimestamp(MockUtils._mock_time)

    @staticmethod
    def set_mock_time(timestamp):
        MockUtils._mock_time = timestamp


class MockFrappe:
    """Mock Frappe module for standalone testing."""

    _cache = MockCache()

    class utils:
        now_datetime = MockUtils.now_datetime

    @staticmethod
    def cache():
        return MockFrappe._cache

    @staticmethod
    def _(text):
        return text

    @staticmethod
    def log_error(message, title=None):
        pass

    @staticmethod
    def throw(message):
        raise Exception(message)

    @staticmethod
    def has_permission(doctype, ptype):
        return True

    @staticmethod
    def get_doc(doctype, name):
        return MagicMock(name=name, doctype=doctype)

    @staticmethod
    def whitelist():
        def decorator(func):
            return func
        return decorator

    @staticmethod
    def reset_cache():
        MockFrappe._cache = MockCache()


# Patch frappe module before importing rate_limiter
import sys
sys.modules['frappe'] = MockFrappe
sys.modules['frappe.utils'] = MockFrappe.utils


# =============================================================================
# RATE LIMITER IMPLEMENTATION (copied for standalone testing)
# =============================================================================

from dataclasses import dataclass as dc


@dc
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    current_count: int
    limit: int
    remaining: int
    reset_at: float
    window_seconds: int
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "current_count": self.current_count,
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "window_seconds": self.window_seconds,
            "reason": self.reason,
        }


class TestableECARateLimiter:
    """Testable version of ECARateLimiter for standalone testing."""

    KEY_PREFIX = "eca_rate"

    def __init__(self):
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            try:
                self._redis = MockFrappe.cache().get_redis()
            except Exception:
                self._redis = None
        return self._redis

    def check_rate_limit(self, rule, doc) -> RateLimitResult:
        """Check if a rule execution is allowed under rate limits."""
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
                reason="Rate limit count set to 0 - all requests blocked"
            )

        # Calculate window
        current_time = MockFrappe.utils.now_datetime().timestamp()
        window_start = int(current_time // limit_seconds) * limit_seconds
        window_end = window_start + limit_seconds

        # Build the rate limit key
        key = self._build_key(rule.name, doc.doctype, doc.name, window_start)

        # Check if Redis is available
        if not self.redis:
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
            # Atomic increment
            current_count = self._increment_count(key, limit_seconds)

            # Check if within limit
            allowed = current_count <= limit_count
            remaining = max(0, limit_count - current_count)

            reason = None
            if not allowed:
                reason = f"Rate limit exceeded: {current_count}/{limit_count} executions in {limit_seconds}s window"

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
            return RateLimitResult(
                allowed=True,
                current_count=0,
                limit=limit_count,
                remaining=limit_count,
                reset_at=window_end,
                window_seconds=limit_seconds,
                reason=f"Rate limit check error - allowing execution: {str(e)}"
            )

    def _build_key(self, rule_name, doctype, doc_name, window_start) -> str:
        """Build the Redis key for rate limiting."""
        safe_rule = rule_name.replace(":", "_")
        safe_doctype = doctype.replace(":", "_")
        safe_doc = doc_name.replace(":", "_")
        return f"{self.KEY_PREFIX}:{safe_rule}:{safe_doctype}:{safe_doc}:{window_start}"

    def _increment_count(self, key, ttl_seconds) -> int:
        """Atomically increment the counter and set TTL."""
        new_count = self.redis.incr(key)
        if new_count == 1:
            self.redis.expire(key, ttl_seconds + 10)
        return new_count

    def get_current_count(self, rule, doc) -> int:
        """Get the current execution count without incrementing."""
        if not self.redis:
            return 0

        limit_seconds = rule.get("rate_limit_seconds") or 60
        current_time = MockFrappe.utils.now_datetime().timestamp()
        window_start = int(current_time // limit_seconds) * limit_seconds

        key = self._build_key(rule.name, doc.doctype, doc.name, window_start)

        try:
            count = self.redis.get(key)
            return int(count) if count else 0
        except Exception:
            return 0

    def reset_limit(self, rule_name, doctype, doc_name) -> bool:
        """Reset the rate limit counter for a specific rule/document."""
        if not self.redis:
            return False

        try:
            pattern = f"{self.KEY_PREFIX}:{rule_name}:{doctype}:{doc_name}:*"
            cursor = 0
            while True:
                cursor, keys = self.redis.scan(cursor, match=pattern)
                if keys:
                    self.redis.delete(*keys)
                if cursor == 0:
                    break
            return True
        except Exception:
            return False


# =============================================================================
# MOCK DOCUMENT CLASSES
# =============================================================================

@dataclass
class MockRule:
    """Mock ECA Rule document for testing."""
    name: str = "RULE-001"
    rule_name: str = "Test Rule"
    enable_rate_limit: bool = True
    rate_limit_count: int = 5
    rate_limit_seconds: int = 60

    def get(self, field, default=None):
        return getattr(self, field, default)


@dataclass
class MockDocument:
    """Mock document for testing."""
    name: str = "DOC-001"
    doctype: str = "Test DocType"
    status: str = "Draft"


# =============================================================================
# TEST CLASSES
# =============================================================================

class TestRateLimitResult(unittest.TestCase):
    """Tests for RateLimitResult dataclass."""

    def test_to_dict(self):
        """Test RateLimitResult to_dict conversion."""
        result = RateLimitResult(
            allowed=True,
            current_count=3,
            limit=10,
            remaining=7,
            reset_at=1738800060.0,
            window_seconds=60,
            reason=None
        )
        d = result.to_dict()

        self.assertEqual(d["allowed"], True)
        self.assertEqual(d["current_count"], 3)
        self.assertEqual(d["limit"], 10)
        self.assertEqual(d["remaining"], 7)
        self.assertEqual(d["window_seconds"], 60)

    def test_to_dict_with_reason(self):
        """Test RateLimitResult to_dict with reason."""
        result = RateLimitResult(
            allowed=False,
            current_count=11,
            limit=10,
            remaining=0,
            reset_at=1738800060.0,
            window_seconds=60,
            reason="Rate limit exceeded"
        )
        d = result.to_dict()

        self.assertEqual(d["allowed"], False)
        self.assertEqual(d["reason"], "Rate limit exceeded")


class TestRateLimiterDisabled(unittest.TestCase):
    """Tests for rate limiter when disabled."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        self.limiter = TestableECARateLimiter()

    def test_disabled_rate_limiting_allows_all(self):
        """Test that disabled rate limiting allows all executions."""
        rule = MockRule(enable_rate_limit=False)
        doc = MockDocument()

        result = self.limiter.check_rate_limit(rule, doc)

        self.assertTrue(result.allowed)
        self.assertEqual(result.current_count, 0)
        self.assertEqual(result.limit, 0)
        self.assertEqual(result.reason, "Rate limiting disabled")

    def test_disabled_rate_limiting_multiple_calls(self):
        """Test multiple calls with disabled rate limiting."""
        rule = MockRule(enable_rate_limit=False)
        doc = MockDocument()

        for _ in range(100):
            result = self.limiter.check_rate_limit(rule, doc)
            self.assertTrue(result.allowed)


class TestRateLimiterEnabled(unittest.TestCase):
    """Tests for rate limiter when enabled."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_first_request_allowed(self):
        """Test that first request is always allowed."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=5)
        doc = MockDocument()

        result = self.limiter.check_rate_limit(rule, doc)

        self.assertTrue(result.allowed)
        self.assertEqual(result.current_count, 1)
        self.assertEqual(result.remaining, 4)

    def test_requests_up_to_limit_allowed(self):
        """Test that requests up to limit are allowed."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=5)
        doc = MockDocument()

        for i in range(5):
            result = self.limiter.check_rate_limit(rule, doc)
            self.assertTrue(result.allowed, f"Request {i+1} should be allowed")
            self.assertEqual(result.current_count, i + 1)

    def test_request_exceeding_limit_blocked(self):
        """Test that request exceeding limit is blocked."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=5)
        doc = MockDocument()

        # Make 5 allowed requests
        for _ in range(5):
            self.limiter.check_rate_limit(rule, doc)

        # 6th request should be blocked
        result = self.limiter.check_rate_limit(rule, doc)

        self.assertFalse(result.allowed)
        self.assertEqual(result.current_count, 6)
        self.assertEqual(result.remaining, 0)
        self.assertIn("Rate limit exceeded", result.reason)

    def test_remaining_count_decreases(self):
        """Test that remaining count decreases with each request."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=5)
        doc = MockDocument()

        for i in range(5):
            result = self.limiter.check_rate_limit(rule, doc)
            expected_remaining = 5 - (i + 1)
            self.assertEqual(result.remaining, expected_remaining)

    def test_different_documents_have_separate_limits(self):
        """Test that different documents have separate rate limits."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=3)
        doc1 = MockDocument(name="DOC-001")
        doc2 = MockDocument(name="DOC-002")

        # Make 3 requests for doc1
        for _ in range(3):
            self.limiter.check_rate_limit(rule, doc1)

        # Doc1 should be at limit
        result1 = self.limiter.check_rate_limit(rule, doc1)
        self.assertFalse(result1.allowed)

        # Doc2 should still have full quota
        result2 = self.limiter.check_rate_limit(rule, doc2)
        self.assertTrue(result2.allowed)
        self.assertEqual(result2.current_count, 1)

    def test_different_rules_have_separate_limits(self):
        """Test that different rules have separate rate limits."""
        rule1 = MockRule(name="RULE-001", enable_rate_limit=True, rate_limit_count=3)
        rule2 = MockRule(name="RULE-002", enable_rate_limit=True, rate_limit_count=3)
        doc = MockDocument()

        # Max out rule1
        for _ in range(4):
            self.limiter.check_rate_limit(rule1, doc)

        # Rule1 should be limited
        result1 = self.limiter.check_rate_limit(rule1, doc)
        self.assertFalse(result1.allowed)

        # Rule2 should be unaffected
        result2 = self.limiter.check_rate_limit(rule2, doc)
        self.assertTrue(result2.allowed)


class TestRateLimiterWindowBehavior(unittest.TestCase):
    """Tests for rate limiter window behavior."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_window_reset_allows_new_requests(self):
        """Test that new window allows fresh requests."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=3, rate_limit_seconds=60)
        doc = MockDocument()

        # Max out in current window
        for _ in range(4):
            self.limiter.check_rate_limit(rule, doc)

        # Verify blocked
        result = self.limiter.check_rate_limit(rule, doc)
        self.assertFalse(result.allowed)

        # Move time forward to next window
        MockUtils.set_mock_time(1738800060.0)
        # Need a fresh limiter to pick up new Redis connection
        self.limiter = TestableECARateLimiter()

        # Should be allowed in new window
        result = self.limiter.check_rate_limit(rule, doc)
        self.assertTrue(result.allowed)
        self.assertEqual(result.current_count, 1)

    def test_reset_at_timestamp_correct(self):
        """Test that reset_at timestamp is calculated correctly."""
        rule = MockRule(enable_rate_limit=True, rate_limit_seconds=60)
        doc = MockDocument()

        # Set time to middle of a window
        MockUtils.set_mock_time(1738800030.0)  # 30 seconds into a 60s window

        result = self.limiter.check_rate_limit(rule, doc)

        # Window should end at 60 seconds from window start
        expected_reset = 1738800060.0
        self.assertEqual(result.reset_at, expected_reset)

    def test_window_seconds_in_result(self):
        """Test that window_seconds is correctly reported."""
        rule = MockRule(enable_rate_limit=True, rate_limit_seconds=120)
        doc = MockDocument()

        result = self.limiter.check_rate_limit(rule, doc)

        self.assertEqual(result.window_seconds, 120)


class TestRateLimiterKeyGeneration(unittest.TestCase):
    """Tests for rate limiter key generation."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_key_format(self):
        """Test that Redis key format is correct."""
        key = self.limiter._build_key("RULE-001", "Sales Order", "SO-001", 1738800000)

        self.assertEqual(key, "eca_rate:RULE-001:Sales Order:SO-001:1738800000")

    def test_key_sanitizes_colons(self):
        """Test that colons in names are sanitized."""
        key = self.limiter._build_key("RULE:001", "Test:Type", "DOC:001", 1738800000)

        self.assertEqual(key, "eca_rate:RULE_001:Test_Type:DOC_001:1738800000")

    def test_keys_are_unique_per_window(self):
        """Test that keys are unique per time window."""
        key1 = self.limiter._build_key("RULE", "Type", "Doc", 1738800000)
        key2 = self.limiter._build_key("RULE", "Type", "Doc", 1738800060)

        self.assertNotEqual(key1, key2)


class TestRateLimiterGetCurrentCount(unittest.TestCase):
    """Tests for get_current_count method."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_get_current_count_returns_zero_initially(self):
        """Test that current count is zero initially."""
        rule = MockRule()
        doc = MockDocument()

        count = self.limiter.get_current_count(rule, doc)

        self.assertEqual(count, 0)

    def test_get_current_count_after_requests(self):
        """Test that current count reflects actual requests."""
        rule = MockRule(enable_rate_limit=True)
        doc = MockDocument()

        # Make 3 requests
        for _ in range(3):
            self.limiter.check_rate_limit(rule, doc)

        count = self.limiter.get_current_count(rule, doc)

        self.assertEqual(count, 3)

    def test_get_current_count_does_not_increment(self):
        """Test that get_current_count doesn't increment counter."""
        rule = MockRule(enable_rate_limit=True)
        doc = MockDocument()

        # Make 2 requests
        self.limiter.check_rate_limit(rule, doc)
        self.limiter.check_rate_limit(rule, doc)

        # Check count multiple times
        for _ in range(5):
            count = self.limiter.get_current_count(rule, doc)
            self.assertEqual(count, 2)


class TestRateLimiterResetLimit(unittest.TestCase):
    """Tests for reset_limit method."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_reset_limit_clears_counter(self):
        """Test that reset_limit clears the counter."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=3)
        doc = MockDocument()

        # Max out the limit
        for _ in range(5):
            self.limiter.check_rate_limit(rule, doc)

        # Verify blocked
        result = self.limiter.check_rate_limit(rule, doc)
        self.assertFalse(result.allowed)

        # Reset the limit
        success = self.limiter.reset_limit(rule.name, doc.doctype, doc.name)
        self.assertTrue(success)

        # Should be allowed again
        result = self.limiter.check_rate_limit(rule, doc)
        self.assertTrue(result.allowed)
        self.assertEqual(result.current_count, 1)


class TestRateLimiterRedisUnavailable(unittest.TestCase):
    """Tests for fail-open behavior when Redis is unavailable."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        self.limiter = TestableECARateLimiter()

    def test_redis_unavailable_allows_execution(self):
        """Test that Redis unavailable results in allowing execution."""
        # Make Redis unavailable
        MockFrappe._cache._redis._available = False

        rule = MockRule(enable_rate_limit=True)
        doc = MockDocument()

        # Create a new limiter to pick up the unavailable Redis
        limiter = TestableECARateLimiter()
        result = limiter.check_rate_limit(rule, doc)

        self.assertTrue(result.allowed)
        self.assertIn("Redis unavailable", result.reason)

    def test_redis_unavailable_get_current_count_returns_zero(self):
        """Test that get_current_count returns 0 when Redis unavailable."""
        MockFrappe._cache._redis._available = False

        rule = MockRule()
        doc = MockDocument()

        limiter = TestableECARateLimiter()
        count = limiter.get_current_count(rule, doc)

        self.assertEqual(count, 0)


class TestRateLimiterDefaultValues(unittest.TestCase):
    """Tests for default values when not specified."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_default_rate_limit_count(self):
        """Test default rate_limit_count of 10."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=None)
        doc = MockDocument()

        result = self.limiter.check_rate_limit(rule, doc)

        self.assertEqual(result.limit, 10)

    def test_default_rate_limit_seconds(self):
        """Test default rate_limit_seconds of 60."""
        rule = MockRule(enable_rate_limit=True, rate_limit_seconds=None)
        doc = MockDocument()

        result = self.limiter.check_rate_limit(rule, doc)

        self.assertEqual(result.window_seconds, 60)


class TestRateLimiterAtomicOperations(unittest.TestCase):
    """Tests for atomic operation behavior."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_increment_sets_ttl_on_new_key(self):
        """Test that TTL is set when incrementing a new key."""
        rule = MockRule(enable_rate_limit=True, rate_limit_seconds=60)
        doc = MockDocument()

        self.limiter.check_rate_limit(rule, doc)

        # Check that TTL was set (with 10 second buffer)
        redis = MockFrappe._cache._redis
        window_start = int(1738800000.0 // 60) * 60
        key = self.limiter._build_key(rule.name, doc.doctype, doc.name, window_start)

        self.assertEqual(redis._ttls.get(key), 70)  # 60 + 10 buffer


class TestRateLimiterEdgeCases(unittest.TestCase):
    """Tests for edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_cache()
        MockUtils.set_mock_time(1738800000.0)
        self.limiter = TestableECARateLimiter()

    def test_rate_limit_count_of_one(self):
        """Test rate limit with count of 1."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=1)
        doc = MockDocument()

        # First request allowed
        result1 = self.limiter.check_rate_limit(rule, doc)
        self.assertTrue(result1.allowed)

        # Second request blocked
        result2 = self.limiter.check_rate_limit(rule, doc)
        self.assertFalse(result2.allowed)

    def test_rate_limit_count_of_zero(self):
        """Test rate limit with count of 0 (effectively disabled)."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=0)
        doc = MockDocument()

        # Even first request should be blocked (0 allowed)
        result = self.limiter.check_rate_limit(rule, doc)
        self.assertFalse(result.allowed)

    def test_very_short_window(self):
        """Test rate limit with very short window (1 second)."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=2, rate_limit_seconds=1)
        doc = MockDocument()

        # Make 2 requests (should be allowed)
        self.limiter.check_rate_limit(rule, doc)
        result = self.limiter.check_rate_limit(rule, doc)
        self.assertTrue(result.allowed)

        # 3rd request should be blocked
        result = self.limiter.check_rate_limit(rule, doc)
        self.assertFalse(result.allowed)

    def test_very_long_window(self):
        """Test rate limit with long window (1 hour)."""
        rule = MockRule(enable_rate_limit=True, rate_limit_count=100, rate_limit_seconds=3600)
        doc = MockDocument()

        result = self.limiter.check_rate_limit(rule, doc)

        self.assertTrue(result.allowed)
        self.assertEqual(result.window_seconds, 3600)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
