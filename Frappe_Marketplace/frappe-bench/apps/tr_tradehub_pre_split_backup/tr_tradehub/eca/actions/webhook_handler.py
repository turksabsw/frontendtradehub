# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA Webhook Action Handler

Makes HTTP requests (GET/POST/PUT/PATCH/DELETE) to webhook URLs with document
data as payload. Supports custom headers, Jinja template rendering for
dynamic URL, headers, and body content.

Usage:
    from tr_tradehub.eca.actions.webhook_handler import WebhookHandler, execute_webhook_action

    handler = WebhookHandler()
    result = handler.execute(action, doc, context)
"""

import json
from typing import Any, Dict, List, Optional

try:
    import frappe
    from frappe import _
except ImportError:
    frappe = None
    _ = str

try:
    import requests
except ImportError:
    requests = None

from . import ActionResult, BaseActionHandler, register_handler


# Default timeout for webhook requests (in seconds)
DEFAULT_TIMEOUT = 30

# Maximum response body size to log (in characters)
MAX_RESPONSE_LOG_SIZE = 1000


@register_handler
class WebhookHandler(BaseActionHandler):
    """
    Handler for Webhook actions.

    Makes HTTP requests to external endpoints with support for:
    - Multiple HTTP methods (GET, POST, PUT, PATCH, DELETE)
    - Custom headers (JSON format with Jinja support)
    - Custom request body (JSON format with Jinja support)
    - Document data as default payload
    - Jinja template rendering in URL, headers, and body

    Fields used from ECA Rule Action:
    - webhook_url: Target URL for webhook (required, supports Jinja)
    - webhook_method: HTTP method (default: POST)
    - webhook_headers: Custom HTTP headers as JSON (optional)
    - webhook_body: Request body template as JSON (optional, supports Jinja)
    """

    action_type = 'Webhook'

    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the webhook action.

        Args:
            action: ECA Rule Action child document with webhook configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult with success/failure status and message
        """
        if not frappe:
            return ActionResult.error_result(
                error="Frappe not available",
                message="Cannot execute webhook: Frappe framework not loaded"
            )

        if not requests:
            return ActionResult.error_result(
                error="Requests library not available",
                message="Cannot execute webhook: 'requests' library not installed"
            )

        try:
            # Build template context
            full_context = self.build_context(doc, context)

            # Get and validate URL
            url = self._get_webhook_url(action, doc, full_context)
            if not url:
                return ActionResult.error_result(
                    error="No webhook URL specified",
                    message="Webhook action failed: URL is required"
                )

            # Get HTTP method
            method = self._get_http_method(action)

            # Get headers
            headers = self._get_headers(action, doc, full_context)

            # Get request body
            body = self._get_body(action, doc, full_context)

            # Execute the webhook request
            response = self._make_request(method, url, headers, body)

            # Build success result
            return ActionResult.success_result(
                message=f"Webhook {method} to {url} - Status: {response.status_code}",
                data={
                    'url': url,
                    'method': method,
                    'status_code': response.status_code,
                    'response_body': self._truncate_response(response.text)
                }
            )

        except requests.exceptions.Timeout as e:
            error_msg = f"Request timed out after {DEFAULT_TIMEOUT} seconds"
            if frappe:
                frappe.log_error(
                    title="ECA Webhook Timeout",
                    message=f"Document: {doc.doctype} {doc.name}\nURL: {getattr(action, 'webhook_url', 'N/A')}\nError: {error_msg}"
                )
            return ActionResult.error_result(
                error=error_msg,
                message=f"Webhook failed: {error_msg}"
            )

        except requests.exceptions.ConnectionError as e:
            error_msg = f"Connection error: {str(e)}"
            if frappe:
                frappe.log_error(
                    title="ECA Webhook Connection Error",
                    message=f"Document: {doc.doctype} {doc.name}\nURL: {getattr(action, 'webhook_url', 'N/A')}\nError: {error_msg}"
                )
            return ActionResult.error_result(
                error=error_msg,
                message=f"Webhook failed: Unable to connect to server"
            )

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP error: {e.response.status_code if e.response else str(e)}"
            response_text = e.response.text[:500] if e.response else ''
            if frappe:
                frappe.log_error(
                    title="ECA Webhook HTTP Error",
                    message=f"Document: {doc.doctype} {doc.name}\nURL: {getattr(action, 'webhook_url', 'N/A')}\nError: {error_msg}\nResponse: {response_text}"
                )
            return ActionResult.error_result(
                error=error_msg,
                message=f"Webhook failed: {error_msg}"
            )

        except Exception as e:
            if frappe:
                frappe.log_error(
                    title="ECA Webhook Action Error",
                    message=f"Document: {doc.doctype} {doc.name}\nError: {str(e)}"
                )
            return ActionResult.error_result(
                error=str(e),
                message=f"Failed to execute webhook: {str(e)}"
            )

    def validate(self, action: Any) -> List[str]:
        """
        Validate webhook action configuration.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages
        """
        errors = []

        # Check for webhook URL
        webhook_url = getattr(action, 'webhook_url', None)
        if not webhook_url:
            errors.append("Webhook URL is required for Webhook action")

        # Validate URL format (basic check)
        if webhook_url and not self._is_valid_url(webhook_url):
            # Allow Jinja templates (contain {{ }})
            if '{{' not in webhook_url:
                errors.append(f"Invalid webhook URL format: {webhook_url}")

        # Validate HTTP method
        method = getattr(action, 'webhook_method', None)
        valid_methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
        if method and method.upper() not in valid_methods:
            errors.append(f"Invalid HTTP method: {method}. Must be one of: {', '.join(valid_methods)}")

        # Validate headers JSON if provided
        headers = getattr(action, 'webhook_headers', None)
        if headers:
            # Skip validation if it contains Jinja templates
            if '{{' not in headers:
                try:
                    parsed_headers = json.loads(headers)
                    if not isinstance(parsed_headers, dict):
                        errors.append("Webhook headers must be a JSON object")
                except json.JSONDecodeError as e:
                    errors.append(f"Invalid JSON in webhook headers: {str(e)}")

        # Validate body JSON if provided
        body = getattr(action, 'webhook_body', None)
        if body:
            # Skip validation if it contains Jinja templates
            if '{{' not in body:
                try:
                    json.loads(body)
                except json.JSONDecodeError as e:
                    errors.append(f"Invalid JSON in webhook body: {str(e)}")

        return errors

    def _get_webhook_url(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> Optional[str]:
        """
        Get and render the webhook URL.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            Rendered URL string or None
        """
        url = getattr(action, 'webhook_url', None) or ''

        if not url:
            return None

        # Render Jinja template in URL
        rendered_url = self.render_template(url, doc, context)

        # Strip whitespace
        rendered_url = rendered_url.strip()

        # Validate basic URL structure
        if not rendered_url:
            return None

        return rendered_url

    def _get_http_method(self, action: Any) -> str:
        """
        Get the HTTP method for the request.

        Args:
            action: Action configuration

        Returns:
            HTTP method string (uppercase)
        """
        method = getattr(action, 'webhook_method', None) or 'POST'
        return method.upper()

    def _get_headers(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> Dict[str, str]:
        """
        Get and parse HTTP headers.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            Dictionary of HTTP headers
        """
        # Default headers
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'TR-TradeHub-ECA-Webhook/1.0'
        }

        # Get custom headers
        custom_headers_str = getattr(action, 'webhook_headers', None) or ''

        if custom_headers_str:
            try:
                # Render Jinja templates in headers
                rendered_headers = self.render_template(custom_headers_str, doc, context)

                # Parse JSON
                custom_headers = json.loads(rendered_headers)

                if isinstance(custom_headers, dict):
                    # Update headers (custom headers override defaults)
                    headers.update(custom_headers)

            except json.JSONDecodeError:
                # Log error but continue with default headers
                if frappe:
                    frappe.log_error(
                        title="ECA Webhook Headers Parse Error",
                        message=f"Failed to parse webhook headers JSON: {custom_headers_str}"
                    )

        return headers

    def _get_body(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> Any:
        """
        Get the request body.

        If no custom body is specified, uses the document data as payload.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            Request body (dict, list, or string)
        """
        body_template = getattr(action, 'webhook_body', None) or ''

        if body_template:
            try:
                # Render Jinja template
                rendered_body = self.render_template(body_template, doc, context)

                # Try to parse as JSON
                try:
                    return json.loads(rendered_body)
                except json.JSONDecodeError:
                    # Return as string if not valid JSON
                    return rendered_body

            except Exception as e:
                if frappe:
                    frappe.log_error(
                        title="ECA Webhook Body Render Error",
                        message=f"Failed to render webhook body: {str(e)}"
                    )
                # Fall back to document data
                return doc.as_dict() if hasattr(doc, 'as_dict') else doc

        # Default: use document data as payload
        return doc.as_dict() if hasattr(doc, 'as_dict') else doc

    def _make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Any
    ) -> requests.Response:
        """
        Make the HTTP request.

        Args:
            method: HTTP method
            url: Target URL
            headers: HTTP headers
            body: Request body

        Returns:
            Response object

        Raises:
            requests.exceptions.RequestException: On request failure
        """
        # Prepare request arguments
        kwargs = {
            'url': url,
            'headers': headers,
            'timeout': DEFAULT_TIMEOUT
        }

        # Add body based on method
        if method == 'GET':
            # For GET requests, body goes as query parameters
            if isinstance(body, dict):
                kwargs['params'] = body
        elif method == 'DELETE':
            # DELETE typically doesn't have a body
            pass
        else:
            # For POST, PUT, PATCH - send JSON body
            kwargs['json'] = body

        # Make the request
        response = requests.request(method, **kwargs)

        # Raise exception for HTTP errors (4xx, 5xx)
        response.raise_for_status()

        return response

    def _is_valid_url(self, url: str) -> bool:
        """
        Check if URL has a valid format.

        Args:
            url: URL string to validate

        Returns:
            True if URL appears valid
        """
        if not url:
            return False

        # Basic URL validation
        url_lower = url.lower()
        return url_lower.startswith('http://') or url_lower.startswith('https://')

    def _truncate_response(self, text: str) -> str:
        """
        Truncate response text for logging.

        Args:
            text: Response text

        Returns:
            Truncated text
        """
        if not text:
            return ''

        if len(text) > MAX_RESPONSE_LOG_SIZE:
            return text[:MAX_RESPONSE_LOG_SIZE] + '... (truncated)'

        return text


def execute_webhook_action(action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
    """
    Convenience function to execute webhook action.

    This is the main entry point for webhook action execution.

    Args:
        action: ECA Rule Action child document with webhook configuration
        doc: The document that triggered the ECA rule
        context: Optional additional context for template rendering

    Returns:
        ActionResult with success/failure status
    """
    handler = WebhookHandler()
    return handler.execute(action, doc, context)


def validate_webhook_action(action: Any) -> List[str]:
    """
    Validate webhook action configuration.

    Args:
        action: ECA Rule Action child document

    Returns:
        List of validation error messages
    """
    handler = WebhookHandler()
    return handler.validate(action)


# Export public API
__all__ = [
    'WebhookHandler',
    'execute_webhook_action',
    'validate_webhook_action',
]
