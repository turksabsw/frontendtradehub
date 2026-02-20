"""
Hooks configuration for Mock Data Engine Frappe Application.

This file defines the metadata of the app and integration points with
Frappe Framework for task scheduling, document events, and other hooks.
"""

app_name = "mock_data_engine"
app_title = "Mock Data Engine"
app_publisher = "Custom"
app_description = "AI-powered mock data generation for Frappe applications"
app_email = "support@example.com"
app_license = "MIT"
app_version = "0.0.1"

# Required for proper app detection
required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/mock_data_engine/css/mock_data_engine.css"
# app_include_js = "/assets/mock_data_engine/js/mock_data_engine.js"

# include js, css files in header of web template
# web_include_css = "/assets/mock_data_engine/css/mock_data_engine.css"
# web_include_js = "/assets/mock_data_engine/js/mock_data_engine.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "mock_data_engine/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ---------
# include app icons in desk
# app_include_icons = "mock_data_engine/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#	"methods": "mock_data_engine.utils.jinja_methods",
#	"filters": "mock_data_engine.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "mock_data_engine.install.before_install"
# after_install = "mock_data_engine.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "mock_data_engine.uninstall.before_uninstall"
# after_uninstall = "mock_data_engine.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "mock_data_engine.utils.before_app_install"
# after_app_install = "mock_data_engine.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "mock_data_engine.utils.before_app_uninstall"
# after_app_uninstall = "mock_data_engine.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "mock_data_engine.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
#	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Mock Generation Request": {
		"on_update": "mock_data_engine.utils.doc_events.on_generation_request_update",
		"on_trash": "mock_data_engine.utils.doc_events.on_generation_request_trash"
	},
	"Mock Generation Log": {
		"after_insert": "mock_data_engine.utils.doc_events.on_generation_log_insert"
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
#	"all": [
#		"mock_data_engine.tasks.all"
#	],
#	"daily": [
#		"mock_data_engine.tasks.daily"
#	],
#	"hourly": [
#		"mock_data_engine.tasks.hourly"
#	],
#	"weekly": [
#		"mock_data_engine.tasks.weekly"
#	],
#	"monthly": [
#		"mock_data_engine.tasks.monthly"
#	],
# }

# Testing
# -------

# before_tests = "mock_data_engine.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "mock_data_engine.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "mock_data_engine.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["mock_data_engine.utils.before_request"]
# after_request = ["mock_data_engine.utils.after_request"]

# Job Events
# ----------
# before_job = ["mock_data_engine.utils.before_job"]
# after_job = ["mock_data_engine.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#	{
#		"doctype": "{doctype_1}",
#		"filter_by": "{filter_by}",
#		"redact_fields": ["{field_1}", "{field_2}"],
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_2}",
#		"filter_by": "{filter_by}",
#		"partial": 1,
#	},
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"mock_data_engine.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
#	"Logging DocType Name": 30  # days to retain logs
# }

# ============================================================
# Mock Data Engine Custom Hooks
# ============================================================
# These hooks allow other apps to customize mock data generation

# mock_data_before_generation = []
# mock_data_after_generation = []
# mock_data_before_doctype = []
# mock_data_after_doctype = []
# mock_data_before_record = []
# mock_data_after_record = []
# mock_data_on_error = []
# mock_data_field_generator = []

# Fixtures
# --------
# Automatically exported/imported data for this app
# These DocTypes will be exported with bench export-fixtures
# and imported automatically during app installation
fixtures = [
	# Industry master data - export all enabled industries
	{"dt": "Mock Industry", "filters": [["enabled", "=", 1]]},
	# Field mapping rules - export all enabled mappings
	{"dt": "Mock Field Mapping", "filters": [["enabled", "=", 1]]}
]
