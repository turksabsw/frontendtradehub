# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, getdate, flt, cint
import json


class PaymentMethod(Document):
    """
    Payment Method DocType - Manages payment methods with customer/group assignment

    Features:
    - Multiple payment method types (Card, Bank Transfer, COD, BNPL, Credit Terms, etc.)
    - Customer/group assignment and restrictions
    - Buyer level requirements
    - Risk level restrictions and integration with Risk Score
    - Regional and currency settings
    - Fee configuration and transaction limits
    - Installment support for Turkish banks (Taksit)
    - Credit terms for B2B transactions
    - Cron BI integration
    """

    def validate(self):
        """Validate payment method data before save"""
        self.validate_method_code()
        self.validate_default_method()
        self.validate_limits()
        self.validate_fees()
        self.validate_installments()
        self.validate_credit_terms()
        self.validate_risk_settings()
        self.set_display_name()

    def before_save(self):
        """Before save hook"""
        self.validate_gateway_config()

    def on_update(self):
        """After update hook"""
        self.clear_cache()

    def validate_method_code(self):
        """Validate method code format"""
        if self.method_code:
            # Convert to uppercase and replace spaces with underscores
            self.method_code = self.method_code.upper().replace(" ", "_").replace("-", "_")

            # Remove any non-alphanumeric characters except underscores
            import re
            self.method_code = re.sub(r'[^A-Z0-9_]', '', self.method_code)

            if not self.method_code:
                frappe.throw(_("Method Code cannot be empty after sanitization"))

    def validate_default_method(self):
        """Ensure only one default payment method exists"""
        if self.is_default:
            existing_default = frappe.db.get_value(
                "Payment Method",
                {"is_default": 1, "name": ("!=", self.name)},
                "name"
            )
            if existing_default:
                frappe.db.set_value("Payment Method", existing_default, "is_default", 0)
                frappe.msgprint(
                    _("Previous default payment method '{0}' has been unset").format(existing_default),
                    indicator="orange"
                )

    def validate_limits(self):
        """Validate transaction limits"""
        if self.minimum_amount and self.maximum_amount:
            if flt(self.minimum_amount) > flt(self.maximum_amount) > 0:
                frappe.throw(_("Minimum Amount cannot be greater than Maximum Amount"))

        # Validate daily/weekly/monthly limits hierarchy
        if self.daily_limit and self.weekly_limit:
            if flt(self.daily_limit) > flt(self.weekly_limit):
                frappe.throw(_("Daily Limit cannot be greater than Weekly Limit"))

        if self.weekly_limit and self.monthly_limit:
            if flt(self.weekly_limit) > flt(self.monthly_limit):
                frappe.throw(_("Weekly Limit cannot be greater than Monthly Limit"))

        # Validate risk score threshold
        if self.risk_score_threshold:
            if cint(self.risk_score_threshold) < 0 or cint(self.risk_score_threshold) > 100:
                frappe.throw(_("Risk Score Threshold must be between 0 and 100"))

    def validate_fees(self):
        """Validate fee configuration"""
        if self.fee_type in ["Percentage", "Percentage + Fixed", "Tiered"]:
            if self.fee_percentage and flt(self.fee_percentage) < 0:
                frappe.throw(_("Fee Percentage cannot be negative"))
            if self.fee_percentage and flt(self.fee_percentage) > 100:
                frappe.throw(_("Fee Percentage cannot exceed 100%"))

        if self.fee_type in ["Fixed", "Percentage + Fixed"]:
            if self.fee_fixed_amount and flt(self.fee_fixed_amount) < 0:
                frappe.throw(_("Fixed Fee Amount cannot be negative"))

        if self.minimum_fee and self.maximum_fee:
            if flt(self.minimum_fee) > flt(self.maximum_fee) > 0:
                frappe.throw(_("Minimum Fee cannot be greater than Maximum Fee"))

    def validate_installments(self):
        """Validate installment settings"""
        if self.supports_installments:
            if not self.max_installments or cint(self.max_installments) < 2:
                frappe.throw(_("Maximum Installments must be at least 2 when installments are enabled"))

            if cint(self.max_installments) > 36:
                frappe.throw(_("Maximum Installments cannot exceed 36"))

            if self.installment_fee_percentage and flt(self.installment_fee_percentage) < 0:
                frappe.throw(_("Installment Fee Percentage cannot be negative"))

            # Validate installment options JSON
            if self.installment_options:
                try:
                    options = json.loads(self.installment_options)
                    if not isinstance(options, (list, dict)):
                        frappe.throw(_("Installment Options must be a valid JSON array or object"))
                except json.JSONDecodeError:
                    frappe.throw(_("Installment Options contains invalid JSON"))

    def validate_credit_terms(self):
        """Validate credit terms settings"""
        if self.supports_credit_terms:
            if not self.default_credit_days or cint(self.default_credit_days) < 1:
                self.default_credit_days = 30

            if not self.max_credit_days or cint(self.max_credit_days) < 1:
                self.max_credit_days = 90

            if cint(self.default_credit_days) > cint(self.max_credit_days):
                frappe.throw(_("Default Credit Days cannot exceed Maximum Credit Days"))

    def validate_risk_settings(self):
        """Validate risk management settings"""
        # Validate excluded risk levels format
        if self.excluded_risk_levels:
            valid_levels = ["Very Low", "Low", "Medium", "High", "Very High", "Critical"]
            levels = [l.strip() for l in self.excluded_risk_levels.split(",")]
            for level in levels:
                if level and level not in valid_levels:
                    frappe.throw(_("Invalid risk level: {0}").format(level))

    def validate_gateway_config(self):
        """Validate gateway configuration JSON"""
        if self.gateway_config:
            try:
                config = json.loads(self.gateway_config)
                if not isinstance(config, dict):
                    frappe.throw(_("Gateway Configuration must be a valid JSON object"))
            except json.JSONDecodeError:
                frappe.throw(_("Gateway Configuration contains invalid JSON"))

    def set_display_name(self):
        """Set display name if not provided"""
        if not self.display_name:
            self.display_name = self.method_name

    def clear_cache(self):
        """Clear payment method cache"""
        frappe.cache().delete_key("payment_methods")
        frappe.cache().delete_key(f"payment_method_{self.name}")

    def is_active(self):
        """Check if payment method is active"""
        return self.status == "Active"

    def is_available_for_buyer(self, buyer_user, buyer_level=None, organization=None):
        """
        Check if this payment method is available for a specific buyer

        Args:
            buyer_user: User ID of the buyer
            buyer_level: Buyer level code (optional)
            organization: Organization name (optional)

        Returns:
            Boolean indicating availability
        """
        if not self.is_active():
            return False

        # Check availability setting
        if self.available_to == "All":
            return True

        if self.available_to == "All Buyers":
            return True

        if self.available_to == "Specific Customers":
            if self.specific_customers:
                customer_list = frappe.get_all(
                    "Payment Method Customer",
                    filters={"parent": self.name},
                    pluck="customer"
                )
                return buyer_user in customer_list
            return False

        if self.available_to == "Buyer Levels" and buyer_level:
            if self.required_buyer_levels:
                required = [l.strip() for l in self.required_buyer_levels.split(",")]
                return buyer_level in required
            return True

        if self.available_to == "Premium Only":
            # Check if buyer has premium subscription
            premium = frappe.db.get_value(
                "Premium Buyer",
                {"buyer_profile": buyer_user, "status": "Active"},
                "name"
            )
            return bool(premium)

        if self.available_to == "Enterprise Only":
            # Check if organization has enterprise plan
            if organization:
                org_type = frappe.db.get_value("Organization", organization, "organization_type")
                return org_type == "Enterprise"
            return False

        return True

    def check_risk_eligibility(self, risk_score=None, risk_level=None):
        """
        Check if a buyer's risk profile allows this payment method

        Args:
            risk_score: Numeric risk score (0-100)
            risk_level: Risk level string

        Returns:
            Tuple of (eligible, reason)
        """
        # Check risk score threshold
        if risk_score is not None and self.risk_score_threshold:
            if cint(risk_score) > cint(self.risk_score_threshold):
                return False, _("Risk score {0} exceeds threshold {1}").format(
                    risk_score, self.risk_score_threshold
                )

        # Check risk level
        if risk_level:
            # Check excluded levels
            if self.excluded_risk_levels:
                excluded = [l.strip() for l in self.excluded_risk_levels.split(",")]
                if risk_level in excluded:
                    return False, _("Risk level '{0}' is excluded for this payment method").format(risk_level)

            # Check max risk level
            risk_order = ["Very Low", "Low", "Medium", "High", "Very High", "Critical"]
            if risk_level in risk_order and self.max_risk_level in risk_order:
                if risk_order.index(risk_level) > risk_order.index(self.max_risk_level):
                    return False, _("Risk level '{0}' exceeds maximum allowed '{1}'").format(
                        risk_level, self.max_risk_level
                    )

        return True, None

    def check_amount_limits(self, amount, buyer_user=None, period="transaction"):
        """
        Check if transaction amount is within limits

        Args:
            amount: Transaction amount
            buyer_user: User ID for cumulative checks (optional)
            period: 'transaction', 'daily', 'weekly', or 'monthly'

        Returns:
            Tuple of (within_limits, reason)
        """
        amount = flt(amount)

        # Check minimum
        if self.minimum_amount and amount < flt(self.minimum_amount):
            return False, _("Amount {0} is below minimum {1}").format(
                amount, self.minimum_amount
            )

        # Check maximum
        if self.maximum_amount and flt(self.maximum_amount) > 0:
            if amount > flt(self.maximum_amount):
                return False, _("Amount {0} exceeds maximum {1}").format(
                    amount, self.maximum_amount
                )

        # Check cumulative limits if buyer specified
        if buyer_user and period != "transaction":
            cumulative = self._get_cumulative_amount(buyer_user, period)

            if period == "daily" and self.daily_limit and flt(self.daily_limit) > 0:
                if cumulative + amount > flt(self.daily_limit):
                    return False, _("Transaction would exceed daily limit of {0}").format(self.daily_limit)

            if period == "weekly" and self.weekly_limit and flt(self.weekly_limit) > 0:
                if cumulative + amount > flt(self.weekly_limit):
                    return False, _("Transaction would exceed weekly limit of {0}").format(self.weekly_limit)

            if period == "monthly" and self.monthly_limit and flt(self.monthly_limit) > 0:
                if cumulative + amount > flt(self.monthly_limit):
                    return False, _("Transaction would exceed monthly limit of {0}").format(self.monthly_limit)

        return True, None

    def _get_cumulative_amount(self, buyer_user, period):
        """Get cumulative transaction amount for a buyer in a period"""
        from frappe.utils import add_days, add_to_date

        today = getdate(nowdate())

        if period == "daily":
            start_date = today
        elif period == "weekly":
            start_date = add_days(today, -7)
        elif period == "monthly":
            start_date = add_to_date(today, months=-1)
        else:
            return 0

        # Sum from Payment Intent
        total = frappe.db.sql("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM `tabPayment Intent`
            WHERE buyer = %s
            AND payment_method = %s
            AND status IN ('Paid', 'Captured', 'Authorized')
            AND DATE(created_at) >= %s
        """, (buyer_user, self.name, start_date))[0][0]

        return flt(total)

    def check_region_eligibility(self, country=None, region=None):
        """
        Check if payment method is available in a region

        Args:
            country: Country code
            region: Region/state/city name

        Returns:
            Tuple of (eligible, reason)
        """
        if not country and not region:
            return True, None

        # Check country
        if country and self.available_countries:
            available = [c.strip().upper() for c in self.available_countries.split(",")]
            if country.upper() not in available:
                if self.regional_restrictions_mode == "Include":
                    return False, _("Payment method not available in country: {0}").format(country)

        if country and self.excluded_countries:
            excluded = [c.strip().upper() for c in self.excluded_countries.split(",")]
            if country.upper() in excluded:
                return False, _("Payment method excluded in country: {0}").format(country)

        # Check region
        if region and self.excluded_regions:
            excluded = [r.strip().lower() for r in self.excluded_regions.split(",")]
            if region.lower() in excluded:
                return False, _("Payment method excluded in region: {0}").format(region)

        return True, None

    def calculate_fee(self, amount):
        """
        Calculate transaction fee for an amount

        Args:
            amount: Transaction amount

        Returns:
            Calculated fee amount
        """
        amount = flt(amount)
        fee = 0

        if self.fee_type == "None":
            return 0

        if self.fee_type in ["Percentage", "Percentage + Fixed"]:
            fee += amount * flt(self.fee_percentage) / 100

        if self.fee_type in ["Fixed", "Percentage + Fixed"]:
            fee += flt(self.fee_fixed_amount)

        # Apply minimum/maximum
        if self.minimum_fee and fee < flt(self.minimum_fee):
            fee = flt(self.minimum_fee)

        if self.maximum_fee and flt(self.maximum_fee) > 0:
            if fee > flt(self.maximum_fee):
                fee = flt(self.maximum_fee)

        return flt(fee, 2)

    def calculate_installment_amount(self, total_amount, installment_count):
        """
        Calculate installment amounts

        Args:
            total_amount: Total transaction amount
            installment_count: Number of installments

        Returns:
            Dictionary with installment details
        """
        if not self.supports_installments:
            return None

        if installment_count < 2 or installment_count > cint(self.max_installments):
            return None

        total_amount = flt(total_amount)

        # Calculate installment fee
        fee_rate = flt(self.installment_fee_percentage) / 100
        total_fee = total_amount * fee_rate * (installment_count - 1) / 12  # Approximate
        total_with_fee = total_amount + total_fee

        installment_amount = flt(total_with_fee / installment_count, 2)

        return {
            "total_amount": total_amount,
            "installment_count": installment_count,
            "installment_amount": installment_amount,
            "total_fee": flt(total_fee, 2),
            "total_with_fee": flt(total_with_fee, 2),
            "first_payment": installment_amount,
            "remaining_payments": installment_count - 1
        }

    def update_statistics(self, amount, success=True):
        """
        Update transaction statistics

        Args:
            amount: Transaction amount
            success: Whether transaction was successful
        """
        self.total_transactions = cint(self.total_transactions) + 1

        if success:
            self.total_amount_processed = flt(self.total_amount_processed) + flt(amount)

        # Calculate success rate
        successful = frappe.db.count(
            "Payment Intent",
            {"payment_method": self.name, "status": ["in", ["Paid", "Captured"]]}
        )
        total = frappe.db.count(
            "Payment Intent",
            {"payment_method": self.name}
        )

        if total > 0:
            self.success_rate = flt(successful / total * 100, 2)

        # Calculate average
        if successful > 0:
            self.average_transaction_amount = flt(self.total_amount_processed / successful, 2)

        self.last_transaction_at = now_datetime()
        self.save(ignore_permissions=True)

    def get_config(self):
        """Get payment method configuration as dictionary"""
        return {
            "name": self.name,
            "method_name": self.method_name,
            "method_code": self.method_code,
            "method_type": self.method_type,
            "display_name": self.display_name,
            "icon": self.icon,
            "method_image": self.method_image,
            "payment_gateway": self.payment_gateway,
            "requires_redirect": self.requires_redirect,
            "supports_refund": self.supports_refund,
            "supports_installments": self.supports_installments,
            "max_installments": self.max_installments,
            "supports_credit_terms": self.supports_credit_terms,
            "requires_3d_secure": self.requires_3d_secure,
            "requires_cvv": self.requires_cvv,
            "requires_billing_address": self.requires_billing_address,
            "minimum_amount": self.minimum_amount,
            "maximum_amount": self.maximum_amount,
            "fee_type": self.fee_type,
            "fee_percentage": self.fee_percentage,
            "fee_fixed_amount": self.fee_fixed_amount,
            "status": self.status
        }


@frappe.whitelist()
def get_payment_method(method_code):
    """
    Get payment method by code

    Args:
        method_code: Payment method code

    Returns:
        Payment Method document
    """
    if frappe.db.exists("Payment Method", method_code):
        return frappe.get_doc("Payment Method", method_code)
    return None


@frappe.whitelist()
def get_active_payment_methods(method_type=None):
    """
    Get all active payment methods

    Args:
        method_type: Filter by method type (optional)

    Returns:
        List of payment method configurations
    """
    filters = {"status": "Active"}
    if method_type:
        filters["method_type"] = method_type

    methods = frappe.get_all(
        "Payment Method",
        filters=filters,
        order_by="display_order asc, method_name asc"
    )

    result = []
    for m in methods:
        doc = frappe.get_doc("Payment Method", m.name)
        result.append(doc.get_config())

    return result


@frappe.whitelist()
def get_available_methods_for_buyer(buyer_user, amount=None, country=None, region=None):
    """
    Get payment methods available for a specific buyer

    Args:
        buyer_user: User ID of buyer
        amount: Transaction amount (optional)
        country: Billing country (optional)
        region: Billing region (optional)

    Returns:
        List of available payment method configurations
    """
    # Get buyer details
    buyer_level = None
    organization = None
    risk_score = None
    risk_level = None

    # Try to get buyer level
    buyer_level_doc = frappe.db.get_value(
        "Buyer Profile",
        {"user": buyer_user},
        ["buyer_level"],
        as_dict=True
    )
    if buyer_level_doc:
        buyer_level = buyer_level_doc.buyer_level

    # Try to get organization
    organization = frappe.db.get_value("User", buyer_user, "organization")

    # Try to get risk score
    risk_score_doc = frappe.db.get_value(
        "Risk Score",
        {"profile_type": "Buyer", "buyer_profile": buyer_user, "status": "Active"},
        ["risk_score", "risk_level"],
        as_dict=True
    )
    if risk_score_doc:
        risk_score = risk_score_doc.risk_score
        risk_level = risk_score_doc.risk_level

    # Get all active methods
    all_methods = frappe.get_all(
        "Payment Method",
        filters={"status": "Active"},
        order_by="display_order asc"
    )

    available = []
    for m in all_methods:
        doc = frappe.get_doc("Payment Method", m.name)

        # Check buyer eligibility
        if not doc.is_available_for_buyer(buyer_user, buyer_level, organization):
            continue

        # Check risk eligibility
        eligible, _ = doc.check_risk_eligibility(risk_score, risk_level)
        if not eligible:
            continue

        # Check amount limits
        if amount:
            within_limits, _ = doc.check_amount_limits(flt(amount))
            if not within_limits:
                continue

        # Check region eligibility
        if country or region:
            region_eligible, _ = doc.check_region_eligibility(country, region)
            if not region_eligible:
                continue

        available.append(doc.get_config())

    return available


@frappe.whitelist()
def calculate_payment_fee(method_code, amount):
    """
    Calculate fee for a payment method and amount

    Args:
        method_code: Payment method code
        amount: Transaction amount

    Returns:
        Fee calculation details
    """
    doc = frappe.get_doc("Payment Method", method_code)
    fee = doc.calculate_fee(flt(amount))

    return {
        "method_code": method_code,
        "amount": flt(amount),
        "fee": fee,
        "fee_type": doc.fee_type,
        "fee_percentage": doc.fee_percentage,
        "fee_fixed_amount": doc.fee_fixed_amount,
        "fee_paid_by": doc.fee_paid_by,
        "total_with_fee": flt(amount) + fee if doc.fee_paid_by == "Buyer" else flt(amount),
        "net_amount": flt(amount) - fee if doc.fee_paid_by == "Seller" else flt(amount)
    }


@frappe.whitelist()
def calculate_installment_options(method_code, amount):
    """
    Calculate installment options for a payment method and amount

    Args:
        method_code: Payment method code
        amount: Transaction amount

    Returns:
        List of installment options
    """
    doc = frappe.get_doc("Payment Method", method_code)

    if not doc.supports_installments:
        return []

    options = []
    for count in range(2, cint(doc.max_installments) + 1):
        option = doc.calculate_installment_amount(flt(amount), count)
        if option:
            options.append(option)

    return options


@frappe.whitelist()
def check_payment_eligibility(method_code, buyer_user, amount, country=None, region=None):
    """
    Check if a buyer is eligible to use a payment method for a transaction

    Args:
        method_code: Payment method code
        buyer_user: User ID of buyer
        amount: Transaction amount
        country: Billing country (optional)
        region: Billing region (optional)

    Returns:
        Eligibility result with reasons
    """
    doc = frappe.get_doc("Payment Method", method_code)

    result = {
        "eligible": True,
        "reasons": [],
        "warnings": []
    }

    # Check active status
    if not doc.is_active():
        result["eligible"] = False
        result["reasons"].append(_("Payment method is not active"))
        return result

    # Check buyer eligibility
    if not doc.is_available_for_buyer(buyer_user):
        result["eligible"] = False
        result["reasons"].append(_("Payment method is not available for this buyer"))

    # Check amount limits
    within_limits, reason = doc.check_amount_limits(flt(amount), buyer_user, "daily")
    if not within_limits:
        result["eligible"] = False
        result["reasons"].append(reason)

    # Check region
    if country or region:
        region_eligible, reason = doc.check_region_eligibility(country, region)
        if not region_eligible:
            result["eligible"] = False
            result["reasons"].append(reason)

    # Check risk
    risk_score_doc = frappe.db.get_value(
        "Risk Score",
        {"profile_type": "Buyer", "buyer_profile": buyer_user, "status": "Active"},
        ["risk_score", "risk_level"],
        as_dict=True
    )
    if risk_score_doc:
        risk_eligible, reason = doc.check_risk_eligibility(
            risk_score_doc.risk_score,
            risk_score_doc.risk_level
        )
        if not risk_eligible:
            result["eligible"] = False
            result["reasons"].append(reason)

    # Add warnings
    if doc.requires_kyc:
        kyc = frappe.db.get_value(
            "KYC Profile",
            {"user": buyer_user, "verification_status": "Verified"},
            "name"
        )
        if not kyc:
            result["warnings"].append(_("KYC verification required for this payment method"))

    if doc.requires_3d_secure:
        result["warnings"].append(_("3D Secure authentication will be required"))

    return result


@frappe.whitelist()
def get_default_payment_method():
    """
    Get the default payment method

    Returns:
        Default payment method configuration or None
    """
    default = frappe.db.get_value(
        "Payment Method",
        {"is_default": 1, "status": "Active"},
        "name"
    )

    if default:
        doc = frappe.get_doc("Payment Method", default)
        return doc.get_config()

    return None


@frappe.whitelist()
def update_method_statistics(method_code, amount, success=True):
    """
    Update payment method statistics after a transaction

    Args:
        method_code: Payment method code
        amount: Transaction amount
        success: Whether transaction was successful
    """
    doc = frappe.get_doc("Payment Method", method_code)
    doc.update_statistics(flt(amount), success)
    return {"status": "updated"}


# =============================================================================
# CONDITIONAL PAYMENT METHODS BASED ON RISK SCORE
# =============================================================================

def get_buyer_risk_profile(buyer_user):
    """
    Get the complete risk profile for a buyer

    Args:
        buyer_user: User ID of the buyer

    Returns:
        Dictionary with risk profile details or None
    """
    # Try to get active risk score for buyer
    risk_score_doc = frappe.db.get_value(
        "Risk Score",
        {
            "profile_type": "Buyer",
            "buyer_profile": buyer_user,
            "status": "Active"
        },
        ["name", "risk_score", "risk_level", "credit_decision", "credit_limit",
         "recommended_payment_methods", "restricted_payment_methods",
         "confidence_level", "manual_override"],
        as_dict=True
    )

    if not risk_score_doc:
        return None

    return risk_score_doc


def is_payment_method_restricted_by_risk(payment_method_name, buyer_user):
    """
    Check if a specific payment method is restricted for a buyer based on their risk score

    Args:
        payment_method_name: Name/code of the payment method
        buyer_user: User ID of the buyer

    Returns:
        Tuple of (is_restricted, reason)
    """
    risk_profile = get_buyer_risk_profile(buyer_user)

    if not risk_profile:
        # No risk profile, apply default policy - allow if no restrictions
        return False, None

    # Get payment method details
    payment_method = frappe.get_doc("Payment Method", payment_method_name)

    # Check 1: Method's own risk restrictions
    eligible, reason = payment_method.check_risk_eligibility(
        risk_profile.get("risk_score"),
        risk_profile.get("risk_level")
    )
    if not eligible:
        return True, reason

    # Check 2: Risk Score's restricted payment methods list
    restricted_methods = risk_profile.get("restricted_payment_methods", "")
    if restricted_methods:
        # Handle special case "All other methods"
        if restricted_methods == "All other methods":
            recommended = risk_profile.get("recommended_payment_methods", "")
            if payment_method.method_name not in recommended and payment_method.method_type not in recommended:
                return True, _("Payment method restricted due to high risk level")

        # Check if method name or type is in restricted list
        restricted_list = [m.strip().lower() for m in restricted_methods.split(",")]
        if payment_method.method_name.lower() in restricted_list or \
           payment_method.method_type.lower() in restricted_list or \
           payment_method.method_code.lower() in restricted_list:
            return True, _("Payment method '{0}' is restricted for your risk profile").format(
                payment_method.display_name or payment_method.method_name
            )

    # Check 3: Credit decision based restrictions
    credit_decision = risk_profile.get("credit_decision", "")
    if credit_decision == "Reject":
        # Only allow prepaid/escrow for rejected profiles
        if payment_method.method_type not in ["Prepaid", "Escrow"]:
            return True, _("Only prepaid or escrow payment methods are available")

    return False, None


@frappe.whitelist()
def get_conditional_payment_methods(buyer_user, amount=None, country=None, region=None,
                                    include_restricted=False):
    """
    Get payment methods with conditional restrictions based on buyer's risk score

    This is the main API endpoint for retrieving available payment methods
    with risk-based filtering applied.

    Args:
        buyer_user: User ID of buyer
        amount: Transaction amount (optional)
        country: Billing country (optional)
        region: Billing region (optional)
        include_restricted: Include restricted methods with flags (optional)

    Returns:
        Dictionary with available and optionally restricted payment methods
    """
    result = {
        "available": [],
        "restricted": [],
        "risk_profile": None,
        "buyer_level": None,
        "total_available": 0,
        "total_restricted": 0
    }

    # Get buyer details
    buyer_profile = frappe.db.get_value(
        "Buyer Profile",
        {"user": buyer_user},
        ["buyer_level", "name"],
        as_dict=True
    )

    if buyer_profile:
        result["buyer_level"] = buyer_profile.buyer_level

    # Get risk profile
    risk_profile = get_buyer_risk_profile(buyer_user)
    if risk_profile:
        result["risk_profile"] = {
            "risk_level": risk_profile.get("risk_level"),
            "risk_score": risk_profile.get("risk_score"),
            "credit_decision": risk_profile.get("credit_decision"),
            "credit_limit": risk_profile.get("credit_limit"),
            "recommended_methods": risk_profile.get("recommended_payment_methods"),
            "restricted_methods": risk_profile.get("restricted_payment_methods")
        }

    # Get organization
    organization = frappe.db.get_value("User", buyer_user, "organization")

    # Get all active payment methods
    all_methods = frappe.get_all(
        "Payment Method",
        filters={"status": "Active"},
        order_by="display_order asc"
    )

    for m in all_methods:
        doc = frappe.get_doc("Payment Method", m.name)
        method_info = doc.get_config()
        method_info["restrictions"] = []
        method_info["is_restricted"] = False
        method_info["is_recommended"] = False

        # Check if this method is recommended
        if risk_profile and risk_profile.get("recommended_payment_methods"):
            recommended = risk_profile.get("recommended_payment_methods", "")
            if doc.method_name in recommended or doc.method_type in recommended:
                method_info["is_recommended"] = True

        # Check buyer eligibility (level, organization, etc.)
        buyer_level = buyer_profile.buyer_level if buyer_profile else None
        if not doc.is_available_for_buyer(buyer_user, buyer_level, organization):
            method_info["is_restricted"] = True
            method_info["restrictions"].append(_("Not available for your buyer level"))
            if include_restricted:
                result["restricted"].append(method_info)
            continue

        # Check risk-based restriction
        is_restricted, reason = is_payment_method_restricted_by_risk(m.name, buyer_user)
        if is_restricted:
            method_info["is_restricted"] = True
            method_info["restrictions"].append(reason or _("Restricted due to risk assessment"))
            if include_restricted:
                result["restricted"].append(method_info)
            continue

        # Check amount limits
        if amount:
            within_limits, reason = doc.check_amount_limits(flt(amount), buyer_user, "daily")
            if not within_limits:
                method_info["is_restricted"] = True
                method_info["restrictions"].append(reason)
                if include_restricted:
                    result["restricted"].append(method_info)
                continue

        # Check region eligibility
        if country or region:
            region_eligible, reason = doc.check_region_eligibility(country, region)
            if not region_eligible:
                method_info["is_restricted"] = True
                method_info["restrictions"].append(reason)
                if include_restricted:
                    result["restricted"].append(method_info)
                continue

        # Check KYC requirements
        if doc.requires_kyc:
            kyc = frappe.db.get_value(
                "KYC Profile",
                {"user": buyer_user, "verification_status": "Verified"},
                ["verification_level"],
                as_dict=True
            )
            if not kyc:
                method_info["is_restricted"] = True
                method_info["restrictions"].append(_("KYC verification required"))
                if include_restricted:
                    result["restricted"].append(method_info)
                continue

            # Check KYC level requirement
            if doc.required_kyc_level:
                kyc_levels = ["Basic", "Standard", "Advanced", "Premium", "Enterprise"]
                required_idx = kyc_levels.index(doc.required_kyc_level) if doc.required_kyc_level in kyc_levels else -1
                current_idx = kyc_levels.index(kyc.verification_level) if kyc.verification_level in kyc_levels else -1

                if current_idx < required_idx:
                    method_info["is_restricted"] = True
                    method_info["restrictions"].append(
                        _("Requires {0} KYC level or higher").format(doc.required_kyc_level)
                    )
                    if include_restricted:
                        result["restricted"].append(method_info)
                    continue

        # Check credit limit for credit terms
        if doc.method_type == "Credit Terms" and amount:
            credit_limit = risk_profile.get("credit_limit", 0) if risk_profile else 0
            if credit_limit and flt(amount) > flt(credit_limit):
                method_info["is_restricted"] = True
                method_info["restrictions"].append(
                    _("Amount exceeds credit limit of {0}").format(credit_limit)
                )
                if include_restricted:
                    result["restricted"].append(method_info)
                continue

        # Method is available
        result["available"].append(method_info)

    result["total_available"] = len(result["available"])
    result["total_restricted"] = len(result["restricted"])

    return result


@frappe.whitelist()
def get_risk_based_payment_restrictions(buyer_user):
    """
    Get detailed payment restrictions based on buyer's risk score

    Args:
        buyer_user: User ID of the buyer

    Returns:
        Dictionary with restriction details
    """
    risk_profile = get_buyer_risk_profile(buyer_user)

    if not risk_profile:
        return {
            "has_risk_profile": False,
            "risk_level": None,
            "restrictions": [],
            "recommendations": [],
            "credit_limit": None,
            "message": _("No risk assessment found. Default payment options available.")
        }

    # Parse recommendations and restrictions
    recommended_list = []
    restricted_list = []

    if risk_profile.get("recommended_payment_methods"):
        recommended_list = [m.strip() for m in risk_profile.get("recommended_payment_methods").split(",")]

    if risk_profile.get("restricted_payment_methods"):
        restricted_list = [m.strip() for m in risk_profile.get("restricted_payment_methods").split(",")]

    # Generate user-friendly message based on risk level
    risk_level = risk_profile.get("risk_level", "")
    messages = {
        "Very Low": _("Excellent! All payment methods are available to you."),
        "Low": _("Great standing! Most payment methods are available."),
        "Medium": _("Some payment methods may have restrictions."),
        "High": _("Limited payment options available due to risk assessment."),
        "Very High": _("Very limited payment options. Consider improving your profile."),
        "Critical": _("Only secure payment methods (escrow) are available.")
    }

    return {
        "has_risk_profile": True,
        "risk_level": risk_level,
        "risk_score": risk_profile.get("risk_score"),
        "credit_decision": risk_profile.get("credit_decision"),
        "restrictions": restricted_list,
        "recommendations": recommended_list,
        "credit_limit": risk_profile.get("credit_limit"),
        "confidence_level": risk_profile.get("confidence_level"),
        "message": messages.get(risk_level, _("Payment options may vary."))
    }


@frappe.whitelist()
def validate_payment_method_for_transaction(method_code, buyer_user, amount, country=None):
    """
    Comprehensive validation of a payment method for a specific transaction

    Args:
        method_code: Payment method code
        buyer_user: User ID of the buyer
        amount: Transaction amount
        country: Billing country (optional)

    Returns:
        Validation result with details
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "requires_approval": False,
        "applied_restrictions": []
    }

    try:
        doc = frappe.get_doc("Payment Method", method_code)
    except frappe.DoesNotExistError:
        return {
            "valid": False,
            "errors": [_("Payment method not found")],
            "warnings": [],
            "requires_approval": False,
            "applied_restrictions": []
        }

    # Check if method is active
    if not doc.is_active():
        result["valid"] = False
        result["errors"].append(_("Payment method is currently not active"))
        return result

    # Get risk profile
    risk_profile = get_buyer_risk_profile(buyer_user)

    # 1. Check basic risk eligibility
    if risk_profile:
        eligible, reason = doc.check_risk_eligibility(
            risk_profile.get("risk_score"),
            risk_profile.get("risk_level")
        )
        if not eligible:
            result["valid"] = False
            result["errors"].append(reason)
            result["applied_restrictions"].append("risk_threshold")

    # 2. Check risk-based method restrictions
    is_restricted, reason = is_payment_method_restricted_by_risk(method_code, buyer_user)
    if is_restricted:
        result["valid"] = False
        result["errors"].append(reason or _("Method restricted by risk assessment"))
        result["applied_restrictions"].append("risk_restricted_method")

    # 3. Check amount limits
    within_limits, reason = doc.check_amount_limits(flt(amount), buyer_user, "daily")
    if not within_limits:
        result["valid"] = False
        result["errors"].append(reason)
        result["applied_restrictions"].append("amount_limit")

    # 4. Check cumulative limits
    for period in ["weekly", "monthly"]:
        within_limits, reason = doc.check_amount_limits(flt(amount), buyer_user, period)
        if not within_limits:
            result["valid"] = False
            result["errors"].append(reason)
            result["applied_restrictions"].append(f"{period}_limit")

    # 5. Check region
    if country:
        region_eligible, reason = doc.check_region_eligibility(country)
        if not region_eligible:
            result["valid"] = False
            result["errors"].append(reason)
            result["applied_restrictions"].append("region_restriction")

    # 6. Check buyer eligibility
    buyer_level = None
    organization = None

    buyer_profile = frappe.db.get_value(
        "Buyer Profile",
        {"user": buyer_user},
        ["buyer_level"],
        as_dict=True
    )
    if buyer_profile:
        buyer_level = buyer_profile.buyer_level

    organization = frappe.db.get_value("User", buyer_user, "organization")

    if not doc.is_available_for_buyer(buyer_user, buyer_level, organization):
        result["valid"] = False
        result["errors"].append(_("Payment method not available for your account type"))
        result["applied_restrictions"].append("buyer_eligibility")

    # 7. Check KYC requirements
    if doc.requires_kyc:
        kyc = frappe.db.get_value(
            "KYC Profile",
            {"user": buyer_user, "verification_status": "Verified"},
            ["verification_level"],
            as_dict=True
        )
        if not kyc:
            result["valid"] = False
            result["errors"].append(_("KYC verification required"))
            result["applied_restrictions"].append("kyc_required")
        elif doc.required_kyc_level:
            kyc_levels = ["Basic", "Standard", "Advanced", "Premium", "Enterprise"]
            required_idx = kyc_levels.index(doc.required_kyc_level) if doc.required_kyc_level in kyc_levels else -1
            current_idx = kyc_levels.index(kyc.verification_level) if kyc.verification_level in kyc_levels else -1

            if current_idx < required_idx:
                result["valid"] = False
                result["errors"].append(
                    _("Requires {0} KYC level (you have {1})").format(
                        doc.required_kyc_level,
                        kyc.verification_level
                    )
                )
                result["applied_restrictions"].append("kyc_level")

    # 8. Check credit limit for credit terms
    if doc.method_type == "Credit Terms" or doc.supports_credit_terms:
        credit_limit = risk_profile.get("credit_limit", 0) if risk_profile else 0
        if credit_limit and flt(amount) > flt(credit_limit):
            result["valid"] = False
            result["errors"].append(
                _("Amount {0} exceeds your credit limit of {1}").format(amount, credit_limit)
            )
            result["applied_restrictions"].append("credit_limit")

        # Check if approval required above threshold
        if doc.requires_approval_above and flt(amount) > flt(doc.requires_approval_above):
            result["requires_approval"] = True
            result["warnings"].append(
                _("Transaction requires approval for amounts above {0}").format(
                    doc.requires_approval_above
                )
            )

    # 9. Add warnings
    if doc.requires_3d_secure:
        result["warnings"].append(_("3D Secure authentication will be required"))

    if doc.requires_billing_address:
        result["warnings"].append(_("Billing address verification required"))

    if risk_profile and risk_profile.get("risk_level") in ["High", "Very High"]:
        result["warnings"].append(_("Additional verification may be required due to risk assessment"))

    return result


@frappe.whitelist()
def get_payment_methods_by_risk_level(risk_level):
    """
    Get payment methods suitable for a specific risk level

    Args:
        risk_level: Risk level (Very Low, Low, Medium, High, Very High, Critical)

    Returns:
        List of suitable payment method configurations
    """
    risk_order = ["Very Low", "Low", "Medium", "High", "Very High", "Critical"]

    if risk_level not in risk_order:
        frappe.throw(_("Invalid risk level: {0}").format(risk_level))

    risk_idx = risk_order.index(risk_level)

    # Get all active methods
    methods = frappe.get_all(
        "Payment Method",
        filters={"status": "Active"},
        order_by="display_order asc"
    )

    suitable = []
    for m in methods:
        doc = frappe.get_doc("Payment Method", m.name)

        # Check max risk level
        if doc.max_risk_level and doc.max_risk_level in risk_order:
            max_idx = risk_order.index(doc.max_risk_level)
            if risk_idx > max_idx:
                continue

        # Check excluded risk levels
        if doc.excluded_risk_levels:
            excluded = [l.strip() for l in doc.excluded_risk_levels.split(",")]
            if risk_level in excluded:
                continue

        config = doc.get_config()
        config["suitable_for_risk_level"] = risk_level
        suitable.append(config)

    return suitable


@frappe.whitelist()
def apply_risk_based_limits(method_code, buyer_user, base_amount):
    """
    Calculate adjusted limits based on buyer's risk profile

    High-risk buyers may have reduced transaction limits.

    Args:
        method_code: Payment method code
        buyer_user: User ID of the buyer
        base_amount: Requested transaction amount

    Returns:
        Dictionary with adjusted limits and allowances
    """
    doc = frappe.get_doc("Payment Method", method_code)
    risk_profile = get_buyer_risk_profile(buyer_user)

    # Base limits from payment method
    limits = {
        "minimum_amount": flt(doc.minimum_amount),
        "maximum_amount": flt(doc.maximum_amount) if flt(doc.maximum_amount) > 0 else None,
        "daily_limit": flt(doc.daily_limit) if flt(doc.daily_limit) > 0 else None,
        "weekly_limit": flt(doc.weekly_limit) if flt(doc.weekly_limit) > 0 else None,
        "monthly_limit": flt(doc.monthly_limit) if flt(doc.monthly_limit) > 0 else None,
        "credit_limit": None,
        "adjustment_factor": 1.0,
        "risk_level": "Unknown"
    }

    if risk_profile:
        risk_level = risk_profile.get("risk_level", "")
        limits["risk_level"] = risk_level
        limits["credit_limit"] = risk_profile.get("credit_limit")

        # Apply risk-based adjustment factors
        # Higher risk = lower limits
        adjustment_factors = {
            "Very Low": 1.0,
            "Low": 1.0,
            "Medium": 0.8,
            "High": 0.5,
            "Very High": 0.25,
            "Critical": 0.1
        }

        factor = adjustment_factors.get(risk_level, 1.0)
        limits["adjustment_factor"] = factor

        # Apply adjustments to limits
        if limits["maximum_amount"]:
            limits["adjusted_maximum"] = flt(limits["maximum_amount"] * factor, 2)
        else:
            limits["adjusted_maximum"] = None

        if limits["daily_limit"]:
            limits["adjusted_daily"] = flt(limits["daily_limit"] * factor, 2)
        else:
            limits["adjusted_daily"] = None

        if limits["weekly_limit"]:
            limits["adjusted_weekly"] = flt(limits["weekly_limit"] * factor, 2)
        else:
            limits["adjusted_weekly"] = None

        if limits["monthly_limit"]:
            limits["adjusted_monthly"] = flt(limits["monthly_limit"] * factor, 2)
        else:
            limits["adjusted_monthly"] = None

    # Calculate remaining allowance
    base_amount = flt(base_amount)
    daily_used = doc._get_cumulative_amount(buyer_user, "daily")
    weekly_used = doc._get_cumulative_amount(buyer_user, "weekly")
    monthly_used = doc._get_cumulative_amount(buyer_user, "monthly")

    limits["used_today"] = daily_used
    limits["used_this_week"] = weekly_used
    limits["used_this_month"] = monthly_used

    # Calculate remaining based on adjusted limits
    adjusted_daily = limits.get("adjusted_daily") or limits["daily_limit"]
    adjusted_weekly = limits.get("adjusted_weekly") or limits["weekly_limit"]
    adjusted_monthly = limits.get("adjusted_monthly") or limits["monthly_limit"]

    if adjusted_daily:
        limits["remaining_daily"] = max(0, flt(adjusted_daily) - daily_used)
    else:
        limits["remaining_daily"] = None

    if adjusted_weekly:
        limits["remaining_weekly"] = max(0, flt(adjusted_weekly) - weekly_used)
    else:
        limits["remaining_weekly"] = None

    if adjusted_monthly:
        limits["remaining_monthly"] = max(0, flt(adjusted_monthly) - monthly_used)
    else:
        limits["remaining_monthly"] = None

    # Determine if requested amount is within limits
    limits["requested_amount"] = base_amount
    limits["is_within_limits"] = True
    limits["limit_exceeded"] = None

    if limits["adjusted_maximum"] and base_amount > limits["adjusted_maximum"]:
        limits["is_within_limits"] = False
        limits["limit_exceeded"] = "maximum_amount"
    elif limits["remaining_daily"] is not None and base_amount > limits["remaining_daily"]:
        limits["is_within_limits"] = False
        limits["limit_exceeded"] = "daily_limit"
    elif limits["remaining_weekly"] is not None and base_amount > limits["remaining_weekly"]:
        limits["is_within_limits"] = False
        limits["limit_exceeded"] = "weekly_limit"
    elif limits["remaining_monthly"] is not None and base_amount > limits["remaining_monthly"]:
        limits["is_within_limits"] = False
        limits["limit_exceeded"] = "monthly_limit"
    elif limits["credit_limit"] and base_amount > limits["credit_limit"]:
        limits["is_within_limits"] = False
        limits["limit_exceeded"] = "credit_limit"

    return limits


@frappe.whitelist()
def get_checkout_payment_options(buyer_user, cart_total, shipping_country=None):
    """
    Convenience API for checkout - get complete payment options with all context

    Args:
        buyer_user: User ID of the buyer
        cart_total: Total cart amount
        shipping_country: Shipping destination country (optional)

    Returns:
        Complete payment options for checkout UI
    """
    # Get conditional payment methods
    methods = get_conditional_payment_methods(
        buyer_user=buyer_user,
        amount=cart_total,
        country=shipping_country,
        include_restricted=True
    )

    # Get risk restrictions info
    risk_info = get_risk_based_payment_restrictions(buyer_user)

    # Get default method
    default_method = get_default_payment_method()

    # Find recommended method from available options
    recommended_method = None
    if methods["available"]:
        # First try to find one marked as recommended
        for m in methods["available"]:
            if m.get("is_recommended"):
                recommended_method = m
                break

        # Otherwise use default or first available
        if not recommended_method:
            if default_method:
                for m in methods["available"]:
                    if m["name"] == default_method["name"]:
                        recommended_method = m
                        break

            if not recommended_method:
                recommended_method = methods["available"][0]

    return {
        "available_methods": methods["available"],
        "restricted_methods": methods["restricted"],
        "default_method": default_method,
        "recommended_method": recommended_method,
        "risk_info": risk_info,
        "buyer_profile": {
            "risk_level": risk_info.get("risk_level"),
            "credit_limit": risk_info.get("credit_limit"),
            "has_risk_assessment": risk_info.get("has_risk_profile", False)
        },
        "cart_total": flt(cart_total),
        "total_available": len(methods["available"]),
        "message": risk_info.get("message")
    }
