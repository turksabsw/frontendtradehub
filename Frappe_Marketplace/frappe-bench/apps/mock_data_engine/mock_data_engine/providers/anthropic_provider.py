# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Anthropic LLM Provider for Mock Data Engine.

This module provides the Anthropic Claude provider implementation for AI-powered
mock data generation. It uses the anthropic SDK with the messages API.

Key Features:
- Uses anthropic SDK for Claude API access
- Supports Claude Sonnet 4.5 (default), Claude 3.5 Sonnet, Claude 3 Opus, and Claude 3 Haiku
- Temperature control for deterministic generation (default: 0)
- Automatic retry on transient failures
- Connection testing for API key validation

Usage:
    from mock_data_engine.providers.anthropic_provider import (
        AnthropicProvider,
        create_anthropic_provider,
    )

    # Create provider with API key
    config = AIServiceConfig(
        provider_type=AIProviderType.ANTHROPIC,
        api_key="sk-ant-...",
        model="claude-sonnet-4-5",
        temperature=0.0,
    )
    provider = AnthropicProvider(config)

    # Generate content
    result = provider.generate(
        prompt="Generate a Turkish company name",
        context={"locale": "tr_TR", "industry": "Technology"}
    )
    print(result.content)

Note:
    Requires the anthropic package to be installed:
    pip install anthropic
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mock_data_engine.providers.ai_service import (
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
    from anthropic import Anthropic
    from anthropic.types import Message


# =============================================================================
# Constants
# =============================================================================

# Default model for Anthropic provider
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

# Available Anthropic models
AVAILABLE_ANTHROPIC_MODELS = [
    "claude-sonnet-4-5",
    "claude-3-5-sonnet-20241022",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
]

# Test prompt for connection testing
TEST_PROMPT = "Say 'OK' if you can read this."


# =============================================================================
# AnthropicProvider Implementation
# =============================================================================


class AnthropicProvider(LLMProvider):
    """
    Anthropic Claude LLM provider implementation.

    This provider uses the anthropic SDK for accessing Anthropic's Claude models.
    It supports text generation for mock data creation.

    Attributes:
        config: The provider configuration (AIServiceConfig).
        name: Provider name ("anthropic").

    Supported Models:
        - claude-sonnet-4-5 (default): Latest and most capable Sonnet model
        - claude-3-5-sonnet-20241022: Claude 3.5 Sonnet, fast and capable
        - claude-3-opus-20240229: Most capable Claude 3 model
        - claude-3-sonnet-20240229: Balanced Claude 3 model
        - claude-3-haiku-20240307: Fast and economical Claude 3 model

    Example:
        >>> config = AIServiceConfig(
        ...     provider_type=AIProviderType.ANTHROPIC,
        ...     api_key="sk-ant-...",
        ...     temperature=0.0,
        ... )
        >>> provider = AnthropicProvider(config)
        >>> result = provider.generate("Generate a Turkish name")
        >>> print(result.content)
        "Ahmet Yilmaz"
    """

    def __init__(self, config: AIServiceConfig):
        """
        Initialize the Anthropic provider.

        Args:
            config: The AIServiceConfig with provider settings.
                    Must have provider_type=AIProviderType.ANTHROPIC.

        Raises:
            ValueError: If provider_type is not ANTHROPIC.
        """
        if config.provider_type != AIProviderType.ANTHROPIC:
            raise ValueError(
                f"Invalid provider type: {config.provider_type}. "
                f"Expected: {AIProviderType.ANTHROPIC}"
            )
        super().__init__(config)
        self._anthropic_client: Optional["Anthropic"] = None

    def _initialize_client(self) -> None:
        """
        Initialize the Anthropic client.

        This method imports the anthropic SDK and creates an Anthropic
        client instance with the configured API key.

        Raises:
            ImportError: If anthropic package is not installed.
            AIProviderError: If client initialization fails.
        """
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ImportError(
                "The anthropic package is required for Anthropic provider. "
                "Install it with: pip install anthropic"
            ) from e

        try:
            # Create the client with API key
            self._anthropic_client = Anthropic(api_key=self._config.api_key)
        except Exception as e:
            raise AIProviderError(
                f"Failed to initialize Anthropic client: {e}",
                provider=self.name,
                original_error=e,
            )

    @property
    def client(self) -> "Anthropic":
        """
        Get the Anthropic client, initializing if needed.

        Returns:
            The initialized Anthropic Client.

        Raises:
            AIProviderError: If client is not initialized and cannot be created.
        """
        if not self._initialized:
            self.initialize()
        return self._anthropic_client

    def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Generate content using Anthropic Claude.

        This method sends a prompt to the Anthropic API and returns
        the generated content wrapped in a GenerationResult.

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
        model = self._config.default_model or DEFAULT_ANTHROPIC_MODEL

        try:
            # Make the API call using anthropic SDK
            # Anthropic uses messages.create() with max_tokens parameter
            message = self._anthropic_client.messages.create(
                model=model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                messages=[{"role": "user", "content": enhanced_prompt}],
            )

            # Extract the text content from response
            content = self._extract_content(message)

            # Determine tokens used if available
            tokens_used = self._extract_token_usage(message)

            # Determine finish reason
            finish_reason = self._extract_finish_reason(message)

            return GenerationResult(
                content=content,
                provider=self.name,
                model=model,
                tokens_used=tokens_used,
                finish_reason=finish_reason,
                raw_response=message,
            )

        except Exception as e:
            # Handle specific error types
            error_str = str(e).lower()

            if "rate limit" in error_str or "429" in error_str or "quota" in error_str:
                raise AIProviderRateLimitError(
                    f"Anthropic rate limit exceeded: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "connection" in error_str or "timeout" in error_str or "network" in error_str:
                raise AIProviderConnectionError(
                    f"Failed to connect to Anthropic API: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "invalid" in error_str and "api" in error_str and "key" in error_str:
                raise AIProviderConnectionError(
                    f"Invalid Anthropic API key: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "authentication" in error_str or "unauthorized" in error_str:
                raise AIProviderConnectionError(
                    f"Anthropic authentication failed: {e}",
                    provider=self.name,
                    original_error=e,
                )
            else:
                raise AIGenerationError(
                    f"Anthropic generation failed: {e}",
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

    def _extract_content(self, message: "Message") -> str:
        """
        Extract text content from Anthropic response.

        Args:
            message: The Message response from the API.

        Returns:
            The extracted text content.

        Raises:
            AIGenerationError: If content cannot be extracted.
        """
        try:
            # Anthropic messages response structure: message.content is a list
            # of content blocks, typically TextBlock objects
            if message.content and len(message.content) > 0:
                # Get the first content block
                content_block = message.content[0]
                # Check if it has text attribute (TextBlock)
                if hasattr(content_block, "text"):
                    return content_block.text.strip()

            # If we can't extract content, raise an error
            raise AIGenerationError(
                "No content in Anthropic response",
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

    def _extract_token_usage(self, message: "Message") -> Optional[int]:
        """
        Extract token usage from Anthropic response.

        Args:
            message: The Message response from the API.

        Returns:
            Total tokens used, or None if not available.
        """
        try:
            # Anthropic provides usage in message.usage
            if hasattr(message, "usage") and message.usage:
                total = 0
                if hasattr(message.usage, "input_tokens"):
                    total += message.usage.input_tokens or 0
                if hasattr(message.usage, "output_tokens"):
                    total += message.usage.output_tokens or 0
                return total if total > 0 else None
            return None
        except Exception:
            return None

    def _extract_finish_reason(self, message: "Message") -> Optional[str]:
        """
        Extract finish reason from Anthropic response.

        Args:
            message: The Message response from the API.

        Returns:
            Finish reason string, or None if not available.
        """
        try:
            # Anthropic uses stop_reason attribute
            if hasattr(message, "stop_reason"):
                return message.stop_reason
            return None
        except Exception:
            return None

    def test_connection(self) -> bool:
        """
        Test the connection to the Anthropic API.

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
            model = self._config.default_model or DEFAULT_ANTHROPIC_MODEL

            message = self._anthropic_client.messages.create(
                model=model,
                max_tokens=10,
                temperature=0,
                messages=[{"role": "user", "content": TEST_PROMPT}],
            )

            # Check if we got a response
            content = self._extract_content(message)
            return bool(content)

        except Exception as e:
            raise AIProviderConnectionError(
                f"Anthropic connection test failed: {e}",
                provider=self.name,
                original_error=e,
            )

    def get_available_models(self) -> List[str]:
        """
        Get list of available Anthropic models.

        Returns:
            List of model identifiers.
        """
        return AVAILABLE_ANTHROPIC_MODELS.copy()

    def __repr__(self) -> str:
        """String representation of the provider."""
        model = self._config.default_model or DEFAULT_ANTHROPIC_MODEL
        return (
            f"AnthropicProvider("
            f"model={model}, "
            f"temperature={self._config.temperature}, "
            f"initialized={self._initialized})"
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_anthropic_provider(
    api_key: str,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> AnthropicProvider:
    """
    Factory function to create an AnthropicProvider instance.

    This is a convenience function for quickly creating an Anthropic provider
    without manually building the AIServiceConfig.

    Args:
        api_key: The Anthropic API key (starts with sk-ant-...).
        model: Optional model to use (default: claude-sonnet-4-5).
        temperature: Temperature for generation (default: 0.0 for determinism).
        max_tokens: Maximum tokens in response (default: 1024).

    Returns:
        Configured AnthropicProvider instance.

    Example:
        >>> provider = create_anthropic_provider(
        ...     api_key="sk-ant-...",
        ...     temperature=0.7,
        ... )
        >>> result = provider.generate("Hello!")
    """
    config = AIServiceConfig(
        provider_type=AIProviderType.ANTHROPIC,
        api_key=api_key,
        model=model or DEFAULT_ANTHROPIC_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return AnthropicProvider(config)


# =============================================================================
# Provider Registration
# =============================================================================

# Register AnthropicProvider with the AIService registry
# This allows get_llm_provider() to automatically create AnthropicProvider
# instances when configured
AIService.register_provider(AIProviderType.ANTHROPIC, AnthropicProvider)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "AnthropicProvider",
    "create_anthropic_provider",
    "DEFAULT_ANTHROPIC_MODEL",
    "AVAILABLE_ANTHROPIC_MODELS",
]
