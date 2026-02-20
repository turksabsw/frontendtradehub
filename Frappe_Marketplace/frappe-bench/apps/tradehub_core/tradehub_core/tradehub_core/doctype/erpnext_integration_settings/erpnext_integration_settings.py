# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
ERPNext Integration Settings DocType for tenant-specific ERPNext synchronization.

This module implements tenant-specific ERPNext integration configuration including:
- Sync toggles for different entity types (Products, Orders, Sellers, Buyers)
- Connection settings for external ERPNext sites
- Webhook configuration for real-time synchronization
- Scheduled sync settings for background jobs
- Custom field mapping between Trade Hub and ERPNext
- Error handling and notification settings

Each tenant can have its own ERPNext integration configuration,
enabling multi-tenant sync isolation while maintaining platform-wide
visibility for administrators.
"""

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, cint, get_url, add_to_date


class ERPNextIntegrationSettings(Document):
    """
    ERPNext Integration Settings DocType for tenant-specific synchronization.

    Provides configuration for:
    - Sync toggles for products, orders, sellers, buyers
    - ERPNext connection settings
    - Webhook configuration
    - Scheduled sync settings
    - Error handling and notifications
    """

    def before_insert(self):
        """Set default values before inserting a new configuration."""
        self.validate_unique_tenant()
        self.set_default_webhook_url()
        self.calculate_next_sync_time()

    def validate(self):
        """Validate ERPNext integration settings before saving."""
        self.validate_connection_settings()
        self.validate_sync_settings()
        self.validate_webhook_settings()
        self.validate_schedule_settings()
        self.validate_error_handling()
        self.validate_field_mappings()

    def on_update(self):
        """Actions to perform after settings are updated."""
        self.clear_integration_cache()
        self.calculate_next_sync_time()

    def on_trash(self):
        """Actions to perform before deletion."""
        self.clear_integration_cache()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_unique_tenant(self):
        """Ensure only one integration settings exists per tenant."""
        if self.tenant:
            existing = frappe.db.get_value(
                "ERPNext Integration Settings",
                {"tenant": self.tenant, "name": ("!=", self.name or "")},
                "name"
            )
            if existing:
                frappe.throw(
                    _("ERPNext Integration Settings already exists for tenant {0}").format(
                        self.tenant
                    )
                )

    def validate_connection_settings(self):
        """Validate ERPNext connection settings."""
        if self.erpnext_site_url:
            url = self.erpnext_site_url.strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                frappe.throw(_("ERPNext site URL must start with http:// or https://"))
            self.erpnext_site_url = url

        # If external site URL is provided, API credentials are required
        if self.erpnext_site_url and self.enabled:
            if not self.erpnext_api_key:
                frappe.msgprint(
                    _("Warning: API Key is recommended when connecting to an external ERPNext site"),
                    indicator="orange"
                )

    def validate_sync_settings(self):
        """Validate sync toggle settings."""
        # At least one sync option should be enabled if integration is enabled
        if self.enabled:
            has_sync_enabled = any([
                self.sync_products,
                self.sync_sellers_to_suppliers,
                self.sync_buyers_to_customers,
                self.sync_orders_to_sales_orders,
                self.sync_rfq_to_supplier_quotation,
                self.sync_inventory
            ])
            if not has_sync_enabled:
                frappe.msgprint(
                    _("Warning: No sync options are enabled. Enable at least one sync option for the integration to be useful."),
                    indicator="orange"
                )

    def validate_webhook_settings(self):
        """Validate webhook configuration."""
        if self.enable_webhooks:
            if self.webhook_events:
                events = [e.strip() for e in self.webhook_events.split(",") if e.strip()]
                valid_events = [
                    "Item", "Sales Order", "Delivery Note", "Sales Invoice",
                    "Purchase Order", "Purchase Receipt", "Purchase Invoice",
                    "Stock Ledger Entry", "Supplier", "Customer"
                ]
                invalid_events = [e for e in events if e not in valid_events]
                if invalid_events:
                    frappe.msgprint(
                        _("Warning: Unknown webhook events: {0}. Valid events are: {1}").format(
                            ", ".join(invalid_events),
                            ", ".join(valid_events)
                        ),
                        indicator="orange"
                    )

    def validate_schedule_settings(self):
        """Validate scheduled sync settings."""
        if self.sync_interval_minutes:
            interval = cint(self.sync_interval_minutes)
            if interval < 5:
                frappe.throw(_("Sync interval must be at least 5 minutes"))
            if interval > 1440:
                frappe.throw(_("Sync interval cannot exceed 1440 minutes (24 hours)"))
            self.sync_interval_minutes = interval

    def validate_error_handling(self):
        """Validate error handling settings."""
        if self.max_retry_attempts:
            attempts = cint(self.max_retry_attempts)
            if attempts < 1:
                frappe.throw(_("Max retry attempts must be at least 1"))
            if attempts > 10:
                frappe.throw(_("Max retry attempts cannot exceed 10"))
            self.max_retry_attempts = attempts

        if self.notify_on_sync_failure and self.notification_email:
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, self.notification_email):
                frappe.throw(_("Invalid notification email format"))

    def validate_field_mappings(self):
        """Validate custom field mappings JSON."""
        if self.custom_field_mappings:
            try:
                mappings = json.loads(self.custom_field_mappings)
                if not isinstance(mappings, dict):
                    frappe.throw(_("Custom field mappings must be a JSON object"))
            except json.JSONDecodeError as e:
                frappe.throw(_("Invalid JSON in custom field mappings: {0}").format(str(e)))

    # =========================================================================
    # DEFAULT VALUE SETTERS
    # =========================================================================

    def set_default_webhook_url(self):
        """Set the default webhook endpoint URL."""
        if not self.webhook_url:
            base_url = get_url()
            self.webhook_url = f"{base_url}/api/method/trade_hub.webhooks.erpnext_hooks.receive_webhook"

    def calculate_next_sync_time(self):
        """Calculate the next scheduled sync time based on frequency."""
        if not self.enable_scheduled_sync:
            self.next_scheduled_sync = None
            return

        current_time = now_datetime()
        frequency_map = {
            "Every 15 Minutes": {"minutes": 15},
            "Every 30 Minutes": {"minutes": 30},
            "Hourly": {"hours": 1},
            "Daily": {"days": 1},
            "Weekly": {"days": 7}
        }

        interval = frequency_map.get(self.sync_frequency, {"hours": 1})
        self.next_scheduled_sync = add_to_date(current_time, **interval)

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_integration_cache(self):
        """Clear cached integration configuration."""
        cache_keys = [
            f"erpnext_integration:{self.tenant}",
            f"erpnext_sync_settings:{self.tenant}",
            f"erpnext_field_mappings:{self.tenant}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # CONFIGURATION GETTERS
    # =========================================================================

    def get_sync_config(self):
        """
        Get the sync configuration for this tenant.

        Returns:
            dict: Sync configuration with all toggle states
        """
        return {
            "enabled": self.enabled,
            "sync_products": self.sync_products,
            "sync_sellers_to_suppliers": self.sync_sellers_to_suppliers,
            "sync_buyers_to_customers": self.sync_buyers_to_customers,
            "sync_orders_to_sales_orders": self.sync_orders_to_sales_orders,
            "sync_rfq_to_supplier_quotation": self.sync_rfq_to_supplier_quotation,
            "sync_inventory": self.sync_inventory,
            "product_settings": {
                "auto_create_items": self.auto_create_items,
                "auto_update_items": self.auto_update_items,
                "sync_images": self.sync_product_images,
                "sync_variants": self.sync_product_variants,
                "default_item_group": self.default_item_group,
            },
            "order_settings": {
                "auto_create_sales_orders": self.auto_create_sales_orders,
                "auto_update_status": self.auto_update_order_status,
                "auto_create_delivery_notes": self.auto_create_delivery_notes,
                "auto_create_sales_invoices": self.auto_create_sales_invoices,
            },
            "inventory_settings": {
                "sync_stock_levels": self.sync_stock_levels,
                "sync_warehouse": self.sync_warehouse,
                "default_warehouse": self.default_warehouse,
                "sync_interval_minutes": self.sync_interval_minutes,
            }
        }

    def get_connection_config(self):
        """
        Get the connection configuration.

        Returns:
            dict: Connection settings (without sensitive data)
        """
        return {
            "site_url": self.erpnext_site_url,
            "is_external": bool(self.erpnext_site_url),
            "connection_status": self.connection_status,
        }

    def get_webhook_config(self):
        """
        Get the webhook configuration.

        Returns:
            dict: Webhook settings
        """
        events = []
        if self.webhook_events:
            events = [e.strip() for e in self.webhook_events.split(",") if e.strip()]

        return {
            "enabled": self.enable_webhooks,
            "webhook_url": self.webhook_url,
            "events": events,
        }

    def get_field_mappings(self):
        """
        Get custom field mappings.

        Returns:
            dict: Field mappings or empty dict if not configured
        """
        if self.custom_field_mappings:
            try:
                return json.loads(self.custom_field_mappings)
            except json.JSONDecodeError:
                return {}
        return {}

    def get_item_group_mappings(self):
        """
        Get item group mappings for category to item group conversion.

        Returns:
            dict: Category to Item Group mappings
        """
        if self.item_group_mapping:
            try:
                return json.loads(self.item_group_mapping)
            except json.JSONDecodeError:
                return {}
        return {}

    # =========================================================================
    # CONNECTION TEST
    # =========================================================================

    def test_connection(self):
        """
        Test the connection to ERPNext.

        Returns:
            dict: Connection test result with status and message
        """
        try:
            # If no external site URL, test local ERPNext installation
            if not self.erpnext_site_url:
                return self._test_local_erpnext()
            else:
                return self._test_external_erpnext()

        except Exception as e:
            self.db_set("connection_status", "Failed")
            self.db_set("last_connection_test", now_datetime())
            frappe.log_error(
                message=str(e),
                title=f"ERPNext Connection Test Error for {self.tenant}"
            )
            return {
                "success": False,
                "message": str(e)
            }

    def _test_local_erpnext(self):
        """Test if ERPNext is installed locally."""
        try:
            # Check if erpnext app is installed
            if "erpnext" not in frappe.get_installed_apps():
                self.db_set("connection_status", "Failed")
                self.db_set("last_connection_test", now_datetime())
                return {
                    "success": False,
                    "message": "ERPNext app is not installed on this site"
                }

            # Check if we can access ERPNext DocTypes
            required_doctypes = ["Item", "Customer", "Supplier", "Sales Order"]
            for doctype in required_doctypes:
                if not frappe.db.exists("DocType", doctype):
                    self.db_set("connection_status", "Failed")
                    return {
                        "success": False,
                        "message": f"ERPNext DocType '{doctype}' not found"
                    }

            self.db_set("connection_status", "Connected")
            self.db_set("last_connection_test", now_datetime())
            return {
                "success": True,
                "message": "Successfully connected to local ERPNext installation",
                "erpnext_version": frappe.get_attr("erpnext.__version__") if hasattr(frappe.get_module("erpnext"), "__version__") else "Unknown"
            }

        except Exception as e:
            self.db_set("connection_status", "Failed")
            self.db_set("last_connection_test", now_datetime())
            return {
                "success": False,
                "message": f"Error testing local ERPNext: {str(e)}"
            }

    def _test_external_erpnext(self):
        """Test connection to external ERPNext site."""
        import requests

        try:
            # Build API URL
            api_url = f"{self.erpnext_site_url}/api/method/frappe.client.get_list"

            headers = {}
            if self.erpnext_api_key and self.erpnext_api_secret:
                headers["Authorization"] = f"token {self.erpnext_api_key}:{self.get_password('erpnext_api_secret')}"

            # Test by fetching Item DocType list
            params = {
                "doctype": "Item",
                "limit_page_length": 1,
                "fields": '["name"]'
            }

            response = requests.get(
                api_url,
                headers=headers,
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                self.db_set("connection_status", "Connected")
                self.db_set("last_connection_test", now_datetime())
                return {
                    "success": True,
                    "message": f"Successfully connected to external ERPNext at {self.erpnext_site_url}"
                }
            elif response.status_code == 401:
                self.db_set("connection_status", "Failed")
                self.db_set("last_connection_test", now_datetime())
                return {
                    "success": False,
                    "message": "Authentication failed. Please check API Key and Secret."
                }
            elif response.status_code == 403:
                self.db_set("connection_status", "Failed")
                self.db_set("last_connection_test", now_datetime())
                return {
                    "success": False,
                    "message": "Access forbidden. The API user may lack necessary permissions."
                }
            else:
                self.db_set("connection_status", "Failed")
                self.db_set("last_connection_test", now_datetime())
                return {
                    "success": False,
                    "message": f"ERPNext returned status {response.status_code}"
                }

        except requests.exceptions.ConnectionError as e:
            self.db_set("connection_status", "Failed")
            self.db_set("last_connection_test", now_datetime())
            return {
                "success": False,
                "message": f"Could not connect to ERPNext server: {str(e)}"
            }

        except requests.exceptions.Timeout:
            self.db_set("connection_status", "Failed")
            self.db_set("last_connection_test", now_datetime())
            return {
                "success": False,
                "message": "Connection timed out after 30 seconds"
            }

    # =========================================================================
    # SYNC METHODS
    # =========================================================================

    def is_sync_enabled(self, entity_type):
        """
        Check if sync is enabled for a specific entity type.

        Args:
            entity_type: Type of entity (product, seller, buyer, order, rfq, inventory)

        Returns:
            bool: Whether sync is enabled for this entity type
        """
        if not self.enabled:
            return False

        entity_map = {
            "product": self.sync_products,
            "seller": self.sync_sellers_to_suppliers,
            "buyer": self.sync_buyers_to_customers,
            "order": self.sync_orders_to_sales_orders,
            "rfq": self.sync_rfq_to_supplier_quotation,
            "inventory": self.sync_inventory,
        }

        return bool(entity_map.get(entity_type, False))

    def increment_sync_count(self, entity_type, count=1):
        """
        Increment the sync count for an entity type.

        Args:
            entity_type: Type of entity (product or order)
            count: Number to increment by
        """
        if entity_type == "product":
            current = cint(self.total_synced_products)
            self.db_set("total_synced_products", current + count)
        elif entity_type == "order":
            current = cint(self.total_synced_orders)
            self.db_set("total_synced_orders", current + count)

    def increment_error_count(self):
        """Increment the sync error count."""
        current = cint(self.sync_error_count)
        self.db_set("sync_error_count", current + 1)

    def reset_error_count(self):
        """Reset the sync error count."""
        self.db_set("sync_error_count", 0)

    def update_last_sync_time(self):
        """Update the last sync timestamp."""
        self.db_set("last_sync_time", now_datetime())
        self.calculate_next_sync_time()
        if self.next_scheduled_sync:
            self.db_set("next_scheduled_sync", self.next_scheduled_sync)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_integration_settings(tenant):
    """
    Get ERPNext integration settings for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Integration settings document or None if not found
    """
    if not frappe.has_permission("ERPNext Integration Settings", "read"):
        frappe.throw(_("Not permitted to view ERPNext Integration Settings"))

    settings = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant},
        "*",
        as_dict=True
    )

    # Remove sensitive fields
    if settings:
        settings.pop("erpnext_api_secret", None)
        settings.pop("webhook_secret", None)

    return settings


@frappe.whitelist()
def get_sync_config(tenant):
    """
    Get the sync configuration for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Sync configuration
    """
    # Check cache first
    cache_key = f"erpnext_sync_settings:{tenant}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    # Get from database
    settings_name = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        return {"enabled": False}

    settings = frappe.get_doc("ERPNext Integration Settings", settings_name)
    config = settings.get_sync_config()

    # Cache for 5 minutes
    frappe.cache().set_value(cache_key, config, expires_in_sec=300)

    return config


@frappe.whitelist()
def test_erpnext_connection(tenant):
    """
    Test the ERPNext connection for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Connection test result
    """
    if not frappe.has_permission("ERPNext Integration Settings", "write"):
        frappe.throw(_("Not permitted to test ERPNext connection"))

    settings_name = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant},
        "name"
    )

    if not settings_name:
        return {"success": False, "message": "ERPNext Integration Settings not found"}

    settings = frappe.get_doc("ERPNext Integration Settings", settings_name)
    return settings.test_connection()


@frappe.whitelist()
def create_integration_settings(
    tenant,
    enabled=False,
    sync_products=True,
    sync_orders=True,
    sync_sellers=True,
    sync_buyers=True
):
    """
    Create ERPNext integration settings for a tenant.

    Args:
        tenant: Tenant name
        enabled: Whether to enable integration immediately
        sync_products: Enable product sync
        sync_orders: Enable order sync
        sync_sellers: Enable seller sync
        sync_buyers: Enable buyer sync

    Returns:
        dict: Created integration settings
    """
    if not frappe.has_permission("ERPNext Integration Settings", "create"):
        frappe.throw(_("Not permitted to create ERPNext Integration Settings"))

    # Check if settings already exist
    existing = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant},
        "name"
    )
    if existing:
        frappe.throw(_("ERPNext Integration Settings already exist for tenant {0}").format(tenant))

    doc = frappe.get_doc({
        "doctype": "ERPNext Integration Settings",
        "tenant": tenant,
        "enabled": 1 if enabled else 0,
        "sync_products": 1 if sync_products else 0,
        "sync_orders_to_sales_orders": 1 if sync_orders else 0,
        "sync_sellers_to_suppliers": 1 if sync_sellers else 0,
        "sync_buyers_to_customers": 1 if sync_buyers else 0,
    })

    doc.insert()

    # Return without sensitive data
    result = doc.as_dict()
    result.pop("erpnext_api_secret", None)
    result.pop("webhook_secret", None)

    return result


@frappe.whitelist()
def is_sync_enabled(tenant, entity_type):
    """
    Check if sync is enabled for a specific entity type.

    Args:
        tenant: Tenant name
        entity_type: Type of entity (product, seller, buyer, order, rfq, inventory)

    Returns:
        bool: Whether sync is enabled
    """
    settings_name = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        return False

    settings = frappe.get_doc("ERPNext Integration Settings", settings_name)
    return settings.is_sync_enabled(entity_type)


@frappe.whitelist()
def get_webhook_config(tenant):
    """
    Get webhook configuration for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Webhook configuration
    """
    settings_name = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant},
        "name"
    )

    if not settings_name:
        return {"enabled": False}

    settings = frappe.get_doc("ERPNext Integration Settings", settings_name)
    return settings.get_webhook_config()


@frappe.whitelist()
def update_sync_toggle(tenant, toggle_name, value):
    """
    Update a specific sync toggle.

    Args:
        tenant: Tenant name
        toggle_name: Name of the toggle field
        value: New value (0 or 1)

    Returns:
        dict: Success status
    """
    if not frappe.has_permission("ERPNext Integration Settings", "write"):
        frappe.throw(_("Not permitted to update ERPNext Integration Settings"))

    valid_toggles = [
        "enabled", "sync_products", "sync_sellers_to_suppliers",
        "sync_buyers_to_customers", "sync_orders_to_sales_orders",
        "sync_rfq_to_supplier_quotation", "sync_inventory"
    ]

    if toggle_name not in valid_toggles:
        frappe.throw(_("Invalid toggle name: {0}").format(toggle_name))

    settings_name = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant},
        "name"
    )

    if not settings_name:
        frappe.throw(_("ERPNext Integration Settings not found for tenant {0}").format(tenant))

    settings = frappe.get_doc("ERPNext Integration Settings", settings_name)
    settings.set(toggle_name, cint(value))
    settings.save()

    return {"success": True, "toggle": toggle_name, "value": cint(value)}


@frappe.whitelist()
def get_sync_statistics(tenant):
    """
    Get synchronization statistics for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Sync statistics
    """
    settings = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant},
        [
            "connection_status", "last_sync_time", "next_scheduled_sync",
            "total_synced_products", "total_synced_orders", "sync_error_count"
        ],
        as_dict=True
    )

    if not settings:
        return {
            "found": False,
            "message": "ERPNext Integration Settings not found"
        }

    return {
        "found": True,
        "connection_status": settings.connection_status,
        "last_sync_time": settings.last_sync_time,
        "next_scheduled_sync": settings.next_scheduled_sync,
        "total_synced_products": settings.total_synced_products or 0,
        "total_synced_orders": settings.total_synced_orders or 0,
        "sync_error_count": settings.sync_error_count or 0,
    }


@frappe.whitelist()
def trigger_manual_sync(tenant, sync_type="all"):
    """
    Trigger a manual synchronization for a tenant.

    Args:
        tenant: Tenant name
        sync_type: Type of sync (all, products, orders, sellers, buyers, inventory)

    Returns:
        dict: Sync job status
    """
    if not frappe.has_permission("ERPNext Integration Settings", "write"):
        frappe.throw(_("Not permitted to trigger synchronization"))

    settings_name = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        return {"success": False, "message": "ERPNext integration is not enabled for this tenant"}

    # Enqueue background sync job
    from tradehub_core.tradehub_core.utils.erpnext_sync import run_scheduled_sync

    frappe.enqueue(
        run_scheduled_sync,
        queue="long",
        tenant=tenant,
        sync_type=sync_type,
        is_manual=True
    )

    return {
        "success": True,
        "message": f"Synchronization job queued for {sync_type}",
        "job_type": sync_type
    }


@frappe.whitelist()
def reset_sync_statistics(tenant):
    """
    Reset sync statistics for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Success status
    """
    if not frappe.has_permission("ERPNext Integration Settings", "write"):
        frappe.throw(_("Not permitted to reset sync statistics"))

    settings_name = frappe.db.get_value(
        "ERPNext Integration Settings",
        {"tenant": tenant},
        "name"
    )

    if not settings_name:
        frappe.throw(_("ERPNext Integration Settings not found for tenant {0}").format(tenant))

    frappe.db.set_value(
        "ERPNext Integration Settings",
        settings_name,
        {
            "total_synced_products": 0,
            "total_synced_orders": 0,
            "sync_error_count": 0,
            "last_sync_time": None
        }
    )

    return {"success": True, "message": "Sync statistics reset successfully"}
