app_name = "tr_contract_center"
app_title = "TR Contract Center"
app_publisher = "TR TradeHub"
app_description = "Contract Management System with Digital/Wet Signature Support for Frappe Framework"
app_email = "info@tr-tradehub.com"
app_license = "MIT"
app_icon = "octicon octicon-file-text"
app_color = "#e67e22"
app_version = "0.0.1"

# Required Apps
required_apps = ["frappe"]

# Fixtures
fixtures = [
    {
        "doctype": "ESign Provider",
        "filters": [["enabled", "=", 1]]
    }
]

# Includes in <head>
# app_include_css = "/assets/tr_contract_center/css/tr_contract_center.css"
# app_include_js = "/assets/tr_contract_center/js/tr_contract_center.js"

# Installation
# before_install = "tr_contract_center.install.before_install"
# after_install = "tr_contract_center.install.after_install"

# Document Events
doc_events = {
    "Contract Instance": {
        "on_update": "tr_contract_center.events.contract_instance_on_update"
    }
}

# Scheduled Tasks
scheduler_events = {
    "daily": [
        "tr_contract_center.tasks.check_expiring_contracts",
        "tr_contract_center.tasks.check_pending_signatures"
    ],
    "hourly": [
        "tr_contract_center.tasks.poll_esign_status"
    ]
}

# User Data Protection
user_data_fields = [
    {
        "doctype": "Contract Instance",
        "filter_by": "party",
        "redact_fields": [],
        "partial": 0,
    }
]

# Automatically update python controller files with type annotations
export_python_type_annotations = True
