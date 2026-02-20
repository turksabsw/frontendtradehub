# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Providers Module for Mock Data Engine.

This module provides data generation providers including Faker integration,
LLM providers, and external service integrations.

Key Components:
- FakerProvider: Locale-aware Faker instance management for generating mock data
- AIService: Service class for managing AI generation operations
- LLMProvider: Abstract interface for LLM providers
- UnsplashProvider: Contextual image fetching from Unsplash API

The Faker provider is the primary source for fast, deterministic data generation.
LLM providers are used for generating context-aware, realistic content when
higher quality is required.

Usage:
    from mock_data_engine.providers import (
        FakerProvider,
        create_faker_provider,
        SUPPORTED_LOCALES,
        AIService,
        LLMProvider,
        get_llm_provider,
    )

    # Create a provider for Turkish locale
    faker = FakerProvider('tr_TR', seed=42)

    # Generate data
    name = faker.name()
    email = faker.email()
    phone = faker.phone_number()

    # Use AI service for complex generation
    provider = get_llm_provider()
    if provider:
        result = provider.generate("Generate a company description")
"""

from mock_data_engine.providers.faker_provider import (
    FakerProvider,
    FakerProviderPool,
    create_faker_provider,
    get_faker_provider,
    SUPPORTED_LOCALES,
    LOCALE_FALLBACKS,
    DEFAULT_LOCALE,
)

from mock_data_engine.providers.ai_service import (
    # Core classes
    LLMProvider,
    AIService,
    AIServiceConfig,
    GenerationResult,
    GenerationStats,
    # Enums
    AIProviderType,
    # Exceptions
    AIProviderError,
    AIProviderNotConfiguredError,
    AIProviderConnectionError,
    AIProviderRateLimitError,
    AIGenerationError,
    # Factory functions
    get_llm_provider,
    create_ai_service,
)

from mock_data_engine.providers.gemini_provider import (
    GeminiProvider,
    create_gemini_provider,
    DEFAULT_GEMINI_MODEL,
    AVAILABLE_GEMINI_MODELS,
)

from mock_data_engine.providers.openai_provider import (
    OpenAIProvider,
    create_openai_provider,
    DEFAULT_OPENAI_MODEL,
    AVAILABLE_OPENAI_MODELS,
)

from mock_data_engine.providers.anthropic_provider import (
    AnthropicProvider,
    create_anthropic_provider,
    DEFAULT_ANTHROPIC_MODEL,
    AVAILABLE_ANTHROPIC_MODELS,
)

from mock_data_engine.providers.ollama_provider import (
    OllamaProvider,
    create_ollama_provider,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    AVAILABLE_OLLAMA_MODELS,
)

from mock_data_engine.providers.response_processor import (
    AIResponseProcessor,
    create_response_processor,
    ParsedResponse,
    ValidationResult,
    ResponseFormat,
    ResponseProcessingError,
    ResponseParseError,
    ResponseValidationError,
    ResponseExtractionError,
)

from mock_data_engine.providers.unsplash_provider import (
    UnsplashProvider,
    UnsplashConfig,
    ImageResult,
    ImageSize,
    UnsplashProviderError,
    UnsplashConnectionError,
    UnsplashRateLimitError,
    UnsplashSearchError,
    create_unsplash_provider,
    get_unsplash_provider,
    DEFAULT_CONTEXT_QUERIES,
    DEFAULT_IMAGE_SIZE,
)

__all__ = [
    # Faker provider
    "FakerProvider",
    "FakerProviderPool",
    "create_faker_provider",
    "get_faker_provider",
    # Faker constants
    "SUPPORTED_LOCALES",
    "LOCALE_FALLBACKS",
    "DEFAULT_LOCALE",
    # AI Service - Core classes
    "LLMProvider",
    "AIService",
    "AIServiceConfig",
    "GenerationResult",
    "GenerationStats",
    # AI Service - Enums
    "AIProviderType",
    # AI Service - Exceptions
    "AIProviderError",
    "AIProviderNotConfiguredError",
    "AIProviderConnectionError",
    "AIProviderRateLimitError",
    "AIGenerationError",
    # AI Service - Factory functions
    "get_llm_provider",
    "create_ai_service",
    # Gemini provider
    "GeminiProvider",
    "create_gemini_provider",
    "DEFAULT_GEMINI_MODEL",
    "AVAILABLE_GEMINI_MODELS",
    # OpenAI provider
    "OpenAIProvider",
    "create_openai_provider",
    "DEFAULT_OPENAI_MODEL",
    "AVAILABLE_OPENAI_MODELS",
    # Anthropic provider
    "AnthropicProvider",
    "create_anthropic_provider",
    "DEFAULT_ANTHROPIC_MODEL",
    "AVAILABLE_ANTHROPIC_MODELS",
    # Ollama provider
    "OllamaProvider",
    "create_ollama_provider",
    "DEFAULT_OLLAMA_MODEL",
    "DEFAULT_OLLAMA_BASE_URL",
    "AVAILABLE_OLLAMA_MODELS",
    # Response processor
    "AIResponseProcessor",
    "create_response_processor",
    "ParsedResponse",
    "ValidationResult",
    "ResponseFormat",
    "ResponseProcessingError",
    "ResponseParseError",
    "ResponseValidationError",
    "ResponseExtractionError",
    # Unsplash provider
    "UnsplashProvider",
    "UnsplashConfig",
    "ImageResult",
    "ImageSize",
    "UnsplashProviderError",
    "UnsplashConnectionError",
    "UnsplashRateLimitError",
    "UnsplashSearchError",
    "create_unsplash_provider",
    "get_unsplash_provider",
    "DEFAULT_CONTEXT_QUERIES",
    "DEFAULT_IMAGE_SIZE",
]
