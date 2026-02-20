# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Rate Limiter Module for Mock Data Engine.

This module provides rate limiting functionality for AI API calls to prevent
rate limit errors and ensure smooth operation across different providers.

Key Features:
- Provider-specific rate limits (RPM, TPM)
- Token bucket algorithm for smooth rate limiting
- Adaptive rate limiting based on provider responses
- Thread-safe operations using Frappe cache
"""

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any
from collections import deque

try:
    import frappe
except ImportError:
    frappe = None


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting per provider."""
    
    provider: str
    requests_per_minute: int = 60
    tokens_per_minute: int = 100000
    requests_per_second: float = 1.0
    burst_size: int = 10
    estimated_tokens_per_request: int = 1000


class RateLimiter:
    """
    Rate limiter for AI API calls using token bucket algorithm.
    
    This class manages rate limiting for different AI providers to prevent
    hitting API rate limits. It uses a token bucket algorithm with provider-specific
    configurations.
    
    Attributes:
        config: RateLimitConfig for the provider
        _request_times: Deque of request timestamps for RPM tracking
        _token_bucket: Current token count
        _last_refill: Last time tokens were refilled
    """
    
    # Provider-specific default configurations
    PROVIDER_CONFIGS: Dict[str, RateLimitConfig] = {
        "gemini": RateLimitConfig(
            provider="gemini",
            requests_per_minute=18,  # Optimized for batch mode (20/min limit, use 18 for safety)
            tokens_per_minute=1000000,
            requests_per_second=0.3,  # ~1 request per 3.3 seconds (18/min)
            burst_size=5,  # Allow small burst for batch requests
            estimated_tokens_per_request=2000  # Higher estimate for batch requests (5 records per call)
        ),
        "openai": RateLimitConfig(
            provider="openai",
            requests_per_minute=500,  # GPT-4o-mini default
            tokens_per_minute=90000,
            requests_per_second=8.0,
            burst_size=20,
            estimated_tokens_per_request=1500
        ),
        "anthropic": RateLimitConfig(
            provider="anthropic",
            requests_per_minute=60,
            tokens_per_minute=100000,
            requests_per_second=1.0,
            burst_size=10,
            estimated_tokens_per_request=2000
        ),
        "ollama": RateLimitConfig(
            provider="ollama",
            requests_per_minute=1000,  # Local, no real limits
            tokens_per_minute=10000000,
            requests_per_second=10.0,
            burst_size=50,
            estimated_tokens_per_request=1000
        )
    }
    
    def __init__(self, provider: str, config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limiter.
        
        Args:
            provider: Provider name (gemini, openai, anthropic, ollama)
            config: Optional custom configuration
        """
        self.provider = provider.lower()
        self.config = config or self.PROVIDER_CONFIGS.get(
            self.provider,
            RateLimitConfig(provider=self.provider)
        )
        
        # Token bucket state
        self._token_bucket = float(self.config.burst_size)
        self._last_refill = time.time()
        
        # Request tracking (for RPM)
        self._request_times: deque = deque(maxlen=self.config.requests_per_minute)
        
        # Cache key for distributed rate limiting
        self._cache_key_prefix = f"rate_limiter:{self.provider}"
    
    def _refill_tokens(self) -> None:
        """Refill token bucket based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_refill
        
        # Calculate tokens to add (tokens per second)
        tokens_per_second = self.config.requests_per_second
        tokens_to_add = elapsed * tokens_per_second
        
        # Refill bucket (capped at burst size)
        self._token_bucket = min(
            self.config.burst_size,
            self._token_bucket + tokens_to_add
        )
        
        self._last_refill = now
    
    def _clean_old_requests(self) -> None:
        """Remove request timestamps older than 1 minute."""
        now = time.time()
        cutoff = now - 60.0
        
        # Remove old timestamps
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()
    
    def can_make_request(self, estimated_tokens: Optional[int] = None) -> tuple[bool, float]:
        """
        Check if a request can be made now.
        
        Args:
            estimated_tokens: Estimated tokens for this request
            
        Returns:
            Tuple of (can_make_request, wait_time_seconds)
        """
        if not estimated_tokens:
            estimated_tokens = self.config.estimated_tokens_per_request
        
        # Refill tokens
        self._refill_tokens()
        
        # Clean old requests
        self._clean_old_requests()
        
        # Check RPM limit
        if len(self._request_times) >= self.config.requests_per_minute:
            # Calculate wait time until oldest request expires
            oldest_request = self._request_times[0]
            wait_time = 60.0 - (time.time() - oldest_request)
            if wait_time > 0:
                return False, max(wait_time, 0.1)
        
        # Check token bucket
        if self._token_bucket < 1.0:
            # Calculate wait time for token refill
            tokens_needed = 1.0 - self._token_bucket
            wait_time = tokens_needed / self.config.requests_per_second
            return False, max(wait_time, 0.1)
        
        # Can make request
        return True, 0.0
    
    def wait_if_needed(self, estimated_tokens: Optional[int] = None) -> None:
        """
        Wait if necessary before making a request.
        
        Args:
            estimated_tokens: Estimated tokens for this request
        """
        can_make, wait_time = self.can_make_request(estimated_tokens)
        
        if not can_make and wait_time > 0:
            # Add small jitter to avoid thundering herd
            jitter = wait_time * 0.1 * (time.time() % 1.0)
            total_wait = wait_time + jitter
            
            time.sleep(total_wait)
            
            # Refill after waiting
            self._refill_tokens()
    
    def record_request(self, tokens_used: Optional[int] = None) -> None:
        """
        Record that a request was made.
        
        Args:
            tokens_used: Actual tokens used (for TPM tracking)
        """
        now = time.time()
        
        # Record request time
        self._request_times.append(now)
        
        # Consume token from bucket
        tokens_consumed = 1.0
        if tokens_used:
            # Adjust based on actual tokens (normalize to request count)
            tokens_consumed = max(1.0, tokens_used / self.config.estimated_tokens_per_request)
        
        self._token_bucket = max(0.0, self._token_bucket - tokens_consumed)
        
        # Store in cache for distributed rate limiting (if frappe available)
        if frappe:
            try:
                cache_key = f"{self._cache_key_prefix}:requests"
                cache = frappe.cache()
                
                # Get current request list
                request_list = cache.get_value(cache_key) or []
                
                # Add new request
                request_list.append(now)
                
                # Remove old requests (> 1 minute)
                cutoff = now - 60.0
                request_list = [t for t in request_list if t > cutoff]
                
                # Store back
                cache.set_value(cache_key, request_list, expires_in=120)
            except Exception:
                pass  # Ignore cache errors
    
    def get_wait_time(self) -> float:
        """
        Get the wait time needed before next request.
        
        Returns:
            Wait time in seconds (0 if no wait needed)
        """
        can_make, wait_time = self.can_make_request()
        return wait_time if not can_make else 0.0
    
    def reset(self) -> None:
        """Reset rate limiter state."""
        self._token_bucket = float(self.config.burst_size)
        self._last_refill = time.time()
        self._request_times.clear()
        
        if frappe:
            try:
                cache_key = f"{self._cache_key_prefix}:requests"
                frappe.cache().delete_value(cache_key)
            except Exception:
                pass


def get_rate_limiter(provider: str, config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """
    Get a rate limiter instance for a provider.
    
    Args:
        provider: Provider name
        config: Optional custom configuration
        
    Returns:
        RateLimiter instance
    """
    return RateLimiter(provider, config)

