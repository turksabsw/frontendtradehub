"""
Desktop configuration for TradeHub Marketing module.
Defines the module's appearance and shortcuts in Frappe Desk.
"""

from frappe import _


def get_data():
    """Return the module configuration for the Desk interface."""
    return [
        {
            "module_name": "TradeHub Marketing",
            "color": "#6C5CE7",
            "icon": "octicon octicon-megaphone",
            "type": "module",
            "label": _("TradeHub Marketing"),
            "link": "modules/TradeHub Marketing",
            "description": "Marketing, campaigns, coupons, and subscriptions",
        }
    ]
