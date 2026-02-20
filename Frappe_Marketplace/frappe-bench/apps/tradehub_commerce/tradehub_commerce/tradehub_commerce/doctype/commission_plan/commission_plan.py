# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, add_days, add_months
from datetime import date


class CommissionPlan(Document):
    """
    Commission Plan DocType for seller agreements.

    Manages commission structures for marketplace sellers including:
    - Base percentage/fixed commission rates
    - Category-specific commission rates
    - Volume-based tiered pricing
    - Payment terms and payout schedules
    - Plan validity and renewal management
    """

    def before_insert(self):
        """Set default values before inserting a new commission plan."""
        if not self.created_by:
            self.created_by = frappe.session.user
        self.created_at = now_datetime()

        # Generate plan code if not provided
        if not self.plan_code:
            self.plan_code = self.generate_plan_code()

        # Set default effective_from to today if not specified
        if not self.effective_from:
            self.effective_from = nowdate()

    def validate(self):
        """Validate commission plan data before saving."""
        self.validate_commission_rates()
        self.validate_dates()
        self.validate_volume_tiers()
        self.validate_payment_terms()
        self.validate_category_rates()
        self.validate_default_plan()
        self.validate_max_sellers()
        self.modified_by = frappe.session.user
        self.modified_at = now_datetime()

    def on_update(self):
        """Actions to perform after commission plan is updated."""
        self.update_seller_count()
        self.clear_cache()

    def on_trash(self):
        """Prevent deletion of commission plan with active sellers."""
        self.check_active_sellers()

    def validate_commission_rates(self):
        """Validate commission rate values."""
        if self.base_commission_rate < 0 or self.base_commission_rate > 100:
            frappe.throw(_("Base commission rate must be between 0 and 100"))

        if flt(self.minimum_commission) < 0:
            frappe.throw(_("Minimum commission cannot be negative"))

        if flt(self.maximum_commission) < 0:
            frappe.throw(_("Maximum commission cannot be negative"))

        if flt(self.maximum_commission) > 0 and flt(self.minimum_commission) > flt(self.maximum_commission):
            frappe.throw(_("Minimum commission cannot be greater than maximum commission"))

        if flt(self.fixed_commission_amount) < 0:
            frappe.throw(_("Fixed commission amount cannot be negative"))

    def validate_dates(self):
        """Validate effective dates."""
        if self.effective_from and self.effective_until:
            if getdate(self.effective_from) > getdate(self.effective_until):
                frappe.throw(_("Effective From date cannot be after Effective Until date"))

        # If perpetual, clear the effective_until date
        if cint(self.is_perpetual):
            self.effective_until = None
        elif not self.effective_until:
            # If not perpetual and no end date, default to 1 year
            self.effective_until = add_months(self.effective_from, 12)

    def validate_volume_tiers(self):
        """Validate volume-based tier configuration."""
        if not cint(self.enable_volume_tiers):
            return

        tiers = []
        if flt(self.volume_tier_1_threshold) > 0:
            tiers.append((flt(self.volume_tier_1_threshold), flt(self.volume_tier_1_rate)))
        if flt(self.volume_tier_2_threshold) > 0:
            tiers.append((flt(self.volume_tier_2_threshold), flt(self.volume_tier_2_rate)))
        if flt(self.volume_tier_3_threshold) > 0:
            tiers.append((flt(self.volume_tier_3_threshold), flt(self.volume_tier_3_rate)))

        # Validate tiers are in ascending order of thresholds
        for i in range(1, len(tiers)):
            if tiers[i][0] <= tiers[i-1][0]:
                frappe.throw(_("Volume tier thresholds must be in ascending order"))

            # Rates should decrease as thresholds increase (discount for volume)
            if tiers[i][1] >= tiers[i-1][1]:
                frappe.msgprint(
                    _("Volume tier rates typically decrease as thresholds increase"),
                    indicator="orange"
                )

        # Validate rates are within bounds
        for threshold, rate in tiers:
            if rate < 0 or rate > 100:
                frappe.throw(_("Volume tier rates must be between 0 and 100"))

    def validate_payment_terms(self):
        """Validate payment terms configuration."""
        if self.payment_day:
            if self.payment_frequency == "Weekly" and (self.payment_day < 1 or self.payment_day > 7):
                frappe.throw(_("For weekly payments, payment day must be between 1 (Monday) and 7 (Sunday)"))
            elif self.payment_frequency == "Monthly" and (self.payment_day < 1 or self.payment_day > 28):
                frappe.throw(_("For monthly payments, payment day must be between 1 and 28"))

        if flt(self.minimum_payout_amount) < 0:
            frappe.throw(_("Minimum payout amount cannot be negative"))

        if cint(self.payout_hold_days) < 0:
            frappe.throw(_("Payout hold days cannot be negative"))

    def validate_category_rates(self):
        """Validate category-specific rates."""
        if not cint(self.enable_category_rates):
            return

        categories_seen = set()
        for rate in self.category_rates:
            if not rate.category:
                frappe.throw(_("Category is required for each category rate"))

            if rate.category in categories_seen:
                frappe.throw(_("Duplicate category {0} in category rates").format(rate.category))
            categories_seen.add(rate.category)

            if flt(rate.commission_rate) < 0 or flt(rate.commission_rate) > 100:
                frappe.throw(_("Commission rate for {0} must be between 0 and 100").format(rate.category))

            # Validate date range if specified
            if rate.effective_from and rate.effective_until:
                if getdate(rate.effective_from) > getdate(rate.effective_until):
                    frappe.throw(_("Invalid date range for category {0}").format(rate.category))

    def validate_default_plan(self):
        """Ensure only one default plan exists per tenant."""
        if cint(self.is_default) and self.status == "Active":
            # Check for existing default plans
            filters = {
                "is_default": 1,
                "status": "Active",
                "name": ["!=", self.name]
            }
            if self.tenant:
                filters["tenant"] = self.tenant
            else:
                filters["tenant"] = ["is", "not set"]

            existing_default = frappe.db.exists("Commission Plan", filters)
            if existing_default:
                # Unset the existing default
                frappe.db.set_value("Commission Plan", existing_default, "is_default", 0)
                frappe.msgprint(
                    _("Previous default plan has been unset"),
                    indicator="blue"
                )

    def validate_max_sellers(self):
        """Validate max sellers constraint."""
        if cint(self.max_sellers) > 0:
            if cint(self.current_seller_count) > cint(self.max_sellers):
                frappe.throw(
                    _("Cannot set max sellers to {0} as there are already {1} sellers on this plan").format(
                        self.max_sellers, self.current_seller_count
                    )
                )

    def generate_plan_code(self):
        """Generate a unique plan code."""
        base_code = self.plan_type.upper().replace(" ", "_")[:10]
        counter = 1
        code = f"{base_code}_{counter:03d}"

        while frappe.db.exists("Commission Plan", {"plan_code": code}):
            counter += 1
            code = f"{base_code}_{counter:03d}"

        return code

    def check_active_sellers(self):
        """Check for active sellers before deletion."""
        seller_count = frappe.db.count("Seller Profile", {"commission_plan": self.name})
        if seller_count > 0:
            frappe.throw(
                _("Cannot delete Commission Plan with {0} active sellers. "
                  "Please reassign sellers to a different plan first.").format(seller_count)
            )

    def update_seller_count(self):
        """Update the current seller count."""
        count = frappe.db.count("Seller Profile", {"commission_plan": self.name})
        if count != cint(self.current_seller_count):
            self.db_set("current_seller_count", count, update_modified=False)
            self.db_set("total_sellers", count, update_modified=False)

    def clear_cache(self):
        """Clear cached commission plan data."""
        cache_keys = [
            f"commission_plan:{self.name}",
            f"commission_plan_code:{self.plan_code}",
            "default_commission_plan"
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)

    # Commission Calculation Methods
    def calculate_commission(self, order_value, category=None, seller=None, shipping_cost=0):
        """
        Calculate commission for an order.

        Args:
            order_value: Total order value
            category: Product category (optional, for category-specific rates)
            seller: Seller Profile name (optional, for volume-based tiers)
            shipping_cost: Shipping cost to potentially exclude from commission base

        Returns:
            dict: Commission details including amount, rate, and breakdown
        """
        # Determine commission base
        commission_base = flt(order_value)
        if cint(self.deduct_shipping_from_commission):
            commission_base = commission_base - flt(shipping_cost)
            commission_base = max(commission_base, 0)

        # Get applicable rate
        rate = self.get_applicable_rate(category, seller)

        # Calculate commission based on type
        commission_amount = 0
        breakdown = {
            "order_value": flt(order_value),
            "commission_base": commission_base,
            "shipping_deducted": flt(shipping_cost) if cint(self.deduct_shipping_from_commission) else 0,
            "calculation_type": self.commission_calculation_type
        }

        if self.commission_calculation_type == "Percentage":
            commission_amount = commission_base * (rate / 100)
        elif self.commission_calculation_type == "Fixed":
            commission_amount = flt(self.fixed_commission_amount)
        elif self.commission_calculation_type == "Percentage + Fixed":
            commission_amount = (commission_base * (rate / 100)) + flt(self.fixed_commission_amount)
        elif self.commission_calculation_type == "Tiered Percentage":
            commission_amount = self.calculate_tiered_commission(commission_base, rate)

        # Apply min/max constraints
        effective_min = self.get_effective_minimum(category)
        effective_max = self.get_effective_maximum(category)

        if effective_min > 0 and commission_amount < effective_min:
            commission_amount = effective_min
            breakdown["applied_minimum"] = True

        if effective_max > 0 and commission_amount > effective_max:
            commission_amount = effective_max
            breakdown["applied_maximum"] = True

        # Round to 2 decimal places
        commission_amount = round(commission_amount, 2)

        return {
            "commission_amount": commission_amount,
            "effective_rate": rate,
            "seller_amount": round(flt(order_value) - commission_amount, 2),
            "breakdown": breakdown
        }

    def get_applicable_rate(self, category=None, seller=None):
        """
        Get the applicable commission rate considering category and volume tiers.

        Args:
            category: Product category
            seller: Seller Profile name

        Returns:
            float: Applicable commission rate
        """
        # Start with base rate
        rate = flt(self.base_commission_rate)

        # Check for category-specific rate
        if category and cint(self.enable_category_rates):
            category_rate = self.get_category_rate(category)
            if category_rate is not None:
                rate = category_rate

        # Check for volume-based tier rate
        if seller and cint(self.enable_volume_tiers):
            tier_rate = self.get_volume_tier_rate(seller)
            if tier_rate is not None:
                rate = tier_rate

        return rate

    def get_category_rate(self, category):
        """
        Get commission rate for a specific category.

        Args:
            category: Category name

        Returns:
            float or None: Category-specific rate or None if not found
        """
        today = getdate(nowdate())

        # Check direct category match
        for rate_row in self.category_rates:
            if rate_row.category == category:
                # Check date validity
                if rate_row.effective_from and getdate(rate_row.effective_from) > today:
                    continue
                if rate_row.effective_until and getdate(rate_row.effective_until) < today:
                    continue
                return flt(rate_row.commission_rate)

        # Check parent categories
        parent_category = frappe.db.get_value("Category", category, "parent_category")
        if parent_category:
            return self.get_category_rate(parent_category)

        return None

    def get_volume_tier_rate(self, seller):
        """
        Get volume-based tier rate for a seller.

        Args:
            seller: Seller Profile name

        Returns:
            float or None: Tier-based rate or None if no tier reached
        """
        volume = self.get_seller_volume(seller)

        if flt(self.volume_tier_3_threshold) > 0 and volume >= flt(self.volume_tier_3_threshold):
            return flt(self.volume_tier_3_rate)
        elif flt(self.volume_tier_2_threshold) > 0 and volume >= flt(self.volume_tier_2_threshold):
            return flt(self.volume_tier_2_rate)
        elif flt(self.volume_tier_1_threshold) > 0 and volume >= flt(self.volume_tier_1_threshold):
            return flt(self.volume_tier_1_rate)

        return None

    def get_seller_volume(self, seller):
        """
        Calculate seller's volume based on tier calculation settings.

        Args:
            seller: Seller Profile name

        Returns:
            float: Seller's volume metric
        """
        # Determine date range based on calculation period
        today = getdate(nowdate())
        start_date = None

        if self.tier_calculation_period == "Monthly":
            start_date = today.replace(day=1)
        elif self.tier_calculation_period == "Quarterly":
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            start_date = today.replace(month=quarter_month, day=1)
        elif self.tier_calculation_period == "Yearly":
            start_date = today.replace(month=1, day=1)
        # Lifetime = no start date filter

        # Build query based on calculation basis
        filters = {"seller": seller, "status": "Completed"}
        if start_date:
            filters["creation"] = [">=", start_date]

        if self.tier_calculation_basis in ["GMV", "Monthly GMV"]:
            # Use parameterized queries to prevent SQL injection
            params = {"seller": seller}
            date_filter = ""
            if start_date:
                date_filter = "AND creation >= %(start_date)s"
                params["start_date"] = start_date

            result = frappe.db.sql("""
                SELECT COALESCE(SUM(total), 0) as volume
                FROM `tabSub Order`
                WHERE seller = %(seller)s
                AND status = 'Completed'
                {date_filter}
            """.format(date_filter=date_filter), params, as_dict=True)
            return flt(result[0].volume) if result else 0

        elif self.tier_calculation_basis in ["Order Count", "Monthly Orders"]:
            return frappe.db.count("Sub Order", filters)

        return 0

    def calculate_tiered_commission(self, commission_base, base_rate):
        """
        Calculate commission using tiered rates (progressive brackets).

        Args:
            commission_base: Base amount for commission calculation
            base_rate: Default rate if no tiers apply

        Returns:
            float: Tiered commission amount
        """
        # Build tier brackets
        tiers = []
        if flt(self.volume_tier_1_threshold) > 0:
            tiers.append((flt(self.volume_tier_1_threshold), flt(self.volume_tier_1_rate)))
        if flt(self.volume_tier_2_threshold) > 0:
            tiers.append((flt(self.volume_tier_2_threshold), flt(self.volume_tier_2_rate)))
        if flt(self.volume_tier_3_threshold) > 0:
            tiers.append((flt(self.volume_tier_3_threshold), flt(self.volume_tier_3_rate)))

        if not tiers:
            return commission_base * (base_rate / 100)

        # Sort tiers by threshold
        tiers.sort(key=lambda x: x[0])

        # Calculate progressive commission
        total_commission = 0
        remaining = commission_base
        prev_threshold = 0

        for i, (threshold, rate) in enumerate(tiers):
            bracket_amount = min(remaining, threshold - prev_threshold)
            if bracket_amount > 0:
                total_commission += bracket_amount * (rate / 100)
                remaining -= bracket_amount
            prev_threshold = threshold

            if remaining <= 0:
                break

        # Apply base rate to remaining amount
        if remaining > 0:
            total_commission += remaining * (base_rate / 100)

        return total_commission

    def get_effective_minimum(self, category=None):
        """Get effective minimum commission considering category overrides."""
        if category and cint(self.enable_category_rates):
            for rate_row in self.category_rates:
                if rate_row.category == category and flt(rate_row.minimum_commission) > 0:
                    return flt(rate_row.minimum_commission)
        return flt(self.minimum_commission)

    def get_effective_maximum(self, category=None):
        """Get effective maximum commission considering category overrides."""
        if category and cint(self.enable_category_rates):
            for rate_row in self.category_rates:
                if rate_row.category == category and flt(rate_row.maximum_commission) > 0:
                    return flt(rate_row.maximum_commission)
        return flt(self.maximum_commission)

    # Status Methods
    def is_active(self):
        """Check if the commission plan is currently active."""
        if self.status != "Active":
            return False

        today = getdate(nowdate())
        if self.effective_from and getdate(self.effective_from) > today:
            return False
        if self.effective_until and getdate(self.effective_until) < today:
            return False

        return True

    def is_accepting_sellers(self):
        """Check if the plan can accept new sellers."""
        if not self.is_active():
            return False

        if cint(self.max_sellers) > 0 and cint(self.current_seller_count) >= cint(self.max_sellers):
            return False

        return True

    def can_seller_join(self, seller):
        """
        Check if a specific seller can join this plan.

        Args:
            seller: Seller Profile document or name

        Returns:
            tuple: (can_join: bool, reason: str)
        """
        if not self.is_accepting_sellers():
            return False, _("This plan is not currently accepting new sellers")

        # Get seller details if name provided
        if isinstance(seller, str):
            seller = frappe.get_doc("Seller Profile", seller)

        # Check seller type restriction
        if self.seller_type_restriction and seller.seller_type != self.seller_type_restriction:
            return False, _("This plan is only available for {0} sellers").format(self.seller_type_restriction)

        # Check minimum tier
        if self.min_seller_tier:
            if not seller.seller_tier or seller.seller_tier != self.min_seller_tier:
                return False, _("This plan requires minimum seller tier: {0}").format(self.min_seller_tier)

        # Check verification level
        if self.required_verification_level and self.required_verification_level != "None":
            verification_levels = ["None", "Basic", "Identity", "Business", "Full"]
            required_level = verification_levels.index(self.required_verification_level)

            seller_level = 0
            if seller.identity_verified:
                seller_level = max(seller_level, 2)
            if seller.business_verified:
                seller_level = max(seller_level, 3)
            if seller.verification_status == "Verified":
                seller_level = max(seller_level, 4)

            if seller_level < required_level:
                return False, _("This plan requires {0} verification").format(self.required_verification_level)

        # Check invite-only
        if cint(self.is_invite_only):
            # Would need to check invitation records
            return False, _("This plan is invite-only")

        return True, _("Seller can join this plan")

    def activate(self):
        """Activate the commission plan."""
        if self.status == "Active":
            frappe.throw(_("Plan is already active"))

        self.status = "Active"
        self.save()
        frappe.msgprint(_("Commission plan activated"))

    def suspend(self, reason=None):
        """Suspend the commission plan."""
        self.status = "Suspended"
        self.save()
        frappe.msgprint(_("Commission plan suspended"))

    def archive(self):
        """Archive the commission plan."""
        if cint(self.current_seller_count) > 0:
            frappe.throw(_("Cannot archive plan with active sellers"))

        self.status = "Archived"
        self.save()
        frappe.msgprint(_("Commission plan archived"))

    def extend(self, months=12):
        """
        Extend the plan validity.

        Args:
            months: Number of months to extend
        """
        if cint(self.is_perpetual):
            frappe.throw(_("Perpetual plans don't need extension"))

        if self.effective_until:
            new_until = add_months(self.effective_until, months)
        else:
            new_until = add_months(nowdate(), months)

        self.effective_until = new_until
        self.save()

        frappe.msgprint(_("Plan extended until {0}").format(new_until))

    def get_plan_summary(self):
        """Get a summary of the commission plan for display."""
        return {
            "name": self.name,
            "plan_name": self.plan_name,
            "plan_code": self.plan_code,
            "plan_type": self.plan_type,
            "status": self.status,
            "base_rate": self.base_commission_rate,
            "calculation_type": self.commission_calculation_type,
            "has_category_rates": cint(self.enable_category_rates),
            "has_volume_tiers": cint(self.enable_volume_tiers),
            "payment_frequency": self.payment_frequency,
            "minimum_payout": self.minimum_payout_amount,
            "payout_hold_days": self.payout_hold_days,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "is_active": self.is_active(),
            "current_sellers": self.current_seller_count,
            "max_sellers": self.max_sellers
        }

    def update_stats(self):
        """Update plan statistics from transaction data."""
        # Get GMV and commission totals (would need actual transaction DocTypes)
        # This is a placeholder implementation
        stats = frappe.db.sql("""
            SELECT
                COUNT(*) as order_count,
                COALESCE(SUM(total), 0) as total_gmv,
                COALESCE(SUM(commission_amount), 0) as total_commission
            FROM `tabSub Order`
            WHERE seller IN (
                SELECT name FROM `tabSeller Profile` WHERE commission_plan = %s
            )
            AND status = 'Completed'
        """, self.name, as_dict=True)

        if stats:
            self.total_gmv_processed = stats[0].total_gmv or 0
            self.total_commission_earned = stats[0].total_commission or 0
            if stats[0].total_gmv > 0:
                self.average_commission_rate = (stats[0].total_commission / stats[0].total_gmv) * 100

        self.last_calculation_date = nowdate()
        self.save()


# API Endpoints
@frappe.whitelist()
def get_commission_plan(plan_name=None, plan_code=None):
    """
    Get commission plan details.

    Args:
        plan_name: Name of the commission plan
        plan_code: Code of the commission plan

    Returns:
        dict: Commission plan summary
    """
    if not plan_name and not plan_code:
        frappe.throw(_("Please provide plan name or code"))

    if plan_code:
        plan_name = frappe.db.get_value("Commission Plan", {"plan_code": plan_code}, "name")

    if not plan_name or not frappe.db.exists("Commission Plan", plan_name):
        return {"error": _("Commission plan not found")}

    plan = frappe.get_doc("Commission Plan", plan_name)
    return plan.get_plan_summary()


@frappe.whitelist()
def get_default_commission_plan(tenant=None):
    """
    Get the default commission plan.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Default plan summary or None
    """
    filters = {
        "is_default": 1,
        "status": "Active"
    }

    if tenant:
        filters["tenant"] = tenant
    else:
        filters["tenant"] = ["is", "not set"]

    plan_name = frappe.db.get_value("Commission Plan", filters, "name")

    if not plan_name:
        # Fall back to any active default plan
        plan_name = frappe.db.get_value("Commission Plan", {
            "is_default": 1,
            "status": "Active"
        }, "name")

    if not plan_name:
        return None

    plan = frappe.get_doc("Commission Plan", plan_name)
    return plan.get_plan_summary()


@frappe.whitelist()
def calculate_commission(plan_name, order_value, category=None, seller=None, shipping_cost=0):
    """
    Calculate commission for an order.

    Args:
        plan_name: Commission plan name
        order_value: Total order value
        category: Product category
        seller: Seller profile name
        shipping_cost: Shipping cost

    Returns:
        dict: Commission calculation result
    """
    if not frappe.db.exists("Commission Plan", plan_name):
        frappe.throw(_("Commission plan not found"))

    plan = frappe.get_doc("Commission Plan", plan_name)

    if not plan.is_active():
        frappe.throw(_("Commission plan is not active"))

    return plan.calculate_commission(
        order_value=flt(order_value),
        category=category,
        seller=seller,
        shipping_cost=flt(shipping_cost)
    )


@frappe.whitelist()
def get_available_plans(seller=None, tenant=None):
    """
    Get commission plans available for a seller.

    Args:
        seller: Seller profile name (optional)
        tenant: Tenant filter (optional)

    Returns:
        list: Available commission plans
    """
    filters = {"status": "Active"}

    if tenant:
        filters["tenant"] = ["in", [tenant, None, ""]]

    plans = frappe.get_all("Commission Plan",
        filters=filters,
        fields=["name", "plan_name", "plan_code", "plan_type",
                "base_commission_rate", "is_default", "short_description",
                "max_sellers", "current_seller_count", "is_invite_only"],
        order_by="is_default desc, base_commission_rate asc"
    )

    result = []
    for p in plans:
        # Check if plan is accepting sellers
        if cint(p.max_sellers) > 0 and cint(p.current_seller_count) >= cint(p.max_sellers):
            p["available"] = False
            p["unavailable_reason"] = _("Plan is full")
        elif cint(p.is_invite_only):
            p["available"] = False
            p["unavailable_reason"] = _("Invite only")
        else:
            p["available"] = True

        # If seller provided, check eligibility
        if seller and p["available"]:
            plan = frappe.get_doc("Commission Plan", p.name)
            can_join, reason = plan.can_seller_join(seller)
            if not can_join:
                p["available"] = False
                p["unavailable_reason"] = reason

        result.append(p)

    return result


@frappe.whitelist()
def assign_plan_to_seller(seller, plan_name):
    """
    Assign a commission plan to a seller.

    Args:
        seller: Seller profile name
        plan_name: Commission plan name

    Returns:
        dict: Result of assignment
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    if not frappe.db.exists("Commission Plan", plan_name):
        frappe.throw(_("Commission plan not found"))

    plan = frappe.get_doc("Commission Plan", plan_name)

    # Check if seller can join
    can_join, reason = plan.can_seller_join(seller)
    if not can_join:
        frappe.throw(reason)

    # Update seller's commission plan
    frappe.db.set_value("Seller Profile", seller, "commission_plan", plan_name)

    # Update plan seller count
    plan.update_seller_count()

    return {
        "status": "success",
        "message": _("Commission plan assigned successfully"),
        "seller": seller,
        "plan": plan_name
    }


@frappe.whitelist()
def get_seller_commission_rate(seller, category=None):
    """
    Get the effective commission rate for a seller.

    Args:
        seller: Seller profile name
        category: Optional category for category-specific rate

    Returns:
        dict: Rate information
    """
    commission_plan = frappe.db.get_value("Seller Profile", seller, "commission_plan")

    if not commission_plan:
        # Get default plan
        default = get_default_commission_plan()
        if default:
            commission_plan = default.get("name")
        else:
            return {"error": _("No commission plan assigned or available")}

    plan = frappe.get_doc("Commission Plan", commission_plan)
    rate = plan.get_applicable_rate(category=category, seller=seller)

    return {
        "plan_name": plan.plan_name,
        "plan_code": plan.plan_code,
        "effective_rate": rate,
        "base_rate": plan.base_commission_rate,
        "is_category_specific": rate != plan.base_commission_rate and category is not None,
        "calculation_type": plan.commission_calculation_type
    }


@frappe.whitelist()
def get_plan_statistics(plan_name):
    """
    Get statistics for a commission plan.

    Args:
        plan_name: Commission plan name

    Returns:
        dict: Plan statistics
    """
    if not frappe.db.exists("Commission Plan", plan_name):
        frappe.throw(_("Commission plan not found"))

    plan = frappe.get_doc("Commission Plan", plan_name)

    # Get sellers on this plan
    sellers = frappe.db.sql("""
        SELECT
            COUNT(*) as total_sellers,
            SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_sellers,
            AVG(seller_score) as avg_seller_score,
            SUM(total_sales_count) as total_orders,
            SUM(total_sales_amount) as total_gmv
        FROM `tabSeller Profile`
        WHERE commission_plan = %s
    """, plan_name, as_dict=True)

    return {
        "plan_name": plan.plan_name,
        "status": plan.status,
        "total_sellers": sellers[0].total_sellers if sellers else 0,
        "active_sellers": sellers[0].active_sellers if sellers else 0,
        "average_seller_score": round(sellers[0].avg_seller_score or 0, 2) if sellers else 0,
        "total_orders": sellers[0].total_orders or 0 if sellers else 0,
        "total_gmv": sellers[0].total_gmv or 0 if sellers else 0,
        "total_commission_earned": plan.total_commission_earned,
        "average_commission_rate": plan.average_commission_rate
    }


@frappe.whitelist()
def compare_plans(plan_names, order_value, category=None):
    """
    Compare commission calculations across multiple plans.

    Args:
        plan_names: List of plan names (JSON string)
        order_value: Order value for comparison
        category: Optional category

    Returns:
        list: Comparison results
    """
    import json
    if isinstance(plan_names, str):
        plan_names = json.loads(plan_names)

    results = []
    for plan_name in plan_names:
        if frappe.db.exists("Commission Plan", plan_name):
            plan = frappe.get_doc("Commission Plan", plan_name)
            calc = plan.calculate_commission(flt(order_value), category=category)
            results.append({
                "plan_name": plan.plan_name,
                "plan_code": plan.plan_code,
                "commission_amount": calc["commission_amount"],
                "effective_rate": calc["effective_rate"],
                "seller_amount": calc["seller_amount"]
            })

    # Sort by seller amount (highest first)
    results.sort(key=lambda x: x["seller_amount"], reverse=True)

    return results
