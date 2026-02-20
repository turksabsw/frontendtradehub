# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Generic E-Sign Provider Adapter

A generic adapter that can be used as a template or for testing.
"""

import frappe
from frappe import _
from typing import Optional, Dict, Any
import hashlib

from tr_contract_center.esign.base import ESignProviderBase


class GenericESignAdapter(ESignProviderBase):
    """
    Generic adapter for e-signature providers.

    Can be used as a base for custom integrations or for testing.
    """

    def create_signing_request(
        self,
        contract_instance: str,
        document_content: str,
        signer_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a generic signing request.
        """
        try:
            doc_hash = hashlib.sha256(document_content.encode()).hexdigest()

            external_id = f"GENERIC-{contract_instance}-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"

            # Store transaction
            transaction = frappe.get_doc({
                "doctype": "ESign Transaction",
                "provider": self.provider_doc.name,
                "contract_instance": contract_instance,
                "external_id": external_id,
                "status": "Initiated",
                "document_hash": doc_hash,
                "signer_email": signer_info.get("email"),
                "signer_name": signer_info.get("name")
            })
            transaction.insert(ignore_permissions=True)

            self.log_transaction("CREATE", external_id, f"Contract: {contract_instance}")

            # Build signing URL based on provider configuration
            signing_url = f"{self.api_url or '/sign'}/{external_id}"
            if self.callback_url:
                signing_url += f"?callback={self.callback_url}"

            return {
                "success": True,
                "external_id": external_id,
                "signing_url": signing_url,
                "expires_at": frappe.utils.add_days(frappe.utils.now_datetime(), 7),
                "transaction_name": transaction.name
            }

        except Exception as e:
            frappe.log_error(f"Generic E-Sign create error: {str(e)}", "ESign")
            return {
                "success": False,
                "error": str(e)
            }

    def check_status(self, external_id: str) -> Optional[str]:
        """
        Check status from local transaction record.
        """
        try:
            status = frappe.db.get_value(
                "ESign Transaction",
                {"external_id": external_id},
                "status"
            )
            return status

        except Exception as e:
            frappe.log_error(f"Generic E-Sign status check error: {str(e)}", "ESign")
            return None

    def get_signed_document(self, external_id: str) -> Optional[bytes]:
        """
        Get signed document from local storage.
        """
        try:
            transaction = frappe.db.get_value(
                "ESign Transaction",
                {"external_id": external_id},
                ["signed_pdf", "status"],
                as_dict=True
            )

            if transaction and transaction.status == "Completed" and transaction.signed_pdf:
                file_doc = frappe.get_doc("File", {"file_url": transaction.signed_pdf})
                return file_doc.get_content()

            return None

        except Exception as e:
            frappe.log_error(f"Generic E-Sign get document error: {str(e)}", "ESign")
            return None


def simulate_signature_completion(external_id: str, signed_pdf_path: str = None):
    """
    Utility function to simulate signature completion for testing.

    Args:
        external_id: Transaction external ID
        signed_pdf_path: Optional path to signed PDF file
    """
    transaction = frappe.get_doc(
        "ESign Transaction",
        {"external_id": external_id}
    )

    transaction.status = "Completed"
    transaction.signed_at = frappe.utils.now_datetime()

    if signed_pdf_path:
        transaction.signed_pdf = signed_pdf_path

    transaction.save(ignore_permissions=True)

    # Update contract instance
    if transaction.contract_instance:
        contract = frappe.get_doc("Contract Instance", transaction.contract_instance)
        contract.status = "Signed"
        contract.signed_at = frappe.utils.now_datetime()
        if signed_pdf_path:
            contract.signed_pdf = signed_pdf_path
        contract.save()

    frappe.db.commit()
