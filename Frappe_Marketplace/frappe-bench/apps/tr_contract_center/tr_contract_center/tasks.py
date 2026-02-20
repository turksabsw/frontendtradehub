# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR Contract Center Scheduled Tasks
"""

import frappe
from frappe import _
from frappe.utils import today, add_days, getdate


def check_expiring_contracts():
    """
    Daily task: Check for contracts expiring in the next 30 days.
    """
    expiry_threshold = add_days(today(), 30)

    expiring = frappe.get_all(
        "Contract Instance",
        filters={
            "status": "Signed",
            "expiry_date": ["<=", expiry_threshold],
            "expiry_date": [">", today()]
        },
        fields=["name", "party_type", "party", "expiry_date"]
    )

    for contract in expiring:
        frappe.logger().info(
            f"Contract {contract.name} expiring on {contract.expiry_date}"
        )
        # TODO: Send notification

    if expiring:
        frappe.logger().info(
            f"TR Contract Center: Found {len(expiring)} contracts expiring within 30 days"
        )

    frappe.db.commit()


def check_pending_signatures():
    """
    Daily task: Check for contracts pending signature for more than 7 days.
    """
    threshold = add_days(today(), -7)

    pending = frappe.get_all(
        "Contract Instance",
        filters={
            "status": "Pending Signature",
            "sent_at": ["<", threshold]
        },
        fields=["name", "party_type", "party", "sent_at"]
    )

    for contract in pending:
        frappe.logger().info(
            f"Contract {contract.name} pending signature since {contract.sent_at}"
        )
        # TODO: Send reminder

    frappe.db.commit()


def poll_esign_status():
    """
    Hourly task: Poll e-sign providers for status updates on pending transactions.
    """
    pending_transactions = frappe.get_all(
        "ESign Transaction",
        filters={
            "status": ["in", ["Initiated", "Pending"]]
        },
        fields=["name", "provider", "external_id", "contract_instance"]
    )

    for transaction in pending_transactions:
        try:
            # Import provider adapter
            from tr_contract_center.esign import get_provider_adapter

            adapter = get_provider_adapter(transaction.provider)
            if adapter:
                status = adapter.check_status(transaction.external_id)

                if status and status != transaction.status:
                    frappe.db.set_value(
                        "ESign Transaction",
                        transaction.name,
                        "status",
                        status
                    )

                    # Update contract if signed
                    if status == "Completed":
                        contract = frappe.get_doc(
                            "Contract Instance",
                            transaction.contract_instance
                        )
                        contract.status = "Signed"
                        contract.signed_at = frappe.utils.now_datetime()
                        contract.save()

        except Exception as e:
            frappe.log_error(
                f"Error polling e-sign status for {transaction.name}: {str(e)}",
                "ESign Status Poll"
            )

    frappe.db.commit()
