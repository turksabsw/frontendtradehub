# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Turkcell E-Sign Provider Adapter

Integration with Turkcell's mobile signature service.
"""

import frappe
from frappe import _
from typing import Optional, Dict, Any
import hashlib
import json

from tr_contract_center.esign.base import ESignProviderBase


class TurkcellESignAdapter(ESignProviderBase):
    """
    Adapter for Turkcell E-Sign service.

    Turkcell E-Sign uses mobile phone verification for signing.
    """

    def create_signing_request(
        self,
        contract_instance: str,
        document_content: str,
        signer_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a signing request with Turkcell E-Sign.

        Args:
            contract_instance: Name of the Contract Instance
            document_content: HTML/PDF content to be signed
            signer_info: Must include 'phone' (Turkish mobile number)

        Returns:
            dict: Result with external_id and signing_url
        """
        try:
            # Validate required fields
            if not signer_info.get("phone"):
                return {
                    "success": False,
                    "error": _("Phone number is required for Turkcell E-Sign")
                }

            # Generate document hash
            doc_hash = hashlib.sha256(document_content.encode()).hexdigest()

            # In production, this would call Turkcell API
            # For now, we simulate the request
            external_id = f"TURKCELL-{contract_instance}-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"

            # Store transaction
            transaction = frappe.get_doc({
                "doctype": "ESign Transaction",
                "provider": self.provider_doc.name,
                "contract_instance": contract_instance,
                "external_id": external_id,
                "status": "Initiated",
                "document_hash": doc_hash,
                "signer_phone": signer_info.get("phone"),
                "signer_name": signer_info.get("name"),
                "signer_tckn": signer_info.get("tckn")
            })
            transaction.insert(ignore_permissions=True)

            self.log_transaction("CREATE", external_id, f"Contract: {contract_instance}")

            return {
                "success": True,
                "external_id": external_id,
                "signing_url": f"{self.api_url}/sign/{external_id}",
                "expires_at": frappe.utils.add_days(frappe.utils.now_datetime(), 7),
                "transaction_name": transaction.name
            }

        except Exception as e:
            frappe.log_error(f"Turkcell E-Sign create error: {str(e)}", "ESign")
            return {
                "success": False,
                "error": str(e)
            }

    def check_status(self, external_id: str) -> Optional[str]:
        """
        Check status of a Turkcell E-Sign request.

        Args:
            external_id: Turkcell transaction ID

        Returns:
            str: Status or None
        """
        try:
            # In production, this would call Turkcell API
            # For now, return status from our transaction record
            status = frappe.db.get_value(
                "ESign Transaction",
                {"external_id": external_id},
                "status"
            )

            self.log_transaction("CHECK_STATUS", external_id, f"Status: {status}")
            return status

        except Exception as e:
            frappe.log_error(f"Turkcell E-Sign status check error: {str(e)}", "ESign")
            return None

    def get_signed_document(self, external_id: str) -> Optional[bytes]:
        """
        Get signed document from Turkcell.

        Args:
            external_id: Turkcell transaction ID

        Returns:
            bytes: Signed PDF or None
        """
        try:
            # In production, this would download from Turkcell
            # For now, check if we have a stored signed_pdf
            transaction = frappe.db.get_value(
                "ESign Transaction",
                {"external_id": external_id},
                ["signed_pdf", "status"],
                as_dict=True
            )

            if transaction and transaction.status == "Completed" and transaction.signed_pdf:
                # Get file content
                file_doc = frappe.get_doc("File", {"file_url": transaction.signed_pdf})
                return file_doc.get_content()

            return None

        except Exception as e:
            frappe.log_error(f"Turkcell E-Sign get document error: {str(e)}", "ESign")
            return None

    def validate_callback(self, payload: Dict[str, Any], signature: str) -> bool:
        """
        Validate Turkcell callback signature.

        Args:
            payload: Callback data
            signature: HMAC signature from header

        Returns:
            bool: True if valid
        """
        if not self.api_secret:
            return False

        # Calculate expected signature
        payload_str = json.dumps(payload, sort_keys=True)
        expected = hashlib.sha256(
            f"{payload_str}{self.api_secret}".encode()
        ).hexdigest()

        return signature == expected

    def process_callback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process Turkcell callback.

        Turkcell callback format:
        {
            "transaction_id": "...",
            "status": "COMPLETED|REJECTED|EXPIRED",
            "signed_at": "ISO datetime",
            "signer": {
                "phone": "...",
                "name": "..."
            }
        }
        """
        status_map = {
            "COMPLETED": "Completed",
            "REJECTED": "Rejected",
            "EXPIRED": "Expired",
            "PENDING": "Pending"
        }

        return {
            "external_id": payload.get("transaction_id"),
            "status": status_map.get(payload.get("status"), payload.get("status")),
            "signed_at": payload.get("signed_at"),
            "signer_info": payload.get("signer", {})
        }
