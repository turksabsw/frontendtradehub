# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Certificate Alerts Background Tasks.

This module provides background job functions for certificate expiry management including:
- Checking for expiring certificates based on renewal_reminder_days
- Sending expiry notifications to sellers and platform admins
- Auto-updating expired certificate status
- Generating certificate compliance reports
- Batch processing of certificate renewal reminders

The processor is designed to be:
- Multi-tenant aware (respects tenant isolation)
- Fault-tolerant (logs errors, continues processing)
- Efficient (batch processing with configurable limits)
- Non-intrusive (tracks sent reminders to avoid duplicates)

Usage in hooks.py:
    scheduler_events = {
        "cron": {
            "0 6 * * *": [
                "tr_tradehub.tasks.certificate_alerts.check_expiring_certificates"
            ]
        }
    }

Usage for single tenant:
    frappe.enqueue(
        "tr_tradehub.tasks.certificate_alerts.process_tenant_certificates",
        tenant="TENANT-001",
        queue="long"
    )
"""

from typing import Optional, Dict, Any, List
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import (
    cint,
    flt,
    nowdate,
    now_datetime,
    getdate,
    add_days,
    date_diff,
    get_datetime,
    cstr,
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default reminder days if not set on certificate type
DEFAULT_REMINDER_DAYS = 30

# Maximum certificates to process in a single batch
BATCH_SIZE = 100

# Days thresholds for notification urgency
URGENCY_LEVELS = {
    "critical": 7,      # 7 days or less
    "urgent": 14,       # 8-14 days
    "warning": 30,      # 15-30 days
    "notice": 60,       # 31-60 days
}

# Status colors for notifications
STATUS_COLORS = {
    "critical": "red",
    "urgent": "orange",
    "warning": "yellow",
    "notice": "blue",
}

# Certificate statuses that should trigger expiry checks
ACTIVE_STATUSES = ["Active", "Verified"]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_urgency_level(days_until_expiry: int) -> str:
    """
    Determine urgency level based on days until expiry.

    Args:
        days_until_expiry: Number of days until certificate expires

    Returns:
        str: Urgency level (critical, urgent, warning, notice)
    """
    if days_until_expiry <= URGENCY_LEVELS["critical"]:
        return "critical"
    elif days_until_expiry <= URGENCY_LEVELS["urgent"]:
        return "urgent"
    elif days_until_expiry <= URGENCY_LEVELS["warning"]:
        return "warning"
    else:
        return "notice"


def get_notification_subject(certificate: Dict[str, Any], urgency: str) -> str:
    """
    Generate notification subject based on certificate and urgency.

    Args:
        certificate: Certificate data dictionary
        urgency: Urgency level

    Returns:
        str: Notification subject
    """
    type_name = certificate.get("type_name", "Certificate")
    days = certificate.get("days_until_expiry", 0)

    if days <= 0:
        return _("[EXPIRED] {0} has expired").format(type_name)

    urgency_prefix = {
        "critical": "[CRITICAL]",
        "urgent": "[URGENT]",
        "warning": "[WARNING]",
        "notice": "[NOTICE]",
    }

    prefix = urgency_prefix.get(urgency, "")
    return _("{0} {1} expiring in {2} days").format(prefix, type_name, days)


def get_notification_message(certificate: Dict[str, Any]) -> str:
    """
    Generate notification message body for certificate expiry.

    Args:
        certificate: Certificate data dictionary

    Returns:
        str: Notification message body
    """
    lines = []

    cert_type = certificate.get("type_name", "Certificate")
    cert_number = certificate.get("certificate_number", "N/A")
    expiry_date = certificate.get("expiry_date", "")
    days = certificate.get("days_until_expiry", 0)

    if days <= 0:
        lines.append(_("Your {0} has expired.").format(cert_type))
    else:
        lines.append(
            _("Your {0} will expire in {1} days.").format(cert_type, days)
        )

    lines.append("")
    lines.append(_("Certificate Details:"))
    lines.append(_("- Type: {0}").format(cert_type))
    lines.append(_("- Number: {0}").format(cert_number))

    if expiry_date:
        lines.append(_("- Expiry Date: {0}").format(expiry_date))

    # Add product or seller info
    if certificate.get("product_name"):
        lines.append(_("- Product: {0}").format(certificate.get("product_name")))

    if certificate.get("seller_name"):
        lines.append(_("- Seller: {0}").format(certificate.get("seller_name")))

    lines.append("")
    lines.append(_("Please renew your certificate to maintain compliance."))

    return "\n".join(lines)


def get_certificate_owner_email(certificate: Dict[str, Any]) -> Optional[str]:
    """
    Get the email address of the certificate owner (seller).

    Args:
        certificate: Certificate data dictionary

    Returns:
        str: Email address or None
    """
    seller = certificate.get("seller")
    if seller:
        # Get seller's user email
        email = frappe.db.get_value("Seller Profile", seller, "contact_email")
        if email:
            return email

        # Fallback to user email
        user = frappe.db.get_value("Seller Profile", seller, "user")
        if user:
            return frappe.db.get_value("User", user, "email")

    return None


def get_tenant_admin_emails(tenant: str) -> List[str]:
    """
    Get email addresses of tenant admins for a given tenant.

    Args:
        tenant: Tenant document name

    Returns:
        list: List of admin email addresses
    """
    if not tenant:
        return []

    # Get users with Tenant Admin role for this tenant
    admin_emails = frappe.db.sql(
        """
        SELECT DISTINCT u.email
        FROM `tabUser` u
        INNER JOIN `tabHas Role` hr ON hr.parent = u.name
        WHERE hr.role = 'Tenant Admin'
        AND u.enabled = 1
        AND u.email IS NOT NULL
        AND u.email != ''
        """,
        as_list=True,
    )

    return [email[0] for email in admin_emails if email[0]]


# =============================================================================
# NOTIFICATION FUNCTIONS
# =============================================================================


def send_certificate_notification(
    certificate: Dict[str, Any],
    urgency: str = "notice",
    send_email: bool = True,
) -> Dict[str, Any]:
    """
    Send notification for an expiring or expired certificate.

    Args:
        certificate: Certificate data dictionary
        urgency: Urgency level for the notification
        send_email: Whether to send email notification

    Returns:
        dict: Result of notification sending
    """
    result = {
        "success": False,
        "certificate": certificate.get("name"),
        "notifications_sent": 0,
        "errors": [],
    }

    try:
        subject = get_notification_subject(certificate, urgency)
        message = get_notification_message(certificate)

        # Get recipient email
        owner_email = get_certificate_owner_email(certificate)

        if not owner_email:
            result["errors"].append("No owner email found for certificate")
            return result

        # Create system notification
        notification = frappe.new_doc("Notification Log")
        notification.for_user = frappe.db.get_value(
            "User", {"email": owner_email}, "name"
        )
        notification.type = "Alert"
        notification.document_type = "Certificate"
        notification.document_name = certificate.get("name")
        notification.subject = subject
        notification.email_content = message

        try:
            notification.insert(ignore_permissions=True)
            result["notifications_sent"] += 1
        except Exception as e:
            result["errors"].append(f"Failed to create notification: {str(e)}")

        # Send email if requested
        if send_email and owner_email:
            try:
                frappe.sendmail(
                    recipients=[owner_email],
                    subject=subject,
                    message=message,
                    delayed=True,
                    reference_doctype="Certificate",
                    reference_name=certificate.get("name"),
                )
                result["notifications_sent"] += 1
            except Exception as e:
                result["errors"].append(f"Failed to send email: {str(e)}")

        result["success"] = result["notifications_sent"] > 0

    except Exception as e:
        result["errors"].append(str(e))
        frappe.log_error(
            message=f"Error sending certificate notification: {str(e)}",
            title=f"Certificate Alert Error: {certificate.get('name')}"
        )

    return result


def send_batch_notification_to_tenant(
    tenant: str,
    certificates: List[Dict[str, Any]],
    send_email: bool = True,
) -> Dict[str, Any]:
    """
    Send a batch notification to tenant admins about multiple certificates.

    Args:
        tenant: Tenant document name
        certificates: List of expiring certificate data
        send_email: Whether to send email notification

    Returns:
        dict: Result of batch notification
    """
    result = {
        "success": False,
        "tenant": tenant,
        "certificates_count": len(certificates),
        "notifications_sent": 0,
        "errors": [],
    }

    if not certificates:
        result["success"] = True
        return result

    try:
        admin_emails = get_tenant_admin_emails(tenant)

        if not admin_emails:
            result["errors"].append("No tenant admin emails found")
            return result

        # Build summary message
        subject = _("[Certificate Alert] {0} certificates expiring soon").format(
            len(certificates)
        )

        lines = [
            _("Certificate Expiry Summary"),
            "=" * 40,
            "",
            _("The following certificates require attention:"),
            "",
        ]

        # Group by urgency
        critical = []
        urgent = []
        warning = []

        for cert in certificates:
            days = cert.get("days_until_expiry", 0)
            if days <= 7:
                critical.append(cert)
            elif days <= 14:
                urgent.append(cert)
            else:
                warning.append(cert)

        if critical:
            lines.append(_("CRITICAL (expires within 7 days):"))
            for cert in critical:
                lines.append(
                    f"  - {cert.get('type_name')}: {cert.get('product_name') or cert.get('seller_name')} "
                    f"(expires: {cert.get('expiry_date')})"
                )
            lines.append("")

        if urgent:
            lines.append(_("URGENT (expires within 14 days):"))
            for cert in urgent:
                lines.append(
                    f"  - {cert.get('type_name')}: {cert.get('product_name') or cert.get('seller_name')} "
                    f"(expires: {cert.get('expiry_date')})"
                )
            lines.append("")

        if warning:
            lines.append(_("WARNING (expires within 30 days):"))
            for cert in warning:
                lines.append(
                    f"  - {cert.get('type_name')}: {cert.get('product_name') or cert.get('seller_name')} "
                    f"(expires: {cert.get('expiry_date')})"
                )
            lines.append("")

        lines.append(_("Please review and renew these certificates promptly."))

        message = "\n".join(lines)

        # Send to tenant admins
        if send_email and admin_emails:
            try:
                frappe.sendmail(
                    recipients=admin_emails,
                    subject=subject,
                    message=message,
                    delayed=True,
                )
                result["notifications_sent"] += len(admin_emails)
            except Exception as e:
                result["errors"].append(f"Failed to send admin email: {str(e)}")

        result["success"] = result["notifications_sent"] > 0

    except Exception as e:
        result["errors"].append(str(e))
        frappe.log_error(
            message=f"Error sending batch notification to tenant {tenant}: {str(e)}",
            title="Certificate Batch Alert Error"
        )

    return result


# =============================================================================
# MAIN PROCESSING FUNCTIONS
# =============================================================================


def check_expiring_certificates() -> Dict[str, Any]:
    """
    Scheduler job to check and notify about expiring certificates.

    This function is designed to be called by Frappe scheduler (daily at 6 AM).
    It processes certificates approaching expiry and sends notifications.

    Returns:
        dict: Processing summary with counts and details
    """
    result = {
        "processed": 0,
        "notifications_sent": 0,
        "reminders_marked": 0,
        "expired_updated": 0,
        "errors": [],
        "started_at": now_datetime(),
    }

    try:
        # Step 1: Get certificates expiring soon that haven't been notified
        expiring_certificates = get_certificates_needing_notification()

        result["processed"] = len(expiring_certificates)

        if not expiring_certificates:
            result["message"] = "No certificates require notification"
            result["completed_at"] = now_datetime()
            return result

        # Step 2: Process each certificate
        for cert in expiring_certificates:
            try:
                days = cert.get("days_until_expiry", 0)
                urgency = get_urgency_level(days)

                # Send individual notification
                notification_result = send_certificate_notification(
                    certificate=cert,
                    urgency=urgency,
                    send_email=True,
                )

                if notification_result.get("success"):
                    result["notifications_sent"] += notification_result.get(
                        "notifications_sent", 0
                    )

                    # Mark reminder as sent
                    frappe.db.set_value(
                        "Certificate",
                        cert.get("name"),
                        "renewal_reminder_sent",
                        1,
                        update_modified=False,
                    )
                    result["reminders_marked"] += 1
                else:
                    result["errors"].extend(notification_result.get("errors", []))

            except Exception as e:
                result["errors"].append(f"Error processing {cert.get('name')}: {str(e)}")
                frappe.log_error(
                    message=f"Error processing certificate {cert.get('name')}: {str(e)}",
                    title="Certificate Alert Processing Error"
                )

        # Step 3: Update expired certificate statuses
        expired_count = update_expired_certificate_statuses()
        result["expired_updated"] = expired_count

        # Step 4: Send batch notifications to tenant admins
        tenant_summaries = get_expiring_by_tenant()
        for tenant, certs in tenant_summaries.items():
            if certs:
                batch_result = send_batch_notification_to_tenant(
                    tenant=tenant,
                    certificates=certs,
                    send_email=True,
                )
                if not batch_result.get("success"):
                    result["errors"].extend(batch_result.get("errors", []))

        frappe.db.commit()

        result["completed_at"] = now_datetime()
        result["message"] = (
            f"Processed {result['processed']} certificates: "
            f"{result['notifications_sent']} notifications sent, "
            f"{result['reminders_marked']} reminders marked, "
            f"{result['expired_updated']} expired statuses updated"
        )

    except Exception as e:
        result["error"] = str(e)
        frappe.log_error(
            message=f"Error in check_expiring_certificates: {str(e)}",
            title="Certificate Alert Scheduler Error"
        )

    return result


def get_certificates_needing_notification() -> List[Dict[str, Any]]:
    """
    Get certificates that need expiry notification.

    Criteria:
    - Status is Active or Verified
    - Has expiry date
    - Expiry date is within renewal_reminder_days
    - Reminder has not been sent yet

    Returns:
        list: List of certificate data dictionaries
    """
    # SQL query to get certificates needing notification
    # Uses COALESCE to default renewal_reminder_days to 30 if not set
    certificates = frappe.db.sql(
        """
        SELECT
            c.name,
            c.certificate_type,
            c.type_name,
            c.certificate_category,
            c.status,
            c.sku_product,
            c.product_name,
            c.seller,
            c.seller_name,
            c.tenant,
            c.tenant_name,
            c.certificate_number,
            c.issue_date,
            c.expiry_date,
            DATEDIFF(c.expiry_date, CURDATE()) AS days_until_expiry,
            COALESCE(c.renewal_reminder_days, ct.renewal_reminder_days, %s) AS reminder_days,
            c.renewal_reminder_sent
        FROM `tabCertificate` c
        LEFT JOIN `tabCertificate Type` ct ON ct.name = c.certificate_type
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date IS NOT NULL
        AND c.renewal_reminder_sent = 0
        AND DATEDIFF(c.expiry_date, CURDATE()) <= COALESCE(c.renewal_reminder_days, ct.renewal_reminder_days, %s)
        AND DATEDIFF(c.expiry_date, CURDATE()) >= 0
        ORDER BY c.expiry_date ASC
        LIMIT %s
        """,
        (DEFAULT_REMINDER_DAYS, DEFAULT_REMINDER_DAYS, BATCH_SIZE),
        as_dict=True,
    )

    return certificates


def get_expiring_by_tenant() -> Dict[str, List[Dict[str, Any]]]:
    """
    Get certificates grouped by tenant for batch notifications.

    Returns:
        dict: Dictionary with tenant names as keys and certificate lists as values
    """
    certificates = frappe.db.sql(
        """
        SELECT
            c.name,
            c.certificate_type,
            c.type_name,
            c.sku_product,
            c.product_name,
            c.seller,
            c.seller_name,
            c.tenant,
            c.tenant_name,
            c.certificate_number,
            c.expiry_date,
            DATEDIFF(c.expiry_date, CURDATE()) AS days_until_expiry
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date IS NOT NULL
        AND DATEDIFF(c.expiry_date, CURDATE()) <= %s
        AND DATEDIFF(c.expiry_date, CURDATE()) >= 0
        ORDER BY c.tenant, c.expiry_date ASC
        """,
        (DEFAULT_REMINDER_DAYS,),
        as_dict=True,
    )

    # Group by tenant
    by_tenant = {}
    for cert in certificates:
        tenant = cert.get("tenant") or "No Tenant"
        if tenant not in by_tenant:
            by_tenant[tenant] = []
        by_tenant[tenant].append(cert)

    return by_tenant


def update_expired_certificate_statuses() -> int:
    """
    Update status of certificates that have expired.

    This function finds certificates that are marked as Active but have
    an expiry date in the past, and updates their status to Expired.

    Returns:
        int: Number of certificates updated
    """
    # Find expired certificates still marked as Active
    expired = frappe.db.sql(
        """
        SELECT name
        FROM `tabCertificate`
        WHERE status IN ('Active', 'Verified')
        AND expiry_date IS NOT NULL
        AND expiry_date < CURDATE()
        """,
        as_dict=True,
    )

    updated_count = 0
    for cert in expired:
        try:
            frappe.db.set_value(
                "Certificate",
                cert["name"],
                {
                    "status": "Expired",
                    "expiry_status": "Expired",
                },
                update_modified=True,
            )
            updated_count += 1
        except Exception as e:
            frappe.log_error(
                message=f"Failed to update expired status for {cert['name']}: {str(e)}",
                title="Certificate Status Update Error"
            )

    return updated_count


# =============================================================================
# TENANT-SPECIFIC PROCESSING
# =============================================================================


def process_tenant_certificates(tenant: str) -> Dict[str, Any]:
    """
    Process certificate alerts for a specific tenant.

    Args:
        tenant: Tenant document name

    Returns:
        dict: Processing result for the tenant
    """
    result = {
        "tenant": tenant,
        "processed": 0,
        "notifications_sent": 0,
        "errors": [],
        "started_at": now_datetime(),
    }

    try:
        # Get expiring certificates for this tenant
        certificates = frappe.db.sql(
            """
            SELECT
                c.name,
                c.certificate_type,
                c.type_name,
                c.certificate_category,
                c.status,
                c.sku_product,
                c.product_name,
                c.seller,
                c.seller_name,
                c.tenant,
                c.tenant_name,
                c.certificate_number,
                c.expiry_date,
                DATEDIFF(c.expiry_date, CURDATE()) AS days_until_expiry,
                c.renewal_reminder_sent
            FROM `tabCertificate` c
            WHERE c.tenant = %s
            AND c.status IN ('Active', 'Verified')
            AND c.expiry_date IS NOT NULL
            AND c.renewal_reminder_sent = 0
            AND DATEDIFF(c.expiry_date, CURDATE()) <= %s
            ORDER BY c.expiry_date ASC
            LIMIT %s
            """,
            (tenant, DEFAULT_REMINDER_DAYS, BATCH_SIZE),
            as_dict=True,
        )

        result["processed"] = len(certificates)

        for cert in certificates:
            days = cert.get("days_until_expiry", 0)
            urgency = get_urgency_level(days)

            notification_result = send_certificate_notification(
                certificate=cert,
                urgency=urgency,
                send_email=True,
            )

            if notification_result.get("success"):
                result["notifications_sent"] += notification_result.get(
                    "notifications_sent", 0
                )

                # Mark reminder as sent
                frappe.db.set_value(
                    "Certificate",
                    cert.get("name"),
                    "renewal_reminder_sent",
                    1,
                    update_modified=False,
                )

        # Send batch notification to tenant admins
        if certificates:
            send_batch_notification_to_tenant(
                tenant=tenant,
                certificates=certificates,
                send_email=True,
            )

        frappe.db.commit()
        result["completed_at"] = now_datetime()

    except Exception as e:
        result["error"] = str(e)
        frappe.log_error(
            message=f"Error processing tenant certificates for {tenant}: {str(e)}",
            title="Certificate Tenant Processing Error"
        )

    return result


# =============================================================================
# STATISTICS AND REPORTING
# =============================================================================


def get_certificate_expiry_stats(tenant: str = None) -> Dict[str, Any]:
    """
    Get certificate expiry statistics for dashboard.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Expiry statistics
    """
    tenant_filter = "AND c.tenant = %s" if tenant else ""
    params = [tenant] if tenant else []

    # Get counts by expiry window
    stats = {
        "expired": 0,
        "critical": 0,      # <= 7 days
        "urgent": 0,        # 8-14 days
        "warning": 0,       # 15-30 days
        "healthy": 0,       # > 30 days or no expiry
    }

    # Expired certificates
    stats["expired"] = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date < CURDATE()
        {tenant_filter}
        """,
        params,
    )[0][0] or 0

    # Critical (7 days or less)
    stats["critical"] = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date IS NOT NULL
        AND DATEDIFF(c.expiry_date, CURDATE()) BETWEEN 0 AND 7
        {tenant_filter}
        """,
        params,
    )[0][0] or 0

    # Urgent (8-14 days)
    stats["urgent"] = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date IS NOT NULL
        AND DATEDIFF(c.expiry_date, CURDATE()) BETWEEN 8 AND 14
        {tenant_filter}
        """,
        params,
    )[0][0] or 0

    # Warning (15-30 days)
    stats["warning"] = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date IS NOT NULL
        AND DATEDIFF(c.expiry_date, CURDATE()) BETWEEN 15 AND 30
        {tenant_filter}
        """,
        params,
    )[0][0] or 0

    # Healthy (> 30 days or no expiry)
    stats["healthy"] = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND (c.expiry_date IS NULL OR DATEDIFF(c.expiry_date, CURDATE()) > 30)
        {tenant_filter}
        """,
        params,
    )[0][0] or 0

    # Total active
    stats["total_active"] = (
        stats["expired"] +
        stats["critical"] +
        stats["urgent"] +
        stats["warning"] +
        stats["healthy"]
    )

    # Pending reminders
    stats["pending_reminders"] = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date IS NOT NULL
        AND c.renewal_reminder_sent = 0
        AND DATEDIFF(c.expiry_date, CURDATE()) <= 30
        {tenant_filter}
        """,
        params,
    )[0][0] or 0

    return stats


def get_expiring_certificates_report(
    days: int = 30,
    tenant: str = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Generate a report of certificates expiring within specified days.

    Args:
        days: Number of days to look ahead
        tenant: Optional tenant filter
        limit: Maximum number of results

    Returns:
        list: List of expiring certificate data
    """
    tenant_filter = "AND c.tenant = %s" if tenant else ""
    params = [days, days]
    if tenant:
        params.append(tenant)
    params.append(limit)

    certificates = frappe.db.sql(
        f"""
        SELECT
            c.name,
            c.certificate_type,
            c.type_name,
            c.certificate_category,
            c.status,
            c.sku_product,
            c.product_name,
            c.seller,
            c.seller_name,
            c.tenant,
            c.tenant_name,
            c.certificate_number,
            c.issue_date,
            c.expiry_date,
            DATEDIFF(c.expiry_date, CURDATE()) AS days_until_expiry,
            c.renewal_reminder_sent,
            CASE
                WHEN DATEDIFF(c.expiry_date, CURDATE()) < 0 THEN 'Expired'
                WHEN DATEDIFF(c.expiry_date, CURDATE()) <= 7 THEN 'Critical'
                WHEN DATEDIFF(c.expiry_date, CURDATE()) <= 14 THEN 'Urgent'
                WHEN DATEDIFF(c.expiry_date, CURDATE()) <= 30 THEN 'Warning'
                ELSE 'Notice'
            END AS urgency_level
        FROM `tabCertificate` c
        WHERE c.status IN ('Active', 'Verified')
        AND c.expiry_date IS NOT NULL
        AND DATEDIFF(c.expiry_date, CURDATE()) <= %s
        AND DATEDIFF(c.expiry_date, CURDATE()) >= -%s
        {tenant_filter}
        ORDER BY c.expiry_date ASC
        LIMIT %s
        """,
        params,
        as_dict=True,
    )

    return certificates


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def enqueue_certificate_alerts(tenant: str = None) -> Dict[str, Any]:
    """
    Enqueue certificate alert processing for background execution.

    Args:
        tenant: Optional tenant filter (processes all tenants if not specified)

    Returns:
        dict: Enqueue result
    """
    if tenant:
        frappe.enqueue(
            "tr_tradehub.tasks.certificate_alerts.process_tenant_certificates",
            tenant=tenant,
            queue="long",
            timeout=600,
        )
        return {
            "success": True,
            "message": f"Certificate alert processing queued for tenant {tenant}",
        }
    else:
        frappe.enqueue(
            "tr_tradehub.tasks.certificate_alerts.check_expiring_certificates",
            queue="long",
            timeout=1800,
        )
        return {
            "success": True,
            "message": "Certificate alert processing queued for all tenants",
        }


@frappe.whitelist()
def get_expiry_statistics(tenant: str = None) -> Dict[str, Any]:
    """
    Get certificate expiry statistics.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Expiry statistics
    """
    return get_certificate_expiry_stats(tenant=tenant)


@frappe.whitelist()
def get_expiring_report(
    days: int = 30,
    tenant: str = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get report of certificates expiring within specified days.

    Args:
        days: Number of days to look ahead
        tenant: Optional tenant filter
        limit: Maximum results

    Returns:
        list: List of expiring certificates
    """
    return get_expiring_certificates_report(
        days=cint(days),
        tenant=tenant,
        limit=cint(limit),
    )


@frappe.whitelist()
def send_test_notification(certificate_name: str) -> Dict[str, Any]:
    """
    Send a test notification for a certificate.

    Args:
        certificate_name: Certificate document name

    Returns:
        dict: Notification result
    """
    if not frappe.db.exists("Certificate", certificate_name):
        return {
            "success": False,
            "message": f"Certificate {certificate_name} not found",
        }

    cert = frappe.db.get_value(
        "Certificate",
        certificate_name,
        [
            "name",
            "certificate_type",
            "type_name",
            "certificate_category",
            "sku_product",
            "product_name",
            "seller",
            "seller_name",
            "tenant",
            "certificate_number",
            "expiry_date",
        ],
        as_dict=True,
    )

    if not cert:
        return {
            "success": False,
            "message": "Failed to load certificate data",
        }

    # Calculate days until expiry
    if cert.get("expiry_date"):
        cert["days_until_expiry"] = date_diff(
            getdate(cert["expiry_date"]),
            getdate(nowdate()),
        )
    else:
        cert["days_until_expiry"] = None

    urgency = get_urgency_level(cert.get("days_until_expiry", 0))

    return send_certificate_notification(
        certificate=cert,
        urgency=urgency,
        send_email=True,
    )


@frappe.whitelist()
def mark_reminder_sent(certificate_name: str) -> Dict[str, Any]:
    """
    Manually mark a certificate's reminder as sent.

    Args:
        certificate_name: Certificate document name

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Certificate", certificate_name):
        return {
            "success": False,
            "message": f"Certificate {certificate_name} not found",
        }

    frappe.db.set_value(
        "Certificate",
        certificate_name,
        "renewal_reminder_sent",
        1,
        update_modified=False,
    )

    return {
        "success": True,
        "message": f"Reminder marked as sent for {certificate_name}",
    }


@frappe.whitelist()
def reset_reminder_status(certificate_name: str = None, tenant: str = None) -> Dict[str, Any]:
    """
    Reset reminder sent status for certificates.

    Args:
        certificate_name: Specific certificate (optional)
        tenant: Reset all for tenant (optional)

    Returns:
        dict: Result
    """
    if certificate_name:
        if not frappe.db.exists("Certificate", certificate_name):
            return {
                "success": False,
                "message": f"Certificate {certificate_name} not found",
            }

        frappe.db.set_value(
            "Certificate",
            certificate_name,
            "renewal_reminder_sent",
            0,
            update_modified=False,
        )
        return {
            "success": True,
            "message": f"Reminder status reset for {certificate_name}",
        }

    elif tenant:
        updated = frappe.db.sql(
            """
            UPDATE `tabCertificate`
            SET renewal_reminder_sent = 0
            WHERE tenant = %s
            """,
            (tenant,),
        )
        frappe.db.commit()
        return {
            "success": True,
            "message": f"Reminder status reset for tenant {tenant}",
        }

    else:
        return {
            "success": False,
            "message": "Either certificate_name or tenant is required",
        }
