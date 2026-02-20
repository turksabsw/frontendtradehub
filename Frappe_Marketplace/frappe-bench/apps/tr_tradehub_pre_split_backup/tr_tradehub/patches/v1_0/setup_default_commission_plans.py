# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Patch: Setup Default Commission Plans

This patch creates the default commission plans for TR-TradeHub:
- Free Plan (0% commission) - Default for new sellers, promotional period
- Standard Plan (10% commission) - Standard marketplace rate
- Premium Plan (8% commission) - For high-volume sellers
- Enterprise Plan (5% commission) - For enterprise sellers with negotiated rates
"""

import frappe
from frappe.utils import nowdate, add_months


def execute():
    """Create default commission plans."""
    # Schema reload for migration safety
    frappe.reload_doc("tr_tradehub", "doctype", "commission_plan")
    # Check if Commission Plan doctype exists
    if not frappe.db.exists("DocType", "Commission Plan"):
        frappe.log_error(
            "Commission Plan DocType does not exist. Please run bench migrate first.",
            "Setup Default Commission Plans Patch"
        )
        return

    today = nowdate()

    commission_plans = [
        {
            "plan_name": "Free Plan (Promotional)",
            "plan_code": "FREE",
            "plan_type": "Promotional",
            "status": "Active",
            "is_default": 1,
            "short_description": "0% commission promotional plan for new sellers. Help sellers grow their business on TR-TradeHub.",
            "full_description": """
                <h3>TR-TradeHub Free Plan</h3>
                <p>Our promotional free plan offers:</p>
                <ul>
                    <li>0% commission on all sales</li>
                    <li>No minimum transaction fees</li>
                    <li>Weekly automatic payouts</li>
                    <li>Basic seller support</li>
                </ul>
                <p>This plan is designed to help new sellers establish their presence on TR-TradeHub without any financial barriers.</p>
            """,
            "base_commission_rate": 0,
            "minimum_commission": 0,
            "maximum_commission": 0,
            "fixed_commission_amount": 0,
            "commission_calculation_type": "Percentage",
            "commission_currency": "TRY",
            "enable_category_rates": 0,
            "enable_volume_tiers": 0,
            "payment_frequency": "Weekly",
            "payment_day": 1,
            "minimum_payout_amount": 50,
            "payout_hold_days": 7,
            "auto_payout": 1,
            "deduct_shipping_from_commission": 0,
            "effective_from": today,
            "is_perpetual": 1,
            "required_verification_level": "None",
            "max_sellers": 0,  # Unlimited
            "is_invite_only": 0
        },
        {
            "plan_name": "Standard Plan",
            "plan_code": "STANDARD",
            "plan_type": "Standard",
            "status": "Active",
            "is_default": 0,
            "short_description": "10% commission standard plan for established sellers with full platform features.",
            "full_description": """
                <h3>TR-TradeHub Standard Plan</h3>
                <p>Our standard plan for established sellers includes:</p>
                <ul>
                    <li>10% commission on all sales</li>
                    <li>Priority customer support</li>
                    <li>Weekly automatic payouts</li>
                    <li>Access to promotional tools</li>
                    <li>Seller analytics dashboard</li>
                </ul>
            """,
            "base_commission_rate": 10,
            "minimum_commission": 1,
            "maximum_commission": 0,
            "fixed_commission_amount": 0,
            "commission_calculation_type": "Percentage",
            "commission_currency": "TRY",
            "enable_category_rates": 0,
            "enable_volume_tiers": 0,
            "payment_frequency": "Weekly",
            "payment_day": 1,
            "minimum_payout_amount": 100,
            "payout_hold_days": 14,
            "auto_payout": 1,
            "deduct_shipping_from_commission": 0,
            "effective_from": today,
            "is_perpetual": 1,
            "required_verification_level": "Basic",
            "max_sellers": 0,
            "is_invite_only": 0
        },
        {
            "plan_name": "Premium Plan",
            "plan_code": "PREMIUM",
            "plan_type": "Premium",
            "status": "Active",
            "is_default": 0,
            "short_description": "8% commission plan for high-volume sellers with volume-based discounts.",
            "full_description": """
                <h3>TR-TradeHub Premium Plan</h3>
                <p>Our premium plan for high-volume sellers includes:</p>
                <ul>
                    <li>8% base commission on all sales</li>
                    <li>Volume-based tier discounts available</li>
                    <li>Dedicated account manager</li>
                    <li>Priority placement in search results</li>
                    <li>Bi-weekly automatic payouts</li>
                    <li>Advanced analytics and reporting</li>
                </ul>
            """,
            "base_commission_rate": 8,
            "minimum_commission": 0,
            "maximum_commission": 0,
            "fixed_commission_amount": 0,
            "commission_calculation_type": "Percentage",
            "commission_currency": "TRY",
            "enable_category_rates": 0,
            "enable_volume_tiers": 1,
            "tier_calculation_basis": "Monthly GMV",
            "tier_calculation_period": "Monthly",
            "volume_tier_1_threshold": 100000,
            "volume_tier_1_rate": 7,
            "volume_tier_2_threshold": 500000,
            "volume_tier_2_rate": 6,
            "volume_tier_3_threshold": 1000000,
            "volume_tier_3_rate": 5,
            "payment_frequency": "Bi-Weekly",
            "payment_day": 1,
            "minimum_payout_amount": 100,
            "payout_hold_days": 7,
            "auto_payout": 1,
            "deduct_shipping_from_commission": 0,
            "effective_from": today,
            "is_perpetual": 1,
            "required_verification_level": "Business",
            "max_sellers": 0,
            "is_invite_only": 0
        },
        {
            "plan_name": "Enterprise Plan",
            "plan_code": "ENTERPRISE",
            "plan_type": "Enterprise",
            "status": "Active",
            "is_default": 0,
            "short_description": "5% commission plan for enterprise sellers with negotiated rates and custom terms.",
            "full_description": """
                <h3>TR-TradeHub Enterprise Plan</h3>
                <p>Our enterprise plan for large-scale sellers includes:</p>
                <ul>
                    <li>5% base commission on all sales</li>
                    <li>Custom negotiated rates available</li>
                    <li>Dedicated enterprise support team</li>
                    <li>API integration support</li>
                    <li>Custom reporting and analytics</li>
                    <li>Daily automatic payouts</li>
                    <li>No payout hold period</li>
                </ul>
            """,
            "base_commission_rate": 5,
            "minimum_commission": 0,
            "maximum_commission": 0,
            "fixed_commission_amount": 0,
            "commission_calculation_type": "Percentage",
            "commission_currency": "TRY",
            "enable_category_rates": 0,
            "enable_volume_tiers": 0,
            "payment_frequency": "Daily",
            "payment_day": 1,
            "minimum_payout_amount": 0,
            "payout_hold_days": 0,
            "auto_payout": 1,
            "deduct_shipping_from_commission": 0,
            "effective_from": today,
            "is_perpetual": 1,
            "required_verification_level": "Full",
            "max_sellers": 0,
            "is_invite_only": 1,
            "requires_signature": 1
        },
        {
            "plan_name": "New Seller Onboarding",
            "plan_code": "NEWSELLER",
            "plan_type": "New Seller",
            "status": "Active",
            "is_default": 0,
            "short_description": "0% commission for first 3 months, then transitions to Standard Plan.",
            "full_description": """
                <h3>TR-TradeHub New Seller Onboarding Plan</h3>
                <p>Special onboarding plan for new sellers:</p>
                <ul>
                    <li>0% commission for the first 3 months</li>
                    <li>Automatic transition to Standard Plan after onboarding period</li>
                    <li>Free seller training and onboarding support</li>
                    <li>Listing optimization assistance</li>
                    <li>Weekly payouts</li>
                </ul>
                <p>Start selling on TR-TradeHub risk-free!</p>
            """,
            "base_commission_rate": 0,
            "minimum_commission": 0,
            "maximum_commission": 0,
            "fixed_commission_amount": 0,
            "commission_calculation_type": "Percentage",
            "commission_currency": "TRY",
            "enable_category_rates": 0,
            "enable_volume_tiers": 0,
            "payment_frequency": "Weekly",
            "payment_day": 1,
            "minimum_payout_amount": 50,
            "payout_hold_days": 7,
            "auto_payout": 1,
            "deduct_shipping_from_commission": 0,
            "effective_from": today,
            "effective_until": add_months(today, 3),
            "is_perpetual": 0,
            "auto_renew": 0,
            "required_verification_level": "None",
            "max_sellers": 0,
            "is_invite_only": 0
        }
    ]

    created_count = 0
    updated_count = 0

    for plan_data in commission_plans:
        # Check if commission plan already exists by plan_code
        existing = frappe.db.get_value("Commission Plan", {"plan_code": plan_data["plan_code"]}, "name")

        if existing:
            # Update existing plan (but don't change is_default if already set elsewhere)
            doc = frappe.get_doc("Commission Plan", existing)
            for key, value in plan_data.items():
                if key not in ["plan_name", "is_default"]:
                    setattr(doc, key, value)
            doc.flags.ignore_permissions = True
            doc.save()
            updated_count += 1
            frappe.msgprint(f"Updated commission plan: {plan_data['plan_name']}")
        else:
            # Create new commission plan
            doc = frappe.get_doc({
                "doctype": "Commission Plan",
                **plan_data
            })
            doc.flags.ignore_permissions = True
            doc.insert()
            created_count += 1
            frappe.msgprint(f"Created commission plan: {plan_data['plan_name']}")

    # Ensure only one default plan
    default_plans = frappe.get_all(
        "Commission Plan",
        filters={"is_default": 1},
        fields=["name", "plan_code"]
    )

    if len(default_plans) > 1:
        # Keep only FREE as default
        for plan in default_plans:
            if plan.plan_code != "FREE":
                frappe.db.set_value("Commission Plan", plan.name, "is_default", 0)
        frappe.msgprint("Set FREE plan as the only default commission plan")

    frappe.db.commit()

    if created_count > 0:
        frappe.msgprint(f"Setup complete: Created {created_count} commission plans")
    if updated_count > 0:
        frappe.msgprint(f"Updated {updated_count} existing commission plans")
