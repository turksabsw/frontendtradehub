# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime, add_days


class SKU(Document):
    """
    SKU (Stock Keeping Unit) DocType for inventory management.

    Represents a unique product identifier with detailed inventory tracking.
    Each SKU:
    - Has a unique code
    - Links to either a Listing or Listing Variant
    - Tracks detailed inventory metrics
    - Can sync with ERPNext Stock
    - Supports reorder management
    """

    def before_insert(self):
        """Set default values before inserting a new SKU."""
        # Set tenant from seller if not specified
        if not self.tenant and self.seller:
            self.set_tenant_from_seller()

        # Set product details from linked listing/variant
        self.populate_from_product()

    def validate(self):
        """Validate SKU data before saving."""
        self.validate_sku_code()
        self.validate_product_reference()
        self.validate_seller()
        self.validate_inventory()
        self.validate_pricing()
        self.calculate_available_qty()
        self.calculate_profit_margin()
        self.generate_sku_name()
        self.update_status_based_on_inventory()

    def on_update(self):
        """Actions after SKU is updated."""
        self.sync_to_product()
        self.clear_sku_cache()

        # Sync to ERPNext if enabled
        if self.sync_inventory and self.erpnext_item:
            self.sync_to_erpnext()

    def on_trash(self):
        """Actions before SKU is deleted."""
        self.check_linked_documents()

    # Helper Methods
    def set_tenant_from_seller(self):
        """Set tenant from seller's profile."""
        if self.seller:
            tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if tenant:
                self.tenant = tenant

    def populate_from_product(self):
        """Populate SKU details from linked product."""
        if self.product_type == "Listing" and self.listing:
            listing = frappe.get_cached_doc("Listing", self.listing)
            if not self.category:
                self.category = listing.category
            if not self.brand:
                self.brand = listing.brand
            if not self.manufacturer:
                self.manufacturer = listing.manufacturer
            if not self.selling_price:
                self.selling_price = listing.selling_price
            if not self.cost_price:
                self.cost_price = listing.cost_price
            if not self.weight:
                self.weight = listing.weight
            if not self.seller:
                self.seller = listing.seller
            if not self.tenant:
                self.tenant = listing.tenant
            if not self.erpnext_item:
                self.erpnext_item = listing.erpnext_item

        elif self.product_type == "Variant" and self.listing_variant:
            variant = frappe.get_cached_doc("Listing Variant", self.listing_variant)
            listing = frappe.get_cached_doc("Listing", variant.listing)

            if not self.category:
                self.category = listing.category
            if not self.brand:
                self.brand = listing.brand
            if not self.selling_price:
                self.selling_price = variant.selling_price or listing.selling_price
            if not self.cost_price:
                self.cost_price = variant.cost_price or listing.cost_price
            if not self.weight:
                self.weight = variant.weight or listing.weight
            if not self.seller:
                self.seller = variant.seller
            if not self.tenant:
                self.tenant = variant.tenant
            if not self.erpnext_item:
                self.erpnext_item = variant.erpnext_item_variant or listing.erpnext_item

    def generate_sku_name(self):
        """Generate SKU name from product info if not set."""
        if self.sku_name:
            return

        if self.product_type == "Listing" and self.listing:
            listing_title = frappe.db.get_value("Listing", self.listing, "title")
            self.sku_name = f"{listing_title} ({self.sku_code})"

        elif self.product_type == "Variant" and self.listing_variant:
            variant_name = frappe.db.get_value(
                "Listing Variant", self.listing_variant, "variant_name"
            )
            listing_name = frappe.db.get_value(
                "Listing Variant", self.listing_variant, "listing"
            )
            listing_title = frappe.db.get_value("Listing", listing_name, "title")
            self.sku_name = f"{listing_title} - {variant_name} ({self.sku_code})"

        elif not self.sku_name:
            self.sku_name = self.sku_code

    # Validation Methods
    def validate_sku_code(self):
        """Validate SKU code format and uniqueness."""
        if not self.sku_code:
            frappe.throw(_("SKU Code is required"))

        # Check for invalid characters
        import re
        if not re.match(r"^[A-Za-z0-9\-_]+$", self.sku_code):
            frappe.throw(
                _("SKU Code can only contain letters, numbers, hyphens, and underscores")
            )

        # Check uniqueness (handled by unique constraint, but good for error message)
        existing = frappe.db.get_value(
            "SKU",
            {"sku_code": self.sku_code, "name": ["!=", self.name or ""]},
            "name"
        )
        if existing:
            frappe.throw(
                _("SKU Code {0} is already in use").format(self.sku_code)
            )

    def validate_product_reference(self):
        """Validate product reference based on product type."""
        if self.product_type == "Listing":
            if not self.listing:
                frappe.throw(
                    _("Listing is required when product type is 'Listing'")
                )
            if not frappe.db.exists("Listing", self.listing):
                frappe.throw(_("Listing {0} does not exist").format(self.listing))

        elif self.product_type == "Variant":
            if not self.listing_variant:
                frappe.throw(
                    _("Listing Variant is required when product type is 'Variant'")
                )
            if not frappe.db.exists("Listing Variant", self.listing_variant):
                frappe.throw(
                    _("Listing Variant {0} does not exist").format(self.listing_variant)
                )

        # Standalone SKUs don't need product reference

    def validate_seller(self):
        """Validate seller reference."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Seller Profile {0} does not exist").format(self.seller))

    def validate_inventory(self):
        """Validate inventory fields."""
        if flt(self.stock_qty) < 0:
            frappe.throw(_("Stock Quantity cannot be negative"))

        if flt(self.reorder_level) < 0:
            frappe.throw(_("Reorder Level cannot be negative"))

        if flt(self.reorder_qty) < 0:
            frappe.throw(_("Reorder Quantity cannot be negative"))

        if flt(self.low_stock_threshold) < 0:
            frappe.throw(_("Low Stock Threshold cannot be negative"))

    def validate_pricing(self):
        """Validate pricing fields."""
        if self.cost_price and flt(self.cost_price) < 0:
            frappe.throw(_("Cost Price cannot be negative"))

        if self.selling_price and flt(self.selling_price) < 0:
            frappe.throw(_("Selling Price cannot be negative"))

        if self.compare_at_price and self.selling_price:
            if flt(self.compare_at_price) < flt(self.selling_price):
                frappe.throw(
                    _("Compare at Price should be greater than Selling Price")
                )

    def calculate_available_qty(self):
        """Calculate available quantity."""
        self.available_qty = max(
            0,
            flt(self.stock_qty) - flt(self.reserved_qty) - flt(self.committed_qty)
        )

    def calculate_profit_margin(self):
        """Calculate profit margin percentage."""
        if flt(self.cost_price) > 0 and flt(self.selling_price) > 0:
            profit = flt(self.selling_price) - flt(self.cost_price)
            self.profit_margin = (profit / flt(self.cost_price)) * 100
        else:
            self.profit_margin = 0

    def update_status_based_on_inventory(self):
        """Update status based on inventory levels."""
        if self.status in ["Inactive", "Discontinued", "Pending"]:
            return

        if self.track_inventory:
            if flt(self.available_qty) <= 0 and not self.allow_backorders:
                self.status = "Out of Stock"
            elif self.status == "Out of Stock" and flt(self.available_qty) > 0:
                self.status = "Active"

    # Stock Management Methods
    def update_stock(self, qty_change, transaction_type="Adjustment", reason=None):
        """
        Update stock quantity.

        Args:
            qty_change: Quantity to add (positive) or subtract (negative)
            transaction_type: Type of transaction (Adjustment, Sale, Return, etc.)
            reason: Reason for the adjustment
        """
        new_qty = flt(self.stock_qty) + flt(qty_change)
        if new_qty < 0:
            frappe.throw(_("Stock quantity cannot go below 0"))

        self.db_set("stock_qty", new_qty)
        self.db_set(
            "available_qty",
            max(0, new_qty - flt(self.reserved_qty) - flt(self.committed_qty))
        )

        # Update total received/sold
        if flt(qty_change) > 0 and transaction_type in ["Purchase", "Return", "Adjustment"]:
            self.db_set("total_received", flt(self.total_received) + flt(qty_change))
            self.db_set("last_received_at", now_datetime())
        elif flt(qty_change) < 0 and transaction_type in ["Sale", "Adjustment"]:
            self.db_set("total_sold", flt(self.total_sold) + abs(flt(qty_change)))
            self.db_set("last_sold_at", now_datetime())

        # Update status
        if self.track_inventory:
            if new_qty <= 0 and not self.allow_backorders:
                self.db_set("status", "Out of Stock")
            elif self.status == "Out of Stock" and new_qty > 0:
                self.db_set("status", "Active")

        self.sync_to_product()
        self.clear_sku_cache()

    def reserve_stock(self, qty):
        """Reserve stock for pending orders."""
        if flt(qty) < 0:
            frappe.throw(_("Reserve quantity cannot be negative"))

        if flt(qty) > flt(self.available_qty) and not self.allow_backorders:
            frappe.throw(_("Not enough stock available"))

        new_reserved = flt(self.reserved_qty) + flt(qty)
        self.db_set("reserved_qty", new_reserved)
        self.db_set(
            "available_qty",
            max(0, flt(self.stock_qty) - new_reserved - flt(self.committed_qty))
        )
        self.clear_sku_cache()

    def release_reservation(self, qty):
        """Release reserved stock."""
        new_reserved = max(0, flt(self.reserved_qty) - flt(qty))
        self.db_set("reserved_qty", new_reserved)
        self.db_set(
            "available_qty",
            max(0, flt(self.stock_qty) - new_reserved - flt(self.committed_qty))
        )
        self.clear_sku_cache()

    def commit_stock(self, qty):
        """Commit reserved stock (convert reservation to commitment)."""
        if flt(qty) > flt(self.reserved_qty):
            frappe.throw(_("Cannot commit more than reserved quantity"))

        new_reserved = flt(self.reserved_qty) - flt(qty)
        new_committed = flt(self.committed_qty) + flt(qty)

        self.db_set("reserved_qty", new_reserved)
        self.db_set("committed_qty", new_committed)
        self.clear_sku_cache()

    def fulfill_commitment(self, qty):
        """Fulfill committed stock (deduct from actual stock)."""
        if flt(qty) > flt(self.committed_qty):
            frappe.throw(_("Cannot fulfill more than committed quantity"))

        new_committed = flt(self.committed_qty) - flt(qty)
        new_stock = flt(self.stock_qty) - flt(qty)

        if new_stock < 0:
            frappe.throw(_("Insufficient stock to fulfill commitment"))

        self.db_set("committed_qty", new_committed)
        self.db_set("stock_qty", new_stock)
        self.db_set(
            "available_qty",
            max(0, new_stock - flt(self.reserved_qty) - new_committed)
        )
        self.db_set("total_sold", flt(self.total_sold) + flt(qty))
        self.db_set("last_sold_at", now_datetime())

        self.sync_to_product()
        self.clear_sku_cache()

    def receive_stock(self, qty, purchase_price=None):
        """Receive stock from purchase."""
        if flt(qty) < 0:
            frappe.throw(_("Receive quantity cannot be negative"))

        new_stock = flt(self.stock_qty) + flt(qty)
        self.db_set("stock_qty", new_stock)
        self.db_set(
            "available_qty",
            max(0, new_stock - flt(self.reserved_qty) - flt(self.committed_qty))
        )
        self.db_set("total_received", flt(self.total_received) + flt(qty))
        self.db_set("last_received_at", now_datetime())

        if purchase_price:
            self.db_set("last_purchase_price", purchase_price)

        # Update status
        if self.status == "Out of Stock" and new_stock > 0:
            self.db_set("status", "Active")

        self.sync_to_product()
        self.clear_sku_cache()

    def record_stock_count(self, counted_qty, counter=None):
        """Record physical stock count."""
        variance = flt(counted_qty) - flt(self.stock_qty)

        self.db_set("stock_qty", counted_qty)
        self.db_set(
            "available_qty",
            max(0, counted_qty - flt(self.reserved_qty) - flt(self.committed_qty))
        )
        self.db_set("last_stock_count", now_datetime())
        self.db_set("last_stock_count_by", counter or frappe.session.user)
        self.db_set("stock_count_variance", variance)

        self.sync_to_product()
        self.clear_sku_cache()

        return variance

    # Status Methods
    def is_in_stock(self):
        """Check if SKU is in stock."""
        if not self.track_inventory:
            return True
        return flt(self.available_qty) > 0 or self.allow_backorders

    def is_low_stock(self):
        """Check if SKU is low on stock."""
        if not self.track_inventory:
            return False
        return flt(self.available_qty) <= flt(self.low_stock_threshold)

    def needs_reorder(self):
        """Check if SKU needs to be reordered."""
        if not self.track_inventory or not flt(self.reorder_level):
            return False
        return flt(self.stock_qty) <= flt(self.reorder_level)

    def activate(self):
        """Activate the SKU."""
        if self.status == "Discontinued":
            frappe.throw(_("Cannot activate a discontinued SKU"))

        if flt(self.available_qty) <= 0 and self.track_inventory and not self.allow_backorders:
            self.db_set("status", "Out of Stock")
        else:
            self.db_set("status", "Active")
        self.db_set("is_active", 1)
        self.clear_sku_cache()

    def deactivate(self):
        """Deactivate the SKU."""
        self.db_set("status", "Inactive")
        self.db_set("is_active", 0)
        self.clear_sku_cache()

    def discontinue(self):
        """Discontinue the SKU."""
        self.db_set("status", "Discontinued")
        self.db_set("is_active", 0)
        self.clear_sku_cache()

    # Sync Methods
    def sync_to_product(self):
        """Sync stock quantity to linked listing/variant."""
        if self.product_type == "Listing" and self.listing:
            frappe.db.set_value(
                "Listing", self.listing,
                {"stock_qty": self.stock_qty, "available_qty": self.available_qty}
            )
        elif self.product_type == "Variant" and self.listing_variant:
            frappe.db.set_value(
                "Listing Variant", self.listing_variant,
                {"stock_qty": self.stock_qty, "available_qty": self.available_qty}
            )

    def sync_to_erpnext(self):
        """Sync stock to ERPNext Stock Ledger."""
        if not self.erpnext_item or not self.erpnext_warehouse:
            return

        if not frappe.db.exists("DocType", "Stock Entry"):
            return

        try:
            # Get current ERPNext stock
            from erpnext.stock.utils import get_stock_balance
            erpnext_qty = get_stock_balance(
                self.erpnext_item, self.erpnext_warehouse
            )

            # Only sync if there's a difference
            if abs(flt(self.stock_qty) - flt(erpnext_qty)) > 0.001:
                # Create stock reconciliation entry
                # (Simplified - in production, would use Stock Reconciliation)
                self.db_set("last_synced_at", now_datetime())

        except Exception as e:
            frappe.log_error(
                f"Failed to sync SKU {self.name} to ERPNext: {str(e)}",
                "SKU ERPNext Sync Error"
            )

    def sync_from_erpnext(self):
        """Sync stock from ERPNext Stock Ledger."""
        if not self.erpnext_item or not self.erpnext_warehouse:
            return

        try:
            from erpnext.stock.utils import get_stock_balance
            erpnext_qty = get_stock_balance(
                self.erpnext_item, self.erpnext_warehouse
            )

            self.db_set("stock_qty", erpnext_qty)
            self.db_set(
                "available_qty",
                max(0, erpnext_qty - flt(self.reserved_qty) - flt(self.committed_qty))
            )
            self.db_set("last_synced_at", now_datetime())

            self.sync_to_product()
            self.clear_sku_cache()

        except Exception as e:
            frappe.log_error(
                f"Failed to sync SKU {self.name} from ERPNext: {str(e)}",
                "SKU ERPNext Sync Error"
            )

    # Helper Methods
    def check_linked_documents(self):
        """Check for linked documents before deletion."""
        # Check for order items
        # (would check when Order Item DocType exists)
        pass

    def clear_sku_cache(self):
        """Clear cached SKU data."""
        cache_key = f"sku:{self.name}"
        frappe.cache().delete_value(cache_key)

        if self.sku_code:
            code_cache_key = f"sku_by_code:{self.sku_code}"
            frappe.cache().delete_value(code_cache_key)

    def get_stock_info(self):
        """Get comprehensive stock information."""
        return {
            "sku_code": self.sku_code,
            "sku_name": self.sku_name,
            "stock_qty": flt(self.stock_qty),
            "reserved_qty": flt(self.reserved_qty),
            "committed_qty": flt(self.committed_qty),
            "available_qty": flt(self.available_qty),
            "incoming_qty": flt(self.incoming_qty),
            "in_stock": self.is_in_stock(),
            "low_stock": self.is_low_stock(),
            "needs_reorder": self.needs_reorder(),
            "status": self.status,
            "warehouse": self.warehouse,
            "storage_location": self.storage_location,
            "bin_location": self.bin_location,
        }


# API Endpoints
@frappe.whitelist()
def get_sku(sku_name=None, sku_code=None):
    """
    Get SKU details.

    Args:
        sku_name: Name of the SKU
        sku_code: Unique SKU code

    Returns:
        dict: SKU details
    """
    if not sku_name and not sku_code:
        frappe.throw(_("Either sku_name or sku_code is required"))

    if sku_code and not sku_name:
        sku_name = sku_code  # SKU uses sku_code as name

    if not frappe.db.exists("SKU", sku_name):
        return {"error": _("SKU not found")}

    sku = frappe.get_doc("SKU", sku_name)
    return sku.get_stock_info()


@frappe.whitelist()
def get_seller_skus(seller=None, status=None, low_stock_only=False, page=1, page_size=20):
    """
    Get SKUs for a seller.

    Args:
        seller: Seller profile name
        status: Filter by status
        low_stock_only: Only return low stock items
        page: Page number
        page_size: Results per page

    Returns:
        dict: SKUs with pagination
    """
    if not seller:
        seller = frappe.db.get_value(
            "Seller Profile", {"user": frappe.session.user}, "name"
        )

    if not seller:
        return {"error": _("Seller profile not found")}

    filters = {"seller": seller}
    if status:
        filters["status"] = status

    start = (cint(page) - 1) * cint(page_size)

    # Get SKUs
    skus = frappe.get_all(
        "SKU",
        filters=filters,
        fields=[
            "name", "sku_code", "sku_name", "status",
            "stock_qty", "available_qty", "reserved_qty",
            "low_stock_threshold", "selling_price", "cost_price",
            "warehouse", "last_sold_at"
        ],
        order_by="modified DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    # Filter low stock if requested
    if low_stock_only:
        skus = [
            s for s in skus
            if flt(s.available_qty) <= flt(s.low_stock_threshold)
        ]

    total = frappe.db.count("SKU", filters)

    return {
        "skus": skus,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def create_sku(**kwargs):
    """
    Create a new SKU.

    Returns:
        dict: Created SKU details
    """
    required = ["sku_code", "seller"]
    for field in required:
        if not kwargs.get(field):
            frappe.throw(_(f"{field} is required"))

    # Check permission
    seller = kwargs.get("seller")
    seller_user = frappe.db.get_value("Seller Profile", seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("SKU", "create"):
            frappe.throw(_("Not permitted to create SKUs for this seller"))

    sku = frappe.get_doc({
        "doctype": "SKU",
        **kwargs
    })
    sku.insert()

    return {
        "status": "success",
        "sku_name": sku.name,
        "sku_code": sku.sku_code,
        "message": _("SKU created successfully")
    }


@frappe.whitelist()
def update_sku_stock(sku_code, qty_change, transaction_type="Adjustment", reason=None):
    """
    Update SKU stock quantity.

    Args:
        sku_code: SKU code
        qty_change: Quantity to add (positive) or subtract (negative)
        transaction_type: Type of transaction
        reason: Reason for adjustment

    Returns:
        dict: Updated stock info
    """
    if not frappe.db.exists("SKU", sku_code):
        return {"error": _("SKU not found")}

    sku = frappe.get_doc("SKU", sku_code)

    # Check permission
    seller_user = frappe.db.get_value("Seller Profile", sku.seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("SKU", "write"):
            frappe.throw(_("Not permitted to update stock for this SKU"))

    sku.update_stock(flt(qty_change), transaction_type, reason)

    return {
        "status": "success",
        **sku.get_stock_info()
    }


@frappe.whitelist()
def record_stock_count(sku_code, counted_qty):
    """
    Record physical stock count.

    Args:
        sku_code: SKU code
        counted_qty: Quantity counted

    Returns:
        dict: Stock count result with variance
    """
    if not frappe.db.exists("SKU", sku_code):
        return {"error": _("SKU not found")}

    sku = frappe.get_doc("SKU", sku_code)

    # Check permission
    seller_user = frappe.db.get_value("Seller Profile", sku.seller, "user")
    if seller_user != frappe.session.user:
        if not frappe.has_permission("SKU", "write"):
            frappe.throw(_("Not permitted to record stock count for this SKU"))

    variance = sku.record_stock_count(flt(counted_qty))

    return {
        "status": "success",
        "variance": variance,
        **sku.get_stock_info()
    }


@frappe.whitelist()
def get_low_stock_skus(seller=None, threshold=None):
    """
    Get SKUs that are low on stock.

    Args:
        seller: Seller profile name (optional)
        threshold: Custom threshold (optional, uses SKU setting if not provided)

    Returns:
        list: Low stock SKUs
    """
    filters = {"status": ["in", ["Active", "Out of Stock"]], "track_inventory": 1}

    if seller:
        filters["seller"] = seller
    elif frappe.session.user != "Administrator":
        seller = frappe.db.get_value(
            "Seller Profile", {"user": frappe.session.user}, "name"
        )
        if seller:
            filters["seller"] = seller

    skus = frappe.get_all(
        "SKU",
        filters=filters,
        fields=[
            "name", "sku_code", "sku_name", "stock_qty", "available_qty",
            "low_stock_threshold", "reorder_level", "reorder_qty",
            "warehouse", "default_supplier", "status"
        ]
    )

    # Filter to only low stock
    low_stock_skus = []
    for s in skus:
        check_threshold = flt(threshold) if threshold else flt(s.low_stock_threshold)
        if flt(s.available_qty) <= check_threshold:
            s["needs_reorder"] = flt(s.stock_qty) <= flt(s.reorder_level)
            low_stock_skus.append(s)

    return low_stock_skus


@frappe.whitelist()
def get_reorder_suggestions(seller=None):
    """
    Get SKUs that need reordering with suggested quantities.

    Args:
        seller: Seller profile name (optional)

    Returns:
        list: SKUs needing reorder with suggested quantities
    """
    filters = {
        "status": ["in", ["Active", "Out of Stock"]],
        "track_inventory": 1,
        "reorder_level": [">", 0]
    }

    if seller:
        filters["seller"] = seller
    elif frappe.session.user != "Administrator":
        seller = frappe.db.get_value(
            "Seller Profile", {"user": frappe.session.user}, "name"
        )
        if seller:
            filters["seller"] = seller

    skus = frappe.get_all(
        "SKU",
        filters=filters,
        fields=[
            "name", "sku_code", "sku_name", "stock_qty", "available_qty",
            "reorder_level", "reorder_qty", "max_stock_level",
            "default_supplier", "supplier_sku", "lead_time_days",
            "cost_price", "last_purchase_price"
        ]
    )

    # Filter to only those needing reorder
    reorder_suggestions = []
    for s in skus:
        if flt(s.stock_qty) <= flt(s.reorder_level):
            # Calculate suggested order quantity
            suggested_qty = flt(s.reorder_qty)
            if not suggested_qty:
                # Calculate based on max stock level
                if flt(s.max_stock_level) > 0:
                    suggested_qty = flt(s.max_stock_level) - flt(s.stock_qty)
                else:
                    suggested_qty = flt(s.reorder_level) * 2

            s["suggested_order_qty"] = suggested_qty
            s["estimated_cost"] = suggested_qty * flt(
                s.last_purchase_price or s.cost_price
            )
            reorder_suggestions.append(s)

    return reorder_suggestions
