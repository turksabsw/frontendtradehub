# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
AI Service Module for Mock Data Engine.

This module provides the abstract interface for LLM providers and the factory
pattern for creating and managing AI service instances. It serves as the
foundation for multi-LLM support (Gemini, OpenAI, Anthropic, Ollama).

Key Components:
- LLMProvider: Abstract base class for all LLM providers
- AIService: Service class for managing AI generation operations
- get_llm_provider(): Factory function for retrieving configured provider
- AIServiceConfig: Configuration dataclass for AI services

The design follows a strategy pattern where different LLM providers can be
swapped interchangeably while maintaining consistent interfaces.

Usage:
    from mock_data_engine.providers.ai_service import (
        AIService,
        LLMProvider,
        get_llm_provider,
        AIServiceConfig,
    )

    # Get the configured provider
    provider = get_llm_provider()

    # Generate content
    result = provider.generate(
        prompt="Generate a realistic Turkish company name",
        context={"locale": "tr_TR", "industry": "Technology"}
    )

Note:
    - Use temperature=0 for deterministic results as per specification
    - API keys are retrieved using get_password() for security
    - Fallback to Faker is handled if LLM fails
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, Union, TYPE_CHECKING

if TYPE_CHECKING:
    pass


class AIProviderType(Enum):
    """
    Enumeration of supported AI/LLM provider types.

    These are the providers supported by the Mock Data Engine
    for AI-powered content generation.
    """

    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"

    @classmethod
    def from_string(cls, value: str) -> "AIProviderType":
        """
        Convert a string to AIProviderType.

        Args:
            value: The string value to convert.

        Returns:
            The corresponding AIProviderType.

        Raises:
            ValueError: If the value is not a valid provider type.
        """
        value_lower = value.lower().strip()
        for provider in cls:
            if provider.value == value_lower:
                return provider
        raise ValueError(
            f"Unknown provider type: {value}. "
            f"Supported: {[p.value for p in cls]}"
        )


class AIProviderError(Exception):
    """
    Base exception for AI provider errors.

    Attributes:
        provider: The provider that raised the error.
        message: The error message.
        original_error: The underlying exception if any.
    """

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        """
        Initialize AIProviderError.

        Args:
            message: The error message.
            provider: The provider name.
            original_error: The underlying exception.
        """
        self.provider = provider
        self.message = message
        self.original_error = original_error

        full_message = message
        if provider:
            full_message = f"[{provider}] {message}"

        super().__init__(full_message)


class AIProviderNotConfiguredError(AIProviderError):
    """Raised when no AI provider is configured."""

    def __init__(self, message: str = "No AI provider configured"):
        super().__init__(message)


class AIProviderConnectionError(AIProviderError):
    """Raised when connection to AI provider fails."""

    pass


class AIProviderRateLimitError(AIProviderError):
    """Raised when AI provider rate limit is exceeded."""

    pass


class AIGenerationError(AIProviderError):
    """Raised when AI content generation fails."""

    pass


@dataclass
class AIServiceConfig:
    """
    Configuration for AI service.

    Holds all settings required for AI provider initialization
    and generation operations.

    Attributes:
        provider_type: The type of AI provider to use.
        api_key: The API key for the provider (required for cloud providers).
        model: The model to use for generation.
        temperature: The temperature for generation (0-2, default 0 for determinism).
        max_tokens: Maximum tokens in the response.
        timeout: Request timeout in seconds.
        retry_count: Number of retries on failure.
        base_url: Optional base URL for API endpoints (Ollama).
    """

    provider_type: AIProviderType
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: int = 30
    retry_count: int = 3
    base_url: Optional[str] = None

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Validate temperature range
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                f"Temperature must be between 0 and 2, got {self.temperature}"
            )

        # Validate max_tokens
        if self.max_tokens <= 0:
            raise ValueError(
                f"max_tokens must be positive, got {self.max_tokens}"
            )

        # Cloud providers require API key
        cloud_providers = {AIProviderType.GEMINI, AIProviderType.OPENAI, AIProviderType.ANTHROPIC}
        if self.provider_type in cloud_providers and not self.api_key:
            raise ValueError(
                f"{self.provider_type.value} provider requires an API key"
            )

    @property
    def default_model(self) -> str:
        """Get the default model for this provider type."""
        defaults = {
            AIProviderType.GEMINI: "gemini-2.0-flash",
            AIProviderType.OPENAI: "gpt-4o-mini",
            AIProviderType.ANTHROPIC: "claude-sonnet-4-5",
            AIProviderType.OLLAMA: "gemma3",
        }
        return self.model or defaults.get(self.provider_type, "")

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "provider_type": self.provider_type.value,
            "model": self.default_model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "base_url": self.base_url,
            # Never include API key in dict output for security
        }


@dataclass
class GenerationResult:
    """
    Result of an AI generation operation.

    Attributes:
        content: The generated content.
        provider: The provider that generated the content.
        model: The model used for generation.
        tokens_used: Number of tokens used (if available).
        finish_reason: The reason generation stopped.
        raw_response: The raw response from the provider.
    """

    content: str
    provider: str
    model: str
    tokens_used: Optional[int] = None
    finish_reason: Optional[str] = None
    raw_response: Optional[Any] = None

    @property
    def success(self) -> bool:
        """Check if generation was successful."""
        return bool(self.content)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "content": self.content,
            "provider": self.provider,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "finish_reason": self.finish_reason,
            "success": self.success,
        }


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All LLM provider implementations must inherit from this class
    and implement the required methods. This ensures consistent
    interfaces across different providers.

    The class provides:
    - Abstract generate() method for content generation
    - Connection testing via test_connection()
    - Configuration validation
    - Retry logic for transient failures

    Subclasses should implement:
    - generate(): Core generation logic
    - test_connection(): Verify API connectivity
    - _initialize_client(): Set up the provider client

    Example:
        class GeminiProvider(LLMProvider):
            def __init__(self, config: AIServiceConfig):
                super().__init__(config)

            def _initialize_client(self):
                from google import genai
                self._client = genai.Client(api_key=self.config.api_key)

            def generate(self, prompt: str, context: Optional[dict] = None) -> GenerationResult:
                response = self._client.models.generate_content(
                    model=self.config.default_model,
                    contents=prompt
                )
                return GenerationResult(
                    content=response.text,
                    provider="gemini",
                    model=self.config.default_model
                )

    Attributes:
        config: The AIServiceConfig for this provider.
        name: The name of the provider (for logging).
    """

    def __init__(self, config: AIServiceConfig):
        """
        Initialize the LLM provider.

        Args:
            config: The configuration for this provider.

        Raises:
            AIProviderError: If initialization fails.
        """
        self._config = config
        self._client: Optional[Any] = None
        self._initialized: bool = False

    @property
    def config(self) -> AIServiceConfig:
        """Get the provider configuration."""
        return self._config

    @property
    def name(self) -> str:
        """Get the provider name."""
        return self._config.provider_type.value

    @property
    def is_initialized(self) -> bool:
        """Check if the provider client is initialized."""
        return self._initialized

    def initialize(self) -> None:
        """
        Initialize the provider client.

        This method should be called before using the provider.
        It handles lazy initialization of the underlying client.

        Raises:
            AIProviderError: If initialization fails.
        """
        if not self._initialized:
            try:
                self._initialize_client()
                self._initialized = True
            except ImportError as e:
                raise AIProviderError(
                    f"Required package not installed: {e}",
                    provider=self.name,
                    original_error=e,
                )
            except Exception as e:
                raise AIProviderError(
                    f"Failed to initialize provider: {e}",
                    provider=self.name,
                    original_error=e,
                )

    @abstractmethod
    def _initialize_client(self) -> None:
        """
        Initialize the underlying client.

        Subclasses must implement this to set up their specific client.

        Raises:
            ImportError: If required packages are not installed.
            Exception: If client initialization fails.
        """
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Generate content using the LLM.

        This is the main generation method that subclasses must implement.
        It should handle the actual API call and response parsing.

        Args:
            prompt: The prompt for content generation.
            context: Optional context dictionary with additional information
                     like locale, field type, doctype, etc.

        Returns:
            GenerationResult with the generated content.

        Raises:
            AIGenerationError: If generation fails.
            AIProviderConnectionError: If connection to provider fails.
            AIProviderRateLimitError: If rate limit is exceeded.

        Example:
            result = provider.generate(
                prompt="Generate a Turkish company name",
                context={"locale": "tr_TR", "industry": "Technology"}
            )
            company_name = result.content
        """
        pass

    def generate_with_retry(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Generate content with retry logic.

        Wraps generate() with automatic retries on transient failures.

        Args:
            prompt: The prompt for content generation.
            context: Optional context dictionary.

        Returns:
            GenerationResult with the generated content.

        Raises:
            AIGenerationError: If all retries fail.
        """
        import time

        last_error: Optional[Exception] = None
        retry_count = self._config.retry_count

        for attempt in range(retry_count + 1):
            try:
                if not self._initialized:
                    self.initialize()
                return self.generate(prompt, context)
            except AIProviderRateLimitError as e:
                last_error = e
                if attempt < retry_count:
                    # Exponential backoff for rate limits
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
            except AIProviderConnectionError as e:
                last_error = e
                if attempt < retry_count:
                    time.sleep(1)
            except AIGenerationError:
                raise
            except Exception as e:
                last_error = e
                break

        raise AIGenerationError(
            f"Generation failed after {retry_count + 1} attempts: {last_error}",
            provider=self.name,
            original_error=last_error,
        )

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test the connection to the AI provider.

        This method should verify that the API key is valid and
        the provider is accessible.

        Returns:
            True if connection is successful, False otherwise.

        Raises:
            AIProviderConnectionError: If connection test fails with details.
        """
        pass

    def get_available_models(self) -> List[str]:
        """
        Get list of available models for this provider.

        Returns:
            List of model identifiers.

        Note:
            Subclasses can override this to provide dynamic model lists.
        """
        defaults = {
            AIProviderType.GEMINI: [
                "gemini-2.0-flash",
                "gemini-1.5-flash",
                "gemini-1.5-pro",
            ],
            AIProviderType.OPENAI: [
                "gpt-4o-mini",
                "gpt-4o",
                "gpt-4-turbo",
                "gpt-3.5-turbo",
            ],
            AIProviderType.ANTHROPIC: [
                "claude-sonnet-4-5",
                "claude-3-5-sonnet-20241022",
                "claude-3-opus-20240229",
                "claude-3-haiku-20240307",
            ],
            AIProviderType.OLLAMA: [
                "gemma3",
                "llama3",
                "mistral",
                "codellama",
            ],
        }
        return defaults.get(self._config.provider_type, [])

    def __repr__(self) -> str:
        """String representation of the provider."""
        return (
            f"{self.__class__.__name__}("
            f"provider={self.name}, "
            f"model={self._config.default_model}, "
            f"initialized={self._initialized})"
        )


class AIService:
    """
    Service class for managing AI generation operations.

    This class provides a high-level interface for AI content generation,
    handling provider management, fallback logic, and caching.

    Key Features:
    - Provider registration and selection
    - Fallback chain when primary provider fails
    - Response caching for efficiency
    - Batch generation support
    - Statistics tracking

    Usage:
        service = AIService()

        # Configure from Frappe settings
        service.configure_from_settings()

        # Generate content
        result = service.generate(
            prompt="Generate a product description",
            context={"locale": "tr_TR", "category": "Electronics"}
        )

    Attributes:
        provider: The current active LLM provider.
        fallback_providers: List of fallback providers.
        stats: Generation statistics.
    """

    # Registry of provider implementations
    _provider_registry: Dict[AIProviderType, Type[LLMProvider]] = {}

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        fallback_providers: Optional[List[LLMProvider]] = None,
    ):
        """
        Initialize the AI service.

        Args:
            provider: Optional primary LLM provider.
            fallback_providers: Optional list of fallback providers.
        """
        self._provider = provider
        self._fallback_providers = fallback_providers or []
        self._stats = GenerationStats()
        self._cache: Dict[str, GenerationResult] = {}
        self._cache_enabled = False

    @classmethod
    def register_provider(
        cls,
        provider_type: AIProviderType,
        provider_class: Type[LLMProvider],
    ) -> None:
        """
        Register a provider implementation.

        Args:
            provider_type: The provider type to register.
            provider_class: The provider class implementing LLMProvider.
        """
        cls._provider_registry[provider_type] = provider_class

    @classmethod
    def get_registered_providers(cls) -> Dict[AIProviderType, Type[LLMProvider]]:
        """Get all registered provider implementations."""
        return cls._provider_registry.copy()

    @property
    def provider(self) -> Optional[LLMProvider]:
        """Get the current provider."""
        return self._provider

    @property
    def has_provider(self) -> bool:
        """Check if a provider is configured."""
        return self._provider is not None

    @property
    def stats(self) -> "GenerationStats":
        """Get generation statistics."""
        return self._stats

    def set_provider(self, provider: LLMProvider) -> None:
        """
        Set the primary provider.

        Args:
            provider: The LLM provider to use.
        """
        self._provider = provider

    def add_fallback_provider(self, provider: LLMProvider) -> None:
        """
        Add a fallback provider.

        Args:
            provider: The fallback provider to add.
        """
        self._fallback_providers.append(provider)

    def enable_cache(self, enabled: bool = True) -> None:
        """
        Enable or disable response caching.

        Args:
            enabled: Whether to enable caching.
        """
        self._cache_enabled = enabled

    def clear_cache(self) -> None:
        """Clear the response cache."""
        self._cache.clear()

    def configure_from_settings(self) -> None:
        """
        Configure the service from Frappe Mock Engine Settings.

        This method reads the settings DocType and configures
        the appropriate provider based on available API keys.

        Raises:
            AIProviderNotConfiguredError: If no provider can be configured.
        """
        provider = get_llm_provider()
        if provider:
            self._provider = provider
        else:
            raise AIProviderNotConfiguredError(
                "No AI provider configured in Mock Engine Settings"
            )

    def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> GenerationResult:
        """
        Generate content using the configured provider.

        Args:
            prompt: The prompt for content generation.
            context: Optional context dictionary.
            use_cache: Whether to use cached results.

        Returns:
            GenerationResult with the generated content.

        Raises:
            AIProviderNotConfiguredError: If no provider is configured.
            AIGenerationError: If generation fails on all providers.
        """
        if not self._provider:
            raise AIProviderNotConfiguredError()

        # Check cache
        if use_cache and self._cache_enabled:
            cache_key = self._make_cache_key(prompt, context)
            if cache_key in self._cache:
                self._stats.cache_hits += 1
                return self._cache[cache_key]

        # Try primary provider
        providers_to_try = [self._provider] + self._fallback_providers
        last_error: Optional[Exception] = None

        for provider in providers_to_try:
            try:
                result = provider.generate_with_retry(prompt, context)
                self._stats.successful_generations += 1
                self._stats.total_tokens += result.tokens_used or 0

                # Cache result
                if use_cache and self._cache_enabled:
                    cache_key = self._make_cache_key(prompt, context)
                    self._cache[cache_key] = result

                return result
            except AIGenerationError as e:
                last_error = e
                self._stats.failed_generations += 1
                continue

        raise AIGenerationError(
            f"All providers failed. Last error: {last_error}",
            original_error=last_error,
        )

    def generate_batch(
        self,
        prompts: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[GenerationResult]:
        """
        Generate content for multiple prompts.

        Args:
            prompts: List of prompts for content generation.
            context: Optional shared context dictionary.

        Returns:
            List of GenerationResult objects.
        """
        results = []
        for prompt in prompts:
            try:
                result = self.generate(prompt, context)
                results.append(result)
            except AIGenerationError as e:
                # Create a failed result
                results.append(
                    GenerationResult(
                        content="",
                        provider="none",
                        model="",
                        finish_reason=f"error: {e}",
                    )
                )
        return results

    def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to all configured providers.

        Returns:
            Dictionary with connection test results.
        """
        results = {}

        if self._provider:
            try:
                success = self._provider.test_connection()
                results[self._provider.name] = {
                    "success": success,
                    "primary": True,
                }
            except Exception as e:
                results[self._provider.name] = {
                    "success": False,
                    "error": str(e),
                    "primary": True,
                }

        for provider in self._fallback_providers:
            try:
                success = provider.test_connection()
                results[provider.name] = {
                    "success": success,
                    "primary": False,
                }
            except Exception as e:
                results[provider.name] = {
                    "success": False,
                    "error": str(e),
                    "primary": False,
                }

        return results

    def _make_cache_key(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        """
        Create a cache key from prompt and context.

        Args:
            prompt: The generation prompt.
            context: The context dictionary.

        Returns:
            A unique cache key string.
        """
        import hashlib
        import json

        key_data = {
            "prompt": prompt,
            "context": context or {},
            "provider": self._provider.name if self._provider else "",
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get generation statistics.

        Returns:
            Dictionary with generation statistics.
        """
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        """Reset generation statistics."""
        self._stats = GenerationStats()


@dataclass
class GenerationStats:
    """
    Statistics for AI generation operations.

    Attributes:
        successful_generations: Number of successful generations.
        failed_generations: Number of failed generations.
        total_tokens: Total tokens used.
        cache_hits: Number of cache hits.
    """

    successful_generations: int = 0
    failed_generations: int = 0
    total_tokens: int = 0
    cache_hits: int = 0

    @property
    def total_generations(self) -> int:
        """Get total number of generations attempted."""
        return self.successful_generations + self.failed_generations

    @property
    def success_rate(self) -> float:
        """Get the success rate as a percentage."""
        if self.total_generations == 0:
            return 0.0
        return (self.successful_generations / self.total_generations) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "successful_generations": self.successful_generations,
            "failed_generations": self.failed_generations,
            "total_generations": self.total_generations,
            "success_rate": self.success_rate,
            "total_tokens": self.total_tokens,
            "cache_hits": self.cache_hits,
        }


# =============================================================================
# Factory Functions
# =============================================================================


def get_llm_provider(
    provider_type: Optional[AIProviderType] = None,
    config: Optional[AIServiceConfig] = None,
) -> Optional[LLMProvider]:
    """
    Factory function to get a configured LLM provider.

    This is the main entry point for obtaining an LLM provider instance.
    If no provider_type is specified, it reads the configuration from
    Mock Engine Settings and returns the first available provider.

    Provider priority order (when auto-selecting):
    1. Gemini (if API key configured)
    2. OpenAI (if API key configured)
    3. Anthropic (if API key configured)
    4. Ollama (if enabled)

    Args:
        provider_type: Optional specific provider type to use.
        config: Optional pre-built configuration.

    Returns:
        Configured LLMProvider instance, or None if no provider available.

    Raises:
        AIProviderError: If provider initialization fails.

    Example:
        # Auto-select from settings
        provider = get_llm_provider()

        # Specific provider
        provider = get_llm_provider(AIProviderType.GEMINI)

        # With custom config
        config = AIServiceConfig(
            provider_type=AIProviderType.OPENAI,
            api_key="sk-...",
            temperature=0.7
        )
        provider = get_llm_provider(config=config)
    """
    # If config provided, use it directly
    if config:
        return _create_provider_from_config(config)

    # If specific type requested, try to configure it from settings
    if provider_type:
        return _get_provider_for_type(provider_type)

    # Auto-select from Mock Engine Settings
    return _auto_select_provider()


def _auto_select_provider() -> Optional[LLMProvider]:
    """
    Auto-select a provider based on Mock Engine Settings.

    Returns:
        The first available configured provider, or None.
    """
    try:
        # Try to import frappe - if not available, return None
        try:
            import frappe
        except ImportError:
            return None

        settings = frappe.get_single("Mock Engine Settings")

        # Check if AI generation is enabled
        if not getattr(settings, "enable_ai_generation", False):
            return None

        # Try providers in priority order
        priority_order = [
            (AIProviderType.GEMINI, "gemini_api_key"),
            (AIProviderType.OPENAI, "openai_api_key"),
            (AIProviderType.ANTHROPIC, "anthropic_api_key"),
            (AIProviderType.OLLAMA, "ollama_enabled"),
        ]

        for provider_type, key_field in priority_order:
            if provider_type == AIProviderType.OLLAMA:
                if getattr(settings, key_field, False):
                    return _get_provider_for_type(provider_type, settings)
            else:
                api_key = settings.get_password(key_field) if hasattr(settings, key_field) else None
                if api_key:
                    return _get_provider_for_type(provider_type, settings)

        return None

    except Exception:
        return None


def _get_provider_for_type(
    provider_type: AIProviderType,
    settings: Optional[Any] = None,
) -> Optional[LLMProvider]:
    """
    Get a provider instance for a specific type.

    Args:
        provider_type: The provider type.
        settings: Optional pre-loaded settings document.

    Returns:
        Configured LLMProvider instance, or None.
    """
    try:
        try:
            import frappe
        except ImportError:
            return None

        if settings is None:
            settings = frappe.get_single("Mock Engine Settings")

        config = _build_config_from_settings(provider_type, settings)
        if config:
            return _create_provider_from_config(config)

        return None

    except Exception:
        return None


def _build_config_from_settings(
    provider_type: AIProviderType,
    settings: Any,
) -> Optional[AIServiceConfig]:
    """
    Build AIServiceConfig from Mock Engine Settings.

    Args:
        provider_type: The provider type to configure.
        settings: The settings document.

    Returns:
        AIServiceConfig if successful, None otherwise.
    """
    try:
        base_params = {
            "provider_type": provider_type,
            "temperature": getattr(settings, "ai_temperature", 0.0) or 0.0,
            "max_tokens": getattr(settings, "ai_max_tokens", 1024) or 1024,
        }

        if provider_type == AIProviderType.GEMINI:
            api_key = settings.get_password("gemini_api_key")
            if not api_key:
                return None
            return AIServiceConfig(
                api_key=api_key,
                model=getattr(settings, "gemini_model", None),
                **base_params,
            )

        elif provider_type == AIProviderType.OPENAI:
            api_key = settings.get_password("openai_api_key")
            if not api_key:
                return None
            return AIServiceConfig(
                api_key=api_key,
                model=getattr(settings, "openai_model", None),
                **base_params,
            )

        elif provider_type == AIProviderType.ANTHROPIC:
            api_key = settings.get_password("anthropic_api_key")
            if not api_key:
                return None
            return AIServiceConfig(
                api_key=api_key,
                model=getattr(settings, "anthropic_model", None),
                **base_params,
            )

        elif provider_type == AIProviderType.OLLAMA:
            if not getattr(settings, "ollama_enabled", False):
                return None
            return AIServiceConfig(
                model=getattr(settings, "ollama_model", None) or "gemma3",
                base_url=getattr(settings, "ollama_base_url", None) or "http://localhost:11434",
                **base_params,
            )

        return None

    except Exception:
        return None


def _create_provider_from_config(config: AIServiceConfig) -> Optional[LLMProvider]:
    """
    Create a provider instance from configuration.

    This function checks the provider registry for registered implementations.
    If not found, it returns None (provider implementations are registered
    in their respective modules).

    Args:
        config: The provider configuration.

    Returns:
        LLMProvider instance if available, None otherwise.
    """
    # Check if provider is registered
    provider_class = AIService._provider_registry.get(config.provider_type)

    if provider_class:
        return provider_class(config)

    # Provider not registered - implementations will register themselves
    # when imported (gemini_provider.py, openai_provider.py, etc.)
    return None


def create_ai_service(
    provider_type: Optional[AIProviderType] = None,
) -> AIService:
    """
    Factory function to create an AIService instance.

    Args:
        provider_type: Optional specific provider type to use.

    Returns:
        Configured AIService instance.

    Example:
        service = create_ai_service()
        result = service.generate("Generate a name")
    """
    provider = get_llm_provider(provider_type)
    return AIService(provider=provider)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Core classes
    "LLMProvider",
    "AIService",
    "AIServiceConfig",
    "GenerationResult",
    "GenerationStats",
    # Enums
    "AIProviderType",
    # Exceptions
    "AIProviderError",
    "AIProviderNotConfiguredError",
    "AIProviderConnectionError",
    "AIProviderRateLimitError",
    "AIGenerationError",
    # Factory functions
    "get_llm_provider",
    "create_ai_service",
]
