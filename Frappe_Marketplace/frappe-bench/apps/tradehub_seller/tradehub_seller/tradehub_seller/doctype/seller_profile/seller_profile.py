# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate, now_datetime, add_days
import json


class SellerProfile(Document):
    """
    Seller Profile DocType extending ERPNext Supplier for marketplace sellers.

    Seller Profiles represent individuals or businesses that sell products on the
    TR-TradeHub marketplace. Each seller profile:
    - Links to a Frappe User account
    - Syncs with ERPNext Supplier for ERP integration
    - Tracks performance metrics and ratings
    - Supports Turkish tax compliance (VKN/TCKN, E-Invoice)
    - Has verification workflow (KYC/KYB)
    - Can belong to an Organization (for business sellers)
    """

    def before_insert(self):
        """Set default values before inserting a new seller profile."""
        if not self.created_by:
            self.created_by = frappe.session.user

        if not self.joined_at:
            self.joined_at = now_datetime()

        # Set tenant from user context if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Set contact email from user if not specified
        if not self.contact_email and self.user:
            self.contact_email = frappe.db.get_value("User", self.user, "email")

        # Set display name if not specified
        if not self.display_name:
            self.display_name = self.seller_name

        # Initialize badges as empty array
        if not self.badges:
            self.badges = "[]"

    def before_validate(self):
        """
        Auto-fill fields before validation runs.

        IMPORTANT: Use before_validate for auto-fill, NOT before_save.
        before_save runs AFTER validate(), so mandatory field check would fail first.
        Hook execution order: before_validate → validate → before_save → save
        """
        self.auto_fill_tenant_from_organization()

    def validate(self):
        """Validate seller profile data before saving."""
        self.validate_user()
        self.validate_tenant_organization_consistency()
        self.validate_tax_id()
        self.validate_iban()
        self.validate_mersis_number()
        self.validate_e_invoice_alias()
        self.validate_seller_limits()
        self.validate_vacation_mode()
        self.modified_by = frappe.session.user
        self.last_active_at = now_datetime()

    def on_update(self):
        """Actions to perform after seller profile is updated."""
        self.sync_to_erpnext_supplier()
        self.update_permissions()
        self.clear_seller_cache()

    def after_insert(self):
        """Actions to perform after seller profile is inserted."""
        # Create ERPNext Supplier if not exists
        if not self.erpnext_supplier:
            self.create_erpnext_supplier()

        # Assign seller role to user
        self.assign_seller_role()

        # Create User Permission for tenant data isolation
        self.create_user_permission_for_tenant()

    def on_trash(self):
        """Prevent deletion of seller profile with active orders or listings."""
        self.check_linked_documents()

    def set_tenant_from_context(self):
        """Set tenant from user's session context."""
        try:
            from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant
        except ImportError:
            pass

    def auto_fill_tenant_from_organization(self):
        """
        Auto-fill tenant from organization if not set.

        When a seller selects an organization, the tenant should be automatically
        populated from the organization's tenant. This ensures consistency and
        reduces data entry errors.
        """
        if self.organization and not self.tenant:
            org_tenant = frappe.db.get_value("Organization", self.organization, "tenant")
            if org_tenant:
                self.tenant = org_tenant

    def validate_tenant_organization_consistency(self):
        """
        Ensure tenant matches organization's tenant.

        This validation prevents data inconsistency where a seller profile
        could be linked to an organization from a different tenant. Such
        inconsistency would break tenant isolation and data security.

        Raises:
            frappe.ValidationError: If the selected organization belongs to
            a different tenant than the one selected on the seller profile.
        """
        if self.organization:
            org_tenant = frappe.db.get_value("Organization", self.organization, "tenant")
            if org_tenant and self.tenant != org_tenant:
                frappe.throw(
                    _("Selected Organization does not belong to the selected Tenant. "
                      "Please select an Organization from the same Tenant or change the Tenant.")
                )

    def validate_user(self):
        """Validate user link and ensure user is not already a seller."""
        if not self.user:
            frappe.throw(_("User is required"))

        if not frappe.db.exists("User", self.user):
            frappe.throw(_("User {0} does not exist").format(self.user))

        # Check if user already has a seller profile (for new records)
        if self.is_new():
            existing = frappe.db.exists("Seller Profile", {"user": self.user})
            if existing:
                frappe.throw(_("User {0} already has a Seller Profile").format(self.user))

    def validate_tax_id(self):
        """
        Validate Turkish Tax ID (VKN or TCKN) format and checksum.
        - VKN: 10 digits for companies
        - TCKN: 11 digits for individuals
        """
        if not self.tax_id:
            return

        tax_id = self.tax_id.strip()
        if not tax_id.isdigit():
            frappe.throw(_("Tax ID must contain only digits"))

        if self.tax_id_type == "VKN":
            if len(tax_id) != 10:
                frappe.throw(_("VKN (Company Tax ID) must be exactly 10 digits"))
            if not self.validate_vkn_checksum(tax_id):
                frappe.throw(_("Invalid VKN. Checksum validation failed."))
        elif self.tax_id_type == "TCKN":
            if len(tax_id) != 11:
                frappe.throw(_("TCKN (Individual Tax ID) must be exactly 11 digits"))
            if not self.validate_tckn_checksum(tax_id):
                frappe.throw(_("Invalid TCKN. Checksum validation failed."))

    def validate_vkn_checksum(self, vkn):
        """
        Validate Turkish VKN (Vergi Kimlik Numarasi) checksum.
        Algorithm: Each digit is processed with specific rules.
        """
        if len(vkn) != 10:
            return False

        try:
            digits = [int(d) for d in vkn]
            total = 0

            for i in range(9):
                tmp = (digits[i] + (9 - i)) % 10
                tmp = (tmp * (2 ** (9 - i))) % 9
                if tmp == 0 and digits[i] != 0:
                    tmp = 9
                total += tmp

            check_digit = (10 - (total % 10)) % 10
            return check_digit == digits[9]
        except (ValueError, IndexError):
            return False

    def validate_tckn_checksum(self, tckn):
        """
        Validate Turkish TCKN (T.C. Kimlik Numarasi) checksum.
        Algorithm: Uses specific formula for 10th and 11th digits.
        """
        if len(tckn) != 11:
            return False

        try:
            digits = [int(d) for d in tckn]

            # First digit cannot be 0
            if digits[0] == 0:
                return False

            # Calculate 10th digit
            odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
            even_sum = digits[1] + digits[3] + digits[5] + digits[7]
            digit_10 = ((odd_sum * 7) - even_sum) % 10
            if digit_10 < 0:
                digit_10 += 10

            if digits[9] != digit_10:
                return False

            # Calculate 11th digit
            total = sum(digits[:10])
            digit_11 = total % 10

            return digits[10] == digit_11
        except (ValueError, IndexError):
            return False

    def validate_iban(self):
        """
        Validate Turkish IBAN format.
        Turkish IBAN: TR + 2 check digits + 5 digit bank code + 16 digit account number = 26 chars
        """
        if not self.iban:
            return

        iban = self.iban.strip().upper().replace(" ", "")

        # Basic format check
        if len(iban) != 26:
            frappe.throw(_("Turkish IBAN must be exactly 26 characters"))

        if not iban.startswith("TR"):
            frappe.throw(_("Turkish IBAN must start with 'TR'"))

        # Check that rest is alphanumeric
        if not iban[2:].isalnum():
            frappe.throw(_("IBAN contains invalid characters"))

        # IBAN checksum validation
        if not self.validate_iban_checksum(iban):
            frappe.throw(_("Invalid IBAN. Checksum validation failed."))

        self.iban = iban

    def validate_iban_checksum(self, iban):
        """
        Validate IBAN using MOD-97 algorithm.
        """
        # Move first 4 characters to end
        rearranged = iban[4:] + iban[:4]

        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        numeric = ""
        for char in rearranged:
            if char.isalpha():
                numeric += str(ord(char) - ord("A") + 10)
            else:
                numeric += char

        # Check if remainder is 1
        return int(numeric) % 97 == 1

    def validate_mersis_number(self):
        """Validate MERSIS number format (16 digits)."""
        if not self.mersis_number:
            return

        mersis = self.mersis_number.strip()
        if not mersis.isdigit():
            frappe.throw(_("MERSIS Number must contain only digits"))
        if len(mersis) != 16:
            frappe.throw(_("MERSIS Number must be exactly 16 digits"))

    def validate_e_invoice_alias(self):
        """Validate E-Invoice alias format."""
        if self.e_invoice_registered and self.e_invoice_alias:
            alias = self.e_invoice_alias.strip().upper()
            if not (alias.startswith("PK:") or alias.startswith("GB:")):
                frappe.throw(_("E-Invoice Alias must start with 'PK:' or 'GB:'"))
            self.e_invoice_alias = alias

    def validate_seller_limits(self):
        """Validate seller against tenant limits."""
        if not self.tenant:
            return

        tenant = frappe.get_doc("Tenant", self.tenant)

        # Check max listings
        if not self.max_listings:
            self.max_listings = tenant.max_listings_per_seller

    def validate_vacation_mode(self):
        """Handle vacation mode status change."""
        if self.vacation_mode and self.status == "Active":
            self.status = "Vacation"
        elif not self.vacation_mode and self.status == "Vacation":
            self.status = "Active"

    def create_erpnext_supplier(self):
        """Create linked ERPNext Supplier record."""
        # Check if supplier with same tax_id exists
        if self.tax_id and frappe.db.exists("Supplier", {"tax_id": self.tax_id}):
            existing = frappe.db.get_value("Supplier", {"tax_id": self.tax_id}, "name")
            self.db_set("erpnext_supplier", existing)
            return

        supplier_data = {
            "doctype": "Supplier",
            "supplier_name": self.seller_name,
            "supplier_type": "Company" if self.seller_type in ["Business", "Enterprise"] else "Individual",
            "supplier_group": "All Supplier Groups",
            "country": self.country or "Turkey",
            "tax_id": self.tax_id,
            "default_currency": "TRY"
        }

        try:
            supplier = frappe.get_doc(supplier_data)
            supplier.flags.ignore_permissions = True
            supplier.insert()
            self.db_set("erpnext_supplier", supplier.name)
            frappe.msgprint(_("ERPNext Supplier {0} created").format(supplier.name))
        except Exception as e:
            frappe.log_error(f"Failed to create ERPNext Supplier for Seller Profile {self.name}: {str(e)}")

    def sync_to_erpnext_supplier(self):
        """Sync seller profile data to linked ERPNext Supplier."""
        if not self.erpnext_supplier:
            return

        try:
            supplier = frappe.get_doc("Supplier", self.erpnext_supplier)

            # Update supplier fields
            supplier.supplier_name = self.seller_name
            supplier.tax_id = self.tax_id

            # Set supplier type based on seller type
            if self.seller_type in ["Business", "Enterprise"]:
                supplier.supplier_type = "Company"
            else:
                supplier.supplier_type = "Individual"

            # Sync disabled status
            if self.status in ["Suspended", "Blocked", "Inactive"]:
                supplier.disabled = 1
            else:
                supplier.disabled = 0

            supplier.flags.ignore_permissions = True
            supplier.save()
        except frappe.DoesNotExistError:
            self.db_set("erpnext_supplier", None)
        except Exception as e:
            frappe.log_error(f"Failed to sync ERPNext Supplier for Seller Profile {self.name}: {str(e)}")

    def assign_seller_role(self):
        """Assign seller role to user."""
        if not self.user:
            return

        try:
            user = frappe.get_doc("User", self.user)
            if not user.has_role("Seller"):
                user.add_roles("Seller")
        except Exception as e:
            frappe.log_error(f"Failed to assign Seller role to user {self.user}: {str(e)}")

    def create_user_permission_for_tenant(self):
        """
        Create User Permission for seller's user to enable tenant data isolation.

        This ensures that the seller user can only access data belonging to
        their tenant by creating a User Permission linking the user to the
        tenant. This is essential for multi-tenant data isolation.
        """
        if not self.user or not self.tenant:
            return

        if self.user == "Administrator":
            return

        # Check if User Permission already exists
        if frappe.db.exists("User Permission", {
            "user": self.user,
            "allow": "Tenant",
            "for_value": self.tenant
        }):
            return

        try:
            user_permission = frappe.get_doc({
                "doctype": "User Permission",
                "user": self.user,
                "allow": "Tenant",
                "for_value": self.tenant,
                "apply_to_all_doctypes": 1,
                "is_default": 1
            })
            user_permission.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                message=str(e),
                title=_("Failed to create User Permission for Seller Profile {0}").format(self.name)
            )

    def update_permissions(self):
        """Update seller permissions based on status and verification."""
        if self.status == "Active" and self.verification_status == "Verified":
            self.db_set("can_sell", 1)
            self.db_set("can_withdraw", 1)
            self.db_set("can_create_listings", 1)
        elif self.status in ["Pending", "Under Review"]:
            self.db_set("can_sell", 0)
            self.db_set("can_withdraw", 0)
            self.db_set("can_create_listings", 0)
        elif self.status in ["Suspended", "Blocked"]:
            self.db_set("can_sell", 0)
            self.db_set("can_withdraw", 0)
            self.db_set("can_create_listings", 0)

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for active listings
        if frappe.db.exists("Listing", {"seller": self.name, "status": ["!=", "Archived"]}):
            frappe.throw(
                _("Cannot delete Seller Profile with active listings. "
                  "Please archive all listings first.")
            )

        # Check for pending orders
        if frappe.db.exists("Sub Order", {"seller": self.name, "status": ["not in", ["Completed", "Cancelled"]]}):
            frappe.throw(
                _("Cannot delete Seller Profile with pending orders. "
                  "Please complete or cancel all orders first.")
            )

    def clear_seller_cache(self):
        """Clear cached seller data."""
        cache_key = f"seller_profile:{self.name}"
        frappe.cache().delete_value(cache_key)

        if self.user:
            user_cache_key = f"seller_by_user:{self.user}"
            frappe.cache().delete_value(user_cache_key)

    # Verification Methods
    def mark_verified(self, verified_by=None):
        """Mark seller profile as verified after KYC/KYB review."""
        self.verification_status = "Verified"
        self.verified_at = now_datetime()
        self.verified_by = verified_by or frappe.session.user
        self.identity_verified = 1
        self.status = "Active"
        self.can_sell = 1
        self.can_withdraw = 1
        self.can_create_listings = 1
        self.save()

        # Send verification success notification
        self.send_notification("verification_success")

    def mark_rejected(self, reason=None):
        """Mark seller profile verification as rejected."""
        self.verification_status = "Rejected"
        if reason:
            self.verification_notes = f"Rejected: {reason}\n\n{self.verification_notes or ''}"
        self.save()

        # Send rejection notification
        self.send_notification("verification_rejected", reason=reason)

    def request_documents(self, note=None):
        """Request additional documents for verification."""
        self.verification_status = "Documents Requested"
        if note:
            self.verification_notes = f"Documents requested: {note}\n\n{self.verification_notes or ''}"
        self.save()

        # Send document request notification
        self.send_notification("documents_requested", note=note)

    def send_notification(self, notification_type, **kwargs):
        """Send notification to seller."""
        # Placeholder for notification system integration
        pass

    # Restriction Methods
    def apply_restriction(self, reason, restrict_selling=True, restrict_withdrawal=True,
                          restrict_listings=True):
        """Apply restrictions to the seller profile."""
        self.is_restricted = 1
        self.restriction_reason = reason
        self.restricted_at = now_datetime()

        if restrict_selling:
            self.can_sell = 0
        if restrict_withdrawal:
            self.can_withdraw = 0
        if restrict_listings:
            self.can_create_listings = 0

        self.save()

    def remove_restriction(self):
        """Remove restrictions from the seller profile."""
        self.is_restricted = 0
        self.restriction_reason = None
        self.restricted_at = None

        if self.status == "Active" and self.verification_status == "Verified":
            self.can_sell = 1
            self.can_withdraw = 1
            self.can_create_listings = 1

        self.save()

    def suspend(self, reason=None):
        """Suspend the seller profile."""
        self.status = "Suspended"
        self.apply_restriction(reason or "Account suspended")

    def activate(self):
        """Activate the seller profile."""
        if self.verification_status != "Verified":
            frappe.throw(_("Cannot activate seller profile without verification"))

        self.status = "Active"
        self.remove_restriction()

    # Performance Methods
    def recalculate_score(self):
        """Recalculate seller score based on various metrics."""
        weights = {
            "average_rating": 0.30,
            "order_fulfillment_rate": 0.20,
            "on_time_delivery_rate": 0.20,
            "return_rate": 0.10,  # Lower is better
            "cancellation_rate": 0.10,  # Lower is better
            "positive_feedback_rate": 0.10
        }

        # Calculate weighted score
        score = 0

        # Rating (1-5 scale to 0-100)
        if self.average_rating:
            score += (flt(self.average_rating) / 5) * 100 * weights["average_rating"]

        # Fulfillment rate
        score += flt(self.order_fulfillment_rate) * weights["order_fulfillment_rate"]

        # On-time delivery rate
        score += flt(self.on_time_delivery_rate) * weights["on_time_delivery_rate"]

        # Return rate (inverted - lower is better)
        score += (100 - flt(self.return_rate)) * weights["return_rate"]

        # Cancellation rate (inverted - lower is better)
        score += (100 - flt(self.cancellation_rate)) * weights["cancellation_rate"]

        # Positive feedback rate
        score += flt(self.positive_feedback_rate) * weights["positive_feedback_rate"]

        self.seller_score = round(score, 2)
        self.last_metrics_update = now_datetime()
        self.save()

        return self.seller_score

    def update_metrics(self):
        """Update seller performance metrics from orders and reviews."""
        # Get order metrics
        order_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_orders,
                SUM(CASE WHEN status = 'Cancelled' AND cancelled_by = 'seller' THEN 1 ELSE 0 END) as seller_cancellations,
                SUM(CASE WHEN delivered_on_time = 1 THEN 1 ELSE 0 END) as on_time_deliveries,
                SUM(total) as total_amount
            FROM `tabSub Order`
            WHERE seller = %s
            AND creation >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        """, self.name, as_dict=True)

        if order_stats:
            stats = order_stats[0]
            total = stats.total_orders or 1  # Avoid division by zero

            self.order_fulfillment_rate = round((stats.completed_orders / total) * 100, 2) if total > 0 else 100
            self.cancellation_rate = round((stats.seller_cancellations / total) * 100, 2) if total > 0 else 0
            self.on_time_delivery_rate = round((stats.on_time_deliveries / total) * 100, 2) if total > 0 else 100

        # Get return metrics
        return_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_returns
            FROM `tabSub Order`
            WHERE seller = %s
            AND status = 'Returned'
            AND creation >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        """, self.name, as_dict=True)

        if return_stats and order_stats:
            total = order_stats[0].total_orders or 1
            self.return_rate = round((return_stats[0].total_returns / total) * 100, 2)

        # Get review metrics
        review_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_reviews,
                AVG(rating) as avg_rating,
                SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as positive_reviews
            FROM `tabReview`
            WHERE seller = %s
            AND status = 'Approved'
        """, self.name, as_dict=True)

        if review_stats:
            stats = review_stats[0]
            self.total_reviews = stats.total_reviews or 0
            self.average_rating = round(stats.avg_rating or 0, 2)
            if stats.total_reviews:
                self.positive_feedback_rate = round((stats.positive_reviews / stats.total_reviews) * 100, 2)

        # Update lifetime totals
        lifetime_stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_count,
                COALESCE(SUM(total), 0) as total_amount
            FROM `tabSub Order`
            WHERE seller = %s
            AND status = 'Completed'
        """, self.name, as_dict=True)

        if lifetime_stats:
            self.total_sales_count = lifetime_stats[0].total_count or 0
            self.total_sales_amount = lifetime_stats[0].total_amount or 0

        self.last_metrics_update = now_datetime()
        self.save()

        # Recalculate score
        self.recalculate_score()

    # Badge Methods
    def add_badge(self, badge_id, badge_name, badge_description=None):
        """Add a badge to the seller profile."""
        badges = json.loads(self.badges or "[]")

        # Check if badge already exists
        for badge in badges:
            if badge.get("id") == badge_id:
                return False

        badges.append({
            "id": badge_id,
            "name": badge_name,
            "description": badge_description,
            "awarded_at": now_datetime().isoformat()
        })

        self.badges = json.dumps(badges)
        self.save()
        return True

    def remove_badge(self, badge_id):
        """Remove a badge from the seller profile."""
        badges = json.loads(self.badges or "[]")
        badges = [b for b in badges if b.get("id") != badge_id]
        self.badges = json.dumps(badges)
        self.save()

    def has_badge(self, badge_id):
        """Check if seller has a specific badge."""
        badges = json.loads(self.badges or "[]")
        return any(b.get("id") == badge_id for b in badges)

    # Status Check Methods
    def is_active(self):
        """Check if seller profile is active."""
        return self.status == "Active"

    def is_verified(self):
        """Check if seller profile is verified."""
        return self.verification_status == "Verified"

    def can_accept_orders(self):
        """Check if seller can accept new orders."""
        return (self.is_active() and
                self.is_verified() and
                not self.vacation_mode and
                cint(self.can_sell))

    def can_create_listing(self):
        """Check if seller can create new listings."""
        if not cint(self.can_create_listings):
            return False

        # Check listing limit
        current_listings = frappe.db.count("Listing", {
            "seller": self.name,
            "status": ["!=", "Archived"]
        })

        return current_listings < cint(self.max_listings)

    def get_available_listing_slots(self):
        """Get number of available listing slots."""
        current_listings = frappe.db.count("Listing", {
            "seller": self.name,
            "status": ["!=", "Archived"]
        })

        return max(0, cint(self.max_listings) - current_listings)


# API Endpoints
@frappe.whitelist()
def get_seller_profile(seller_name=None, user=None):
    """
    Get seller profile details.

    Args:
        seller_name: Name of the seller profile
        user: User linked to seller profile

    Returns:
        dict: Seller profile details
    """
    if not seller_name and not user:
        user = frappe.session.user

    if user and not seller_name:
        seller_name = frappe.db.get_value("Seller Profile", {"user": user}, "name")

    if not seller_name:
        return {"error": _("Seller profile not found")}

    if not frappe.has_permission("Seller Profile", "read"):
        frappe.throw(_("Not permitted to view seller profile"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    return {
        "name": seller.name,
        "seller_name": seller.seller_name,
        "display_name": seller.display_name,
        "seller_type": seller.seller_type,
        "status": seller.status,
        "verification_status": seller.verification_status,
        "seller_tier": seller.seller_tier,
        "seller_score": seller.seller_score,
        "average_rating": seller.average_rating,
        "total_reviews": seller.total_reviews,
        "total_sales_count": seller.total_sales_count,
        "is_active": seller.is_active(),
        "is_verified": seller.is_verified(),
        "can_accept_orders": seller.can_accept_orders(),
        "is_top_seller": seller.is_top_seller,
        "is_premium_seller": seller.is_premium_seller,
        "badges": json.loads(seller.badges or "[]"),
        "city": seller.city,
        "country": seller.country
    }


@frappe.whitelist()
def verify_seller(seller_name):
    """
    Verify a seller profile after KYC/KYB review.

    Args:
        seller_name: Name of the seller profile

    Returns:
        dict: Updated seller status
    """
    if not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to verify sellers"))

    seller = frappe.get_doc("Seller Profile", seller_name)
    seller.mark_verified()

    return {
        "status": "success",
        "message": _("Seller verified successfully"),
        "verification_status": seller.verification_status
    }


@frappe.whitelist()
def reject_seller(seller_name, reason=None):
    """
    Reject a seller profile verification.

    Args:
        seller_name: Name of the seller profile
        reason: Reason for rejection

    Returns:
        dict: Updated seller status
    """
    if not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to reject sellers"))

    seller = frappe.get_doc("Seller Profile", seller_name)
    seller.mark_rejected(reason)

    return {
        "status": "success",
        "message": _("Seller verification rejected"),
        "verification_status": seller.verification_status
    }


@frappe.whitelist()
def suspend_seller(seller_name, reason=None):
    """
    Suspend a seller profile.

    Args:
        seller_name: Name of the seller profile
        reason: Reason for suspension

    Returns:
        dict: Updated seller status
    """
    if not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to suspend sellers"))

    seller = frappe.get_doc("Seller Profile", seller_name)
    seller.suspend(reason)

    return {
        "status": "success",
        "message": _("Seller suspended"),
        "seller_status": seller.status
    }


@frappe.whitelist()
def activate_seller(seller_name):
    """
    Activate a seller profile.

    Args:
        seller_name: Name of the seller profile

    Returns:
        dict: Updated seller status
    """
    if not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to activate sellers"))

    seller = frappe.get_doc("Seller Profile", seller_name)
    seller.activate()

    return {
        "status": "success",
        "message": _("Seller activated"),
        "seller_status": seller.status
    }


@frappe.whitelist()
def update_seller_metrics(seller_name):
    """
    Recalculate seller performance metrics.

    Args:
        seller_name: Name of the seller profile

    Returns:
        dict: Updated metrics
    """
    seller = frappe.get_doc("Seller Profile", seller_name)
    seller.update_metrics()

    return {
        "status": "success",
        "seller_score": seller.seller_score,
        "average_rating": seller.average_rating,
        "order_fulfillment_rate": seller.order_fulfillment_rate,
        "on_time_delivery_rate": seller.on_time_delivery_rate,
        "return_rate": seller.return_rate,
        "cancellation_rate": seller.cancellation_rate
    }


@frappe.whitelist()
def toggle_vacation_mode(seller_name, enable=True):
    """
    Toggle vacation mode for a seller.

    Args:
        seller_name: Name of the seller profile
        enable: True to enable vacation mode

    Returns:
        dict: Updated status
    """
    seller = frappe.get_doc("Seller Profile", seller_name)

    # Check if current user owns this seller profile
    if seller.user != frappe.session.user and not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to change vacation mode"))

    seller.vacation_mode = cint(enable)
    seller.save()

    return {
        "status": "success",
        "vacation_mode": seller.vacation_mode,
        "seller_status": seller.status
    }


@frappe.whitelist()
def get_seller_by_user(user=None):
    """
    Get seller profile for a user.

    Args:
        user: User to check (defaults to current user)

    Returns:
        dict: Seller profile or None
    """
    user = user or frappe.session.user

    seller_name = frappe.db.get_value("Seller Profile", {"user": user}, "name")

    if not seller_name:
        return None

    return get_seller_profile(seller_name)


@frappe.whitelist()
def get_seller_statistics(seller_name):
    """
    Get detailed statistics for a seller.

    Args:
        seller_name: Name of the seller profile

    Returns:
        dict: Seller statistics
    """
    if not frappe.has_permission("Seller Profile", "read"):
        frappe.throw(_("Not permitted to view seller statistics"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    # Get listing count by status
    listing_stats = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabListing`
        WHERE seller = %s
        GROUP BY status
    """, seller_name, as_dict=True)

    # Get order stats by period
    order_stats = frappe.db.sql("""
        SELECT
            DATE_FORMAT(creation, '%%Y-%%m') as month,
            COUNT(*) as order_count,
            COALESCE(SUM(total), 0) as total_amount
        FROM `tabSub Order`
        WHERE seller = %s
        AND status = 'Completed'
        AND creation >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
        GROUP BY DATE_FORMAT(creation, '%%Y-%%m')
        ORDER BY month DESC
    """, seller_name, as_dict=True)

    return {
        "seller_name": seller_name,
        "seller_score": seller.seller_score,
        "average_rating": seller.average_rating,
        "total_reviews": seller.total_reviews,
        "total_sales_count": seller.total_sales_count,
        "total_sales_amount": seller.total_sales_amount,
        "listing_stats": {s.status: s.count for s in listing_stats},
        "monthly_sales": order_stats,
        "metrics": {
            "order_fulfillment_rate": seller.order_fulfillment_rate,
            "on_time_delivery_rate": seller.on_time_delivery_rate,
            "return_rate": seller.return_rate,
            "cancellation_rate": seller.cancellation_rate,
            "response_time_hours": seller.response_time_hours,
            "complaint_rate": seller.complaint_rate,
            "positive_feedback_rate": seller.positive_feedback_rate
        },
        "badges": json.loads(seller.badges or "[]"),
        "available_listing_slots": seller.get_available_listing_slots()
    }


@frappe.whitelist()
def award_badge(seller_name, badge_id, badge_name, badge_description=None):
    """
    Award a badge to a seller.

    Args:
        seller_name: Name of the seller profile
        badge_id: Unique badge identifier
        badge_name: Display name for the badge
        badge_description: Description of the badge

    Returns:
        dict: Result of operation
    """
    if not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to award badges"))

    seller = frappe.get_doc("Seller Profile", seller_name)
    success = seller.add_badge(badge_id, badge_name, badge_description)

    if success:
        return {
            "status": "success",
            "message": _("Badge awarded successfully"),
            "badges": json.loads(seller.badges or "[]")
        }
    else:
        return {
            "status": "error",
            "message": _("Seller already has this badge")
        }


@frappe.whitelist()
def validate_tax_id(tax_id, tax_id_type="TCKN"):
    """
    Validate a Turkish tax ID (VKN or TCKN).

    Args:
        tax_id: Tax ID to validate
        tax_id_type: Type of tax ID (VKN or TCKN)

    Returns:
        dict: Validation result
    """
    seller = SellerProfile({"tax_id": tax_id, "tax_id_type": tax_id_type})

    if tax_id_type == "VKN":
        is_valid = seller.validate_vkn_checksum(tax_id)
        expected_length = 10
    else:
        is_valid = seller.validate_tckn_checksum(tax_id)
        expected_length = 11

    return {
        "is_valid": is_valid,
        "tax_id_type": tax_id_type,
        "expected_length": expected_length,
        "actual_length": len(tax_id) if tax_id else 0
    }


@frappe.whitelist()
def validate_iban(iban):
    """
    Validate a Turkish IBAN.

    Args:
        iban: IBAN to validate

    Returns:
        dict: Validation result
    """
    seller = SellerProfile({})

    iban_cleaned = iban.strip().upper().replace(" ", "") if iban else ""

    # Basic checks
    if len(iban_cleaned) != 26:
        return {"is_valid": False, "error": "Turkish IBAN must be 26 characters"}

    if not iban_cleaned.startswith("TR"):
        return {"is_valid": False, "error": "Turkish IBAN must start with 'TR'"}

    is_valid = seller.validate_iban_checksum(iban_cleaned)

    return {
        "is_valid": is_valid,
        "iban_formatted": f"{iban_cleaned[:4]} {iban_cleaned[4:8]} {iban_cleaned[8:12]} {iban_cleaned[12:16]} {iban_cleaned[16:20]} {iban_cleaned[20:24]} {iban_cleaned[24:]}"
    }
