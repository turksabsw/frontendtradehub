# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Contract Check Module

This module provides functions to check contract requirements and block operations
when required contracts are not signed. It integrates with the Contract Center's
Contract Rule and Contract DocTypes.

Key functions:
- check_contract_requirements: Check if any contracts are required for a trigger point
- has_signed_contract: Check if a user has signed a specific contract
- get_pending_contracts: Get list of contracts user needs to sign
- block_operation_for_contracts: Raise exception if required contracts not signed
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, add_days, now_datetime
import json


class ContractBlockError(frappe.ValidationError):
    """Custom exception for contract blocking."""
    pass


def check_contract_requirements(trigger_point, user=None, context=None):
    """
    Check if there are any contract requirements for a given trigger point.

    Args:
        trigger_point (str): The trigger point to check (e.g., 'First Order',
                            'Registration', 'Profile Update')
        user (str): User to check for. Defaults to current user.
        context (dict): Additional context for rule evaluation. May include:
                       - user_type: 'Seller' or 'Buyer'
                       - entity_type: 'Individual', 'Business', 'Enterprise'
                       - seller_level: Seller level for level-specific rules
                       - buyer_level: Buyer level for level-specific rules
                       - order_total: Order total for threshold-based rules
                       - doctype: The DocType being operated on
                       - docname: The document name

    Returns:
        dict: Contract requirements result containing:
            - has_requirements (bool): True if contracts are required
            - blocking (bool): True if operation should be blocked
            - contracts (list): List of required contracts with details
            - signed_contracts (list): List of already signed contracts
            - pending_contracts (list): List of contracts needing signature
            - message (str): User-friendly message about requirements
    """
    user = user or frappe.session.user
    context = context or {}

    result = {
        "has_requirements": False,
        "blocking": False,
        "contracts": [],
        "signed_contracts": [],
        "pending_contracts": [],
        "message": None,
        "trigger_point": trigger_point,
        "user": user
    }

    # Get applicable contract rules from Contract Center
    try:
        from tr_contract_center.tr_contract_center.doctype.contract_rule.contract_rule import (
            get_applicable_rules
        )
        applicable_rules = get_applicable_rules(trigger_point, user, context)
    except ImportError:
        # Contract Center not installed or import failed
        frappe.log_error(
            message="Contract Center not available for contract checks",
            title=_("Contract Check Import Error")
        )
        return result
    except Exception as e:
        frappe.log_error(
            message=str(e),
            title=_("Contract Rule Evaluation Error")
        )
        return result

    if not applicable_rules:
        return result

    result["has_requirements"] = True
    result["contracts"] = applicable_rules

    # Check which contracts have been signed
    for rule in applicable_rules:
        contract_template = rule.get("contract_template")
        is_signed = has_signed_contract(user, contract_template, context)

        contract_info = {
            "rule": rule.get("rule"),
            "rule_name": rule.get("rule_name"),
            "contract_template": contract_template,
            "blocking": rule.get("blocking", False),
            "priority": rule.get("priority", 0),
            "is_signed": is_signed
        }

        # Get template details
        try:
            template_doc = frappe.get_doc("Contract Template", contract_template)
            contract_info["contract_title"] = template_doc.template_name
            contract_info["contract_description"] = template_doc.description
        except Exception:
            contract_info["contract_title"] = contract_template
            contract_info["contract_description"] = ""

        if is_signed:
            result["signed_contracts"].append(contract_info)
        else:
            result["pending_contracts"].append(contract_info)
            if rule.get("blocking"):
                result["blocking"] = True

    # Generate message
    if result["pending_contracts"]:
        pending_count = len(result["pending_contracts"])
        blocking_count = sum(1 for c in result["pending_contracts"] if c.get("blocking"))

        if blocking_count > 0:
            result["message"] = _(
                "You must accept {0} contract(s) before you can proceed with this operation."
            ).format(blocking_count)
        else:
            result["message"] = _(
                "There are {0} optional contract(s) available for review."
            ).format(pending_count)
    else:
        result["message"] = _("All required contracts have been signed.")

    return result


def has_signed_contract(user, contract_template, context=None):
    """
    Check if a user has signed a specific contract template.

    Args:
        user (str): User to check
        contract_template (str): Contract Template name/ID
        context (dict): Additional context (may include auto_expire handling)

    Returns:
        bool: True if contract is signed and still valid
    """
    if not user or not contract_template:
        return False

    context = context or {}

    try:
        # Check for signed contracts
        # Assuming there's a Contract DocType that stores signed contracts
        filters = {
            "user": user,
            "contract_template": contract_template,
            "status": ["in", ["Signed", "Active", "Accepted"]]
        }

        signed_contracts = frappe.get_all(
            "Contract",
            filters=filters,
            fields=["name", "signed_at", "expires_at", "status"],
            order_by="signed_at desc",
            limit=1
        )

        if not signed_contracts:
            return False

        contract = signed_contracts[0]

        # Check if contract has expired
        if contract.get("expires_at"):
            if getdate(contract.get("expires_at")) < getdate(nowdate()):
                return False

        return True

    except Exception as e:
        # If Contract DocType doesn't exist or other error, log and return False
        # This allows the system to work even if Contract Center is partially set up
        if "Contract" not in str(e) or "does not exist" not in str(e):
            frappe.log_error(
                message=str(e),
                title=_("Contract Check Error")
            )
        return False


def get_pending_contracts(user=None, trigger_point=None, context=None):
    """
    Get list of pending contracts that user needs to sign.

    Args:
        user (str): User to check. Defaults to current user.
        trigger_point (str): Optional trigger point to filter contracts.
                            If None, returns all pending contracts.
        context (dict): Additional context for rule evaluation.

    Returns:
        list: List of pending contract details
    """
    user = user or frappe.session.user
    context = context or {}

    if trigger_point:
        # Get contracts for specific trigger point
        requirements = check_contract_requirements(trigger_point, user, context)
        return requirements.get("pending_contracts", [])

    # Get all pending contracts across all trigger points
    pending = []
    trigger_points = [
        "Registration",
        "First Order",
        "First Sale",
        "Profile Update",
        "Subscription Change",
        "Level Upgrade",
        "Verification Complete",
        "Document Upload",
        "Payment Method Add"
    ]

    seen_templates = set()

    for tp in trigger_points:
        requirements = check_contract_requirements(tp, user, context)
        for contract in requirements.get("pending_contracts", []):
            template = contract.get("contract_template")
            if template not in seen_templates:
                seen_templates.add(template)
                contract["trigger_points"] = [tp]
                pending.append(contract)
            else:
                # Add trigger point to existing contract
                for p in pending:
                    if p.get("contract_template") == template:
                        p.setdefault("trigger_points", []).append(tp)
                        break

    return pending


def block_operation_for_contracts(doc, trigger_point, context=None):
    """
    Block an operation if required contracts are not signed.

    This function should be called from doc_events hooks (before_submit,
    before_save, etc.) to enforce contract requirements.

    Args:
        doc: The document being operated on
        trigger_point (str): The trigger point for this operation
        context (dict): Additional context. If not provided, will be built
                       from the document.

    Raises:
        ContractBlockError: If blocking contracts are not signed

    Returns:
        dict: Contract requirements result (if not blocked)
    """
    user = frappe.session.user

    # Build context from document if not provided
    if context is None:
        context = build_context_from_doc(doc)

    # Check contract requirements
    requirements = check_contract_requirements(trigger_point, user, context)

    if not requirements.get("blocking"):
        return requirements

    # Get blocking contracts
    blocking_contracts = [
        c for c in requirements.get("pending_contracts", [])
        if c.get("blocking")
    ]

    if not blocking_contracts:
        return requirements

    # Build error message with contract details
    contract_names = [
        c.get("contract_title") or c.get("contract_template")
        for c in blocking_contracts
    ]

    error_msg = _(
        "This operation requires you to accept the following contract(s): {0}"
    ).format(", ".join(contract_names))

    # Add link to contract acceptance page if available
    error_msg += "<br><br>" + _(
        "Please review and accept the required contracts before proceeding."
    )

    # Trigger the contract rules to record the block attempt
    for contract in blocking_contracts:
        try:
            from tr_contract_center.tr_contract_center.doctype.contract_rule.contract_rule import (
                trigger_rule
            )
            trigger_rule(contract.get("rule"), user, context)
        except Exception:
            pass  # Non-critical - just for statistics

    # Raise the blocking error
    raise ContractBlockError(error_msg)


def build_context_from_doc(doc):
    """
    Build context dictionary from a document for contract rule evaluation.

    Args:
        doc: The document to extract context from

    Returns:
        dict: Context dictionary for contract rule evaluation
    """
    context = {
        "doctype": doc.doctype,
        "docname": doc.name,
        "user": frappe.session.user
    }

    # Add user type
    user_roles = frappe.get_roles(frappe.session.user)
    if "Seller" in user_roles:
        context["user_type"] = "Seller"
    elif "Buyer" in user_roles:
        context["user_type"] = "Buyer"
    else:
        context["user_type"] = "User"

    # Try to get entity type from profile
    try:
        if context["user_type"] == "Seller":
            seller_profile = frappe.db.get_value(
                "Seller Profile",
                {"user": frappe.session.user},
                ["name", "seller_type", "seller_level"],
                as_dict=True
            )
            if seller_profile:
                context["entity_type"] = seller_profile.get("seller_type")
                context["seller_level"] = seller_profile.get("seller_level")
                context["seller_profile"] = seller_profile.get("name")
        elif context["user_type"] == "Buyer":
            buyer_profile = frappe.db.get_value(
                "Buyer Profile",
                {"user": frappe.session.user},
                ["name", "buyer_type", "buyer_level"],
                as_dict=True
            )
            if buyer_profile:
                context["entity_type"] = buyer_profile.get("buyer_type")
                context["buyer_level"] = buyer_profile.get("buyer_level")
                context["buyer_profile"] = buyer_profile.get("name")
    except Exception:
        pass

    # Add document-specific context
    if hasattr(doc, "grand_total"):
        context["order_total"] = doc.grand_total

    if hasattr(doc, "total"):
        context["order_total"] = doc.total

    if hasattr(doc, "seller"):
        context["seller"] = doc.seller

    if hasattr(doc, "buyer"):
        context["buyer"] = doc.buyer

    if hasattr(doc, "organization"):
        context["organization"] = doc.organization

    if hasattr(doc, "tenant"):
        context["tenant"] = doc.tenant

    return context


def check_first_order_contracts(doc, method=None):
    """
    Check contract requirements for first order trigger.
    Called from doc_events on Marketplace Order.

    Args:
        doc: Marketplace Order document
        method: The method that triggered this check
    """
    user = doc.buyer or frappe.session.user

    # Check if this is the user's first order
    existing_orders = frappe.db.count(
        "Marketplace Order",
        filters={
            "buyer": user,
            "name": ["!=", doc.name],
            "docstatus": ["in", [0, 1]]  # Draft or submitted
        }
    )

    if existing_orders > 0:
        # Not first order, skip first order contracts
        return

    context = build_context_from_doc(doc)
    context["is_first_order"] = True

    block_operation_for_contracts(doc, "First Order", context)


def check_first_sale_contracts(doc, method=None):
    """
    Check contract requirements for first sale trigger.
    Called from doc_events on Sub Order.

    Args:
        doc: Sub Order document
        method: The method that triggered this check
    """
    seller = doc.seller
    if not seller:
        return

    # Get the user for this seller
    seller_user = frappe.db.get_value("Seller Profile", seller, "user")
    if not seller_user:
        return

    # Check if this is the seller's first sale
    existing_sales = frappe.db.count(
        "Sub Order",
        filters={
            "seller": seller,
            "name": ["!=", doc.name],
            "docstatus": ["in", [0, 1]]
        }
    )

    if existing_sales > 0:
        return

    context = build_context_from_doc(doc)
    context["is_first_sale"] = True
    context["seller_user"] = seller_user

    # Check contracts for the seller user
    requirements = check_contract_requirements("First Sale", seller_user, context)

    if requirements.get("blocking"):
        blocking_contracts = [
            c for c in requirements.get("pending_contracts", [])
            if c.get("blocking")
        ]

        if blocking_contracts:
            contract_names = [
                c.get("contract_title") or c.get("contract_template")
                for c in blocking_contracts
            ]

            error_msg = _(
                "The seller must accept the following contract(s) before completing this sale: {0}"
            ).format(", ".join(contract_names))

            raise ContractBlockError(error_msg)


def check_registration_contracts(doc, method=None):
    """
    Check contract requirements for registration trigger.
    Called from doc_events on Seller Application or User.

    Args:
        doc: Document being registered
        method: The method that triggered this check
    """
    if doc.doctype == "Seller Application":
        user = doc.user_email or frappe.session.user
    else:
        user = doc.name if doc.doctype == "User" else frappe.session.user

    context = build_context_from_doc(doc)
    block_operation_for_contracts(doc, "Registration", context)


def check_profile_update_contracts(doc, method=None):
    """
    Check contract requirements for profile update trigger.
    Called from doc_events on Seller Profile or Buyer Profile.

    Args:
        doc: Profile document being updated
        method: The method that triggered this check
    """
    # Only check on update, not insert
    if doc.is_new():
        return

    context = build_context_from_doc(doc)
    block_operation_for_contracts(doc, "Profile Update", context)


def check_subscription_change_contracts(doc, method=None):
    """
    Check contract requirements for subscription changes.
    Called from doc_events on subscription-related documents.

    Args:
        doc: Document being changed
        method: The method that triggered this check
    """
    context = build_context_from_doc(doc)
    block_operation_for_contracts(doc, "Subscription Change", context)


def check_payment_method_contracts(doc, method=None):
    """
    Check contract requirements for adding payment methods.
    Called from doc_events on payment method documents.

    Args:
        doc: Payment method document
        method: The method that triggered this check
    """
    context = build_context_from_doc(doc)
    block_operation_for_contracts(doc, "Payment Method Add", context)


@frappe.whitelist()
def get_contract_requirements(trigger_point, context=None):
    """
    API endpoint to get contract requirements for a trigger point.

    Args:
        trigger_point (str): The trigger point to check
        context (str/dict): Optional JSON context

    Returns:
        dict: Contract requirements
    """
    if isinstance(context, str):
        context = json.loads(context)

    return check_contract_requirements(trigger_point, context=context)


@frappe.whitelist()
def get_all_pending_contracts():
    """
    API endpoint to get all pending contracts for current user.

    Returns:
        list: List of pending contracts
    """
    return get_pending_contracts()


@frappe.whitelist()
def get_pending_contracts_for_trigger(trigger_point, context=None):
    """
    API endpoint to get pending contracts for a specific trigger point.

    Args:
        trigger_point (str): The trigger point to check
        context (str/dict): Optional JSON context

    Returns:
        list: List of pending contracts
    """
    if isinstance(context, str):
        context = json.loads(context)

    return get_pending_contracts(trigger_point=trigger_point, context=context)


@frappe.whitelist()
def check_can_proceed(trigger_point, context=None):
    """
    API endpoint to check if user can proceed with an operation.

    Args:
        trigger_point (str): The trigger point to check
        context (str/dict): Optional JSON context

    Returns:
        dict: Result with can_proceed flag and details
    """
    if isinstance(context, str):
        context = json.loads(context)

    requirements = check_contract_requirements(trigger_point, context=context)

    return {
        "can_proceed": not requirements.get("blocking"),
        "has_requirements": requirements.get("has_requirements"),
        "pending_count": len(requirements.get("pending_contracts", [])),
        "blocking_count": sum(
            1 for c in requirements.get("pending_contracts", [])
            if c.get("blocking")
        ),
        "message": requirements.get("message"),
        "pending_contracts": requirements.get("pending_contracts", [])
    }


@frappe.whitelist()
def record_contract_acceptance(contract_template, context=None):
    """
    Record that a user has accepted a contract.

    This creates a Contract document linking the user to the contract template.

    Args:
        contract_template (str): Contract Template name
        context (str/dict): Optional context (may include rule_name for statistics)

    Returns:
        dict: Result with contract name
    """
    if isinstance(context, str):
        context = json.loads(context)

    context = context or {}
    user = frappe.session.user

    # Check if already signed
    if has_signed_contract(user, contract_template, context):
        return {
            "success": False,
            "message": _("Contract already signed"),
            "already_signed": True
        }

    try:
        # Create Contract document
        contract = frappe.new_doc("Contract")
        contract.user = user
        contract.contract_template = contract_template
        contract.status = "Signed"
        contract.signed_at = now_datetime()

        # Set expiry if specified in context or rule
        rule_name = context.get("rule_name")
        if rule_name:
            rule = frappe.get_doc("Contract Rule", rule_name)
            if rule.auto_expire and rule.expire_after_days:
                contract.expires_at = add_days(nowdate(), rule.expire_after_days)

            # Record acceptance in rule statistics
            rule.record_acceptance()

        # Get template details
        template = frappe.get_doc("Contract Template", contract_template)
        contract.contract_version = template.version if hasattr(template, "version") else "1.0"

        contract.flags.ignore_permissions = True
        contract.insert()

        return {
            "success": True,
            "message": _("Contract accepted successfully"),
            "contract": contract.name
        }

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title=_("Contract Acceptance Error")
        )
        return {
            "success": False,
            "message": str(e)
        }
