"""
Scheduled tasks for TradeHub Compliance module.

These tasks are moved from the monolithic tr_tradehub app during decomposition.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate


def certificate_alerts():
    """
    Daily task to send alerts for expiring certificates.

    This function:
    1. Finds certificates expiring within the configured alert period
    2. Sends notification emails to certificate holders
    3. Creates notification records for dashboard alerts
    4. Logs the alert activities for audit purposes
    """
    try:
        # Get compliance settings for alert thresholds
        alert_days = frappe.db.get_single_value(
            "Analytics Settings", "certificate_alert_days"
        ) or 30

        # Find certificates expiring soon
        expiring_date = add_days(nowdate(), alert_days)

        expiring_certificates = frappe.get_all(
            "Certificate",
            filters={
                "status": "Active",
                "expiry_date": ["<=", expiring_date],
                "expiry_date": [">=", nowdate()],
                "alert_sent": 0
            },
            fields=["name", "certificate_type", "holder", "expiry_date", "organization"]
        )

        for cert in expiring_certificates:
            _send_certificate_expiry_alert(cert)

        frappe.db.commit()

        frappe.logger().info(
            f"Certificate alerts: Processed {len(expiring_certificates)} expiring certificates"
        )

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title="Certificate Alerts Task Error"
        )


def _send_certificate_expiry_alert(certificate):
    """
    Send expiry alert for a single certificate.

    Args:
        certificate: Dict with certificate details
    """
    try:
        days_until_expiry = (getdate(certificate.expiry_date) - getdate(nowdate())).days

        # Get holder email
        holder_email = frappe.db.get_value(
            "User", certificate.holder, "email"
        ) if certificate.holder else None

        if holder_email:
            # Send email notification
            frappe.sendmail(
                recipients=[holder_email],
                subject=f"Certificate Expiring: {certificate.certificate_type}",
                message=f"""
                    <p>Your certificate <strong>{certificate.name}</strong> of type
                    <strong>{certificate.certificate_type}</strong> is expiring
                    in <strong>{days_until_expiry} days</strong>.</p>

                    <p>Expiry Date: {certificate.expiry_date}</p>

                    <p>Please take action to renew your certificate before it expires.</p>
                """,
                now=False  # Queue for background sending
            )

        # Create system notification
        frappe.get_doc({
            "doctype": "Notification Log",
            "document_type": "Certificate",
            "document_name": certificate.name,
            "from_user": "Administrator",
            "for_user": certificate.holder,
            "subject": f"Certificate Expiring in {days_until_expiry} days",
            "type": "Alert"
        }).insert(ignore_permissions=True)

        # Mark certificate as alert sent
        frappe.db.set_value(
            "Certificate", certificate.name, "alert_sent", 1
        )

    except Exception as e:
        frappe.log_error(
            message=f"Failed to send alert for certificate {certificate.name}: {str(e)}",
            title="Certificate Alert Error"
        )
