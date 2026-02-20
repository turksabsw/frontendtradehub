app_name = "tr_consent_center"
app_title = "TR Consent Center"
app_publisher = "TR TradeHub"
app_description = "KVKK/GDPR Compliant Consent Management System for Frappe Framework"
app_email = "info@tr-tradehub.com"
app_license = "MIT"
app_icon = "octicon octicon-shield-check"
app_color = "#2ecc71"
app_version = "0.0.1"

# Required Apps
required_apps = ["frappe"]

# Fixtures
# --------
# Fixtures are data records exported from the database as JSON and loaded during
# app installation. Order matters - parent DocTypes should be loaded before children.
fixtures = [
    {
        "doctype": "Consent Channel",
        "filters": [["enabled", "=", 1]]
    },
    {
        "doctype": "Consent Topic",
        "filters": [["enabled", "=", 1]]
    },
    {
        "doctype": "Consent Method",
        "filters": [["enabled", "=", 1]]
    },
    {
        "doctype": "Consent Text",
        "filters": [["status", "=", "Active"]]
    }
]

# Module Definitions
# ------------------
# Define the modules that will be created in this app.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/tr_consent_center/css/tr_consent_center.css"
# app_include_js = "/assets/tr_consent_center/js/tr_consent_center.js"

# include js, css files in header of web template
# web_include_css = "/assets/tr_consent_center/css/tr_consent_center.css"
# web_include_js = "/assets/tr_consent_center/js/tr_consent_center.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "tr_consent_center/public/scss/website"

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
# app_include_icons = "tr_consent_center/public/icons.svg"

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
#     "methods": "tr_consent_center.utils.jinja_methods",
#     "filters": "tr_consent_center.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "tr_consent_center.install.before_install"
# after_install = "tr_consent_center.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "tr_consent_center.uninstall.before_uninstall"
# after_uninstall = "tr_consent_center.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "tr_consent_center.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#     "Consent Record": "tr_consent_center.permissions.consent_record_query",
# }
#
# has_permission = {
#     "Consent Record": "tr_consent_center.permissions.consent_record_has_permission",
# }

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
# KVKK/GDPR compliance requires automated consent expiry checks

scheduler_events = {
    "daily": [
        "tr_consent_center.tasks.check_expiring_consents",
        "tr_consent_center.tasks.purge_expired_records"
    ],
    "weekly": [
        "tr_consent_center.tasks.generate_consent_reports"
    ]
}

# Testing
# -------

# before_tests = "tr_consent_center.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#     "frappe.desk.doctype.event.event.get_events": "tr_consent_center.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#     "Task": "tr_consent_center.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["tr_consent_center.utils.before_request"]
# after_request = ["tr_consent_center.utils.after_request"]

# Job Events
# ----------
# before_job = ["tr_consent_center.utils.before_job"]
# after_job = ["tr_consent_center.utils.after_job"]

# User Data Protection
# --------------------
# KVKK/GDPR compliance - define user data fields for export/deletion

user_data_fields = [
    {
        "doctype": "Consent Record",
        "filter_by": "party",
        "redact_fields": [],
        "partial": 0,
    }
]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#     "tr_consent_center.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# default_log_clearing_doctypes = {
#     "Logging DocType Name": 30  # days to retain logs
# }
