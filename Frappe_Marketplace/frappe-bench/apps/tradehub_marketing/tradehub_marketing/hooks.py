app_name = "tradehub_marketing"
app_title = "TradeHub Marketing"
app_publisher = "TradeHub Team"
app_description = "Marketing, campaigns, coupons, and subscriptions layer for TradeHub Marketplace"
app_email = "dev@tradehub.local"
app_license = "MIT"
app_icon = "octicon octicon-megaphone"
app_color = "#6C5CE7"

# Dependencies - tradehub_core provides tenant isolation, tradehub_catalog provides products/categories,
# tradehub_commerce provides orders/carts for coupon application
required_apps = ["tradehub_core", "tradehub_catalog", "tradehub_commerce"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/tradehub_marketing/css/tradehub_marketing.css"
# app_include_js = "/assets/tradehub_marketing/js/tradehub_marketing.js"

# include js, css files in header of web template
# web_include_css = "/assets/tradehub_marketing/css/tradehub_marketing.css"
# web_include_js = "/assets/tradehub_marketing/js/tradehub_marketing.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "tradehub_marketing/public/scss/website"

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
# 	"methods": "tradehub_marketing.utils.jinja_methods",
# 	"filters": "tradehub_marketing.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "tradehub_marketing.install.before_install"
# after_install = "tradehub_marketing.install.after_install"

# Uninstallation
# --------------

# before_uninstall = "tradehub_marketing.uninstall.before_uninstall"
# after_uninstall = "tradehub_marketing.uninstall.after_uninstall"

# Desk Notifications
# ------------------

# See frappe.core.notifications.get_notification_config

# notification_config = "tradehub_marketing.notifications.get_notification_config"

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
# Marketing-specific doc_events for campaign and coupon management
doc_events = {
	"Campaign": {
		"on_update": "tradehub_marketing.handlers.on_campaign_update",
		"after_insert": "tradehub_marketing.handlers.on_campaign_created"
	},
	"Coupon": {
		"validate": "tradehub_marketing.handlers.validate_coupon"
	},
	"Group Buy": {
		"on_update": "tradehub_marketing.handlers.on_group_buy_update"
	}
}

# Scheduled Tasks
# ---------------

# Marketing-specific scheduled tasks: campaign management
# This task is moved from the monolithic tr_tradehub app during decomposition
scheduler_events = {
	"daily": [
		"tradehub_marketing.tasks.campaign_tasks"
	],
	"hourly": [
		"tradehub_marketing.tasks.group_buy_tasks"
	]
}

# Testing
# -------

# before_tests = "tradehub_marketing.install.before_tests"

# Overriding Methods
# ------------------------------

# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "tradehub_marketing.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "tradehub_marketing.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Request Events
# --------------

# before_request = ["tradehub_marketing.utils.before_request"]
# after_request = ["tradehub_marketing.utils.after_request"]

# Job Events
# ----------

# before_job = ["tradehub_marketing.utils.before_job"]
# after_job = ["tradehub_marketing.utils.after_job"]

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
# 	"tradehub_marketing.auth.validate"
# ]
