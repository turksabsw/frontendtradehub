# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
OpenAI LLM Provider for Mock Data Engine.

This module provides the OpenAI provider implementation for AI-powered
mock data generation. It uses the openai SDK with the chat completions API.

Key Features:
- Uses openai SDK for OpenAI API access
- Supports GPT-4o-mini (default), GPT-4o, GPT-4-turbo, and GPT-3.5-turbo models
- Uses max_completion_tokens (NOT deprecated max_tokens since Sept 2024)
- Temperature control for deterministic generation (default: 0)
- Automatic retry on transient failures
- Connection testing for API key validation

Usage:
    from mock_data_engine.mock_data_engine.providers.openai_provider import (
        OpenAIProvider,
        create_openai_provider,
    )

    # Create provider with API key
    config = AIServiceConfig(
        provider_type=AIProviderType.OPENAI,
        api_key="sk-...",
        model="gpt-4o-mini",
        temperature=0.0,
    )
    provider = OpenAIProvider(config)

    # Generate content
    result = provider.generate(
        prompt="Generate a Turkish company name",
        context={"locale": "tr_TR", "industry": "Technology"}
    )
    print(result.content)

Note:
    Requires the openai package to be installed:
    pip install openai

    IMPORTANT: Uses max_completion_tokens instead of max_tokens
    (max_tokens is deprecated since September 2024)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mock_data_engine.mock_data_engine.providers.ai_service import (
    AIProviderType,
    AIServiceConfig,
    AIProviderError,
    AIProviderConnectionError,
    AIProviderRateLimitError,
    AIGenerationError,
    GenerationResult,
    LLMProvider,
    AIService,
)

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletion


# =============================================================================
# Constants
# =============================================================================

# Default model for OpenAI provider
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# Available OpenAI models
AVAILABLE_OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
]

# Test prompt for connection testing
TEST_PROMPT = "Say 'OK' if you can read this."


# =============================================================================
# OpenAIProvider Implementation
# =============================================================================


class OpenAIProvider(LLMProvider):
    """
    OpenAI LLM provider implementation.

    This provider uses the openai SDK for accessing OpenAI's GPT models.
    It supports text generation for mock data creation.

    IMPORTANT: This uses max_completion_tokens instead of max_tokens
    (max_tokens is deprecated since September 2024).

    Attributes:
        config: The provider configuration (AIServiceConfig).
        name: Provider name ("openai").

    Supported Models:
        - gpt-4o-mini (default): Fast and cost-effective
        - gpt-4o: Most capable GPT-4 model
        - gpt-4-turbo: High-performance GPT-4
        - gpt-4: Original GPT-4 model
        - gpt-3.5-turbo: Fast and economical

    Example:
        >>> config = AIServiceConfig(
        ...     provider_type=AIProviderType.OPENAI,
        ...     api_key="sk-...",
        ...     temperature=0.0,
        ... )
        >>> provider = OpenAIProvider(config)
        >>> result = provider.generate("Generate a Turkish name")
        >>> print(result.content)
        "Ahmet Yilmaz"
    """

    def __init__(self, config: AIServiceConfig):
        """
        Initialize the OpenAI provider.

        Args:
            config: The AIServiceConfig with provider settings.
                    Must have provider_type=AIProviderType.OPENAI.

        Raises:
            ValueError: If provider_type is not OPENAI.
        """
        if config.provider_type != AIProviderType.OPENAI:
            raise ValueError(
                f"Invalid provider type: {config.provider_type}. "
                f"Expected: {AIProviderType.OPENAI}"
            )
        super().__init__(config)
        self._openai_client: Optional["OpenAI"] = None

    def _initialize_client(self) -> None:
        """
        Initialize the OpenAI client.

        This method imports the openai SDK and creates an OpenAI
        client instance with the configured API key.

        Raises:
            ImportError: If openai package is not installed.
            AIProviderError: If client initialization fails.
        """
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "The openai package is required for OpenAI provider. "
                "Install it with: pip install openai"
            ) from e

        try:
            # Create the client with API key
            self._openai_client = OpenAI(api_key=self._config.api_key)
        except Exception as e:
            raise AIProviderError(
                f"Failed to initialize OpenAI client: {e}",
                provider=self.name,
                original_error=e,
            )

    @property
    def client(self) -> "OpenAI":
        """
        Get the OpenAI client, initializing if needed.

        Returns:
            The initialized OpenAI Client.

        Raises:
            AIProviderError: If client is not initialized and cannot be created.
        """
        if not self._initialized:
            self.initialize()
        return self._openai_client

    def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Generate content using OpenAI.

        This method sends a prompt to the OpenAI API and returns
        the generated content wrapped in a GenerationResult.

        IMPORTANT: Uses max_completion_tokens (NOT deprecated max_tokens).

        Args:
            prompt: The prompt for content generation.
            context: Optional context dictionary with additional information.
                     Supported context keys:
                     - locale: The locale for generation (e.g., "tr_TR")
                     - doctype: The DocType being generated
                     - fieldname: The field being generated
                     - industry: Industry context for more relevant content

        Returns:
            GenerationResult containing the generated content and metadata.

        Raises:
            AIGenerationError: If content generation fails.
            AIProviderConnectionError: If connection to API fails.
            AIProviderRateLimitError: If rate limit is exceeded.

        Example:
            >>> result = provider.generate(
            ...     prompt="Generate a Turkish business name",
            ...     context={"locale": "tr_TR", "industry": "Retail"}
            ... )
            >>> print(result.content)
            "Yildiz Ticaret A.S."
        """
        if not self._initialized:
            self.initialize()

        # Build the enhanced prompt with context if provided
        enhanced_prompt = self._build_prompt_with_context(prompt, context)

        # Get the model to use
        model = self._config.default_model or DEFAULT_OPENAI_MODEL

        try:
            # Make the API call using openai SDK
            # IMPORTANT: Using max_completion_tokens (NOT max_tokens - deprecated Sept 2024)
            response = self._openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": enhanced_prompt}],
                temperature=self._config.temperature,
                max_completion_tokens=self._config.max_tokens,
            )

            # Extract the text content from response
            content = self._extract_content(response)

            # Determine tokens used if available
            tokens_used = self._extract_token_usage(response)

            # Determine finish reason
            finish_reason = self._extract_finish_reason(response)

            return GenerationResult(
                content=content,
                provider=self.name,
                model=model,
                tokens_used=tokens_used,
                finish_reason=finish_reason,
                raw_response=response,
            )

        except Exception as e:
            # Handle specific error types
            error_str = str(e).lower()

            if "rate limit" in error_str or "429" in error_str or "quota" in error_str:
                raise AIProviderRateLimitError(
                    f"OpenAI rate limit exceeded: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "connection" in error_str or "timeout" in error_str or "network" in error_str:
                raise AIProviderConnectionError(
                    f"Failed to connect to OpenAI API: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "invalid" in error_str and "api" in error_str and "key" in error_str:
                raise AIProviderConnectionError(
                    f"Invalid OpenAI API key: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "authentication" in error_str or "unauthorized" in error_str:
                raise AIProviderConnectionError(
                    f"OpenAI authentication failed: {e}",
                    provider=self.name,
                    original_error=e,
                )
            else:
                raise AIGenerationError(
                    f"OpenAI generation failed: {e}",
                    provider=self.name,
                    original_error=e,
                )

    def _build_prompt_with_context(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        """
        Build an enhanced prompt with context information.

        Args:
            prompt: The base prompt.
            context: Optional context dictionary.

        Returns:
            Enhanced prompt string.
        """
        if not context:
            return prompt

        # Build context prefix
        context_parts = []

        if context.get("locale"):
            locale = context["locale"]
            locale_map = {
                "tr_TR": "Turkish",
                "en_US": "American English",
                "en_GB": "British English",
                "de_DE": "German",
                "fr_FR": "French",
            }
            language = locale_map.get(locale, locale)
            context_parts.append(f"Language/Locale: {language}")

        if context.get("industry"):
            context_parts.append(f"Industry: {context['industry']}")

        if context.get("doctype"):
            context_parts.append(f"DocType: {context['doctype']}")

        if context.get("fieldname"):
            context_parts.append(f"Field: {context['fieldname']}")

        if context.get("fieldtype"):
            context_parts.append(f"Field Type: {context['fieldtype']}")

        if context_parts:
            context_str = "\n".join(context_parts)
            return f"Context:\n{context_str}\n\nTask:\n{prompt}"

        return prompt

    def _extract_content(self, response: "ChatCompletion") -> str:
        """
        Extract text content from OpenAI response.

        Args:
            response: The ChatCompletion response from the API.

        Returns:
            The extracted text content.

        Raises:
            AIGenerationError: If content cannot be extracted.
        """
        try:
            # OpenAI chat completions response structure
            if response.choices and len(response.choices) > 0:
                message = response.choices[0].message
                if message and message.content:
                    return message.content.strip()

            # If we can't extract content, raise an error
            raise AIGenerationError(
                "No content in OpenAI response",
                provider=self.name,
            )

        except AIGenerationError:
            raise
        except Exception as e:
            raise AIGenerationError(
                f"Failed to extract content from response: {e}",
                provider=self.name,
                original_error=e,
            )

    def _extract_token_usage(self, response: "ChatCompletion") -> Optional[int]:
        """
        Extract token usage from OpenAI response.

        Args:
            response: The ChatCompletion response from the API.

        Returns:
            Total tokens used, or None if not available.
        """
        try:
            if response.usage:
                return response.usage.total_tokens
            return None
        except Exception:
            return None

    def _extract_finish_reason(self, response: "ChatCompletion") -> Optional[str]:
        """
        Extract finish reason from OpenAI response.

        Args:
            response: The ChatCompletion response from the API.

        Returns:
            Finish reason string, or None if not available.
        """
        try:
            if response.choices and len(response.choices) > 0:
                return response.choices[0].finish_reason
            return None
        except Exception:
            return None

    def test_connection(self) -> bool:
        """
        Test the connection to the OpenAI API.

        This method sends a simple prompt to verify the API key is valid
        and the service is accessible.

        Returns:
            True if connection is successful.

        Raises:
            AIProviderConnectionError: If connection test fails.
        """
        if not self._initialized:
            self.initialize()

        try:
            # Use a simple test prompt with minimal tokens
            model = self._config.default_model or DEFAULT_OPENAI_MODEL

            response = self._openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": TEST_PROMPT}],
                temperature=0,
                max_completion_tokens=10,
            )

            # Check if we got a response
            content = self._extract_content(response)
            return bool(content)

        except Exception as e:
            raise AIProviderConnectionError(
                f"OpenAI connection test failed: {e}",
                provider=self.name,
                original_error=e,
            )

    def get_available_models(self) -> List[str]:
        """
        Get list of available OpenAI models.

        Returns:
            List of model identifiers.
        """
        return AVAILABLE_OPENAI_MODELS.copy()

    def __repr__(self) -> str:
        """String representation of the provider."""
        model = self._config.default_model or DEFAULT_OPENAI_MODEL
        return (
            f"OpenAIProvider("
            f"model={model}, "
            f"temperature={self._config.temperature}, "
            f"initialized={self._initialized})"
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_openai_provider(
    api_key: str,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> OpenAIProvider:
    """
    Factory function to create an OpenAIProvider instance.

    This is a convenience function for quickly creating an OpenAI provider
    without manually building the AIServiceConfig.

    Args:
        api_key: The OpenAI API key (starts with sk-...).
        model: Optional model to use (default: gpt-4o-mini).
        temperature: Temperature for generation (default: 0.0 for determinism).
        max_tokens: Maximum tokens in response (default: 1024).
                   Note: Internally uses max_completion_tokens.

    Returns:
        Configured OpenAIProvider instance.

    Example:
        >>> provider = create_openai_provider(
        ...     api_key="sk-...",
        ...     temperature=0.7,
        ... )
        >>> result = provider.generate("Hello!")
    """
    config = AIServiceConfig(
        provider_type=AIProviderType.OPENAI,
        api_key=api_key,
        model=model or DEFAULT_OPENAI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return OpenAIProvider(config)


# =============================================================================
# Provider Registration
# =============================================================================

# Register OpenAIProvider with the AIService registry
# This allows get_llm_provider() to automatically create OpenAIProvider
# instances when configured
AIService.register_provider(AIProviderType.OPENAI, OpenAIProvider)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "OpenAIProvider",
    "create_openai_provider",
    "DEFAULT_OPENAI_MODEL",
    "AVAILABLE_OPENAI_MODELS",
]
