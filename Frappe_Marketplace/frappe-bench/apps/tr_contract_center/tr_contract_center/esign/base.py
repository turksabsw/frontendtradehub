# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Base E-Sign Provider Adapter

Abstract base class for all e-signature provider integrations.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import frappe


class ESignProviderBase(ABC):
    """
    Abstract base class for e-signature provider adapters.

    All provider adapters must implement these methods.
    """

    def __init__(self, provider_doc):
        """
        Initialize the adapter with provider configuration.

        Args:
            provider_doc: The ESign Provider document
        """
        self.provider_doc = provider_doc
        self.api_key = provider_doc.api_key
        self.api_secret = provider_doc.get_password("api_secret") if provider_doc.api_secret else None
        self.api_url = provider_doc.api_url
        self.callback_url = provider_doc.callback_url

    @abstractmethod
    def create_signing_request(
        self,
        contract_instance: str,
        document_content: str,
        signer_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a new signing request with the provider.

        Args:
            contract_instance: Name of the Contract Instance
            document_content: HTML/PDF content to be signed
            signer_info: Dictionary with signer details (name, email, phone, tckn)

        Returns:
            dict: {
                "success": bool,
                "external_id": str,  # Provider's transaction ID
                "signing_url": str,  # URL for signer to complete signature
                "expires_at": datetime,
                "error": str  # If success is False
            }
        """
        pass

    @abstractmethod
    def check_status(self, external_id: str) -> Optional[str]:
        """
        Check the status of a signing request.

        Args:
            external_id: The provider's transaction ID

        Returns:
            str: Status ("Pending", "Completed", "Rejected", "Expired") or None if error
        """
        pass

    @abstractmethod
    def get_signed_document(self, external_id: str) -> Optional[bytes]:
        """
        Retrieve the signed document from the provider.

        Args:
            external_id: The provider's transaction ID

        Returns:
            bytes: Signed PDF content or None if not available
        """
        pass

    def cancel_request(self, external_id: str) -> bool:
        """
        Cancel a pending signing request.

        Args:
            external_id: The provider's transaction ID

        Returns:
            bool: True if cancelled successfully
        """
        # Default implementation - override if provider supports cancellation
        return False

    def validate_callback(self, payload: Dict[str, Any], signature: str) -> bool:
        """
        Validate a callback from the provider.

        Args:
            payload: The callback payload
            signature: The signature header from the callback

        Returns:
            bool: True if callback is valid
        """
        # Default implementation - override for specific validation
        return True

    def process_callback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a callback from the provider.

        Args:
            payload: The callback payload

        Returns:
            dict: {
                "external_id": str,
                "status": str,
                "signed_at": datetime,
                "signer_info": dict
            }
        """
        # Default implementation - override for specific processing
        return {
            "external_id": payload.get("transaction_id") or payload.get("external_id"),
            "status": payload.get("status"),
            "signed_at": payload.get("signed_at"),
            "signer_info": payload.get("signer", {})
        }

    def log_transaction(self, action: str, external_id: str, details: str = None):
        """Log transaction activity."""
        frappe.logger().info(
            f"ESign [{self.provider_doc.name}] {action}: {external_id} - {details or ''}"
        )
