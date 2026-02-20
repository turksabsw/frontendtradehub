# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA Notification Action Handler

Creates system notifications for users with support for different notification
types (Alert, System, Toast). Notifications are sent to specified recipients
with Jinja template support for dynamic message content.

Usage:
    from tr_tradehub.eca.actions.notification_handler import NotificationHandler, execute_notification_action

    handler = NotificationHandler()
    result = handler.execute(action, doc, context)
"""

from typing import Any, Dict, List, Optional

try:
    import frappe
    from frappe import _
    from frappe.utils import now_datetime
except ImportError:
    frappe = None
    _ = str
    now_datetime = None

from . import ActionResult, BaseActionHandler, register_handler


@register_handler
class NotificationHandler(BaseActionHandler):
    """
    Handler for System Notification actions.

    Creates system notifications for users with support for:
    - Multiple notification types (Alert, System, Toast)
    - Multiple recipients (comma-separated or Jinja expressions)
    - Dynamic message content via Jinja templates
    - Document linking for notification context

    Notification Types:
    - Alert: Desktop alert notification (uses Frappe's system notification)
    - System: System notification in the notification bell
    - Toast: Toast/popup message (temporary visual feedback)

    Fields used from ECA Rule Action:
    - notification_type: Type of notification (Alert/System/Toast)
    - notification_recipients: Users to notify (comma-separated or Jinja expression)
    - notification_message: Message content (supports Jinja variables)
    """

    action_type = 'System Notification'

    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the notification action.

        Args:
            action: ECA Rule Action child document with notification configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult with success/failure status and message
        """
        if not frappe:
            return ActionResult.error_result(
                error="Frappe not available",
                message="Cannot send notification: Frappe framework not loaded"
            )

        try:
            # Build template context
            full_context = self.build_context(doc, context)

            # Get notification type
            notification_type = getattr(action, 'notification_type', 'System') or 'System'

            # Get recipients
            recipients = self._get_recipients(action, doc, full_context)
            if not recipients:
                return ActionResult.error_result(
                    error="No recipients specified",
                    message="Notification action failed: No valid recipients found"
                )

            # Get notification message
            message = self._get_message(action, doc, full_context)
            if not message:
                # Default message if none provided
                message = self._get_default_message(doc)

            # Get subject/title for notification
            subject = self._get_subject(doc)

            # Track results
            sent_count = 0
            failed_recipients = []

            # Send notifications based on type
            for recipient in recipients:
                try:
                    if notification_type == 'Toast':
                        self._send_toast_notification(recipient, subject, message, doc)
                    elif notification_type == 'Alert':
                        self._send_alert_notification(recipient, subject, message, doc)
                    else:  # System (default)
                        self._send_system_notification(recipient, subject, message, doc)
                    sent_count += 1
                except Exception as e:
                    failed_recipients.append({
                        'recipient': recipient,
                        'error': str(e)
                    })
                    frappe.log_error(
                        title="ECA Notification Send Error",
                        message=f"Recipient: {recipient}\nError: {str(e)}"
                    )

            # Build result message
            if sent_count > 0:
                recipient_str = ', '.join(recipients[:3])
                if len(recipients) > 3:
                    recipient_str += f" and {len(recipients) - 3} more"

                result_message = f"{notification_type} notification sent to {recipient_str}"
                if failed_recipients:
                    result_message += f" ({len(failed_recipients)} failed)"

                return ActionResult.success_result(
                    message=result_message,
                    data={
                        'notification_type': notification_type,
                        'recipients': recipients,
                        'sent_count': sent_count,
                        'failed_count': len(failed_recipients),
                        'failed_recipients': failed_recipients,
                        'subject': subject[:100],
                        'message': message[:200]
                    }
                )
            else:
                return ActionResult.error_result(
                    error="All notifications failed to send",
                    message=f"Failed to send notifications to {len(recipients)} recipient(s)"
                )

        except Exception as e:
            if frappe:
                frappe.log_error(
                    title="ECA Notification Action Error",
                    message=f"Document: {doc.doctype} {doc.name}\nError: {str(e)}"
                )
            return ActionResult.error_result(
                error=str(e),
                message=f"Failed to send notification: {str(e)}"
            )

    def validate(self, action: Any) -> List[str]:
        """
        Validate notification action configuration.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages
        """
        errors = []

        # Check for recipients
        recipients = getattr(action, 'notification_recipients', None)
        if not recipients:
            errors.append("Notification Recipients field is required for System Notification action")

        # Validate notification type
        notification_type = getattr(action, 'notification_type', None)
        valid_types = ['Alert', 'System', 'Toast']
        if notification_type and notification_type not in valid_types:
            errors.append(f"Invalid notification type: {notification_type}. Must be one of: {', '.join(valid_types)}")

        return errors

    def _get_recipients(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> List[str]:
        """
        Get and validate recipient users.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            List of valid user IDs
        """
        recipients_str = getattr(action, 'notification_recipients', '') or ''

        if not recipients_str:
            return []

        # Render Jinja template in recipients
        rendered = self.render_template(recipients_str, doc, context)

        # Parse comma-separated list
        raw_recipients = self.parse_recipients(rendered)

        # Validate users exist
        valid_recipients = []
        for recipient in raw_recipients:
            recipient = recipient.strip()
            if not recipient:
                continue

            # Check if it's a Jinja variable that resolved to empty
            if recipient.startswith('{{') and recipient.endswith('}}'):
                continue

            # Validate user exists in the system
            if self._user_exists(recipient):
                valid_recipients.append(recipient)
            elif '@' in recipient:
                # Try to find user by email
                user = self._get_user_by_email(recipient)
                if user:
                    valid_recipients.append(user)

        return valid_recipients

    def _user_exists(self, user: str) -> bool:
        """
        Check if a user exists in the system.

        Args:
            user: User ID to check

        Returns:
            True if user exists
        """
        if not frappe:
            return False

        try:
            return frappe.db.exists("User", user)
        except Exception:
            return False

    def _get_user_by_email(self, email: str) -> Optional[str]:
        """
        Get user ID by email address.

        Args:
            email: Email address

        Returns:
            User ID or None
        """
        if not frappe:
            return None

        try:
            user = frappe.db.get_value("User", {"email": email}, "name")
            return user
        except Exception:
            return None

    def _get_message(
        self,
        action: Any,
        doc: Any,
        context: Dict
    ) -> str:
        """
        Get the notification message content.

        Args:
            action: Action configuration
            doc: Trigger document
            context: Template context

        Returns:
            Rendered message string
        """
        message_template = getattr(action, 'notification_message', '') or ''

        if not message_template:
            return ''

        # Render Jinja template
        return self.render_template(message_template, doc, context)

    def _get_subject(self, doc: Any) -> str:
        """
        Get the notification subject/title.

        Args:
            doc: Trigger document

        Returns:
            Subject string
        """
        # Create a subject from document type and name
        doctype = doc.doctype
        name = doc.name

        # Try to get a more descriptive title if available
        if hasattr(doc, 'title') and doc.title:
            return f"[{doctype}] {doc.title}"
        elif hasattr(doc, 'subject') and doc.subject:
            return f"[{doctype}] {doc.subject}"

        return f"[{doctype}] {name}"

    def _get_default_message(self, doc: Any) -> str:
        """
        Generate a default notification message.

        Args:
            doc: Trigger document

        Returns:
            Default message string
        """
        doctype = doc.doctype
        name = doc.name

        return f"An ECA rule has been triggered for {doctype}: {name}"

    def _send_system_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        doc: Any
    ) -> None:
        """
        Send a system notification (notification bell).

        This creates a notification log that appears in the user's
        notification panel.

        Args:
            recipient: User to notify
            subject: Notification subject
            message: Notification message
            doc: Source document for linking
        """
        if not frappe:
            raise Exception("Frappe not available")

        # Create a notification log entry
        notification = frappe.new_doc("Notification Log")
        notification.for_user = recipient
        notification.type = "Alert"  # Alert type shows in notification bell
        notification.document_type = doc.doctype
        notification.document_name = doc.name
        notification.subject = subject
        notification.email_content = message

        # Set sender
        notification.from_user = frappe.session.user if hasattr(frappe, 'session') else "Administrator"

        notification.insert(ignore_permissions=True)
        frappe.db.commit()

    def _send_alert_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        doc: Any
    ) -> None:
        """
        Send an alert notification.

        This creates a high-priority notification that appears prominently.

        Args:
            recipient: User to notify
            subject: Notification subject
            message: Notification message
            doc: Source document for linking
        """
        if not frappe:
            raise Exception("Frappe not available")

        # Create notification log with Alert type
        notification = frappe.new_doc("Notification Log")
        notification.for_user = recipient
        notification.type = "Alert"
        notification.document_type = doc.doctype
        notification.document_name = doc.name
        notification.subject = f"⚠️ {subject}"  # Add alert emoji
        notification.email_content = message

        # Set sender
        notification.from_user = frappe.session.user if hasattr(frappe, 'session') else "Administrator"

        notification.insert(ignore_permissions=True)
        frappe.db.commit()

        # Also publish real-time event for immediate attention
        try:
            frappe.publish_realtime(
                event="alert",
                message={
                    "subject": subject,
                    "message": message,
                    "doctype": doc.doctype,
                    "docname": doc.name
                },
                user=recipient
            )
        except Exception:
            pass  # Real-time is optional

    def _send_toast_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        doc: Any
    ) -> None:
        """
        Send a toast notification.

        This sends a temporary popup notification that auto-dismisses.
        Uses Frappe's realtime publish for instant delivery.

        Args:
            recipient: User to notify
            subject: Notification subject
            message: Notification message
            doc: Source document for linking
        """
        if not frappe:
            raise Exception("Frappe not available")

        # Publish real-time toast event
        try:
            frappe.publish_realtime(
                event="msgprint",
                message={
                    "message": message,
                    "title": subject,
                    "indicator": "blue"
                },
                user=recipient
            )
        except Exception as e:
            # Fallback to notification log if realtime fails
            frappe.log_error(
                title="Toast Notification Realtime Error",
                message=f"Recipient: {recipient}\nError: {str(e)}\nFalling back to Notification Log"
            )
            # Fall back to system notification
            self._send_system_notification(recipient, subject, message, doc)


def execute_notification_action(action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
    """
    Convenience function to execute notification action.

    This is the main entry point for notification action execution.

    Args:
        action: ECA Rule Action child document with notification configuration
        doc: The document that triggered the ECA rule
        context: Optional additional context for template rendering

    Returns:
        ActionResult with success/failure status
    """
    handler = NotificationHandler()
    return handler.execute(action, doc, context)


def validate_notification_action(action: Any) -> List[str]:
    """
    Validate notification action configuration.

    Args:
        action: ECA Rule Action child document

    Returns:
        List of validation error messages
    """
    handler = NotificationHandler()
    return handler.validate(action)


# Export public API
__all__ = [
    'NotificationHandler',
    'execute_notification_action',
    'validate_notification_action',
]
