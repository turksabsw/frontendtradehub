app_name = "tr_tradehub"
app_title = "TR TradeHub"
app_publisher = "TR TradeHub"
app_description = "TR-TradeHub B2B/B4B/C2C Marketplace Platform - A comprehensive hybrid marketplace combining Alibaba-style B2B/B4B wholesale trade with eBay-style C2C individual sales"
app_email = "info@tr-tradehub.com"
app_license = "MIT"
app_icon = "octicon octicon-globe"
app_color = "#3498db"
app_version = "0.0.1"

# Required Apps
required_apps = ["frappe"]

# Fixtures
# --------
# Fixtures are data records exported from the database as JSON and loaded during
# app installation. Order matters - parent DocTypes should be loaded before children.
# Numbered fixture files (01_, 02_, etc.) ensure correct import order.
fixtures = [
    # Core roles and role profiles - must be loaded first
    {
        "doctype": "Role",
        "filters": [["is_custom", "=", 1]]
    },
    {
        "doctype": "Role Profile"
    },
    # Business configuration data
    {
        "doctype": "Seller Tier",
        "filters": [["status", "=", "Active"]]
    },
    {
        "doctype": "Category",
        "filters": [["is_active", "=", 1]]
    },
    # Address hierarchy - City is parent of District, which is parent of Neighborhood
    # Order matters: load City first, then District, then Neighborhood
    {
        "doctype": "City",
        "filters": [["is_active", "=", 1]]
    },
    {
        "doctype": "District",
        "filters": [["is_active", "=", 1]]
    },
    {
        "doctype": "Neighborhood",
        "filters": [["is_active", "=", 1]]
    },
    # Phone codes linked to cities
    {
        "doctype": "Phone Code"
    },
    # Commercial regions for geographic business groupings
    {
        "doctype": "Commercial Region",
        "filters": [["is_active", "=", 1]]
    }
]

# Module Definitions
# ------------------
# Define the modules that will be created in this app.
# Modules provide groupings for DocTypes in the Frappe Desk.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/tr_tradehub/css/tr_tradehub.css"
# app_include_js = "/assets/tr_tradehub/js/tr_tradehub.js"

# include js, css files in header of web template
# web_include_css = "/assets/tr_tradehub/css/tr_tradehub.css"
# web_include_js = "/assets/tr_tradehub/js/tr_tradehub.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "tr_tradehub/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page": "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype": "public/js/doctype.js"}
# doctype_list_js = {"doctype": "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype": "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype": "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "tr_tradehub/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#     "Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#     "methods": "tr_tradehub.utils.jinja_methods",
#     "filters": "tr_tradehub.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "tr_tradehub.install.before_install"
# after_install = "tr_tradehub.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "tr_tradehub.uninstall.before_uninstall"
# after_uninstall = "tr_tradehub.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "tr_tradehub.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways
# These hooks enable tenant-based data isolation through User Permissions

# Permission query conditions add SQL WHERE clauses to filter data by tenant
# System Manager bypasses all restrictions, other users only see their tenant's data
permission_query_conditions = {
    # Core DocTypes
    "Seller Profile": "tr_tradehub.permissions.get_seller_permission_query",
    "Organization": "tr_tradehub.permissions.get_organization_permission_query",
    "Listing": "tr_tradehub.permissions.get_listing_permission_query",
    # Order-related DocTypes
    "Order": "tr_tradehub.permissions.get_order_permission_query",
    "Sub Order": "tr_tradehub.permissions.get_sub_order_permission_query",
    "Marketplace Order": "tr_tradehub.permissions.get_marketplace_order_permission_query",
    # Cart DocType - for shopping cart isolation
    "Cart": "tr_tradehub.permissions.get_cart_permission_query",
    # RFQ DocType - for B2B request for quote isolation
    "RFQ": "tr_tradehub.permissions.get_rfq_permission_query",
}

# Has permission hooks for document-level access control
# These are called when checking access to individual documents
has_permission = {
    "Seller Profile": "tr_tradehub.permissions.has_seller_permission",
    "Organization": "tr_tradehub.permissions.has_organization_permission",
    # Order-related DocTypes - buyers see their orders, sellers see their sub-orders
    "Marketplace Order": "tr_tradehub.permissions.has_marketplace_order_permission",
    "Sub Order": "tr_tradehub.permissions.has_sub_order_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
#     "ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
#     "*": {
#         "on_update": "method",
#         "on_cancel": "method",
#         "on_trash": "method"
#     }
# }

# Scheduled Tasks
# ---------------
# Scheduled jobs for maintenance, metrics refresh, and cleanup operations.
# Jobs are organized by frequency to optimize resource usage.

scheduler_events = {
    # Hourly jobs - frequent tasks for time-sensitive operations
    "hourly": [
        # Seller metrics refresh - keeps performance data current
        "tr_tradehub.seller_tags.tasks.refresh_seller_metrics",
        # RFQ deadline checking - updates expired RFQs and sends reminders
        "tr_tradehub.rfq.tasks.check_deadlines",
        "tr_tradehub.rfq.tasks.send_deadline_reminders",
    ],
    # Daily jobs - maintenance and cleanup tasks
    "daily": [
        # Seller tag rule evaluation - assigns/removes tags based on metrics
        "tr_tradehub.seller_tags.tasks.evaluate_all_rules",
        # Permission cleanup - removes orphan and duplicate User Permissions
        "tr_tradehub.scheduled_jobs.permission_cleanup.cleanup_orphan_user_permissions",
        "tr_tradehub.scheduled_jobs.permission_cleanup.cleanup_duplicate_permissions",
    ],
    # Weekly jobs - less frequent maintenance tasks
    "weekly": [
        # Metrics history cleanup - keeps only last 30 days of data
        "tr_tradehub.seller_tags.tasks.cleanup_old_metrics",
        # RFQ draft cleanup - removes old draft RFQs
        "tr_tradehub.rfq.tasks.cleanup_draft_rfqs",
        # Permission audit - generates audit log for review
        "tr_tradehub.scheduled_jobs.permission_cleanup.audit_permission_records",
    ],
}

# Testing
# -------

# before_tests = "tr_tradehub.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#     "frappe.desk.doctype.event.event.get_events": "tr_tradehub.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#     "Task": "tr_tradehub.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["tr_tradehub.utils.before_request"]
# after_request = ["tr_tradehub.utils.after_request"]

# Job Events
# ----------
# before_job = ["tr_tradehub.utils.before_job"]
# after_job = ["tr_tradehub.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#     {
#         "doctype": "{doctype_1}",
#         "filter_by": "{filter_by}",
#         "redact_fields": ["{field_1}", "{field_2}"],
#         "partial": 1,
#     },
#     {
#         "doctype": "{doctype_2}",
#         "filter_by": "{filter_by}",
#         "partial": 1,
#     },
#     {
#         "doctype": "{doctype_3}",
#         "strict": False,
#     },
#     {
#         "doctype": "{doctype_4}"
#     }
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#     "tr_tradehub.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
#     "Logging DocType Name": 30  # days to retain logs
# }
