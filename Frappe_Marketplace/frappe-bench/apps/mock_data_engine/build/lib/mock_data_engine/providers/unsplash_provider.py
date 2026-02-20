# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Unsplash Image Provider for Mock Data Engine.

This module provides contextual image fetching from Unsplash for
generating realistic mock data for Attach Image fields.

Key Features:
- Contextual image search based on DocType, field, and custom queries
- Image caching to respect Unsplash rate limits (50 requests/hour on free tier)
- Fallback to placeholder images when rate limits are exceeded
- Proper attribution handling per Unsplash API guidelines
- Support for image size selection (raw, full, regular, small, thumb)

Usage:
    from mock_data_engine.mock_data_engine.providers.unsplash_provider import (
        UnsplashProvider,
        create_unsplash_provider,
    )

    # Create provider with API key
    config = UnsplashConfig(
        access_key="your-unsplash-access-key",
        default_query="business",
    )
    provider = UnsplashProvider(config)

    # Search for images
    result = provider.search_image(
        query="office workspace",
        context={"doctype": "Employee", "fieldname": "image"}
    )
    print(result.url)

Note:
    Requires the pyunsplash package to be installed:
    pip install pyunsplash

    Unsplash API Guidelines:
    - Free tier: 50 requests per hour
    - Requires attribution when displaying images
    - Must use "utm_source" parameter for referral tracking
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING


# =============================================================================
# Constants
# =============================================================================

# Default queries for different contexts
DEFAULT_CONTEXT_QUERIES: Dict[str, str] = {
    # Person/Employee related
    "employee": "professional portrait",
    "user": "person portrait",
    "customer": "business person",
    "contact": "professional headshot",
    "supplier": "business professional",
    # Business/Company related
    "company": "office building",
    "company_logo": "abstract logo",
    "organization": "corporate building",
    # Product related
    "item": "product",
    "product": "product photography",
    "stock_item": "warehouse inventory",
    "asset": "office equipment",
    # Document/Generic
    "document": "business document",
    "file": "paper document",
    "attachment": "office desk",
    # E-commerce
    "website_item": "product showcase",
    "web_page": "modern website",
    # Other
    "default": "business",
}

# Unsplash image sizes
class ImageSize(Enum):
    """Available Unsplash image sizes."""
    RAW = "raw"
    FULL = "full"
    REGULAR = "regular"
    SMALL = "small"
    THUMB = "thumb"


# Default image size for mock data
DEFAULT_IMAGE_SIZE = ImageSize.REGULAR

# Placeholder image URL template (used when Unsplash is unavailable)
PLACEHOLDER_URL_TEMPLATE = "https://via.placeholder.com/{width}x{height}.png?text={text}"

# Default placeholder dimensions
DEFAULT_PLACEHOLDER_WIDTH = 640
DEFAULT_PLACEHOLDER_HEIGHT = 480

# Rate limit settings
MAX_REQUESTS_PER_HOUR = 50
RATE_LIMIT_WINDOW_SECONDS = 3600

# Cache settings
DEFAULT_CACHE_TTL_SECONDS = 3600  # 1 hour
MAX_CACHE_SIZE = 1000


# =============================================================================
# Exceptions
# =============================================================================


class UnsplashProviderError(Exception):
    """Base exception for Unsplash provider errors."""

    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
    ):
        self.message = message
        self.original_error = original_error
        super().__init__(message)


class UnsplashConnectionError(UnsplashProviderError):
    """Raised when connection to Unsplash API fails."""
    pass


class UnsplashRateLimitError(UnsplashProviderError):
    """Raised when Unsplash rate limit is exceeded."""
    pass


class UnsplashSearchError(UnsplashProviderError):
    """Raised when image search fails."""
    pass


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class UnsplashConfig:
    """
    Configuration for Unsplash provider.

    Attributes:
        access_key: Unsplash API access key.
        default_query: Default search query when none specified.
        default_size: Default image size to retrieve.
        enable_cache: Whether to cache search results.
        cache_ttl: Cache time-to-live in seconds.
        use_placeholder_on_error: Whether to return placeholder on errors.
    """

    access_key: str
    default_query: str = "business"
    default_size: ImageSize = DEFAULT_IMAGE_SIZE
    enable_cache: bool = True
    cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS
    use_placeholder_on_error: bool = True

    def __post_init__(self):
        """Validate configuration."""
        if not self.access_key:
            raise ValueError("Unsplash access key is required")

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "default_query": self.default_query,
            "default_size": self.default_size.value,
            "enable_cache": self.enable_cache,
            "cache_ttl": self.cache_ttl,
            "use_placeholder_on_error": self.use_placeholder_on_error,
            # Never include access_key for security
        }


@dataclass
class ImageResult:
    """
    Result of an image search/fetch operation.

    Attributes:
        url: The image URL.
        width: Image width in pixels.
        height: Image height in pixels.
        alt_description: Alternative text description.
        photographer: Photographer name.
        photographer_url: Photographer's Unsplash profile URL.
        unsplash_url: Original Unsplash page URL.
        download_location: Download endpoint for tracking.
        is_placeholder: Whether this is a placeholder image.
    """

    url: str
    width: int = 0
    height: int = 0
    alt_description: Optional[str] = None
    photographer: Optional[str] = None
    photographer_url: Optional[str] = None
    unsplash_url: Optional[str] = None
    download_location: Optional[str] = None
    is_placeholder: bool = False

    @property
    def attribution(self) -> str:
        """Get attribution string per Unsplash guidelines."""
        if self.is_placeholder:
            return "Placeholder image"
        photographer = self.photographer or "Unknown"
        return f"Photo by {photographer} on Unsplash"

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "alt_description": self.alt_description,
            "photographer": self.photographer,
            "photographer_url": self.photographer_url,
            "unsplash_url": self.unsplash_url,
            "attribution": self.attribution,
            "is_placeholder": self.is_placeholder,
        }


@dataclass
class CacheEntry:
    """Cache entry for image results."""
    results: List[ImageResult]
    timestamp: float
    query: str


# =============================================================================
# UnsplashProvider Implementation
# =============================================================================


class UnsplashProvider:
    """
    Unsplash image provider for contextual image fetching.

    This provider fetches images from Unsplash based on contextual queries
    derived from DocType names, field names, or explicit search terms.

    Key Features:
    - Context-aware image selection
    - Request caching to minimize API calls
    - Rate limit handling
    - Placeholder fallback

    Attributes:
        config: The UnsplashConfig for this provider.

    Example:
        >>> config = UnsplashConfig(
        ...     access_key="your-key",
        ...     default_query="business"
        ... )
        >>> provider = UnsplashProvider(config)
        >>> result = provider.search_image("professional portrait")
        >>> print(result.url)
        "https://images.unsplash.com/..."
    """

    def __init__(self, config: UnsplashConfig):
        """
        Initialize the Unsplash provider.

        Args:
            config: The UnsplashConfig with provider settings.
        """
        self._config = config
        self._client: Optional[Any] = None
        self._initialized: bool = False

        # Cache for search results
        self._cache: Dict[str, CacheEntry] = {}

        # Rate limiting
        self._request_timestamps: List[float] = []

        # Index for rotating through cached results
        self._result_index: Dict[str, int] = {}

    @property
    def config(self) -> UnsplashConfig:
        """Get the provider configuration."""
        return self._config

    @property
    def is_initialized(self) -> bool:
        """Check if the provider is initialized."""
        return self._initialized

    def initialize(self) -> None:
        """
        Initialize the Unsplash client.

        This method imports pyunsplash and creates a client instance.

        Raises:
            ImportError: If pyunsplash package is not installed.
            UnsplashProviderError: If initialization fails.
        """
        if self._initialized:
            return

        try:
            from pyunsplash import PyUnsplash
        except ImportError as e:
            raise ImportError(
                "The pyunsplash package is required for Unsplash provider. "
                "Install it with: pip install pyunsplash"
            ) from e

        try:
            self._client = PyUnsplash(api_key=self._config.access_key)
            self._initialized = True
        except Exception as e:
            raise UnsplashProviderError(
                f"Failed to initialize Unsplash client: {e}",
                original_error=e,
            )

    def search_image(
        self,
        query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        size: Optional[ImageSize] = None,
    ) -> ImageResult:
        """
        Search for an image based on query and context.

        Args:
            query: The search query. If not provided, derived from context.
            context: Optional context dictionary with:
                     - doctype: The DocType name (e.g., "Employee")
                     - fieldname: The field name (e.g., "image")
                     - category: Category for filtering (e.g., "Electronics")
            size: The image size to retrieve.

        Returns:
            ImageResult with the image URL and metadata.

        Raises:
            UnsplashSearchError: If search fails and placeholders disabled.
            UnsplashRateLimitError: If rate limit exceeded and no fallback.

        Example:
            >>> result = provider.search_image(
            ...     query="modern office",
            ...     context={"doctype": "Company"}
            ... )
            >>> print(result.url)
        """
        # Determine the search query
        effective_query = self._determine_query(query, context)

        # Check rate limits
        if not self._check_rate_limit():
            if self._config.use_placeholder_on_error:
                return self._create_placeholder(effective_query)
            raise UnsplashRateLimitError(
                f"Unsplash rate limit exceeded ({MAX_REQUESTS_PER_HOUR}/hour)"
            )

        # Check cache first
        cache_key = self._make_cache_key(effective_query)
        if self._config.enable_cache:
            cached = self._get_from_cache(cache_key)
            if cached:
                return self._get_next_result(cache_key, cached)

        # Initialize client if needed
        if not self._initialized:
            try:
                self.initialize()
            except ImportError:
                if self._config.use_placeholder_on_error:
                    return self._create_placeholder(effective_query)
                raise

        # Perform the search
        try:
            results = self._perform_search(effective_query, size)

            if results:
                # Cache the results
                if self._config.enable_cache:
                    self._add_to_cache(cache_key, results, effective_query)

                return self._get_next_result(cache_key, results)
            else:
                # No results found
                if self._config.use_placeholder_on_error:
                    return self._create_placeholder(effective_query)
                raise UnsplashSearchError(
                    f"No images found for query: {effective_query}"
                )

        except UnsplashProviderError:
            raise
        except Exception as e:
            if self._config.use_placeholder_on_error:
                return self._create_placeholder(effective_query)
            raise UnsplashSearchError(
                f"Image search failed: {e}",
                original_error=e,
            )

    def get_random_image(
        self,
        query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        size: Optional[ImageSize] = None,
    ) -> ImageResult:
        """
        Get a random image matching the query.

        This is an alias for search_image that emphasizes random selection
        from the search results.

        Args:
            query: The search query.
            context: Optional context dictionary.
            size: The image size to retrieve.

        Returns:
            ImageResult with the image URL and metadata.
        """
        return self.search_image(query, context, size)

    def get_image_url(
        self,
        query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Get just the image URL (convenience method).

        Args:
            query: The search query.
            context: Optional context dictionary.

        Returns:
            The image URL string.
        """
        result = self.search_image(query, context)
        return result.url

    def _determine_query(
        self,
        query: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> str:
        """
        Determine the effective search query.

        Args:
            query: Explicit query if provided.
            context: Context dictionary for deriving query.

        Returns:
            The effective search query string.
        """
        # Use explicit query if provided
        if query:
            return query

        # Try to derive query from context
        if context:
            # Check for explicit category
            if context.get("category"):
                return str(context["category"])

            # Check for doctype-based query
            doctype = context.get("doctype", "").lower().replace(" ", "_")
            if doctype in DEFAULT_CONTEXT_QUERIES:
                return DEFAULT_CONTEXT_QUERIES[doctype]

            # Check for fieldname-based query
            fieldname = context.get("fieldname", "").lower()
            if "logo" in fieldname:
                return DEFAULT_CONTEXT_QUERIES.get("company_logo", "logo")
            if "profile" in fieldname or "avatar" in fieldname:
                return "professional portrait"
            if "product" in fieldname or "item" in fieldname:
                return "product photography"
            if "banner" in fieldname or "cover" in fieldname:
                return "abstract background"

            # Use doctype name as query
            if doctype:
                return doctype.replace("_", " ")

        # Fall back to default query
        return self._config.default_query

    def _perform_search(
        self,
        query: str,
        size: Optional[ImageSize] = None,
    ) -> List[ImageResult]:
        """
        Perform the actual Unsplash API search.

        Args:
            query: The search query.
            size: The image size to retrieve.

        Returns:
            List of ImageResult objects.
        """
        # Record the request for rate limiting
        self._record_request()

        effective_size = size or self._config.default_size

        # Perform the search
        search = self._client.search(type_="photos", query=query)

        results = []
        for photo in search.entries:
            # Get the photo URLs
            urls = photo.body.get("urls", {})
            url = urls.get(effective_size.value, urls.get("regular", ""))

            if not url:
                continue

            # Extract photo metadata
            user = photo.body.get("user", {})
            links = photo.body.get("links", {})

            result = ImageResult(
                url=url,
                width=photo.body.get("width", 0),
                height=photo.body.get("height", 0),
                alt_description=photo.body.get("alt_description"),
                photographer=user.get("name"),
                photographer_url=user.get("links", {}).get("html"),
                unsplash_url=links.get("html"),
                download_location=links.get("download_location"),
                is_placeholder=False,
            )
            results.append(result)

            # Limit results to avoid excessive memory usage
            if len(results) >= 30:
                break

        return results

    def _check_rate_limit(self) -> bool:
        """
        Check if we're within rate limits.

        Returns:
            True if request is allowed, False otherwise.
        """
        current_time = time.time()
        cutoff_time = current_time - RATE_LIMIT_WINDOW_SECONDS

        # Remove old timestamps
        self._request_timestamps = [
            ts for ts in self._request_timestamps if ts > cutoff_time
        ]

        # Check if we're under the limit
        return len(self._request_timestamps) < MAX_REQUESTS_PER_HOUR

    def _record_request(self) -> None:
        """Record a request timestamp for rate limiting."""
        self._request_timestamps.append(time.time())

    def _make_cache_key(self, query: str) -> str:
        """Create a cache key from query."""
        return hashlib.md5(query.lower().encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[List[ImageResult]]:
        """
        Get results from cache if still valid.

        Args:
            cache_key: The cache key.

        Returns:
            Cached results if valid, None otherwise.
        """
        if cache_key not in self._cache:
            return None

        entry = self._cache[cache_key]
        current_time = time.time()

        # Check if cache entry has expired
        if current_time - entry.timestamp > self._config.cache_ttl:
            del self._cache[cache_key]
            if cache_key in self._result_index:
                del self._result_index[cache_key]
            return None

        return entry.results

    def _add_to_cache(
        self,
        cache_key: str,
        results: List[ImageResult],
        query: str,
    ) -> None:
        """
        Add results to cache.

        Args:
            cache_key: The cache key.
            results: The results to cache.
            query: The original query.
        """
        # Enforce cache size limit
        if len(self._cache) >= MAX_CACHE_SIZE:
            # Remove oldest entry
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].timestamp
            )
            del self._cache[oldest_key]
            if oldest_key in self._result_index:
                del self._result_index[oldest_key]

        self._cache[cache_key] = CacheEntry(
            results=results,
            timestamp=time.time(),
            query=query,
        )

    def _get_next_result(
        self,
        cache_key: str,
        results: List[ImageResult],
    ) -> ImageResult:
        """
        Get the next result in rotation.

        This ensures different images are returned for successive calls
        with the same query.

        Args:
            cache_key: The cache key.
            results: The list of results.

        Returns:
            The next ImageResult in rotation.
        """
        if not results:
            return self._create_placeholder("unknown")

        # Get current index for this query
        current_index = self._result_index.get(cache_key, 0)

        # Get the result at current index
        result = results[current_index % len(results)]

        # Increment index for next call
        self._result_index[cache_key] = current_index + 1

        return result

    def _create_placeholder(self, query: str) -> ImageResult:
        """
        Create a placeholder image result.

        Args:
            query: The query to use in placeholder text.

        Returns:
            ImageResult for placeholder image.
        """
        # Sanitize query for URL
        text = query.replace(" ", "+")[:50]

        url = PLACEHOLDER_URL_TEMPLATE.format(
            width=DEFAULT_PLACEHOLDER_WIDTH,
            height=DEFAULT_PLACEHOLDER_HEIGHT,
            text=text,
        )

        return ImageResult(
            url=url,
            width=DEFAULT_PLACEHOLDER_WIDTH,
            height=DEFAULT_PLACEHOLDER_HEIGHT,
            alt_description=f"Placeholder for: {query}",
            is_placeholder=True,
        )

    def test_connection(self) -> bool:
        """
        Test the connection to Unsplash API.

        Returns:
            True if connection is successful.

        Raises:
            UnsplashConnectionError: If connection test fails.
        """
        if not self._initialized:
            self.initialize()

        try:
            # Perform a simple search to test the connection
            search = self._client.search(type_="photos", query="test")

            # Just check if we can iterate (don't consume results)
            for _ in search.entries:
                return True
                break

            # Even empty results mean connection worked
            return True

        except Exception as e:
            raise UnsplashConnectionError(
                f"Unsplash connection test failed: {e}",
                original_error=e,
            )

    def clear_cache(self) -> None:
        """Clear all cached results."""
        self._cache.clear()
        self._result_index.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics.
        """
        return {
            "cached_queries": len(self._cache),
            "max_cache_size": MAX_CACHE_SIZE,
            "cache_ttl_seconds": self._config.cache_ttl,
            "requests_in_window": len(self._request_timestamps),
            "rate_limit_remaining": MAX_REQUESTS_PER_HOUR - len(self._request_timestamps),
        }

    def __repr__(self) -> str:
        """String representation of the provider."""
        return (
            f"UnsplashProvider("
            f"default_query='{self._config.default_query}', "
            f"cache_enabled={self._config.enable_cache}, "
            f"initialized={self._initialized})"
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_unsplash_provider(
    access_key: str,
    default_query: str = "business",
    default_size: ImageSize = DEFAULT_IMAGE_SIZE,
    enable_cache: bool = True,
) -> UnsplashProvider:
    """
    Factory function to create an UnsplashProvider instance.

    This is a convenience function for quickly creating an Unsplash provider
    without manually building the UnsplashConfig.

    Args:
        access_key: The Unsplash API access key.
        default_query: Default search query (default: "business").
        default_size: Default image size (default: regular).
        enable_cache: Whether to enable result caching (default: True).

    Returns:
        Configured UnsplashProvider instance.

    Example:
        >>> provider = create_unsplash_provider(
        ...     access_key="your-key",
        ...     default_query="office"
        ... )
        >>> result = provider.search_image("workspace")
    """
    config = UnsplashConfig(
        access_key=access_key,
        default_query=default_query,
        default_size=default_size,
        enable_cache=enable_cache,
    )
    return UnsplashProvider(config)


def get_unsplash_provider() -> Optional[UnsplashProvider]:
    """
    Get an Unsplash provider configured from Mock Engine Settings.

    This function reads the Unsplash settings from the Mock Engine Settings
    DocType and creates a configured provider.

    Returns:
        Configured UnsplashProvider, or None if not configured.

    Example:
        >>> provider = get_unsplash_provider()
        >>> if provider:
        ...     result = provider.search_image("office")
    """
    try:
        # Try to import frappe
        try:
            import frappe
        except ImportError:
            return None

        settings = frappe.get_single("Mock Engine Settings")

        # Check if Unsplash is configured
        access_key = settings.get_password("unsplash_access_key") if hasattr(settings, "unsplash_access_key") else None
        if not access_key:
            return None

        # Get default query
        default_query = getattr(settings, "unsplash_default_query", "business") or "business"

        config = UnsplashConfig(
            access_key=access_key,
            default_query=default_query,
        )

        return UnsplashProvider(config)

    except Exception:
        return None


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Provider class
    "UnsplashProvider",
    # Configuration
    "UnsplashConfig",
    "ImageResult",
    "ImageSize",
    # Exceptions
    "UnsplashProviderError",
    "UnsplashConnectionError",
    "UnsplashRateLimitError",
    "UnsplashSearchError",
    # Factory functions
    "create_unsplash_provider",
    "get_unsplash_provider",
    # Constants
    "DEFAULT_CONTEXT_QUERIES",
    "DEFAULT_IMAGE_SIZE",
]
