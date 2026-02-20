# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Hooks Configuration

This file configures Frappe hooks for the Trade Hub B2B Trading Platform.
Key configurations include:
- Multi-tenant data isolation via doc_events and permission_query_conditions
- Scheduler jobs for background tasks
- Fixtures for initial data
- Jinja and override configurations
"""

app_name = "trade_hub"
app_title = "Trade Hub"
app_publisher = "Trade Hub"
app_description = "B2B Trading Platform with Multi-Tenant Support"
app_email = "support@tradehub.com"
app_license = "MIT"

# Required Apps
required_apps = ["frappe"]

# =============================================================================
# INCLUDES
# =============================================================================

# Include JS and CSS files in desk.html
# app_include_css = "/assets/trade_hub/css/trade_hub.css"
# app_include_js = "/assets/trade_hub/js/trade_hub.js"

# Include JS and CSS files in web.html
# web_include_css = "/assets/trade_hub/css/trade_hub.css"
# web_include_js = "/assets/trade_hub/js/trade_hub.js"

# Include custom scss in website theme
# website_theme_scss = "trade_hub/public/scss/website"

# Include JS in DocType views
doctype_js = {
    "PIM Product": "public/js/pim_product.js"
}

# =============================================================================
# PERMISSION HOOKS - Tenant Isolation
# =============================================================================

# Permission Query Conditions
# These functions add WHERE clause conditions to filter data by tenant
# Ensures users can only see data belonging to their tenant

permission_query_conditions = {
    # SKU and Product Management
    "SKU Product": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Product Category": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Brand": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Product Variant": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Product Attribute": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Product Attribute Value": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Incoterm Price": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Price Break": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Lead Time": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Sample Request": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # User Management
    "Seller Profile": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Seller Tier": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Buyer Profile": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # Media and Certificates
    "Media Asset": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Certificate Type": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Certificate": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # RFQ and Procurement
    "RFQ": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "RFQ Item": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Quotation": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # Orders and Payments
    "Order": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Order Item": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Payment Plan": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # Logistics
    "Shipment": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Carrier": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # Marketplace
    "Buy Box Entry": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Brand Gating": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Filter Config": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "SEO Meta": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Seller Store": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # Messaging
    "Message Thread": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Message": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
    "Notification Template": "tr_tradehub.permissions.get_tenant_permission_query_conditions",

    # Settings (tenant-specific)
    "Analytics Settings": "tr_tradehub.permissions.get_tenant_permission_query_conditions",
}

# Has Permission
# These functions check document-level permissions based on tenant
has_permission = {
    # SKU and Product Management
    "SKU Product": "tr_tradehub.permissions.has_tenant_permission",
    "Product Category": "tr_tradehub.permissions.has_tenant_permission",
    "Brand": "tr_tradehub.permissions.has_tenant_permission",
    "Product Variant": "tr_tradehub.permissions.has_tenant_permission",
    "Product Attribute": "tr_tradehub.permissions.has_tenant_permission",
    "Product Attribute Value": "tr_tradehub.permissions.has_tenant_permission",
    "Incoterm Price": "tr_tradehub.permissions.has_tenant_permission",
    "Price Break": "tr_tradehub.permissions.has_tenant_permission",
    "Lead Time": "tr_tradehub.permissions.has_tenant_permission",
    "Sample Request": "tr_tradehub.permissions.has_tenant_permission",

    # User Management
    "Seller Profile": "tr_tradehub.permissions.has_tenant_permission",
    "Seller Tier": "tr_tradehub.permissions.has_tenant_permission",
    "Buyer Profile": "tr_tradehub.permissions.has_tenant_permission",

    # Media and Certificates
    "Media Asset": "tr_tradehub.permissions.has_tenant_permission",
    "Certificate Type": "tr_tradehub.permissions.has_tenant_permission",
    "Certificate": "tr_tradehub.permissions.has_tenant_permission",

    # RFQ and Procurement
    "RFQ": "tr_tradehub.permissions.has_tenant_permission",
    "RFQ Item": "tr_tradehub.permissions.has_tenant_permission",
    "Quotation": "tr_tradehub.permissions.has_tenant_permission",

    # Orders and Payments
    "Order": "tr_tradehub.permissions.has_tenant_permission",
    "Order Item": "tr_tradehub.permissions.has_tenant_permission",
    "Payment Plan": "tr_tradehub.permissions.has_tenant_permission",

    # Logistics
    "Shipment": "tr_tradehub.permissions.has_tenant_permission",
    "Carrier": "tr_tradehub.permissions.has_tenant_permission",

    # Marketplace
    "Buy Box Entry": "tr_tradehub.permissions.has_tenant_permission",
    "Brand Gating": "tr_tradehub.permissions.has_tenant_permission",
    "Filter Config": "tr_tradehub.permissions.has_tenant_permission",
    "SEO Meta": "tr_tradehub.permissions.has_tenant_permission",
    "Seller Store": "tr_tradehub.permissions.has_tenant_permission",

    # Messaging
    "Message Thread": "tr_tradehub.permissions.has_tenant_permission",
    "Message": "tr_tradehub.permissions.has_tenant_permission",
    "Notification Template": "tr_tradehub.permissions.has_tenant_permission",

    # Settings (tenant-specific)
    "Analytics Settings": "tr_tradehub.permissions.has_tenant_permission",
}

# =============================================================================
# DOCUMENT EVENTS - Tenant Isolation
# =============================================================================

# Document events for automatic tenant assignment and validation
# Applies to ALL DocTypes (wildcard) - tenant utility functions
# handle exempt DocTypes internally

doc_events = {
    "*": {
        "before_insert": [
            "tr_tradehub.utils.tenant.set_tenant",
            "tr_tradehub.eca.dispatcher.evaluate_rules",
        ],
        "after_insert": "tr_tradehub.eca.dispatcher.evaluate_rules",
        "validate": [
            "tr_tradehub.utils.tenant.validate_tenant",
            "tr_tradehub.eca.dispatcher.evaluate_rules",
        ],
        "before_save": "tr_tradehub.eca.dispatcher.evaluate_rules",
        "after_save": "tr_tradehub.eca.dispatcher.evaluate_rules",
        "on_update": "tr_tradehub.eca.dispatcher.evaluate_rules",
        "on_submit": "tr_tradehub.eca.dispatcher.evaluate_rules",
        "on_cancel": "tr_tradehub.eca.dispatcher.evaluate_rules",
        "on_trash": "tr_tradehub.eca.dispatcher.evaluate_rules",
    },
    # Tenant-specific events
    "Tenant": {
        "after_insert": "tr_tradehub.utils.tenant.clear_tenant_cache",
        "on_update": "tr_tradehub.utils.tenant.clear_tenant_cache",
    },
    # =========================================================================
    # ERPNext Webhook Handlers - Reverse Sync
    # These handlers enable bidirectional synchronization between Trade Hub
    # entities and ERPNext documents. When ERPNext documents are modified,
    # the corresponding Trade Hub entities are updated automatically.
    # =========================================================================
    # Supplier -> Seller Profile reverse sync
    "Supplier": {
        "on_update": "tr_tradehub.webhooks.erpnext_hooks.on_supplier_update",
        "on_trash": "tr_tradehub.webhooks.erpnext_hooks.on_supplier_delete",
    },
    # Customer -> Buyer Profile reverse sync
    "Customer": {
        "on_update": "tr_tradehub.webhooks.erpnext_hooks.on_customer_update",
        "on_trash": "tr_tradehub.webhooks.erpnext_hooks.on_customer_delete",
    },
    # Item -> SKU Product reverse sync
    "Item": {
        "on_update": "tr_tradehub.webhooks.erpnext_hooks.on_item_update",
        "on_trash": "tr_tradehub.webhooks.erpnext_hooks.on_item_delete",
    },
    # Sales Order -> Order reverse sync
    "Sales Order": {
        "on_update": "tr_tradehub.webhooks.erpnext_hooks.on_sales_order_update",
        "on_submit": "tr_tradehub.webhooks.erpnext_hooks.on_sales_order_submit",
        "on_cancel": "tr_tradehub.webhooks.erpnext_hooks.on_sales_order_cancel",
    },
    # Stock Entry -> Inventory updates
    "Stock Entry": {
        "on_submit": "tr_tradehub.webhooks.erpnext_hooks.on_stock_entry_submit",
        "on_cancel": "tr_tradehub.webhooks.erpnext_hooks.on_stock_entry_cancel",
    },
    # Delivery Note -> Shipment status updates
    "Delivery Note": {
        "on_submit": "tr_tradehub.webhooks.erpnext_hooks.on_delivery_note_submit",
    },
}

# =============================================================================
# SCHEDULER JOBS
# =============================================================================

# Scheduler events for background tasks
scheduler_events = {
    # Uncomment as modules are implemented:
    # "all": [
    #     "tr_tradehub.tasks.all"
    # ],
    # "daily": [
    #     "tr_tradehub.tasks.daily"
    # ],
    # "hourly": [
    #     "tr_tradehub.tasks.hourly"
    # ],
    # "weekly": [
    #     "tr_tradehub.tasks.weekly"
    # ],
    # "monthly": [
    #     "tr_tradehub.tasks.monthly"
    # ],
    "cron": {
        # Media processing queue every 5 minutes
        # Processes pending media assets (resize, webp conversion, optimization)
        "*/5 * * * *": [
            "tr_tradehub.tasks.media_processor.process_pending_media"
        ],
        # Certificate expiry check at 6 AM daily
        # Checks for expiring certificates, sends notifications, updates expired status
        "0 6 * * *": [
            "tr_tradehub.tasks.certificate_alerts.check_expiring_certificates"
        ],
        # Buy Box rotation every hour
        # Rotates Buy Box winners fairly among similarly-scored sellers
        "0 * * * *": [
            "tr_tradehub.tasks.buybox_rotation.rotate_buybox"
        ],
        # ==========================================================================
        # SELLER KPI SCHEDULED TASKS
        # ==========================================================================
        # Daily Seller KPI calculation at 7 AM
        # Calculates KPI metrics for all active sellers
        "0 7 * * *": [
            "tr_tradehub.tasks.kpi_tasks.calculate_daily_seller_kpis"
        ],
        # Seller ranking recalculation at 8 AM daily (after KPI calculation)
        # Updates seller rankings based on latest KPI scores
        "0 8 * * *": [
            "tr_tradehub.tasks.kpi_tasks.recalculate_seller_rankings",
            "tr_tradehub.tasks.kpi_tasks.update_kpi_trends"
        ],
        # Monthly Seller KPI calculation on 1st of each month at 9 AM
        # Full recalculation for the previous month
        "0 9 1 * *": [
            "tr_tradehub.tasks.kpi_tasks.calculate_monthly_seller_kpis"
        ],
        # Buyer KPI calculation at 10 AM daily
        # Updates buyer statistics and metrics
        "0 10 * * *": [
            "tr_tradehub.tasks.kpi_tasks.calculate_buyer_kpis"
        ],
        # ==========================================================================
        # SELLER TIER SCHEDULED TASKS
        # ==========================================================================
        # Tier statistics update at 11 AM daily
        # Updates seller counts and performance stats for each tier
        "0 11 * * *": [
            "tr_tradehub.tasks.tier_tasks.update_tier_statistics"
        ],
        # Tier upgrade progress notifications at 12 PM daily
        # Notifies sellers who are close to qualifying for next tier
        "0 12 * * *": [
            "tr_tradehub.tasks.tier_tasks.process_tier_notifications"
        ],
        # Weekly tier evaluation every Sunday at 6 AM
        # Evaluates all sellers for tier upgrades/downgrades
        "0 6 * * 0": [
            "tr_tradehub.tasks.tier_tasks.evaluate_seller_tiers"
        ],

        # SELLER PAYOUT SCHEDULED TASKS
        # Process pending escrow releases at 8 AM daily
        # Releases funds to sellers after escrow hold period
        "0 8 * * *": [
            "tr_tradehub.utils.seller_payout.process_pending_escrow_releases"
        ],
        # Process scheduled payouts at 9 AM daily
        # Processes automatic payouts for sellers with auto_payout enabled
        "0 9 * * *": [
            "tr_tradehub.tr_tradehub.doctype.seller_balance.seller_balance.process_scheduled_payouts"
        ],

        # ==========================================================================
        # SHIPMENT & TRACKING SCHEDULED TASKS
        # ==========================================================================
        # Bulk fetch tracking updates every 30 minutes
        # Fetches tracking status from carrier APIs for active shipments
        "*/30 * * * *": [
            "tr_tradehub.tr_tradehub.doctype.shipment.shipment.bulk_fetch_tracking"
        ],

        # ==========================================================================
        # PRODUCT RANKING SCHEDULED TASKS
        # ==========================================================================
        # Full ranking recalculation at 3 AM daily
        # Calculates comprehensive ranking scores for all active listings
        "0 3 * * *": [
            "tr_tradehub.tr_tradehub.tasks.ranking.recalculate_all_rankings"
        ],
        # Category-specific ranking updates every 4 hours
        # More frequent updates focused on active categories
        "0 */4 * * *": [
            "tr_tradehub.tr_tradehub.tasks.ranking.recalculate_category_rankings"
        ],
        # Trending products update every hour
        # Captures real-time trends from recent activity
        "15 * * * *": [
            "tr_tradehub.tr_tradehub.tasks.ranking.update_trending_products"
        ],

        # ==========================================================================
        # CAMPAIGN SCHEDULED TASKS
        # ==========================================================================
        # Update campaign statuses at 5 AM daily
        # Activates scheduled campaigns, deactivates expired ones
        "0 5 * * *": [
            "tr_tradehub.tr_tradehub.doctype.campaign.campaign.update_campaign_statuses"
        ],
        # Process campaign analytics at 2 AM daily
        # Aggregates daily analytics for all active campaigns
        "0 2 * * *": [
            "tr_tradehub.tr_tradehub.doctype.campaign.campaign.aggregate_daily_analytics"
        ],
    }
}

# =============================================================================
# FIXTURES
# =============================================================================

# PIM and ECA Fixtures - auto-imported on bench migrate
# Order matters: PIM Attribute Group must load before PIM Attribute (Link field dependency)
fixtures = [
    {
        "doctype": "PIM Attribute Group",
        "filters": {"is_active": 1}
    },
    {
        "doctype": "PIM Attribute",
        "filters": {"is_active": 1}
    },
    {
        "doctype": "Product Class",
        "filters": {"is_active": 1}
    },
    {
        "doctype": "ECA Action Template",
        "filters": {"is_active": 1}
    }
]

# Legacy fixtures for initial data setup (commented)
# legacy_fixtures = [
#     {
#         "dt": "Custom Field",
#         "filters": [
#             ["module", "=", "Trade Hub"]
#         ]
#     },
#     {
#         "dt": "Property Setter",
#         "filters": [
#             ["module", "=", "Trade Hub"]
#         ]
#     },
#     {
#         "dt": "Role",
#         "filters": [
#             ["name", "in", [
#                 "Trade Hub Admin",
#                 "Tenant Admin",
#                 "Seller",
#                 "Buyer",
#                 "Seller Manager"
#             ]]
#         ]
#     },
#     "Seller Tier",  # Master data for seller tiers
#     "Certificate Type",  # Master data for certificate types
# ]

# =============================================================================
# JINJA CUSTOMIZATIONS
# =============================================================================

# Custom Jinja methods for templates
# jinja = {
#     "methods": "tr_tradehub.utils.jinja_utils"
# }

# =============================================================================
# OVERRIDE WHITELISTED METHODS
# =============================================================================

# Override whitelisted methods
# override_whitelisted_methods = {
#     "frappe.desk.doctype.event.event.get_events": "tr_tradehub.event.get_events"
# }

# =============================================================================
# OVERRIDE DOCTYPE CLASS
# =============================================================================

# Override DocType class
# override_doctype_class = {
#     "ToDo": "custom_app.overrides.CustomToDo"
# }

# =============================================================================
# WEBSITE CONTEXT
# =============================================================================

# Website context
# website_context = {
#     "favicon": "/assets/trade_hub/images/favicon.ico",
#     "splash_image": "/assets/trade_hub/images/splash.png"
# }

# =============================================================================
# BOOT SESSION
# =============================================================================

# Boot session data
# boot_session = "tr_tradehub.startup.boot_session"

# =============================================================================
# NOTIFICATION CONFIGURATION
# =============================================================================

# Notification settings
# notification_config = "tr_tradehub.notifications.get_notification_config"

# =============================================================================
# USER DATA PROTECTION
# =============================================================================

# User data protection for GDPR compliance
# user_data_fields = [
#     {
#         "doctype": "Seller Profile",
#         "filter_by": "user",
#         "partial": False
#     },
#     {
#         "doctype": "Buyer Profile",
#         "filter_by": "user",
#         "partial": False
#     }
# ]

# =============================================================================
# AFTER MIGRATE
# =============================================================================

# After migrate hooks for setup tasks
# after_migrate = ["tr_tradehub.setup.after_migrate"]

# =============================================================================
# BEFORE TESTS
# =============================================================================

# Before tests hook for test setup
# before_tests = "tr_tradehub.install.before_tests"
