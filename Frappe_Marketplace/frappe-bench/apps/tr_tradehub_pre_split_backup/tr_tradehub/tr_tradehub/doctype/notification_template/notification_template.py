# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Notification Template DocType for Trade Hub B2B Marketplace.

This module implements a comprehensive notification template system supporting
multiple channels (Email, Push, SMS, In-App, Webhook) and various event triggers.
Templates support Jinja2 templating for dynamic content.

Key features:
- Multi-channel notification support (Email, Push, SMS, In-App, Webhook)
- Jinja2 templating for dynamic content
- Multi-tenant isolation with global template option
- Template versioning and tracking
- Delivery scheduling (immediate, delayed, scheduled window)
- Delivery statistics tracking (sent, delivered, failed counts)
- Default template management per event type and channel
- Template preview with sample data
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, cint, strip_html
import json
from jinja2 import Template, TemplateSyntaxError, UndefinedError


# Event types requiring specific variables
EVENT_VARIABLE_REQUIREMENTS = {
    "Order Created": ["order_id", "buyer_name", "total_amount", "order_date"],
    "Order Confirmed": ["order_id", "buyer_name", "total_amount", "estimated_delivery"],
    "Order Shipped": ["order_id", "buyer_name", "tracking_number", "carrier", "estimated_delivery"],
    "Order Delivered": ["order_id", "buyer_name", "delivery_date"],
    "Order Cancelled": ["order_id", "buyer_name", "cancellation_reason"],
    "Payment Received": ["order_id", "buyer_name", "amount", "payment_method", "payment_date"],
    "Payment Failed": ["order_id", "buyer_name", "amount", "failure_reason"],
    "Payment Reminder": ["order_id", "buyer_name", "amount", "due_date", "payment_link"],
    "RFQ Created": ["rfq_id", "buyer_name", "product_name", "quantity", "deadline"],
    "RFQ Response Received": ["rfq_id", "buyer_name", "seller_name", "quote_amount"],
    "RFQ Expired": ["rfq_id", "buyer_name", "product_name"],
    "Quotation Received": ["quotation_id", "buyer_name", "seller_name", "total_amount", "valid_until"],
    "Quotation Accepted": ["quotation_id", "seller_name", "buyer_name", "total_amount"],
    "Quotation Rejected": ["quotation_id", "seller_name", "buyer_name", "rejection_reason"],
    "Sample Request Created": ["sample_id", "buyer_name", "product_name", "quantity"],
    "Sample Request Approved": ["sample_id", "buyer_name", "product_name", "estimated_delivery"],
    "Sample Request Rejected": ["sample_id", "buyer_name", "product_name", "rejection_reason"],
    "Sample Shipped": ["sample_id", "buyer_name", "tracking_number", "carrier"],
    "Message Received": ["sender_name", "thread_subject", "message_preview"],
    "Seller Verification": ["seller_name", "verification_status", "verification_notes"],
    "Buyer Verification": ["buyer_name", "verification_status", "verification_notes"],
    "Certificate Expiring": ["certificate_name", "expiry_date", "days_remaining", "holder_name"],
    "Certificate Expired": ["certificate_name", "expiry_date", "holder_name"],
    "Low Stock Alert": ["product_name", "sku_code", "current_stock", "reorder_level"],
    "Price Change Alert": ["product_name", "old_price", "new_price", "change_percent"],
    "New Product Alert": ["product_name", "seller_name", "category", "price"],
    "Welcome Email": ["user_name", "login_link", "support_email"],
    "Password Reset": ["user_name", "reset_link", "expiry_time"],
    "Account Deactivated": ["user_name", "deactivation_reason", "reactivation_link"],
}

# Default variables available in all templates
DEFAULT_VARIABLES = [
    "current_date",
    "current_time",
    "platform_name",
    "platform_url",
    "support_email",
    "support_phone",
]


class NotificationTemplate(Document):
    """
    Notification Template DocType for managing notification templates.

    Each template defines the content and settings for a specific type of
    notification on a specific channel (Email, Push, SMS, etc.).
    Supports Jinja2 templating for dynamic content.
    """

    def before_insert(self):
        """Set defaults before inserting a new template."""
        self.set_default_variables()
        self.normalize_template_code()

    def validate(self):
        """Validate template data before saving."""
        self.validate_template_code()
        self.validate_channel_requirements()
        self.validate_template_syntax()
        self.validate_tenant_and_global()
        self.validate_default_template()
        self.validate_scheduling()
        self.normalize_email_lists()
        self.validate_sms_settings()

    def on_update(self):
        """Actions after template is saved."""
        self.update_default_template_flag()
        self.clear_template_cache()

    def on_trash(self):
        """Actions before template is deleted."""
        self.check_usage_before_delete()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_variables(self):
        """Set default available variables based on event type."""
        if not self.available_variables:
            event_vars = EVENT_VARIABLE_REQUIREMENTS.get(self.event_type, [])
            all_vars = list(set(DEFAULT_VARIABLES + event_vars))
            self.available_variables = json.dumps(all_vars)

    def normalize_template_code(self):
        """Normalize template code to uppercase with underscores."""
        if self.template_code:
            # Convert to uppercase and replace spaces/dashes with underscores
            normalized = self.template_code.upper()
            normalized = normalized.replace(" ", "_").replace("-", "_")
            # Remove any non-alphanumeric characters except underscore
            import re
            normalized = re.sub(r'[^A-Z0-9_]', '', normalized)
            self.template_code = normalized

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_template_code(self):
        """Validate template code format and uniqueness."""
        if not self.template_code:
            frappe.throw(_("Template Code is required"))

        # Check format
        import re
        if not re.match(r'^[A-Z][A-Z0-9_]*$', self.template_code):
            frappe.throw(
                _("Template Code must start with a letter and contain only "
                  "uppercase letters, numbers, and underscores")
            )

        # Check uniqueness within tenant (or global)
        filters = {
            "template_code": self.template_code,
            "name": ["!=", self.name or ""]
        }

        if self.tenant:
            filters["tenant"] = self.tenant
        elif self.is_global:
            filters["is_global"] = 1
        else:
            # Check against both tenant-specific and global templates
            existing = frappe.db.exists(
                "Notification Template",
                {"template_code": self.template_code, "name": ["!=", self.name or ""]}
            )
            if existing:
                frappe.throw(
                    _("Template Code {0} already exists").format(self.template_code)
                )
            return

        if frappe.db.exists("Notification Template", filters):
            scope = self.tenant_name if self.tenant else "global"
            frappe.throw(
                _("Template Code {0} already exists for {1}").format(
                    self.template_code, scope
                )
            )

    def validate_channel_requirements(self):
        """Validate required fields based on notification channel."""
        if self.notification_channel == "Email":
            if not self.subject:
                frappe.throw(_("Subject is required for Email notifications"))
            if not self.body and not self.plain_text_body:
                frappe.throw(_("Body content is required for Email notifications"))

        elif self.notification_channel == "Push Notification":
            if not self.subject:
                frappe.throw(_("Subject/Title is required for Push notifications"))
            if not self.plain_text_body:
                frappe.throw(_("Plain text body is required for Push notifications"))

        elif self.notification_channel == "SMS":
            if not self.plain_text_body:
                frappe.throw(_("Plain text body is required for SMS notifications"))

        elif self.notification_channel == "In-App":
            if not self.subject and not self.plain_text_body:
                frappe.throw(_("Subject or body is required for In-App notifications"))

        elif self.notification_channel == "Webhook":
            if not self.body:
                frappe.throw(_("Body (JSON payload template) is required for Webhook"))

    def validate_template_syntax(self):
        """Validate Jinja2 template syntax in all template fields."""
        template_fields = [
            ("subject", self.subject),
            ("body", self.body),
            ("plain_text_body", self.plain_text_body),
            ("push_click_action", self.push_click_action),
        ]

        for field_name, content in template_fields:
            if content:
                try:
                    Template(content)
                except TemplateSyntaxError as e:
                    frappe.throw(
                        _("Invalid Jinja2 syntax in {0}: {1}").format(
                            field_name, str(e)
                        )
                    )

    def validate_tenant_and_global(self):
        """Validate tenant and global template settings."""
        if self.is_global and self.tenant:
            frappe.throw(
                _("Global templates cannot be assigned to a specific tenant. "
                  "Either set Is Global or assign a Tenant, not both.")
            )

        if not self.is_global and not self.tenant:
            # Check if System Manager - they can create tenant-less templates
            if "System Manager" not in frappe.get_roles():
                frappe.throw(
                    _("Please specify a Tenant or mark as Global template")
                )

    def validate_default_template(self):
        """Validate default template settings."""
        if not self.is_default:
            return

        # Check for existing default template with same event_type and channel
        filters = {
            "event_type": self.event_type,
            "notification_channel": self.notification_channel,
            "is_default": 1,
            "name": ["!=", self.name or ""]
        }

        if self.tenant:
            filters["tenant"] = self.tenant
        elif self.is_global:
            filters["is_global"] = 1

        existing_default = frappe.db.get_value(
            "Notification Template", filters, "name"
        )

        if existing_default:
            frappe.msgprint(
                _("Warning: Another template '{0}' is currently set as default "
                  "for {1} - {2}. It will be unset when you save.").format(
                    existing_default, self.event_type, self.notification_channel
                ),
                indicator='yellow',
                alert=True
            )

    def validate_scheduling(self):
        """Validate scheduling settings."""
        if self.schedule_type == "Delayed":
            if cint(self.delay_minutes) < 0:
                frappe.throw(_("Delay minutes cannot be negative"))
            if cint(self.delay_minutes) > 10080:  # 7 days max
                frappe.throw(_("Delay cannot exceed 7 days (10080 minutes)"))

        elif self.schedule_type == "Scheduled Window":
            if not self.active_from or not self.active_to:
                frappe.throw(
                    _("Active From and Active To times are required for Scheduled Window")
                )

    def normalize_email_lists(self):
        """Normalize CC and BCC email lists."""
        for field in ["cc_list", "bcc_list"]:
            value = getattr(self, field, None)
            if value:
                # Split by comma or semicolon, strip whitespace, filter empty
                emails = [e.strip() for e in value.replace(";", ",").split(",")]
                emails = [e for e in emails if e]
                setattr(self, field, ", ".join(emails))

    def validate_sms_settings(self):
        """Validate SMS-specific settings."""
        if self.notification_channel != "SMS":
            return

        if self.sms_sender_id and len(self.sms_sender_id) > 11:
            frappe.throw(_("SMS Sender ID cannot exceed 11 characters"))

        if cint(self.sms_max_length) <= 0:
            self.sms_max_length = 160

    # =========================================================================
    # DEFAULT TEMPLATE MANAGEMENT
    # =========================================================================

    def update_default_template_flag(self):
        """Unset is_default on other templates when this one is set as default."""
        if not self.is_default:
            return

        filters = {
            "event_type": self.event_type,
            "notification_channel": self.notification_channel,
            "is_default": 1,
            "name": ["!=", self.name]
        }

        if self.tenant:
            filters["tenant"] = self.tenant
        elif self.is_global:
            filters["is_global"] = 1

        # Unset other defaults
        existing_defaults = frappe.get_all(
            "Notification Template",
            filters=filters,
            fields=["name"]
        )

        for template in existing_defaults:
            frappe.db.set_value(
                "Notification Template", template.name,
                "is_default", 0, update_modified=False
            )

    # =========================================================================
    # TEMPLATE RENDERING
    # =========================================================================

    def render(self, data=None, raise_on_error=False):
        """
        Render the template with provided data.

        Args:
            data: Dictionary of variable values for template rendering
            raise_on_error: Whether to raise exceptions on render errors

        Returns:
            dict: Rendered content with keys 'subject', 'body', 'plain_text'
        """
        if data is None:
            data = {}

        # Add default variables
        data = self._add_default_variables(data)

        result = {
            "subject": None,
            "body": None,
            "plain_text": None,
            "push_click_action": None,
        }

        try:
            if self.subject:
                result["subject"] = Template(self.subject).render(**data)

            if self.body:
                result["body"] = Template(self.body).render(**data)

            if self.plain_text_body:
                result["plain_text"] = Template(self.plain_text_body).render(**data)

            if self.push_click_action:
                result["push_click_action"] = Template(
                    self.push_click_action
                ).render(**data)

        except (TemplateSyntaxError, UndefinedError) as e:
            if raise_on_error:
                raise
            frappe.log_error(
                message=f"Template render error: {str(e)}",
                title=f"Notification Template: {self.name}"
            )
            result["error"] = str(e)

        return result

    def _add_default_variables(self, data):
        """Add default platform variables to data dictionary."""
        from frappe.utils import now_datetime, nowdate

        defaults = {
            "current_date": nowdate(),
            "current_time": now_datetime().strftime("%H:%M"),
            "platform_name": frappe.db.get_single_value(
                "System Settings", "app_name"
            ) or "Trade Hub",
            "platform_url": frappe.utils.get_url(),
            "support_email": frappe.db.get_single_value(
                "System Settings", "support_email"
            ) or "",
            "support_phone": "",
        }

        # Merge with provided data (provided data takes precedence)
        return {**defaults, **data}

    def preview(self, sample_data=None):
        """
        Preview the rendered template with sample data.

        Args:
            sample_data: Optional custom data, otherwise uses example_data

        Returns:
            dict: Rendered preview content
        """
        if sample_data is None:
            if self.example_data:
                try:
                    sample_data = json.loads(self.example_data)
                except (json.JSONDecodeError, TypeError):
                    sample_data = {}
            else:
                # Generate sample data from available variables
                sample_data = self._generate_sample_data()

        return self.render(sample_data)

    def _generate_sample_data(self):
        """Generate sample data for preview based on available variables."""
        sample_data = {}

        try:
            variables = json.loads(self.available_variables or "[]")
        except (json.JSONDecodeError, TypeError):
            variables = []

        # Generate sample values for common variable patterns
        sample_values = {
            "name": "John Doe",
            "email": "john.doe@example.com",
            "company": "ACME Corporation",
            "id": "12345",
            "date": nowdate(),
            "time": now_datetime().strftime("%H:%M"),
            "amount": "$1,234.56",
            "quantity": "100",
            "price": "$99.99",
            "percent": "15%",
            "number": "42",
            "link": "https://example.com/action",
            "reason": "Sample reason text",
            "notes": "Sample notes text",
            "status": "Active",
        }

        for var in variables:
            var_lower = var.lower()
            # Match based on partial name
            for key, value in sample_values.items():
                if key in var_lower:
                    sample_data[var] = value
                    break
            else:
                # Default to variable name as value
                sample_data[var] = f"[{var}]"

        return sample_data

    # =========================================================================
    # STATISTICS TRACKING
    # =========================================================================

    def increment_sent_count(self):
        """Increment the sent count and update last_sent_at."""
        frappe.db.set_value(
            self.doctype, self.name,
            {
                "sent_count": cint(self.sent_count) + 1,
                "last_sent_at": now_datetime()
            },
            update_modified=False
        )

    def increment_delivered_count(self):
        """Increment the delivered count."""
        frappe.db.set_value(
            self.doctype, self.name,
            "delivered_count", cint(self.delivered_count) + 1,
            update_modified=False
        )

    def increment_failed_count(self):
        """Increment the failed count."""
        frappe.db.set_value(
            self.doctype, self.name,
            "failed_count", cint(self.failed_count) + 1,
            update_modified=False
        )

    def get_delivery_rate(self):
        """Calculate the delivery success rate."""
        total = cint(self.sent_count)
        if total == 0:
            return 0.0
        return (cint(self.delivered_count) / total) * 100

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_template_cache(self):
        """Clear cached template data."""
        cache_keys = [
            f"notification_template:{self.name}",
            f"notification_template:{self.template_code}",
            f"notification_templates:{self.event_type}:{self.notification_channel}",
        ]

        if self.tenant:
            cache_keys.append(f"tenant_templates:{self.tenant}")
        else:
            cache_keys.append("global_templates")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # DELETION CHECKS
    # =========================================================================

    def check_usage_before_delete(self):
        """Check if template is in use before allowing deletion."""
        # Check if this is the only template for this event type
        count = frappe.db.count(
            "Notification Template",
            {
                "event_type": self.event_type,
                "notification_channel": self.notification_channel,
                "enabled": 1,
                "name": ["!=", self.name]
            }
        )

        if count == 0 and self.enabled:
            frappe.msgprint(
                _("Warning: This is the only enabled template for {0} - {1}. "
                  "Notifications of this type will not be sent after deletion.").format(
                    self.event_type, self.notification_channel
                ),
                indicator='orange',
                alert=True
            )


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_template(template_code=None, event_type=None, channel=None, tenant=None):
    """
    Get a notification template by code or event type and channel.

    Args:
        template_code: The template code (takes precedence)
        event_type: The event type
        channel: The notification channel
        tenant: Optional tenant filter

    Returns:
        dict: Template document data
    """
    if template_code:
        filters = {"template_code": template_code, "enabled": 1}
    elif event_type and channel:
        filters = {
            "event_type": event_type,
            "notification_channel": channel,
            "enabled": 1
        }
    else:
        frappe.throw(_("Provide either template_code or event_type and channel"))

    # Add tenant filter
    if tenant:
        # Try tenant-specific first, then global
        tenant_filters = {**filters, "tenant": tenant}
        template = frappe.db.get_value(
            "Notification Template", tenant_filters, "*", as_dict=True
        )
        if template:
            return template

        # Fall back to global
        filters["is_global"] = 1
        filters["tenant"] = ["is", "not set"]

    template = frappe.db.get_value(
        "Notification Template", filters, "*", as_dict=True
    )

    if not template:
        frappe.throw(
            _("No enabled template found for the specified criteria")
        )

    return template


@frappe.whitelist()
def get_default_template(event_type, channel, tenant=None):
    """
    Get the default template for an event type and channel.

    Args:
        event_type: The event type
        channel: The notification channel
        tenant: Optional tenant filter

    Returns:
        dict: Template document data
    """
    filters = {
        "event_type": event_type,
        "notification_channel": channel,
        "is_default": 1,
        "enabled": 1
    }

    if tenant:
        # Try tenant-specific first
        tenant_filters = {**filters, "tenant": tenant}
        template = frappe.db.get_value(
            "Notification Template", tenant_filters, "*", as_dict=True
        )
        if template:
            return template

    # Fall back to global default
    filters["is_global"] = 1
    template = frappe.db.get_value(
        "Notification Template", filters, "*", as_dict=True
    )

    if not template:
        # Return any enabled template as fallback
        del filters["is_default"]
        template = frappe.db.get_value(
            "Notification Template", filters, "*", as_dict=True
        )

    return template


@frappe.whitelist()
def preview_template(template_name, sample_data=None):
    """
    Preview a rendered template with sample data.

    Args:
        template_name: The template document name
        sample_data: Optional JSON string of sample data

    Returns:
        dict: Rendered content
    """
    doc = frappe.get_doc("Notification Template", template_name)

    data = None
    if sample_data:
        if isinstance(sample_data, str):
            data = json.loads(sample_data)
        else:
            data = sample_data

    return doc.preview(data)


@frappe.whitelist()
def render_template(template_name, data):
    """
    Render a template with provided data.

    Args:
        template_name: The template document name
        data: JSON string or dict of variable values

    Returns:
        dict: Rendered content
    """
    doc = frappe.get_doc("Notification Template", template_name)

    if isinstance(data, str):
        data = json.loads(data)

    return doc.render(data)


@frappe.whitelist()
def get_templates_by_event(event_type, channel=None, tenant=None, include_disabled=False):
    """
    Get all templates for a specific event type.

    Args:
        event_type: The event type
        channel: Optional channel filter
        tenant: Optional tenant filter
        include_disabled: Include disabled templates

    Returns:
        list: List of template records
    """
    filters = {"event_type": event_type}

    if channel:
        filters["notification_channel"] = channel

    if not include_disabled:
        filters["enabled"] = 1

    if tenant:
        # Get both tenant-specific and global templates
        tenant_filters = {**filters, "tenant": tenant}
        global_filters = {**filters, "is_global": 1}

        tenant_templates = frappe.get_all(
            "Notification Template",
            filters=tenant_filters,
            fields=["name", "template_code", "template_name", "notification_channel",
                    "is_default", "enabled", "tenant_name", "is_global"]
        )

        global_templates = frappe.get_all(
            "Notification Template",
            filters=global_filters,
            fields=["name", "template_code", "template_name", "notification_channel",
                    "is_default", "enabled", "tenant_name", "is_global"]
        )

        return tenant_templates + global_templates

    return frappe.get_all(
        "Notification Template",
        filters=filters,
        fields=["name", "template_code", "template_name", "notification_channel",
                "is_default", "enabled", "tenant_name", "is_global"]
    )


@frappe.whitelist()
def get_available_variables(event_type):
    """
    Get the list of available variables for an event type.

    Args:
        event_type: The event type

    Returns:
        dict: Dictionary with 'default' and 'event_specific' variable lists
    """
    event_vars = EVENT_VARIABLE_REQUIREMENTS.get(event_type, [])

    return {
        "default": DEFAULT_VARIABLES,
        "event_specific": event_vars,
        "all": list(set(DEFAULT_VARIABLES + event_vars))
    }


@frappe.whitelist()
def set_default_template(template_name):
    """
    Set a template as the default for its event type and channel.

    Args:
        template_name: The template document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Notification Template", template_name)
    doc.is_default = 1
    doc.save()

    return {
        "success": True,
        "message": _("Template {0} set as default for {1} - {2}").format(
            doc.template_name, doc.event_type, doc.notification_channel
        )
    }


@frappe.whitelist()
def duplicate_template(template_name, new_code, new_name=None, tenant=None):
    """
    Duplicate an existing template.

    Args:
        template_name: The source template document name
        new_code: New template code
        new_name: Optional new template name
        tenant: Optional tenant to assign to new template

    Returns:
        dict: New template info
    """
    source = frappe.get_doc("Notification Template", template_name)

    new_doc = frappe.copy_doc(source)
    new_doc.template_code = new_code.upper().replace(" ", "_")
    new_doc.template_name = new_name or f"Copy of {source.template_name}"
    new_doc.is_default = 0
    new_doc.sent_count = 0
    new_doc.delivered_count = 0
    new_doc.failed_count = 0
    new_doc.last_sent_at = None

    if tenant:
        new_doc.tenant = tenant
        new_doc.is_global = 0
    elif source.is_global:
        new_doc.is_global = 1
        new_doc.tenant = None

    new_doc.insert()

    return {
        "name": new_doc.name,
        "template_code": new_doc.template_code,
        "message": _("Template duplicated successfully")
    }


@frappe.whitelist()
def get_template_statistics(template_name=None, event_type=None, channel=None, tenant=None):
    """
    Get delivery statistics for templates.

    Args:
        template_name: Optional specific template
        event_type: Optional event type filter
        channel: Optional channel filter
        tenant: Optional tenant filter

    Returns:
        dict: Statistics summary
    """
    if template_name:
        doc = frappe.get_doc("Notification Template", template_name)
        return {
            "template_name": doc.template_name,
            "sent_count": doc.sent_count,
            "delivered_count": doc.delivered_count,
            "failed_count": doc.failed_count,
            "delivery_rate": doc.get_delivery_rate(),
            "last_sent_at": str(doc.last_sent_at) if doc.last_sent_at else None
        }

    # Aggregate statistics
    filters = {}
    if event_type:
        filters["event_type"] = event_type
    if channel:
        filters["notification_channel"] = channel
    if tenant:
        filters["tenant"] = tenant

    templates = frappe.get_all(
        "Notification Template",
        filters=filters,
        fields=["sent_count", "delivered_count", "failed_count"]
    )

    total_sent = sum(t.sent_count or 0 for t in templates)
    total_delivered = sum(t.delivered_count or 0 for t in templates)
    total_failed = sum(t.failed_count or 0 for t in templates)

    return {
        "template_count": len(templates),
        "total_sent": total_sent,
        "total_delivered": total_delivered,
        "total_failed": total_failed,
        "overall_delivery_rate": (total_delivered / total_sent * 100) if total_sent > 0 else 0
    }


@frappe.whitelist()
def create_standard_templates(tenant=None):
    """
    Create standard notification templates for common events.

    Args:
        tenant: Optional tenant to create templates for

    Returns:
        dict: Created templates info
    """
    standard_templates = [
        {
            "template_code": "ORDER_CONFIRMATION_EMAIL",
            "template_name": "Order Confirmation",
            "notification_channel": "Email",
            "event_type": "Order Created",
            "subject": "Order Confirmation - Order #{{ order_id }}",
            "body": """<p>Dear {{ buyer_name }},</p>
<p>Thank you for your order!</p>
<p><strong>Order Details:</strong></p>
<ul>
<li>Order ID: {{ order_id }}</li>
<li>Order Date: {{ order_date }}</li>
<li>Total Amount: {{ total_amount }}</li>
</ul>
<p>We will notify you when your order is shipped.</p>
<p>Best regards,<br>{{ platform_name }}</p>""",
            "plain_text_body": "Dear {{ buyer_name }}, Thank you for your order #{{ order_id }}! Total: {{ total_amount }}. We will notify you when your order is shipped.",
            "is_default": 1,
        },
        {
            "template_code": "ORDER_SHIPPED_EMAIL",
            "template_name": "Order Shipped",
            "notification_channel": "Email",
            "event_type": "Order Shipped",
            "subject": "Your Order Has Shipped - Order #{{ order_id }}",
            "body": """<p>Dear {{ buyer_name }},</p>
<p>Great news! Your order has been shipped.</p>
<p><strong>Tracking Information:</strong></p>
<ul>
<li>Carrier: {{ carrier }}</li>
<li>Tracking Number: {{ tracking_number }}</li>
<li>Estimated Delivery: {{ estimated_delivery }}</li>
</ul>
<p>Best regards,<br>{{ platform_name }}</p>""",
            "plain_text_body": "Dear {{ buyer_name }}, Your order #{{ order_id }} has shipped! Tracking: {{ tracking_number }} via {{ carrier }}. Estimated delivery: {{ estimated_delivery }}.",
            "is_default": 1,
        },
        {
            "template_code": "RFQ_RESPONSE_EMAIL",
            "template_name": "RFQ Response Received",
            "notification_channel": "Email",
            "event_type": "RFQ Response Received",
            "subject": "New Quote Received for Your RFQ #{{ rfq_id }}",
            "body": """<p>Dear {{ buyer_name }},</p>
<p>You have received a new quotation for your RFQ!</p>
<p><strong>Quote Details:</strong></p>
<ul>
<li>RFQ ID: {{ rfq_id }}</li>
<li>Seller: {{ seller_name }}</li>
<li>Quote Amount: {{ quote_amount }}</li>
</ul>
<p>Please review and respond at your earliest convenience.</p>
<p>Best regards,<br>{{ platform_name }}</p>""",
            "plain_text_body": "Dear {{ buyer_name }}, You have received a quote from {{ seller_name }} for RFQ #{{ rfq_id }}: {{ quote_amount }}.",
            "is_default": 1,
        },
        {
            "template_code": "MESSAGE_RECEIVED_PUSH",
            "template_name": "New Message Push Notification",
            "notification_channel": "Push Notification",
            "event_type": "Message Received",
            "subject": "New message from {{ sender_name }}",
            "plain_text_body": "{{ message_preview }}",
            "push_click_action": "/messages/{{ thread_id }}",
            "is_default": 1,
        },
        {
            "template_code": "WELCOME_EMAIL",
            "template_name": "Welcome Email",
            "notification_channel": "Email",
            "event_type": "Welcome Email",
            "subject": "Welcome to {{ platform_name }}!",
            "body": """<p>Dear {{ user_name }},</p>
<p>Welcome to {{ platform_name }}!</p>
<p>Your account has been created successfully. You can now:</p>
<ul>
<li>Browse our product catalog</li>
<li>Submit requests for quotation</li>
<li>Connect with verified sellers</li>
</ul>
<p><a href="{{ login_link }}">Click here to login</a></p>
<p>Need help? Contact us at {{ support_email }}</p>
<p>Best regards,<br>{{ platform_name }} Team</p>""",
            "plain_text_body": "Dear {{ user_name }}, Welcome to {{ platform_name }}! Your account is ready. Login: {{ login_link }}. Support: {{ support_email }}",
            "is_default": 1,
        },
        {
            "template_code": "CERTIFICATE_EXPIRING_EMAIL",
            "template_name": "Certificate Expiring Soon",
            "notification_channel": "Email",
            "event_type": "Certificate Expiring",
            "subject": "Certificate Expiring Soon - {{ certificate_name }}",
            "body": """<p>Dear {{ holder_name }},</p>
<p>This is a reminder that your certificate is expiring soon:</p>
<p><strong>Certificate Details:</strong></p>
<ul>
<li>Certificate: {{ certificate_name }}</li>
<li>Expiry Date: {{ expiry_date }}</li>
<li>Days Remaining: {{ days_remaining }}</li>
</ul>
<p>Please renew your certificate to maintain your verified status.</p>
<p>Best regards,<br>{{ platform_name }}</p>""",
            "plain_text_body": "Dear {{ holder_name }}, Your certificate {{ certificate_name }} expires on {{ expiry_date }} ({{ days_remaining }} days remaining). Please renew it soon.",
            "is_default": 1,
        },
    ]

    created = []
    skipped = []

    for template_data in standard_templates:
        try:
            # Check if already exists
            existing = frappe.db.exists(
                "Notification Template",
                {"template_code": template_data["template_code"]}
            )

            if existing:
                skipped.append(template_data["template_code"])
                continue

            doc = frappe.new_doc("Notification Template")
            doc.update(template_data)

            if tenant:
                doc.tenant = tenant
                doc.is_global = 0
            else:
                doc.is_global = 1

            doc.insert(ignore_permissions=True)
            created.append(doc.template_code)

        except Exception as e:
            frappe.log_error(
                message=f"Failed to create template {template_data['template_code']}: {str(e)}",
                title="Standard Templates Creation"
            )

    return {
        "created": created,
        "skipped": skipped,
        "message": _("{0} templates created, {1} skipped (already exist)").format(
            len(created), len(skipped)
        )
    }
