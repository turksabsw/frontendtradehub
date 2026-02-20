# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Environment Validation Module for Mock Data Engine.

This module provides production environment protection to prevent accidental
mock data generation in production environments. This is a CRITICAL safety
feature that helps prevent data pollution in live systems.

Key Features:
- Automatic detection of production environments via multiple indicators
- Integration with Mock Engine Settings for protection toggle
- Clear error messages explaining why generation was blocked
- Support for manual override in testing scenarios

Usage:
    from mock_data_engine.utils.environment import validate_environment

    # Before any generation operation
    validate_environment()  # Raises ProductionEnvironmentError if blocked

    # Check environment without raising
    if is_production_environment():
        print("Running in production!")

IMPORTANT: Never disable production protection in actual production environments.
This safety feature exists to protect your data from accidental corruption.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ProductionEnvironmentError(Exception):
    """
    Exception raised when attempting to generate mock data in a production environment.

    This exception is raised by validate_environment() when production protection
    is enabled and a production environment is detected.

    Attributes:
        message: Explanation of why generation was blocked
        indicators: List of production indicators that were detected
        environment_info: Dictionary with environment details

    Example:
        >>> try:
        ...     validate_environment()
        ... except ProductionEnvironmentError as e:
        ...     print(f"Blocked: {e.message}")
        ...     print(f"Indicators: {e.indicators}")
    """

    def __init__(
        self,
        message: str,
        indicators: Optional[List[str]] = None,
        environment_info: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize ProductionEnvironmentError.

        Args:
            message: Human-readable explanation of why generation was blocked.
            indicators: List of production indicators that triggered the block.
            environment_info: Additional environment details for debugging.
        """
        self.message = message
        self.indicators = indicators or []
        self.environment_info = environment_info or {}
        super().__init__(message)

    def __str__(self) -> str:
        """Return formatted error message."""
        parts = [self.message]
        if self.indicators:
            parts.append(f"Detected indicators: {', '.join(self.indicators)}")
        return " | ".join(parts)


@dataclass
class EnvironmentInfo:
    """
    Container for environment information.

    Attributes:
        site_name: The current Frappe site name
        developer_mode: Whether developer mode is enabled
        maintenance_mode: Whether maintenance mode is enabled
        production_indicators: List of detected production indicators
        is_production: Final determination if this is a production environment
        environment_variables: Relevant environment variables
    """
    site_name: Optional[str] = None
    developer_mode: bool = False
    maintenance_mode: bool = False
    production_indicators: List[str] = field(default_factory=list)
    is_production: bool = False
    environment_variables: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "site_name": self.site_name,
            "developer_mode": self.developer_mode,
            "maintenance_mode": self.maintenance_mode,
            "production_indicators": self.production_indicators,
            "is_production": self.is_production,
            "environment_variables": self.environment_variables,
        }


# Production site name patterns to detect
PRODUCTION_SITE_PATTERNS = [
    r"^prod",           # prod, production, prod-site
    r"prod$",           # my-prod
    r"production",      # production.example.com
    r"live",            # live, live-site
    r"\.com$",          # example.com (production domains)
    r"\.net$",          # example.net
    r"\.org$",          # example.org
    r"\.io$",           # example.io
    r"erp\.",           # erp.example.com
    r"app\.",           # app.example.com
]

# Development/test site name patterns (these are SAFE)
SAFE_SITE_PATTERNS = [
    r"^dev",            # dev, development, dev-site
    r"^test",           # test, testing, test-site
    r"^local",          # local, localhost
    r"^staging",        # staging
    r"\.local$",        # site.local
    r"\.localhost$",    # site.localhost
    r"\.test$",         # site.test
    r"\.dev$",          # site.dev
    r"\.example$",      # site.example
    r"bench",           # frappe-bench
]

# Environment variables that indicate production
PRODUCTION_ENV_VARS = [
    "PRODUCTION",
    "PROD",
    "IS_PRODUCTION",
    "FRAPPE_PRODUCTION",
    "ENVIRONMENT",
]


def _check_site_name(site_name: str) -> List[str]:
    """
    Check site name for production indicators.

    Args:
        site_name: The Frappe site name to check.

    Returns:
        List of production indicators found in the site name.
    """
    indicators = []
    site_lower = site_name.lower()

    # First check if it matches safe patterns
    for pattern in SAFE_SITE_PATTERNS:
        if re.search(pattern, site_lower):
            return []  # Safe site, no indicators

    # Check for production patterns
    for pattern in PRODUCTION_SITE_PATTERNS:
        if re.search(pattern, site_lower):
            indicators.append(f"site_name_matches:{pattern}")

    return indicators


def _check_environment_variables() -> tuple[List[str], Dict[str, str]]:
    """
    Check environment variables for production indicators.

    Returns:
        Tuple of (indicators list, env vars dict).
    """
    indicators = []
    env_vars = {}

    for var in PRODUCTION_ENV_VARS:
        value = os.environ.get(var, "").lower()
        if value:
            env_vars[var] = value
            if value in ("true", "1", "yes", "production", "prod"):
                indicators.append(f"env_var:{var}={value}")

    # Check for explicit environment indicator
    env_value = os.environ.get("ENVIRONMENT", "").lower()
    if env_value in ("production", "prod", "live"):
        if "ENVIRONMENT" not in env_vars:
            env_vars["ENVIRONMENT"] = env_value
        if f"env_var:ENVIRONMENT={env_value}" not in indicators:
            indicators.append(f"env_var:ENVIRONMENT={env_value}")

    return indicators, env_vars


def _check_frappe_flags() -> List[str]:
    """
    Check Frappe flags for production indicators.

    Returns:
        List of production indicators from Frappe flags.
    """
    indicators = []

    try:
        import frappe

        # Check developer mode (ABSENCE indicates production)
        if not getattr(frappe.conf, "developer_mode", False):
            indicators.append("developer_mode:disabled")

        # Check maintenance mode (often enabled for production deployments)
        if getattr(frappe.local, "flags", None):
            if getattr(frappe.local.flags, "in_install", False):
                # During installation is safe
                return []

    except ImportError:
        # If frappe is not available, we can't check flags
        pass

    return indicators


def _check_frappe_site_config() -> tuple[List[str], Optional[str], bool]:
    """
    Check Frappe site configuration for production indicators.

    Returns:
        Tuple of (indicators, site_name, developer_mode).
    """
    indicators = []
    site_name = None
    developer_mode = False

    try:
        import frappe

        # Get site name
        site_name = getattr(frappe.local, "site", None)

        # Check developer mode from config
        developer_mode = getattr(frappe.conf, "developer_mode", False)

        # Check for production-specific config flags
        if hasattr(frappe, "conf"):
            # serve_default_site typically set in production
            if getattr(frappe.conf, "serve_default_site", False):
                indicators.append("config:serve_default_site")

            # Background workers indicate production setup
            if getattr(frappe.conf, "background_workers", 0) > 0:
                indicators.append("config:background_workers")

            # Redis cache in production
            redis_cache = getattr(frappe.conf, "redis_cache", "")
            if redis_cache and "localhost" not in redis_cache and "127.0.0.1" not in redis_cache:
                indicators.append("config:external_redis")

    except ImportError:
        pass

    return indicators, site_name, developer_mode


def get_environment_info() -> EnvironmentInfo:
    """
    Gather comprehensive environment information.

    This function collects all available information about the current
    environment to determine if it's a production environment.

    Returns:
        EnvironmentInfo with all detected indicators and environment details.

    Example:
        >>> info = get_environment_info()
        >>> print(f"Production: {info.is_production}")
        >>> print(f"Indicators: {info.production_indicators}")
    """
    info = EnvironmentInfo()

    # Check environment variables
    env_indicators, env_vars = _check_environment_variables()
    info.production_indicators.extend(env_indicators)
    info.environment_variables = env_vars

    # Check Frappe configuration
    config_indicators, site_name, developer_mode = _check_frappe_site_config()
    info.production_indicators.extend(config_indicators)
    info.site_name = site_name
    info.developer_mode = developer_mode

    # Check Frappe flags
    flag_indicators = _check_frappe_flags()
    info.production_indicators.extend(flag_indicators)

    # Check site name patterns
    if site_name:
        site_indicators = _check_site_name(site_name)
        info.production_indicators.extend(site_indicators)

    # Final determination
    # It's production if:
    # 1. Developer mode is NOT enabled, OR
    # 2. Any production indicator is found
    info.is_production = (
        not developer_mode and len(info.production_indicators) > 0
    )

    return info


def is_production_environment() -> bool:
    """
    Check if the current environment is a production environment.

    This function uses multiple heuristics to detect production environments:
    - Developer mode status in Frappe configuration
    - Site name patterns (prod, production, live, etc.)
    - Environment variables (PRODUCTION, ENVIRONMENT=prod, etc.)
    - Frappe configuration flags

    Returns:
        True if production environment is detected, False otherwise.

    Example:
        >>> if is_production_environment():
        ...     print("WARNING: Running in production!")
    """
    info = get_environment_info()
    return info.is_production


def _get_production_protection_enabled() -> bool:
    """
    Get the production protection setting from Mock Engine Settings.

    Returns:
        True if production protection is enabled (default), False otherwise.
    """
    try:
        import frappe
        settings = frappe.get_single("Mock Engine Settings")
        # Default to True if not explicitly disabled
        return getattr(settings, "production_protection", True)
    except Exception:
        # If we can't read settings, default to enabled (safe default)
        return True


def validate_environment(
    allow_override: bool = False,
    raise_on_failure: bool = True
) -> bool:
    """
    Validate that the current environment is safe for mock data generation.

    This function is the main entry point for environment validation. It should
    be called before any mock data generation operation to ensure data safety.

    The validation process:
    1. Check if production protection is enabled in settings
    2. If enabled, detect production environment indicators
    3. Block generation if production indicators are found

    Args:
        allow_override: If True, skip validation (USE WITH EXTREME CAUTION).
                       This is only for testing and should never be used
                       in actual production code.
        raise_on_failure: If True (default), raise ProductionEnvironmentError
                         when blocked. If False, return False instead.

    Returns:
        True if environment is safe for generation.
        If raise_on_failure=False, returns False when blocked.

    Raises:
        ProductionEnvironmentError: When production protection blocks generation
                                   and raise_on_failure=True.

    Example:
        >>> # Standard usage - raises exception if blocked
        >>> validate_environment()
        True

        >>> # Check without raising
        >>> if not validate_environment(raise_on_failure=False):
        ...     print("Cannot generate - production environment detected")

    Warning:
        NEVER use allow_override=True in production code. It exists only
        for testing purposes and bypasses all safety checks.
    """
    # Allow override for testing (USE WITH EXTREME CAUTION)
    if allow_override:
        return True

    # Check if production protection is enabled
    if not _get_production_protection_enabled():
        return True

    # Get environment information
    info = get_environment_info()

    # If production indicators found, block generation
    if info.is_production:
        message = (
            "Mock data generation is blocked in production environments. "
            "This safety feature prevents accidental data pollution in live systems. "
            "To disable this protection, set 'production_protection' to False "
            "in Mock Engine Settings (NOT RECOMMENDED for production sites)."
        )

        if raise_on_failure:
            raise ProductionEnvironmentError(
                message=message,
                indicators=info.production_indicators,
                environment_info=info.to_dict()
            )
        return False

    return True


def check_environment_safety() -> Dict[str, Any]:
    """
    Perform a comprehensive environment safety check and return a report.

    This function is useful for diagnostics and displaying environment
    status in the UI.

    Returns:
        Dictionary with safety check results including:
        - safe: Boolean indicating if generation is safe
        - production_protection_enabled: Boolean from settings
        - is_production: Boolean indicating production detection
        - indicators: List of detected production indicators
        - site_name: Current site name
        - developer_mode: Whether developer mode is enabled
        - message: Human-readable status message

    Example:
        >>> result = check_environment_safety()
        >>> if result["safe"]:
        ...     print("Environment is safe for mock data generation")
        >>> else:
        ...     print(f"Blocked: {result['message']}")
    """
    info = get_environment_info()
    protection_enabled = _get_production_protection_enabled()

    # Determine safety status
    if not protection_enabled:
        safe = True
        message = "Production protection is disabled - generation allowed (USE WITH CAUTION)"
    elif info.is_production:
        safe = False
        message = (
            f"Production environment detected. "
            f"Indicators: {', '.join(info.production_indicators)}"
        )
    else:
        safe = True
        message = "Environment is safe for mock data generation"

    return {
        "safe": safe,
        "production_protection_enabled": protection_enabled,
        "is_production": info.is_production,
        "indicators": info.production_indicators,
        "site_name": info.site_name,
        "developer_mode": info.developer_mode,
        "environment_variables": info.environment_variables,
        "message": message,
    }
