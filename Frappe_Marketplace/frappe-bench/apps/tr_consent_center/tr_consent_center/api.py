# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR Consent Center API Endpoints

These endpoints provide a REST API for consent management.
All endpoints follow the standard response format:
{
    "success": bool,
    "data": {},
    "message": "str",
    "errors": []
}

KVKK/GDPR Compliance:
- All consent operations are logged
- IP addresses are captured for audit
- Verification (double opt-in) is supported
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, today, getdate
import json


def _api_response(success=True, data=None, message=None, errors=None):
    """Standard API response format."""
    return {
        "success": success,
        "data": data or {},
        "message": message or "",
        "errors": errors or []
    }


@frappe.whitelist(allow_guest=False)
def grant_consent(party_type, party, topic, method=None, channel=None,
                  consent_text=None, ip_address=None, user_agent=None,
                  source_url=None, requires_verification=False):
    """
    Grant consent for a party.

    Args:
        party_type: DocType of the party (e.g., 'User', 'Customer')
        party: Name/ID of the party
        topic: Consent topic name or code
        method: Optional consent method name or code
        channel: Optional consent channel name or code
        consent_text: Optional consent text name
        ip_address: IP address of the user
        user_agent: Browser/device information
        source_url: URL where consent was collected
        requires_verification: Whether to require double opt-in

    Returns:
        dict: API response with consent record details
    """
    try:
        # Resolve topic by code if needed
        topic_name = _resolve_topic(topic)
        if not topic_name:
            return _api_response(False, message=_("Invalid consent topic: {0}").format(topic))

        # Resolve method if provided
        method_name = _resolve_method(method) if method else None

        # Resolve channel if provided
        channel_name = _resolve_channel(channel) if channel else None

        # Get current consent text if not provided
        if not consent_text:
            consent_text = _get_current_consent_text(topic_name)

        # Create consent record
        status = "Pending" if requires_verification else "Active"

        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": party_type,
            "party": party,
            "consent_topic": topic_name,
            "consent_method": method_name,
            "consent_channel": channel_name,
            "consent_text": consent_text,
            "status": status,
            "granted_at": now_datetime(),
            "granted_by": frappe.session.user,
            "ip_address": ip_address or getattr(frappe.local, 'request_ip', None),
            "user_agent": user_agent,
            "source_url": source_url
        })

        doc.insert()
        frappe.db.commit()

        result = {
            "consent_record": doc.name,
            "status": doc.status,
            "granted_at": str(doc.granted_at),
            "requires_verification": requires_verification,
            "verification_url": _get_verification_url(doc.name, doc.verification_token) if requires_verification else None
        }

        return _api_response(True, data=result, message=_("Consent granted successfully"))

    except Exception as e:
        frappe.log_error(f"grant_consent error: {str(e)}", "Consent Center API")
        return _api_response(False, message=str(e), errors=[str(e)])


@frappe.whitelist(allow_guest=False)
def revoke_consent(consent_record=None, party_type=None, party=None, topic=None,
                   reason=None, ip_address=None):
    """
    Revoke consent.

    Can be called with either:
    - consent_record: Name of the specific consent record
    - party_type + party + topic: To find and revoke matching consent

    Args:
        consent_record: Name of consent record (optional)
        party_type: DocType of the party (optional)
        party: Name/ID of the party (optional)
        topic: Consent topic name or code (optional)
        reason: Reason for revocation
        ip_address: IP address of user revoking

    Returns:
        dict: API response
    """
    try:
        # Find consent record if not provided
        if not consent_record:
            if not (party_type and party and topic):
                return _api_response(
                    False,
                    message=_("Either consent_record or (party_type, party, topic) required")
                )

            topic_name = _resolve_topic(topic)
            consent_record = frappe.db.get_value(
                "Consent Record",
                {
                    "party_type": party_type,
                    "party": party,
                    "consent_topic": topic_name,
                    "status": "Active"
                },
                "name"
            )

            if not consent_record:
                return _api_response(
                    False,
                    message=_("No active consent found for the specified party and topic")
                )

        # Get and revoke the consent
        doc = frappe.get_doc("Consent Record", consent_record)

        if doc.status != "Active":
            return _api_response(
                False,
                message=_("Consent is not active. Current status: {0}").format(doc.status)
            )

        doc.status = "Revoked"
        doc.revoked_at = now_datetime()
        doc.revoked_by = frappe.session.user
        doc.revocation_reason = reason
        doc.revocation_ip_address = ip_address or getattr(frappe.local, 'request_ip', None)
        doc.save()
        frappe.db.commit()

        return _api_response(
            True,
            data={
                "consent_record": doc.name,
                "status": "Revoked",
                "revoked_at": str(doc.revoked_at)
            },
            message=_("Consent revoked successfully")
        )

    except Exception as e:
        frappe.log_error(f"revoke_consent error: {str(e)}", "Consent Center API")
        return _api_response(False, message=str(e), errors=[str(e)])


@frappe.whitelist(allow_guest=False)
def get_consents(party_type, party, topic=None, status=None, include_expired=False):
    """
    Get all consents for a party.

    Args:
        party_type: DocType of the party
        party: Name/ID of the party
        topic: Optional topic filter (name or code)
        status: Optional status filter
        include_expired: Include expired consents

    Returns:
        dict: API response with list of consents
    """
    try:
        filters = {
            "party_type": party_type,
            "party": party
        }

        if topic:
            filters["consent_topic"] = _resolve_topic(topic)

        if status:
            filters["status"] = status
        elif not include_expired:
            filters["status"] = ["in", ["Active", "Pending"]]

        consents = frappe.get_all(
            "Consent Record",
            filters=filters,
            fields=[
                "name", "consent_topic", "consent_method", "consent_channel",
                "status", "granted_at", "expiry_date", "is_verified",
                "consent_text", "consent_text_version"
            ],
            order_by="granted_at desc"
        )

        # Enrich with topic details
        for consent in consents:
            topic_data = frappe.db.get_value(
                "Consent Topic",
                consent.consent_topic,
                ["topic_name", "topic_code", "category"],
                as_dict=True
            )
            if topic_data:
                consent["topic_name"] = topic_data.topic_name
                consent["topic_code"] = topic_data.topic_code
                consent["topic_category"] = topic_data.category

        return _api_response(
            True,
            data={"consents": consents, "total": len(consents)},
            message=_("Found {0} consent(s)").format(len(consents))
        )

    except Exception as e:
        frappe.log_error(f"get_consents error: {str(e)}", "Consent Center API")
        return _api_response(False, message=str(e), errors=[str(e)])


@frappe.whitelist(allow_guest=True)
def get_current_text(topic, language="tr"):
    """
    Get the current active consent text for a topic.

    This endpoint is guest-accessible as consent text must be
    shown to users before they authenticate.

    Args:
        topic: Consent topic name or code
        language: Language code (default: Turkish)

    Returns:
        dict: API response with consent text details
    """
    try:
        topic_name = _resolve_topic(topic)
        if not topic_name:
            return _api_response(False, message=_("Invalid consent topic: {0}").format(topic))

        text = frappe.db.get_value(
            "Consent Text",
            {
                "consent_topic": topic_name,
                "is_current": 1,
                "status": "Active"
            },
            ["name", "title", "content", "content_summary", "version",
             "content_hash", "effective_date", "legal_references",
             "data_categories_covered", "processing_purposes"],
            as_dict=True
        )

        if not text:
            return _api_response(
                False,
                message=_("No active consent text found for topic: {0}").format(topic)
            )

        return _api_response(
            True,
            data={"consent_text": text},
            message=_("Consent text retrieved successfully")
        )

    except Exception as e:
        frappe.log_error(f"get_current_text error: {str(e)}", "Consent Center API")
        return _api_response(False, message=str(e), errors=[str(e)])


@frappe.whitelist(allow_guest=False)
def verify_consent(consent_record, verification_token=None):
    """
    Verify a pending consent (double opt-in completion).

    Args:
        consent_record: Name of the consent record
        verification_token: Token sent to user for verification

    Returns:
        dict: API response
    """
    try:
        doc = frappe.get_doc("Consent Record", consent_record)

        if doc.status != "Pending":
            return _api_response(
                False,
                message=_("Consent is not pending verification. Status: {0}").format(doc.status)
            )

        # Verify token if provided
        if verification_token and doc.verification_token != verification_token:
            return _api_response(False, message=_("Invalid verification token"))

        doc.status = "Active"
        doc.is_verified = 1
        doc.verified_at = now_datetime()
        doc.double_opt_in_completed = 1
        doc.save()
        frappe.db.commit()

        return _api_response(
            True,
            data={
                "consent_record": doc.name,
                "status": "Active",
                "verified_at": str(doc.verified_at)
            },
            message=_("Consent verified successfully")
        )

    except Exception as e:
        frappe.log_error(f"verify_consent error: {str(e)}", "Consent Center API")
        return _api_response(False, message=str(e), errors=[str(e)])


@frappe.whitelist(allow_guest=False)
def check_consent(party_type, party, topic, method=None):
    """
    Check if a party has active consent for a topic.

    Args:
        party_type: DocType of the party
        party: Name/ID of the party
        topic: Consent topic name or code
        method: Optional method filter

    Returns:
        dict: API response with consent status
    """
    try:
        topic_name = _resolve_topic(topic)
        if not topic_name:
            return _api_response(False, message=_("Invalid consent topic: {0}").format(topic))

        filters = {
            "party_type": party_type,
            "party": party,
            "consent_topic": topic_name,
            "status": "Active"
        }

        if method:
            filters["consent_method"] = _resolve_method(method)

        consent_record = frappe.db.get_value("Consent Record", filters, "name")

        return _api_response(
            True,
            data={
                "has_consent": bool(consent_record),
                "consent_record": consent_record
            },
            message=_("Consent check completed")
        )

    except Exception as e:
        frappe.log_error(f"check_consent error: {str(e)}", "Consent Center API")
        return _api_response(False, message=str(e), errors=[str(e)])


@frappe.whitelist(allow_guest=False)
def get_audit_trail(consent_record):
    """
    Get the audit trail for a consent record.

    Args:
        consent_record: Name of the consent record

    Returns:
        dict: API response with audit log entries
    """
    try:
        if not frappe.db.exists("Consent Record", consent_record):
            return _api_response(False, message=_("Consent record not found"))

        logs = frappe.get_all(
            "Consent Audit Log",
            filters={"consent_record": consent_record},
            fields=["name", "action", "action_by", "action_date",
                    "details", "ip_address", "old_status", "new_status"],
            order_by="action_date asc"
        )

        return _api_response(
            True,
            data={"audit_logs": logs, "total": len(logs)},
            message=_("Audit trail retrieved successfully")
        )

    except Exception as e:
        frappe.log_error(f"get_audit_trail error: {str(e)}", "Consent Center API")
        return _api_response(False, message=str(e), errors=[str(e)])


# Helper functions

def _resolve_topic(topic):
    """Resolve topic name from name or code."""
    if not topic:
        return None

    # First try exact match
    if frappe.db.exists("Consent Topic", topic):
        return topic

    # Try by code
    return frappe.db.get_value(
        "Consent Topic",
        {"topic_code": topic.upper()},
        "name"
    )


def _resolve_method(method):
    """Resolve method name from name or code."""
    if not method:
        return None

    if frappe.db.exists("Consent Method", method):
        return method

    return frappe.db.get_value(
        "Consent Method",
        {"method_code": method.upper()},
        "name"
    )


def _resolve_channel(channel):
    """Resolve channel name from name or code."""
    if not channel:
        return None

    if frappe.db.exists("Consent Channel", channel):
        return channel

    return frappe.db.get_value(
        "Consent Channel",
        {"channel_code": channel.upper()},
        "name"
    )


def _get_current_consent_text(topic_name):
    """Get the current active consent text for a topic."""
    return frappe.db.get_value(
        "Consent Text",
        {
            "consent_topic": topic_name,
            "is_current": 1,
            "status": "Active"
        },
        "name"
    )


def _get_verification_url(consent_record, token):
    """Generate verification URL for double opt-in."""
    # This would be customized based on your site URL
    site_url = frappe.utils.get_url()
    return f"{site_url}/api/method/tr_consent_center.api.verify_consent?consent_record={consent_record}&verification_token={token}"
