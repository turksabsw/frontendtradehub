app_name = "tradehub_core"
app_title = "TradeHub Core"
app_publisher = "TradeHub Team"
app_description = "Base platform infrastructure layer for TradeHub Marketplace"
app_email = "dev@tradehub.local"
app_license = "MIT"
app_icon = "octicon octicon-organization"
app_color = "#0066CC"

# No dependencies for base layer
required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/tradehub_core/css/tradehub_core.css"
# app_include_js = "/assets/tradehub_core/js/tradehub_core.js"

# Tenant-Seller bidirectional filtering JS module
# Loaded on all desk pages to handle tenant-seller field interactions
app_include_js = ["/assets/tradehub_core/js/tenant_seller_filter.js"]

# include js, css files in header of web template
# web_include_css = "/assets/tradehub_core/css/tradehub_core.css"
# web_include_js = "/assets/tradehub_core/js/tradehub_core.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "tradehub_core/public/scss/website"

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# -----

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "tradehub_core.utils.jinja_methods",
# 	"filters": "tradehub_core.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "tradehub_core.install.before_install"
# after_install = "tradehub_core.install.after_install"

# Uninstallation
# --------------

# before_uninstall = "tradehub_core.uninstall.before_uninstall"
# after_uninstall = "tradehub_core.uninstall.after_uninstall"

# Desk Notifications
# ------------------

# See frappe.core.notifications.get_notification_config

# notification_config = "tradehub_core.notifications.get_notification_config"

# Permissions
# -----------

# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# -------------

# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------

# Hook on document methods and events

# Wildcard doc_events for tenant isolation and ECA dispatch
# These hooks apply to ALL DocTypes for multi-tenant isolation and
# event-condition-action rule evaluation
doc_events = {
	"*": {
		# Tenant isolation - validate tenant field before document operations
		"before_insert": "tradehub_core.utils.tenant.validate_tenant",
		# Tenant validation and tenant-seller consistency check
		# Multiple handlers: tenant isolation + tenant-seller match validation
		"validate": [
			"tradehub_core.utils.tenant.validate_tenant",
			"tradehub_core.utils.tenant_seller_validation.validate_tenant_seller_match"
		],
		# ECA rule dispatch - evaluate rules on document events
		"on_update": "tradehub_core.eca.dispatcher.evaluate_rules",
		"on_submit": "tradehub_core.eca.dispatcher.evaluate_rules",
		"on_cancel": "tradehub_core.eca.dispatcher.evaluate_rules",
		"after_insert": "tradehub_core.eca.dispatcher.evaluate_rules",
		"on_trash": "tradehub_core.eca.dispatcher.evaluate_rules",
	},
	# ERPNext reverse sync handlers - Customer -> Buyer Profile
	"Customer": {
		"on_update": "tradehub_core.webhooks.erpnext_hooks.on_customer_update",
		"after_insert": "tradehub_core.webhooks.erpnext_hooks.on_customer_insert",
		"on_trash": "tradehub_core.webhooks.erpnext_hooks.on_customer_delete"
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"tradehub_core.tasks.all"
# 	],
# 	"daily": [
# 		"tradehub_core.tasks.daily"
# 	],
# 	"hourly": [
# 		"tradehub_core.tasks.hourly"
# 	],
# 	"weekly": [
# 		"tradehub_core.tasks.weekly"
# 	],
# 	"monthly": [
# 		"tradehub_core.tasks.monthly"
# 	]
# }

# Testing
# -------

# before_tests = "tradehub_core.install.before_tests"

# Overriding Methods
# ------------------------------

# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "tradehub_core.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "tradehub_core.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Request Events
# --------------

# before_request = ["tradehub_core.utils.before_request"]
# after_request = ["tradehub_core.utils.after_request"]

# Job Events
# ----------

# before_job = ["tradehub_core.utils.before_job"]
# after_job = ["tradehub_core.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"tradehub_core.auth.validate"
# ]
