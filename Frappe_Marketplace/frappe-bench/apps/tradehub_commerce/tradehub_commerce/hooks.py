app_name = "tradehub_commerce"
app_title = "TradeHub Commerce"
app_publisher = "TradeHub Team"
app_description = "Orders, payments, and transactions layer for TradeHub Marketplace"
app_email = "dev@tradehub.local"
app_license = "MIT"
app_icon = "octicon octicon-credit-card"
app_color = "#0984E3"

# Dependencies - tradehub_core provides tenant isolation and ECA, tradehub_catalog provides products
required_apps = ["tradehub_core", "tradehub_catalog"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/tradehub_commerce/css/tradehub_commerce.css"
# app_include_js = "/assets/tradehub_commerce/js/tradehub_commerce.js"

# include js, css files in header of web template
# web_include_css = "/assets/tradehub_commerce/css/tradehub_commerce.css"
# web_include_js = "/assets/tradehub_commerce/js/tradehub_commerce.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "tradehub_commerce/public/scss/website"

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
# 	"methods": "tradehub_commerce.utils.jinja_methods",
# 	"filters": "tradehub_commerce.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "tradehub_commerce.install.before_install"
# after_install = "tradehub_commerce.install.after_install"

# Uninstallation
# --------------

# before_uninstall = "tradehub_commerce.uninstall.before_uninstall"
# after_uninstall = "tradehub_commerce.uninstall.after_uninstall"

# Desk Notifications
# ------------------

# See frappe.core.notifications.get_notification_config

# notification_config = "tradehub_commerce.notifications.get_notification_config"

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
# Commerce-specific doc_events for ERPNext webhook handlers
# These handle reverse sync from ERPNext back to TradeHub

doc_events = {
	"Sales Order": {
		"on_update": "tradehub_commerce.webhooks.erpnext_hooks.on_sales_order_update",
		"on_submit": "tradehub_commerce.webhooks.erpnext_hooks.on_sales_order_submit"
	},
	"Stock Entry": {
		"on_submit": "tradehub_commerce.webhooks.erpnext_hooks.on_stock_entry_submit"
	},
	"Delivery Note": {
		"on_submit": "tradehub_commerce.webhooks.erpnext_hooks.on_delivery_note_submit"
	}
}

# Scheduled Tasks
# ---------------

# Commerce-specific scheduled tasks: seller_payout
# This task is moved from the monolithic tr_tradehub app during decomposition
scheduler_events = {
	"daily": [
		"tradehub_commerce.tasks.seller_payout"
	]
}

# Testing
# -------

# before_tests = "tradehub_commerce.install.before_tests"

# Overriding Methods
# ------------------------------

# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "tradehub_commerce.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "tradehub_commerce.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Request Events
# --------------

# before_request = ["tradehub_commerce.utils.before_request"]
# after_request = ["tradehub_commerce.utils.after_request"]

# Job Events
# ----------

# before_job = ["tradehub_commerce.utils.before_job"]
# after_job = ["tradehub_commerce.utils.after_job"]

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
# 	"tradehub_commerce.auth.validate"
# ]
