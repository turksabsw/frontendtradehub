# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA Email Action Handler

Sends emails using Frappe Email Templates with Jinja variable substitution
from document context. Supports direct recipients, CC, subject override,
and inline message content.

Usage:
    from tr_tradehub.eca.actions.email_handler import EmailHandler, execute_email_action

    handler = EmailHandler()
    result = handler.execute(action, doc, context)
"""

from typing import Any, Dict, List, Optional

try:
    import frappe
    from frappe import _
    from frappe.utils import validate_email_address
except ImportError:
    frappe = None
    _ = str
    validate_email_address = None

from . import ActionResult, BaseActionHandler, register_handler


@register_handler
class EmailHandler(BaseActionHandler):
    """
    Handler for Send Email actions.

    Sends emails using Frappe's email system with support for:
    - Email Templates with Jinja variable substitution
    - Direct recipient specification (comma-separated or Jinja expressions)
    - CC recipients
    - Subject override
    - Inline message content as fallback

    Fields used from ECA Rule Action:
    - email_template: Link to Email Template (optional)
    - recipients: Comma-separated emails or Jinja expression (required)
    - cc_recipients: CC recipients (optional)
    - subject_override: Override template subject (optional, supports Jinja)
    """

    action_type = 'Send Email'

    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the email action.

        Args:
            action: ECA Rule Action child document with email configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult with success/failure status and message
        """
        if not frappe:
            return ActionResult.error_result(
                error="Frappe not available",
                message="Cannot send email: Frappe framework not loaded"
            )

        try:
            # Build template context
            full_context = self.build_context(doc, context)

            # Get recipients
            recipients = self._get_recipients(action, doc, full_context)
            if not recipients:
                return ActionResult.error_result(
                    error="No recipients specified",
                    message="Email action failed: No valid recipients found"
                )

            # Get CC recipients
            cc_recipients = self._get_cc_recipients(action, doc, full_context)

            # Get email content
            subject, message = self._get_email_content(action, doc, full_context)

            if not subject:
                # Default subject if none provided
                subject = f"[{doc.doctype}] {doc.name}"

            if not message:
                # Default message if none provided
                message = self._get_default_message(doc)

            # Get attachments if configured
            attachments = self._get_attachments(action, doc, full_context)

            # Send email
            frappe.sendmail(
                recipients=recipients,
                cc=cc_recipients if cc_recipients else None,
                subject=subject,
                message=message,
                reference_doctype=doc.doctype,
                reference_name=doc.name,
                attachments=attachments if attachments else None,
                now=False  # Queue for background sending
            )

            # Build success message
            recipient_str = ', '.join(recipients[:3])
            if len(recipients) > 3:
                recipient_str += f" and {len(recipients) - 3} more"

            return ActionResult.success_result(
                message=f"Email sent to {recipient_str}",
                data={
                    'recipients': recipients,
                    'cc': cc_recipients,
                    'subject': subject[:100],  # Truncate for logging
                    'template': action.email_template if hasattr(action, 'email_template') else None
                }
            )

        except Exception as e:
            frappe.log_error(
                title="ECA Email Action Error",
                message=f"Document: {doc.doctype} {doc.name}\nError: {str(e)}"
            )
            return ActionResult.error_result(
                error=str(e),
                message=f"Failed to send email: {str(e)}"
            )

    def validate(self, action: Any) -> List[str]:
        """
        Validate email action configuration.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages
        """
        errors = []

        # Check for recipients
        recipients = getattr(action, 'recipients', None)
        if not recipients:
            errors.append("Recipients field is required for Send Email action")

        # Validate email template if specified
        email_template = getattr(action, 'email_template', None)
        if email_template and frappe:
            if not frappe.db.exists("Email Template", email_template):
                errors.append(f"Email Template '{email_template}' does not exist")

        return errors

    def _get_recipients(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> List[str]:
        """
        Get and validate recipient email addresses.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            List of valid email addresses
        """
        recipients_str = getattr(action, 'recipients', '') or ''

        if not recipients_str:
            return []

        # Render Jinja template in recipients
        rendered = self.render_template(recipients_str, doc, context)

        # Parse comma-separated list
        raw_recipients = self.parse_recipients(rendered)

        # Validate email addresses
        valid_recipients = []
        for email in raw_recipients:
            email = email.strip()
            if not email:
                continue

            # Check if it's a Jinja variable that resolved to empty
            if email.startswith('{{') and email.endswith('}}'):
                continue

            # Validate email format
            if validate_email_address and validate_email_address(email):
                valid_recipients.append(email)
            elif '@' in email and '.' in email:
                # Basic validation if frappe validator not available
                valid_recipients.append(email)

        return valid_recipients

    def _get_cc_recipients(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> List[str]:
        """
        Get and validate CC recipient email addresses.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            List of valid CC email addresses
        """
        cc_str = getattr(action, 'cc_recipients', '') or ''

        if not cc_str:
            return []

        # Render Jinja template in CC recipients
        rendered = self.render_template(cc_str, doc, context)

        # Parse comma-separated list
        raw_cc = self.parse_recipients(rendered)

        # Validate email addresses
        valid_cc = []
        for email in raw_cc:
            email = email.strip()
            if not email:
                continue

            if validate_email_address and validate_email_address(email):
                valid_cc.append(email)
            elif '@' in email and '.' in email:
                valid_cc.append(email)

        return valid_cc

    def _get_email_content(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> tuple:
        """
        Get email subject and message content.

        If an Email Template is specified, uses that template.
        Otherwise, uses subject_override for subject and generates default message.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            Tuple of (subject, message)
        """
        subject = None
        message = None

        email_template_name = getattr(action, 'email_template', None)
        subject_override = getattr(action, 'subject_override', None)

        if email_template_name and frappe:
            try:
                # Load Email Template
                email_template = frappe.get_doc("Email Template", email_template_name)

                # Get subject from template or override
                if subject_override:
                    subject = self.render_template(subject_override, doc, context)
                else:
                    subject = self.render_template(email_template.subject or '', doc, context)

                # Get message from template
                # Email Template can have 'response' or 'response_html' field
                template_content = getattr(email_template, 'response', '') or ''

                if template_content:
                    message = self.render_template(template_content, doc, context)
                else:
                    # Try response_html as fallback
                    template_content = getattr(email_template, 'response_html', '') or ''
                    if template_content:
                        message = self.render_template(template_content, doc, context)

            except frappe.DoesNotExistError:
                # Template not found, use fallbacks
                if subject_override:
                    subject = self.render_template(subject_override, doc, context)
            except Exception as e:
                frappe.log_error(
                    title="ECA Email Template Error",
                    message=f"Template: {email_template_name}\nError: {str(e)}"
                )
                if subject_override:
                    subject = self.render_template(subject_override, doc, context)
        else:
            # No template, use subject override if available
            if subject_override:
                subject = self.render_template(subject_override, doc, context)

        return subject, message

    def _get_default_message(self, doc: Any) -> str:
        """
        Generate a default email message for the document.

        Args:
            doc: Trigger document

        Returns:
            Default message string
        """
        doctype = doc.doctype
        name = doc.name

        # Build basic message
        message = f"""
        <p>An ECA rule has been triggered for the following document:</p>
        <table style="border-collapse: collapse; margin: 10px 0;">
            <tr>
                <td style="padding: 5px 10px; border: 1px solid #ddd;"><strong>DocType</strong></td>
                <td style="padding: 5px 10px; border: 1px solid #ddd;">{doctype}</td>
            </tr>
            <tr>
                <td style="padding: 5px 10px; border: 1px solid #ddd;"><strong>Name</strong></td>
                <td style="padding: 5px 10px; border: 1px solid #ddd;">{name}</td>
            </tr>
        </table>
        """

        # Add link to document if frappe is available
        if frappe:
            try:
                site_name = frappe.local.site
                doc_url = f"{frappe.utils.get_url()}/app/{doctype.lower().replace(' ', '-')}/{name}"
                message += f'<p><a href="{doc_url}">View Document</a></p>'
            except Exception:
                pass

        return message

    def _get_attachments(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> List[Dict]:
        """
        Get email attachments if configured.

        Currently supports:
        - Attachments linked to the document

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            List of attachment dictionaries
        """
        attachments = []

        # Check if action has include_attachments flag
        include_attachments = getattr(action, 'include_attachments', False)

        if include_attachments and frappe:
            try:
                # Get attachments linked to the document
                file_attachments = frappe.get_all(
                    "File",
                    filters={
                        "attached_to_doctype": doc.doctype,
                        "attached_to_name": doc.name,
                        "is_private": 0  # Only include non-private attachments
                    },
                    fields=["name", "file_name", "file_url"]
                )

                for file in file_attachments:
                    attachments.append({
                        "fname": file.file_name,
                        "fid": file.name
                    })

            except Exception as e:
                frappe.log_error(
                    title="ECA Email Attachment Error",
                    message=f"Document: {doc.name}\nError: {str(e)}"
                )

        return attachments


def execute_email_action(action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
    """
    Convenience function to execute email action.

    This is the main entry point for email action execution.

    Args:
        action: ECA Rule Action child document with email configuration
        doc: The document that triggered the ECA rule
        context: Optional additional context for template rendering

    Returns:
        ActionResult with success/failure status
    """
    handler = EmailHandler()
    return handler.execute(action, doc, context)


def validate_email_action(action: Any) -> List[str]:
    """
    Validate email action configuration.

    Args:
        action: ECA Rule Action child document

    Returns:
        List of validation error messages
    """
    handler = EmailHandler()
    return handler.validate(action)


# Export public API
__all__ = [
    'EmailHandler',
    'execute_email_action',
    'validate_email_action',
]
