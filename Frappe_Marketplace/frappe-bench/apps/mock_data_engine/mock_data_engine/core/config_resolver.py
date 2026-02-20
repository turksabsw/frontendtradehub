# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Configuration Resolution Module.

This module provides the ConfigResolver class for implementing the 3-tier
configuration resolution pattern used throughout the Mock Data Engine:

    Request > Profile > Settings

Configuration priority (highest to lowest):
1. Request-level overrides (per-generation request)
2. Profile-level overrides (reusable presets)
3. Settings-level defaults (global configuration)

This ensures that specific request settings always take precedence over
profile defaults, which in turn take precedence over global settings.

Usage:
    # With just a request
    resolver = ConfigResolver(request=request_doc)
    locale = resolver.get_locale()  # Request.locale > Settings.default_locale

    # With request and profile
    resolver = ConfigResolver(request=request_doc, profile=profile_doc)
    locale = resolver.get_locale()  # Request.locale > Profile.locale > Settings.default_locale

    # Get all resolved configuration
    config = resolver.resolve_all()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class ResolvedConfig:
    """
    Container for fully resolved configuration values.

    This dataclass holds all configuration values after resolution
    through the 3-tier hierarchy (Request > Profile > Settings).

    Attributes:
        locale: The resolved locale (e.g., 'tr_TR', 'en_US')
        seed_value: Random seed for reproducibility
        batch_size: Number of records per batch
        record_count: Default number of records to generate
        auto_resolve_dependencies: Whether to auto-create linked documents
        fail_on_error: Whether to fail immediately on errors
        log_generation_details: Whether to log detailed generation info
        enable_ai_generation: Whether AI generation is enabled
        ai_provider: The primary AI provider to use
        ai_temperature: Temperature setting for AI generation
        unsplash_enabled: Whether Unsplash integration is enabled
        production_protection: Whether production protection is enabled
        excluded_apps: Set of app names to exclude from generation
        excluded_doctypes: Set of DocType names to exclude from generation
        field_overrides: Dict of field-specific overrides from profile
    """
    locale: str = "en_US"
    seed_value: Optional[int] = None
    batch_size: int = 100
    record_count: int = 10
    auto_resolve_dependencies: bool = True
    fail_on_error: bool = False
    log_generation_details: bool = True
    enable_ai_generation: bool = False
    ai_provider: Optional[str] = None
    ai_temperature: float = 0.7
    unsplash_enabled: bool = False
    production_protection: bool = True
    excluded_apps: Set[str] = field(default_factory=set)
    excluded_doctypes: Set[str] = field(default_factory=set)
    field_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def is_excluded_app(self, app_name: str) -> bool:
        """Check if an app is in the exclusion list."""
        return app_name in self.excluded_apps

    def is_excluded_doctype(self, doctype: str) -> bool:
        """Check if a DocType is in the exclusion list."""
        return doctype in self.excluded_doctypes

    def get_field_override(self, doctype: str, fieldname: str) -> Optional[Dict[str, Any]]:
        """
        Get field override configuration if available.

        Args:
            doctype: The target DocType name.
            fieldname: The field name.

        Returns:
            Override configuration dict if found, None otherwise.
        """
        key = f"{doctype}:{fieldname}"
        return self.field_overrides.get(key)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "locale": self.locale,
            "seed_value": self.seed_value,
            "batch_size": self.batch_size,
            "record_count": self.record_count,
            "auto_resolve_dependencies": self.auto_resolve_dependencies,
            "fail_on_error": self.fail_on_error,
            "log_generation_details": self.log_generation_details,
            "enable_ai_generation": self.enable_ai_generation,
            "ai_provider": self.ai_provider,
            "ai_temperature": self.ai_temperature,
            "unsplash_enabled": self.unsplash_enabled,
            "production_protection": self.production_protection,
            "excluded_apps": list(self.excluded_apps),
            "excluded_doctypes": list(self.excluded_doctypes),
            "field_overrides": self.field_overrides,
        }


class ConfigResolver:
    """
    3-tier configuration resolver for Mock Data Engine.

    This class resolves configuration values using the priority chain:
    Request > Profile > Settings

    The resolver lazily loads settings and caches them for efficiency
    during generation operations.

    Attributes:
        request: Optional Mock Generation Request document
        profile: Optional Mock Generation Profile document

    Example:
        >>> resolver = ConfigResolver(request=my_request)
        >>> locale = resolver.get_locale()
        >>> config = resolver.resolve_all()
    """

    def __init__(
        self,
        request: Optional[Any] = None,
        profile: Optional[Any] = None,
        settings: Optional[Any] = None
    ):
        """
        Initialize the ConfigResolver.

        Args:
            request: Optional Mock Generation Request document or dict
            profile: Optional Mock Generation Profile document or dict
            settings: Optional Mock Engine Settings document (for testing)
                     If not provided, will be loaded lazily.
        """
        self._request = request
        self._profile = profile
        self._settings = settings
        self._resolved: Optional[ResolvedConfig] = None

    @property
    def settings(self) -> Any:
        """
        Get Mock Engine Settings (lazy loaded and cached).

        Returns:
            Mock Engine Settings document.

        Raises:
            ImportError: If frappe is not available.
        """
        if self._settings is None:
            try:
                import frappe
                self._settings = frappe.get_single("Mock Engine Settings")
            except ImportError:
                raise ImportError(
                    "frappe module not available. "
                    "ConfigResolver requires Frappe Framework to be installed."
                )
        return self._settings

    @property
    def request(self) -> Optional[Any]:
        """Get the request document if available."""
        return self._request

    @property
    def profile(self) -> Optional[Any]:
        """
        Get the profile document (lazy loaded from request if needed).

        If a profile was not directly provided but the request has a
        profile reference, it will be loaded automatically.

        Returns:
            Mock Generation Profile document or None.
        """
        if self._profile is not None:
            return self._profile

        # Try to load profile from request
        if self._request is not None:
            profile_name = self._get_attr(self._request, "profile")
            if profile_name:
                try:
                    import frappe
                    self._profile = frappe.get_doc("Mock Generation Profile", profile_name)
                except Exception:
                    pass

        return self._profile

    def _get_attr(self, obj: Any, attr: str, default: Any = None) -> Any:
        """
        Get attribute from object or dict with fallback.

        Args:
            obj: Object or dict to get attribute from.
            attr: Attribute/key name.
            default: Default value if not found.

        Returns:
            The attribute value or default.
        """
        if obj is None:
            return default

        if isinstance(obj, dict):
            return obj.get(attr, default)

        return getattr(obj, attr, default)

    def _resolve_value(
        self,
        request_attr: str,
        profile_attr: Optional[str] = None,
        settings_attr: Optional[str] = None,
        default: Any = None
    ) -> Any:
        """
        Resolve a configuration value through the 3-tier hierarchy.

        Args:
            request_attr: Attribute name on the request document.
            profile_attr: Attribute name on the profile document (defaults to request_attr).
            settings_attr: Attribute name on the settings document (defaults to request_attr).
            default: Default value if not found in any tier.

        Returns:
            The resolved value from the highest priority source.
        """
        profile_attr = profile_attr or request_attr
        settings_attr = settings_attr or request_attr

        # Tier 1: Request (highest priority)
        if self._request is not None:
            value = self._get_attr(self._request, request_attr)
            if value is not None and value != "":
                return value

        # Tier 2: Profile
        if self.profile is not None:
            value = self._get_attr(self.profile, profile_attr)
            if value is not None and value != "":
                return value

        # Tier 3: Settings (lowest priority)
        try:
            value = self._get_attr(self.settings, settings_attr)
            if value is not None and value != "":
                return value
        except ImportError:
            pass

        return default

    def get_locale(self) -> str:
        """
        Get the resolved locale.

        Priority: Request.locale > Profile.locale > Settings.default_locale

        Returns:
            The locale string (e.g., 'tr_TR', 'en_US').
        """
        return self._resolve_value(
            request_attr="locale",
            profile_attr="locale",
            settings_attr="default_locale",
            default="en_US"
        )

    def get_seed_value(self) -> Optional[int]:
        """
        Get the resolved seed value for reproducibility.

        Priority: Request.seed_value > Profile.seed_value > Settings.seed_value

        Returns:
            The seed value or None if not set.
        """
        value = self._resolve_value(
            request_attr="seed_value",
            profile_attr="seed_value",
            settings_attr="seed_value",
            default=None
        )
        return int(value) if value is not None else None

    def get_batch_size(self) -> int:
        """
        Get the resolved batch size.

        Priority: Settings.default_batch_size (batch size is typically global)

        Returns:
            The batch size for bulk operations.
        """
        value = self._get_attr(self.settings, "default_batch_size")
        return int(value) if value else 100

    def get_record_count(self) -> int:
        """
        Get the default record count.

        Priority: Request.record_count > Settings.default_record_count

        Returns:
            The default number of records to generate.
        """
        value = self._resolve_value(
            request_attr="record_count",
            profile_attr=None,  # Profile uses doctype_quantities instead
            settings_attr="default_record_count",
            default=10
        )
        return int(value) if value else 10

    def get_auto_resolve_dependencies(self) -> bool:
        """
        Get whether to auto-resolve dependencies.

        Priority: Request > Profile > Settings

        Returns:
            True if dependencies should be auto-resolved.
        """
        return bool(self._resolve_value(
            request_attr="auto_resolve_dependencies",
            profile_attr="auto_resolve_dependencies",
            settings_attr="auto_resolve_dependencies",
            default=True
        ))

    def get_fail_on_error(self) -> bool:
        """
        Get whether to fail immediately on errors.

        Priority: Request > Profile > Settings

        Returns:
            True if generation should fail on first error.
        """
        return bool(self._resolve_value(
            request_attr="fail_on_error",
            profile_attr="fail_on_error",
            settings_attr="fail_on_error",
            default=False
        ))

    def get_log_generation_details(self) -> bool:
        """
        Get whether to log detailed generation information.

        Priority: Request > Profile > Settings

        Returns:
            True if detailed logging is enabled.
        """
        return bool(self._resolve_value(
            request_attr="log_generation_details",
            profile_attr="log_generation_details",
            settings_attr="log_generation_details",
            default=True
        ))

    def get_enable_ai_generation(self) -> bool:
        """
        Get whether AI generation is enabled.

        Priority: Profile.use_ai_generation > Settings.enable_ai_generation

        Returns:
            True if AI generation is enabled.
        """
        # Check profile first
        if self.profile is not None:
            value = self._get_attr(self.profile, "use_ai_generation")
            if value is not None:
                return bool(value)

        # Fall back to settings
        return bool(self._get_attr(self.settings, "enable_ai_generation", False))

    def get_ai_provider(self) -> Optional[str]:
        """
        Get the primary AI provider to use.

        Priority: Profile.ai_provider_override > Settings.primary_llm_provider

        Returns:
            The AI provider name (Gemini, OpenAI, Anthropic, Ollama) or None.
        """
        # Check profile override
        if self.profile is not None:
            value = self._get_attr(self.profile, "ai_provider_override")
            if value:
                return value

        # Fall back to settings
        return self._get_attr(self.settings, "primary_llm_provider")

    def get_ai_temperature(self) -> float:
        """
        Get the AI temperature setting.

        Priority: Profile.ai_temperature > Default (0.7)

        Returns:
            The temperature value for AI generation (0-2).
        """
        if self.profile is not None:
            value = self._get_attr(self.profile, "ai_temperature")
            if value is not None:
                return float(value)

        return 0.7  # Default temperature

    def get_unsplash_enabled(self) -> bool:
        """
        Get whether Unsplash integration is enabled.

        Returns:
            True if Unsplash is configured and enabled.
        """
        return bool(self._get_attr(self.settings, "unsplash_access_key"))

    def get_production_protection(self) -> bool:
        """
        Get whether production protection is enabled.

        Returns:
            True if production protection is enabled.
        """
        return bool(self._get_attr(self.settings, "production_protection", True))

    def get_excluded_apps(self) -> Set[str]:
        """
        Get the set of excluded app names.

        Returns:
            Set of app names to exclude from generation.
        """
        excluded = set()

        try:
            excluded_apps = self._get_attr(self.settings, "excluded_apps") or []
            for row in excluded_apps:
                app_name = self._get_attr(row, "app_name")
                if app_name:
                    excluded.add(app_name)
        except Exception:
            pass

        return excluded

    def get_excluded_doctypes(self) -> Set[str]:
        """
        Get the set of excluded DocType names.

        Returns:
            Set of DocType names to exclude from generation.
        """
        excluded = set()

        try:
            excluded_doctypes = self._get_attr(self.settings, "excluded_doctypes") or []
            for row in excluded_doctypes:
                doctype_name = self._get_attr(row, "doctype_name")
                if doctype_name:
                    excluded.add(doctype_name)
        except Exception:
            pass

        return excluded

    def get_field_overrides(self) -> Dict[str, Dict[str, Any]]:
        """
        Get field override configurations from the profile.

        Returns:
            Dict mapping 'DocType:fieldname' to override config.
        """
        overrides = {}

        if self.profile is None:
            return overrides

        field_overrides = self._get_attr(self.profile, "field_overrides") or []

        for row in field_overrides:
            target_doctype = self._get_attr(row, "target_doctype")
            fieldname = self._get_attr(row, "fieldname")

            if target_doctype and fieldname:
                key = f"{target_doctype}:{fieldname}"
                overrides[key] = {
                    "generator_type": self._get_attr(row, "generator_type"),
                    "fixed_value": self._get_attr(row, "fixed_value"),
                    "faker_provider": self._get_attr(row, "faker_provider"),
                    "faker_method": self._get_attr(row, "faker_method"),
                    "custom_options": self._get_attr(row, "custom_options"),
                    "min_value": self._get_attr(row, "min_value"),
                    "max_value": self._get_attr(row, "max_value"),
                    "skip_field": self._get_attr(row, "skip_field"),
                }

        return overrides

    def get_field_override(self, doctype: str, fieldname: str) -> Optional[Dict[str, Any]]:
        """
        Get field override for a specific DocType and field.

        Args:
            doctype: The target DocType name.
            fieldname: The field name.

        Returns:
            Override configuration dict if found, None otherwise.
        """
        overrides = self.get_field_overrides()
        return overrides.get(f"{doctype}:{fieldname}")

    def get_target_doctypes(self) -> List[Dict[str, Any]]:
        """
        Get the target DocTypes and their record counts.

        Returns:
            List of dicts with 'doctype' and 'record_count' keys.
        """
        if self._request is None:
            return []

        generation_mode = self._get_attr(self._request, "generation_mode")

        if generation_mode == "Single DocType":
            target_doctype = self._get_attr(self._request, "target_doctype")
            record_count = self._get_attr(self._request, "record_count") or self.get_record_count()

            if target_doctype:
                return [{
                    "doctype": target_doctype,
                    "record_count": record_count
                }]

        elif generation_mode == "Multiple DocTypes":
            selected = self._get_attr(self._request, "selected_doctypes") or []
            return [
                {
                    "doctype": self._get_attr(row, "doctype_name"),
                    "record_count": self._get_attr(row, "record_count") or self.get_record_count()
                }
                for row in selected
                if self._get_attr(row, "doctype_name")
            ]

        elif generation_mode == "From Profile" and self.profile is not None:
            # Delegate to profile's get_target_doctypes method if available
            if hasattr(self.profile, "get_target_doctypes"):
                return self.profile.get_target_doctypes()

            # Manual extraction from profile
            quantities = self._get_attr(self.profile, "doctype_quantities") or []
            return [
                {
                    "doctype": self._get_attr(row, "doctype_name"),
                    "record_count": self._get_attr(row, "record_count") or self.get_record_count()
                }
                for row in quantities
                if self._get_attr(row, "doctype_name")
            ]

        return []

    def is_excluded(self, doctype: str) -> bool:
        """
        Check if a DocType should be excluded from generation.

        Args:
            doctype: The DocType name to check.

        Returns:
            True if the DocType should be excluded.
        """
        return doctype in self.get_excluded_doctypes()

    def resolve_all(self) -> ResolvedConfig:
        """
        Resolve all configuration values and return as ResolvedConfig.

        This method caches the result for efficiency. Call invalidate_cache()
        to force re-resolution.

        Returns:
            ResolvedConfig with all values resolved through the 3-tier hierarchy.
        """
        if self._resolved is not None:
            return self._resolved

        self._resolved = ResolvedConfig(
            locale=self.get_locale(),
            seed_value=self.get_seed_value(),
            batch_size=self.get_batch_size(),
            record_count=self.get_record_count(),
            auto_resolve_dependencies=self.get_auto_resolve_dependencies(),
            fail_on_error=self.get_fail_on_error(),
            log_generation_details=self.get_log_generation_details(),
            enable_ai_generation=self.get_enable_ai_generation(),
            ai_provider=self.get_ai_provider(),
            ai_temperature=self.get_ai_temperature(),
            unsplash_enabled=self.get_unsplash_enabled(),
            production_protection=self.get_production_protection(),
            excluded_apps=self.get_excluded_apps(),
            excluded_doctypes=self.get_excluded_doctypes(),
            field_overrides=self.get_field_overrides(),
        )

        return self._resolved

    def invalidate_cache(self) -> None:
        """
        Invalidate the cached configuration.

        Call this if the underlying documents have changed and you need
        to re-resolve the configuration.
        """
        self._resolved = None
        self._settings = None
        self._profile = None

    def __repr__(self) -> str:
        """String representation of ConfigResolver."""
        request_name = self._get_attr(self._request, "name") if self._request else None
        profile_name = self._get_attr(self._profile, "name") if self._profile else None
        return f"ConfigResolver(request='{request_name}', profile='{profile_name}')"


def create_resolver_for_request(request_name: str) -> ConfigResolver:
    """
    Factory function to create a ConfigResolver for a request by name.

    Args:
        request_name: The name of the Mock Generation Request document.

    Returns:
        ConfigResolver instance for the request.

    Raises:
        ImportError: If frappe is not available.
        Exception: If request does not exist.

    Example:
        >>> resolver = create_resolver_for_request("MGR-2024-00001")
        >>> config = resolver.resolve_all()
    """
    try:
        import frappe
        request = frappe.get_doc("Mock Generation Request", request_name)
        return ConfigResolver(request=request)
    except ImportError:
        raise ImportError(
            "frappe module not available. "
            "create_resolver_for_request requires Frappe Framework."
        )


def create_resolver_for_profile(profile_name: str) -> ConfigResolver:
    """
    Factory function to create a ConfigResolver for a profile by name.

    This is useful for previewing what configuration a profile would use
    without having a specific request.

    Args:
        profile_name: The name of the Mock Generation Profile document.

    Returns:
        ConfigResolver instance for the profile.

    Raises:
        ImportError: If frappe is not available.
        Exception: If profile does not exist.

    Example:
        >>> resolver = create_resolver_for_profile("Default Turkish Profile")
        >>> config = resolver.resolve_all()
    """
    try:
        import frappe
        profile = frappe.get_doc("Mock Generation Profile", profile_name)
        return ConfigResolver(profile=profile)
    except ImportError:
        raise ImportError(
            "frappe module not available. "
            "create_resolver_for_profile requires Frappe Framework."
        )
