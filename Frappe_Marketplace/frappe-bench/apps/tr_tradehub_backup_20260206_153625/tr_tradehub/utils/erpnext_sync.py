# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
ERPNext Synchronization Utilities

This module provides utilities for synchronizing TR-TradeHub marketplace
DocTypes with ERPNext equivalents:
- Listing -> Item
- Listing Variant -> Item Variant
- Marketplace Order -> Sales Order
- Seller Profile -> Supplier
- Organization -> Customer

All sync operations follow these principles:
1. Create on submit (marketplace -> ERPNext)
2. Update on save (bidirectional sync configurable)
3. Soft-link via reference fields (not hard dependencies)
4. Graceful handling when ERPNext is not installed
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, getdate


class ERPNextNotInstalled(Exception):
    """Raised when ERPNext is not installed but required."""
    pass


class ERPNextSyncError(Exception):
    """Raised when ERPNext synchronization fails."""
    pass


def is_erpnext_installed():
    """
    Check if ERPNext is installed on this site.

    Returns:
        bool: True if ERPNext is installed
    """
    try:
        return frappe.db.exists("DocType", "Item")
    except Exception:
        return False


def require_erpnext(func):
    """
    Decorator that ensures ERPNext is installed before executing.
    Logs a warning and returns None if ERPNext is not available.
    """
    def wrapper(*args, **kwargs):
        if not is_erpnext_installed():
            frappe.log_error(
                f"ERPNext not installed - skipping {func.__name__}",
                "ERPNext Sync Warning"
            )
            return None
        return func(*args, **kwargs)
    return wrapper


# =============================================================================
# Listing -> ERPNext Item Sync
# =============================================================================

@require_erpnext
def create_item_from_listing(listing_doc):
    """
    Create an ERPNext Item from a Listing document.

    This function is called when a Listing is submitted (docstatus = 1).
    It creates a corresponding Item in ERPNext for inventory management.

    Args:
        listing_doc: The Listing document (frappe.get_doc result)

    Returns:
        str: Name of the created Item, or None if creation failed

    Raises:
        ERPNextSyncError: If Item creation fails
    """
    if not listing_doc:
        raise ERPNextSyncError(_("Listing document is required"))

    listing_code = listing_doc.listing_code

    # Check if Item already exists with this listing code
    existing_item = frappe.db.get_value(
        "Item",
        {"item_code": listing_code},
        "name"
    )

    if existing_item:
        # Update the listing's reference if not set
        if listing_doc.erpnext_item != existing_item:
            listing_doc.db_set("erpnext_item", existing_item, update_modified=False)
        return existing_item

    # Prepare Item data
    item_data = _prepare_item_data_from_listing(listing_doc)

    try:
        item = frappe.get_doc(item_data)
        item.flags.ignore_permissions = True
        item.flags.ignore_mandatory = True  # Some ERPNext fields may be mandatory
        item.insert()

        # Update listing with Item reference
        listing_doc.db_set("erpnext_item", item.name, update_modified=False)

        # Log successful sync
        _log_sync_event(
            source_doctype="Listing",
            source_name=listing_doc.name,
            target_doctype="Item",
            target_name=item.name,
            action="created"
        )

        return item.name

    except frappe.exceptions.DuplicateEntryError:
        # Item was created by another process
        existing = frappe.db.get_value("Item", {"item_code": listing_code}, "name")
        if existing:
            listing_doc.db_set("erpnext_item", existing, update_modified=False)
            return existing
        raise

    except Exception as e:
        frappe.log_error(
            f"Failed to create ERPNext Item for Listing {listing_doc.name}: {str(e)}",
            "ERPNext Item Creation Error"
        )
        raise ERPNextSyncError(
            _("Failed to create ERPNext Item: {0}").format(str(e))
        )


def _prepare_item_data_from_listing(listing_doc):
    """
    Prepare ERPNext Item data dictionary from a Listing document.

    Args:
        listing_doc: The Listing document

    Returns:
        dict: Item document data
    """
    # Get ERPNext item group from category
    item_group = _get_item_group_from_category(listing_doc.category)

    # Build item data
    item_data = {
        "doctype": "Item",
        "item_code": listing_doc.listing_code,
        "item_name": _truncate_string(listing_doc.title, 140),
        "item_group": item_group,
        "stock_uom": listing_doc.stock_uom or "Nos",
        "is_stock_item": cint(listing_doc.track_inventory),
        "has_variants": cint(listing_doc.has_variants),
        "description": listing_doc.short_description or listing_doc.description or listing_doc.title,
        "brand": listing_doc.brand,
        "image": listing_doc.primary_image,
        "disabled": 0 if listing_doc.status == "Active" else 1,
    }

    # Add weight if specified
    if listing_doc.weight and flt(listing_doc.weight) > 0:
        item_data["weight_per_unit"] = flt(listing_doc.weight)
        if listing_doc.weight_uom:
            item_data["weight_uom"] = listing_doc.weight_uom

    # Add barcode if specified
    if listing_doc.barcode:
        item_data["barcodes"] = [{
            "barcode": listing_doc.barcode,
            "barcode_type": _detect_barcode_type(listing_doc.barcode)
        }]

    # Add custom fields for marketplace reference
    item_data["custom_marketplace_listing"] = listing_doc.name
    item_data["custom_seller"] = listing_doc.seller

    return item_data


def _get_item_group_from_category(category_name):
    """
    Get ERPNext Item Group from Category.

    Args:
        category_name: Name of the Category document

    Returns:
        str: Item Group name, defaults to "All Item Groups"
    """
    if not category_name:
        return "All Item Groups"

    item_group = frappe.db.get_value(
        "Category",
        category_name,
        "erpnext_item_group"
    )

    if item_group and frappe.db.exists("Item Group", item_group):
        return item_group

    return "All Item Groups"


@require_erpnext
def sync_item_from_listing(listing_doc):
    """
    Synchronize ERPNext Item with Listing changes.

    This function is called when a Listing is updated (on_update hook).
    It updates the corresponding ERPNext Item with the latest data.

    Args:
        listing_doc: The Listing document

    Returns:
        bool: True if sync successful, False otherwise
    """
    if not listing_doc.erpnext_item:
        return False

    if not frappe.db.exists("Item", listing_doc.erpnext_item):
        # Item was deleted, clear reference
        listing_doc.db_set("erpnext_item", None, update_modified=False)
        return False

    try:
        item = frappe.get_doc("Item", listing_doc.erpnext_item)

        # Update item fields
        item.item_name = _truncate_string(listing_doc.title, 140)
        item.description = listing_doc.short_description or listing_doc.description or listing_doc.title
        item.brand = listing_doc.brand
        item.image = listing_doc.primary_image
        item.is_stock_item = cint(listing_doc.track_inventory)
        item.has_variants = cint(listing_doc.has_variants)
        item.disabled = 0 if listing_doc.status == "Active" else 1

        # Update weight
        if listing_doc.weight and flt(listing_doc.weight) > 0:
            item.weight_per_unit = flt(listing_doc.weight)
            if listing_doc.weight_uom:
                item.weight_uom = listing_doc.weight_uom

        item.flags.ignore_permissions = True
        item.save()

        # Log successful sync
        _log_sync_event(
            source_doctype="Listing",
            source_name=listing_doc.name,
            target_doctype="Item",
            target_name=item.name,
            action="updated"
        )

        return True

    except frappe.DoesNotExistError:
        listing_doc.db_set("erpnext_item", None, update_modified=False)
        return False

    except Exception as e:
        frappe.log_error(
            f"Failed to sync ERPNext Item for Listing {listing_doc.name}: {str(e)}",
            "ERPNext Item Sync Error"
        )
        return False


@require_erpnext
def update_item_stock_from_listing(listing_doc, warehouse=None):
    """
    Update ERPNext Item stock quantity from Listing.

    Note: This creates a Stock Reconciliation entry to adjust stock.
    For actual inventory movements, use Stock Entry instead.

    Args:
        listing_doc: The Listing document
        warehouse: Target warehouse (optional, uses default)

    Returns:
        str: Name of Stock Reconciliation entry, or None
    """
    if not listing_doc.erpnext_item:
        return None

    if not listing_doc.track_inventory:
        return None

    # Get default warehouse if not specified
    if not warehouse:
        warehouse = _get_default_warehouse()

    if not warehouse:
        frappe.log_error(
            "No warehouse found for stock sync",
            "ERPNext Stock Sync Warning"
        )
        return None

    try:
        # Create Stock Reconciliation entry
        stock_recon = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "purpose": "Stock Reconciliation",
            "items": [{
                "item_code": listing_doc.erpnext_item,
                "warehouse": warehouse,
                "qty": flt(listing_doc.stock_qty),
                "valuation_rate": flt(listing_doc.cost_price) or flt(listing_doc.selling_price)
            }]
        })
        stock_recon.flags.ignore_permissions = True
        stock_recon.insert()
        stock_recon.submit()

        return stock_recon.name

    except Exception as e:
        frappe.log_error(
            f"Failed to sync stock for Listing {listing_doc.name}: {str(e)}",
            "ERPNext Stock Sync Error"
        )
        return None


# =============================================================================
# Listing Variant -> ERPNext Item Variant Sync
# =============================================================================

@require_erpnext
def create_item_variant_from_listing_variant(variant_doc, parent_item):
    """
    Create an ERPNext Item Variant from a Listing Variant document.

    Args:
        variant_doc: The Listing Variant document
        parent_item: Parent ERPNext Item name

    Returns:
        str: Name of the created Item Variant, or None
    """
    if not parent_item or not frappe.db.exists("Item", parent_item):
        return None

    variant_code = variant_doc.variant_code or f"{parent_item}-{variant_doc.name}"

    # Check if variant already exists
    existing = frappe.db.get_value("Item", {"item_code": variant_code}, "name")
    if existing:
        variant_doc.db_set("erpnext_item_variant", existing, update_modified=False)
        return existing

    try:
        # Build variant attributes from Listing Variant attributes
        attributes = _build_variant_attributes(variant_doc)

        variant_data = {
            "doctype": "Item",
            "item_code": variant_code,
            "item_name": variant_doc.title or f"{parent_item} - {variant_doc.name}",
            "variant_of": parent_item,
            "stock_uom": variant_doc.stock_uom or "Nos",
            "attributes": attributes,
            "image": variant_doc.image,
        }

        variant_item = frappe.get_doc(variant_data)
        variant_item.flags.ignore_permissions = True
        variant_item.insert()

        variant_doc.db_set("erpnext_item_variant", variant_item.name, update_modified=False)

        return variant_item.name

    except Exception as e:
        frappe.log_error(
            f"Failed to create Item Variant for Listing Variant {variant_doc.name}: {str(e)}",
            "ERPNext Variant Creation Error"
        )
        return None


def _build_variant_attributes(variant_doc):
    """
    Build ERPNext Item attributes from Listing Variant.

    Args:
        variant_doc: The Listing Variant document

    Returns:
        list: List of attribute dicts for ERPNext Item
    """
    attributes = []

    # Get attributes from child table
    if hasattr(variant_doc, 'attributes') and variant_doc.attributes:
        for attr in variant_doc.attributes:
            attributes.append({
                "attribute": attr.attribute,
                "attribute_value": attr.value
            })

    return attributes


# =============================================================================
# Seller Profile -> ERPNext Supplier Sync
# =============================================================================

@require_erpnext
def create_supplier_from_seller(seller_doc):
    """
    Create an ERPNext Supplier from a Seller Profile document.

    Args:
        seller_doc: The Seller Profile document

    Returns:
        str: Name of the created Supplier, or None
    """
    supplier_name = seller_doc.seller_name or seller_doc.name

    # Check if Supplier already exists
    existing = frappe.db.get_value(
        "Supplier",
        {"supplier_name": supplier_name},
        "name"
    )

    if existing:
        seller_doc.db_set("erpnext_supplier", existing, update_modified=False)
        return existing

    try:
        supplier_data = {
            "doctype": "Supplier",
            "supplier_name": supplier_name,
            "supplier_group": _get_default_supplier_group(),
            "supplier_type": "Company" if seller_doc.seller_type == "Business" else "Individual",
            "disabled": 0 if seller_doc.status == "Active" else 1,
        }

        # Add tax ID if available
        if seller_doc.tax_id:
            supplier_data["tax_id"] = seller_doc.tax_id

        # Add contact details
        if seller_doc.email:
            supplier_data["email_id"] = seller_doc.email
        if seller_doc.phone:
            supplier_data["mobile_no"] = seller_doc.phone

        supplier = frappe.get_doc(supplier_data)
        supplier.flags.ignore_permissions = True
        supplier.insert()

        seller_doc.db_set("erpnext_supplier", supplier.name, update_modified=False)

        _log_sync_event(
            source_doctype="Seller Profile",
            source_name=seller_doc.name,
            target_doctype="Supplier",
            target_name=supplier.name,
            action="created"
        )

        return supplier.name

    except Exception as e:
        frappe.log_error(
            f"Failed to create Supplier for Seller {seller_doc.name}: {str(e)}",
            "ERPNext Supplier Creation Error"
        )
        return None


@require_erpnext
def sync_supplier_from_seller(seller_doc):
    """
    Synchronize ERPNext Supplier with Seller Profile changes.

    Args:
        seller_doc: The Seller Profile document

    Returns:
        bool: True if sync successful, False otherwise
    """
    if not seller_doc.erpnext_supplier:
        return False

    if not frappe.db.exists("Supplier", seller_doc.erpnext_supplier):
        seller_doc.db_set("erpnext_supplier", None, update_modified=False)
        return False

    try:
        supplier = frappe.get_doc("Supplier", seller_doc.erpnext_supplier)

        supplier.supplier_name = seller_doc.seller_name or seller_doc.name
        supplier.disabled = 0 if seller_doc.status == "Active" else 1

        if seller_doc.tax_id:
            supplier.tax_id = seller_doc.tax_id
        if seller_doc.email:
            supplier.email_id = seller_doc.email
        if seller_doc.phone:
            supplier.mobile_no = seller_doc.phone

        supplier.flags.ignore_permissions = True
        supplier.save()

        return True

    except Exception as e:
        frappe.log_error(
            f"Failed to sync Supplier for Seller {seller_doc.name}: {str(e)}",
            "ERPNext Supplier Sync Error"
        )
        return False


# =============================================================================
# Organization -> ERPNext Customer Sync
# =============================================================================

@require_erpnext
def create_customer_from_organization(org_doc):
    """
    Create an ERPNext Customer from an Organization document.

    Args:
        org_doc: The Organization document

    Returns:
        str: Name of the created Customer, or None
    """
    customer_name = org_doc.company_name or org_doc.organization_name or org_doc.name

    # Check if Customer already exists
    existing = frappe.db.get_value(
        "Customer",
        {"customer_name": customer_name},
        "name"
    )

    if existing:
        org_doc.db_set("erpnext_customer", existing, update_modified=False)
        return existing

    try:
        customer_data = {
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_group": _get_default_customer_group(),
            "customer_type": "Company",
            "disabled": 0 if org_doc.status == "Active" else 1,
        }

        # Add tax ID if available
        if org_doc.vkn:
            customer_data["tax_id"] = org_doc.vkn

        customer = frappe.get_doc(customer_data)
        customer.flags.ignore_permissions = True
        customer.insert()

        org_doc.db_set("erpnext_customer", customer.name, update_modified=False)

        _log_sync_event(
            source_doctype="Organization",
            source_name=org_doc.name,
            target_doctype="Customer",
            target_name=customer.name,
            action="created"
        )

        return customer.name

    except Exception as e:
        frappe.log_error(
            f"Failed to create Customer for Organization {org_doc.name}: {str(e)}",
            "ERPNext Customer Creation Error"
        )
        return None


@require_erpnext
def sync_customer_from_organization(org_doc):
    """
    Synchronize ERPNext Customer with Organization changes.

    Args:
        org_doc: The Organization document

    Returns:
        bool: True if sync successful, False otherwise
    """
    if not org_doc.erpnext_customer:
        return False

    if not frappe.db.exists("Customer", org_doc.erpnext_customer):
        org_doc.db_set("erpnext_customer", None, update_modified=False)
        return False

    try:
        customer = frappe.get_doc("Customer", org_doc.erpnext_customer)

        customer.customer_name = org_doc.company_name or org_doc.organization_name or org_doc.name
        customer.disabled = 0 if org_doc.status == "Active" else 1

        if org_doc.vkn:
            customer.tax_id = org_doc.vkn

        customer.flags.ignore_permissions = True
        customer.save()

        return True

    except Exception as e:
        frappe.log_error(
            f"Failed to sync Customer for Organization {org_doc.name}: {str(e)}",
            "ERPNext Customer Sync Error"
        )
        return False


# =============================================================================
# Marketplace Order -> ERPNext Sales Order Sync
# =============================================================================

@require_erpnext
def create_sales_order_from_marketplace_order(order_doc):
    """
    Create an ERPNext Sales Order from a Marketplace Order document.

    This function is called when a Marketplace Order is submitted (docstatus = 1).
    It creates a corresponding Sales Order in ERPNext for order processing.

    Args:
        order_doc: The Marketplace Order document

    Returns:
        str: Name of the created Sales Order, or None

    Raises:
        ERPNextSyncError: If Sales Order creation fails
    """
    if order_doc.erpnext_sales_order:
        # Already synced
        return order_doc.erpnext_sales_order

    # Get or create customer
    customer = _get_or_create_customer_for_order(order_doc)
    if not customer:
        frappe.log_error(
            f"Cannot create Sales Order - no customer for buyer {order_doc.buyer}",
            "ERPNext Sales Order Error"
        )
        return None

    try:
        # Build items from order lines
        items = _build_sales_order_items(order_doc)
        if not items:
            frappe.log_error(
                f"Cannot create Sales Order - no valid items for order {order_doc.name}",
                "ERPNext Sales Order Error"
            )
            return None

        # Get default warehouse
        warehouse = _get_default_warehouse()

        # Calculate delivery date (default 7 days if not specified)
        from frappe.utils import add_days
        delivery_date = None
        if hasattr(order_doc, 'expected_delivery_date') and order_doc.expected_delivery_date:
            delivery_date = getdate(order_doc.expected_delivery_date)
        else:
            delivery_date = add_days(getdate(order_doc.order_date or order_doc.creation), 7)

        # Build Sales Order data
        sales_order_data = {
            "doctype": "Sales Order",
            "customer": customer,
            "order_type": "Sales",
            "transaction_date": getdate(order_doc.order_date or order_doc.creation),
            "delivery_date": delivery_date,
            "currency": order_doc.currency or "TRY",
            "conversion_rate": 1,
            "selling_price_list": "Standard Selling",
            "po_no": order_doc.order_id,
            "po_date": getdate(order_doc.order_date or order_doc.creation),
            "items": items,
            "taxes": [],
        }

        # Add shipping charges if applicable
        if flt(order_doc.shipping_amount) > 0:
            sales_order_data["taxes"].append({
                "charge_type": "Actual",
                "account_head": _get_shipping_account(),
                "description": "Shipping Charges",
                "tax_amount": flt(order_doc.shipping_amount)
            })

        # Create Sales Order
        sales_order = frappe.get_doc(sales_order_data)
        sales_order.flags.ignore_permissions = True
        sales_order.flags.ignore_mandatory = True
        sales_order.insert()

        # Store reference in Marketplace Order
        order_doc.db_set("erpnext_sales_order", sales_order.name, update_modified=False)
        order_doc.db_set("erpnext_customer", customer, update_modified=False)

        # Update item references in Marketplace Order items
        if hasattr(order_doc, 'items') and order_doc.items:
            for i, item in enumerate(order_doc.items):
                if i < len(sales_order.items):
                    item.db_set("sales_order_item", sales_order.items[i].name, update_modified=False)
                    item.db_set("erpnext_item", sales_order.items[i].item_code, update_modified=False)

        # Log successful sync
        _log_sync_event(
            source_doctype="Marketplace Order",
            source_name=order_doc.name,
            target_doctype="Sales Order",
            target_name=sales_order.name,
            action="created"
        )

        frappe.msgprint(
            frappe._("ERPNext Sales Order {0} created").format(sales_order.name),
            indicator="green",
            alert=True
        )

        return sales_order.name

    except frappe.exceptions.DuplicateEntryError:
        # Sales Order was created by another process
        existing = frappe.db.get_value(
            "Sales Order",
            {"po_no": order_doc.order_id},
            "name"
        )
        if existing:
            order_doc.db_set("erpnext_sales_order", existing, update_modified=False)
            return existing
        raise

    except Exception as e:
        frappe.log_error(
            f"Failed to create Sales Order for Marketplace Order {order_doc.name}: {str(e)}",
            "ERPNext Sales Order Creation Error"
        )
        raise ERPNextSyncError(
            frappe._("Failed to create ERPNext Sales Order: {0}").format(str(e))
        )


@require_erpnext
def sync_sales_order_from_marketplace_order(order_doc):
    """
    Synchronize ERPNext Sales Order with Marketplace Order changes.

    This function is called when a Marketplace Order is updated (on_update hook).
    It updates the corresponding ERPNext Sales Order with the latest data.

    Args:
        order_doc: The Marketplace Order document

    Returns:
        bool: True if sync successful, False otherwise
    """
    if not order_doc.erpnext_sales_order:
        return False

    if not frappe.db.exists("Sales Order", order_doc.erpnext_sales_order):
        # Sales Order was deleted, clear reference
        order_doc.db_set("erpnext_sales_order", None, update_modified=False)
        return False

    try:
        so = frappe.get_doc("Sales Order", order_doc.erpnext_sales_order)

        # Only update if SO is in draft or submitted (not cancelled)
        if so.docstatus == 2:
            return False

        # Update basic fields
        so.transaction_date = getdate(order_doc.order_date or order_doc.creation)
        so.po_no = order_doc.order_id

        # Update delivery date if changed
        if hasattr(order_doc, 'expected_delivery_date') and order_doc.expected_delivery_date:
            so.delivery_date = getdate(order_doc.expected_delivery_date)

        so.flags.ignore_permissions = True
        so.save()

        # Log successful sync
        _log_sync_event(
            source_doctype="Marketplace Order",
            source_name=order_doc.name,
            target_doctype="Sales Order",
            target_name=so.name,
            action="updated"
        )

        return True

    except frappe.DoesNotExistError:
        order_doc.db_set("erpnext_sales_order", None, update_modified=False)
        return False

    except Exception as e:
        frappe.log_error(
            f"Failed to sync Sales Order for Marketplace Order {order_doc.name}: {str(e)}",
            "ERPNext Sales Order Sync Error"
        )
        return False


@require_erpnext
def cancel_sales_order_for_marketplace_order(order_doc):
    """
    Cancel the ERPNext Sales Order linked to a Marketplace Order.

    This function is called when a Marketplace Order is cancelled.

    Args:
        order_doc: The Marketplace Order document

    Returns:
        bool: True if cancellation successful, False otherwise
    """
    if not order_doc.erpnext_sales_order:
        return True  # No Sales Order to cancel

    if not frappe.db.exists("Sales Order", order_doc.erpnext_sales_order):
        order_doc.db_set("erpnext_sales_order", None, update_modified=False)
        return True

    try:
        so = frappe.get_doc("Sales Order", order_doc.erpnext_sales_order)

        if so.docstatus == 1:
            # Only cancel if submitted
            so.flags.ignore_permissions = True
            so.cancel()

            # Log successful cancellation
            _log_sync_event(
                source_doctype="Marketplace Order",
                source_name=order_doc.name,
                target_doctype="Sales Order",
                target_name=so.name,
                action="cancelled"
            )

        return True

    except Exception as e:
        frappe.log_error(
            f"Failed to cancel Sales Order for Marketplace Order {order_doc.name}: {str(e)}",
            "ERPNext Sales Order Cancel Error"
        )
        return False


@require_erpnext
def submit_sales_order_for_marketplace_order(order_doc):
    """
    Submit the ERPNext Sales Order linked to a Marketplace Order.

    This function can be called when a Marketplace Order is confirmed.

    Args:
        order_doc: The Marketplace Order document

    Returns:
        bool: True if submission successful, False otherwise
    """
    if not order_doc.erpnext_sales_order:
        return False

    if not frappe.db.exists("Sales Order", order_doc.erpnext_sales_order):
        return False

    try:
        so = frappe.get_doc("Sales Order", order_doc.erpnext_sales_order)

        if so.docstatus == 0:
            # Only submit if in draft
            so.flags.ignore_permissions = True
            so.submit()

            # Log successful submission
            _log_sync_event(
                source_doctype="Marketplace Order",
                source_name=order_doc.name,
                target_doctype="Sales Order",
                target_name=so.name,
                action="submitted"
            )

        return True

    except Exception as e:
        frappe.log_error(
            f"Failed to submit Sales Order for Marketplace Order {order_doc.name}: {str(e)}",
            "ERPNext Sales Order Submit Error"
        )
        return False


def _build_sales_order_items(order_doc):
    """
    Build ERPNext Sales Order items from Marketplace Order.

    Args:
        order_doc: The Marketplace Order document

    Returns:
        list: List of item dicts for Sales Order
    """
    items = []
    warehouse = _get_default_warehouse()

    # Calculate default delivery date
    from frappe.utils import add_days
    delivery_date = None
    if hasattr(order_doc, 'expected_delivery_date') and order_doc.expected_delivery_date:
        delivery_date = getdate(order_doc.expected_delivery_date)
    else:
        delivery_date = add_days(getdate(order_doc.order_date or order_doc.creation), 7)

    # Get order items from child table
    if hasattr(order_doc, 'items') and order_doc.items:
        for line in order_doc.items:
            # Get ERPNext Item code from Listing
            item_code = None
            listing_code = None

            if line.listing:
                item_code = frappe.db.get_value("Listing", line.listing, "erpnext_item")
                listing_code = frappe.db.get_value("Listing", line.listing, "listing_code")

            # Use listing_code as item_code if no ERPNext item exists
            if not item_code:
                item_code = listing_code or line.listing

            # Skip if still no valid item code
            if not item_code:
                continue

            # Verify item exists in ERPNext
            if not frappe.db.exists("Item", item_code):
                # Try to create item from listing if possible
                if line.listing:
                    try:
                        listing_doc = frappe.get_doc("Listing", line.listing)
                        item_code = create_item_from_listing(listing_doc)
                    except Exception:
                        pass

                if not item_code or not frappe.db.exists("Item", item_code):
                    frappe.log_error(
                        f"Item {item_code} not found for order item {line.name}",
                        "ERPNext Sales Order Item Warning"
                    )
                    continue

            # Get rate from order item
            rate = flt(line.unit_price) or flt(line.rate) or flt(line.selling_price)

            items.append({
                "item_code": item_code,
                "item_name": line.title or frappe.db.get_value("Item", item_code, "item_name"),
                "qty": flt(line.qty),
                "uom": line.stock_uom or "Nos",
                "rate": rate,
                "amount": flt(line.line_subtotal) or (flt(line.qty) * rate),
                "warehouse": warehouse,
                "delivery_date": delivery_date,
            })

    return items


def _get_or_create_customer_for_order(order_doc):
    """
    Get or create ERPNext Customer for a Marketplace Order.

    This considers both individual buyers and organization orders.

    Args:
        order_doc: The Marketplace Order document

    Returns:
        str: Customer name, or None
    """
    # Check if customer already exists for this order
    if hasattr(order_doc, 'erpnext_customer') and order_doc.erpnext_customer:
        if frappe.db.exists("Customer", order_doc.erpnext_customer):
            return order_doc.erpnext_customer

    # For organization orders, check organization's customer
    buyer_type = getattr(order_doc, 'buyer_type', 'Individual')
    if buyer_type == "Organization" and hasattr(order_doc, 'organization') and order_doc.organization:
        org_customer = frappe.db.get_value(
            "Organization", order_doc.organization, "erpnext_customer"
        )
        if org_customer and frappe.db.exists("Customer", org_customer):
            return org_customer

    # Check by email
    buyer_email = getattr(order_doc, 'buyer_email', None) or order_doc.buyer
    if buyer_email:
        existing = frappe.db.get_value("Customer", {"email_id": buyer_email}, "name")
        if existing:
            return existing

    # Create new customer
    try:
        customer_type = "Company" if buyer_type == "Organization" else "Individual"

        # Determine customer name
        customer_name = (
            getattr(order_doc, 'buyer_company_name', None) or
            getattr(order_doc, 'buyer_name', None) or
            frappe.db.get_value("User", order_doc.buyer, "full_name") or
            order_doc.buyer
        )

        customer_data = {
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": customer_type,
            "customer_group": _get_default_customer_group(),
            "territory": "Turkey",
        }

        # Add email if available
        if buyer_email:
            customer_data["email_id"] = buyer_email

        # Add phone if available
        buyer_phone = getattr(order_doc, 'buyer_phone', None)
        if buyer_phone:
            customer_data["mobile_no"] = buyer_phone

        # Add tax ID if available
        buyer_tax_id = getattr(order_doc, 'buyer_tax_id', None)
        if buyer_tax_id:
            customer_data["tax_id"] = buyer_tax_id

        customer = frappe.get_doc(customer_data)
        customer.flags.ignore_permissions = True
        customer.insert()

        return customer.name

    except frappe.exceptions.DuplicateEntryError:
        # Customer was created by another process
        if buyer_email:
            existing = frappe.db.get_value("Customer", {"email_id": buyer_email}, "name")
            if existing:
                return existing
        return None

    except Exception as e:
        frappe.log_error(
            f"Failed to create Customer for order {order_doc.name}: {str(e)}",
            "ERPNext Customer Creation Error"
        )
        return None


def _get_or_create_customer_for_buyer(buyer):
    """
    Get or create ERPNext Customer for a marketplace buyer.

    Args:
        buyer: User email or buyer identifier

    Returns:
        str: Customer name, or None
    """
    if not buyer:
        return None

    # Check if customer already exists
    existing = frappe.db.get_value("Customer", {"email_id": buyer}, "name")
    if existing:
        return existing

    # Try to get from User
    user_name = frappe.db.get_value("User", buyer, "full_name")
    customer_name = user_name or buyer

    try:
        customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_group": _get_default_customer_group(),
            "customer_type": "Individual",
            "email_id": buyer,
            "territory": "Turkey",
        })
        customer.flags.ignore_permissions = True
        customer.insert()
        return customer.name

    except frappe.exceptions.DuplicateEntryError:
        # Customer was created by another process
        existing = frappe.db.get_value("Customer", {"email_id": buyer}, "name")
        if existing:
            return existing
        return None

    except Exception as e:
        frappe.log_error(
            f"Failed to create Customer for buyer {buyer}: {str(e)}",
            "ERPNext Customer Creation Error"
        )
        return None


def _get_shipping_account():
    """Get the shipping charges account for Sales Order taxes."""
    # Try to get from settings
    shipping_account = frappe.db.get_single_value(
        "Selling Settings", "default_shipping_account"
    )
    if shipping_account:
        return shipping_account

    # Find a suitable expense account
    accounts = frappe.get_all(
        "Account",
        filters={
            "account_type": "Expense Account",
            "is_group": 0,
            "disabled": 0
        },
        fields=["name"],
        limit=1
    )

    if accounts:
        return accounts[0].name

    # Fallback - get any expense account
    return frappe.db.get_value(
        "Account",
        {"root_type": "Expense", "is_group": 0},
        "name"
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _get_default_warehouse():
    """Get default warehouse for inventory operations."""
    # Try to get from settings
    default = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    if default:
        return default

    # Get first active warehouse
    warehouse = frappe.db.get_value(
        "Warehouse",
        {"disabled": 0, "is_group": 0},
        "name",
        order_by="creation"
    )
    return warehouse


def _get_default_supplier_group():
    """Get default supplier group."""
    return frappe.db.get_single_value("Buying Settings", "supplier_group") or "All Supplier Groups"


def _get_default_customer_group():
    """Get default customer group."""
    return frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"


def _truncate_string(s, max_length):
    """Truncate string to max length."""
    if not s:
        return s
    if len(s) <= max_length:
        return s
    return s[:max_length - 3] + "..."


def _detect_barcode_type(barcode):
    """Detect barcode type from barcode value."""
    if not barcode:
        return None

    barcode = barcode.strip()
    length = len(barcode)

    if length == 13:
        return "EAN"
    elif length == 12:
        return "UPC-A"
    elif length == 8:
        return "EAN-8"
    elif length == 14:
        return "GTIN"
    else:
        return "CODE-128"


def _log_sync_event(source_doctype, source_name, target_doctype, target_name, action):
    """
    Log an ERPNext sync event for auditing.

    Args:
        source_doctype: Source DocType name (e.g., "Listing")
        source_name: Source document name
        target_doctype: Target DocType name (e.g., "Item")
        target_name: Target document name
        action: Action performed (created/updated/deleted)
    """
    try:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": source_doctype,
            "reference_name": source_name,
            "content": f"ERPNext Sync: {target_doctype} '{target_name}' {action}"
        }).insert(ignore_permissions=True)
    except Exception:
        # Non-critical, don't fail on logging errors
        pass


# =============================================================================
# Bulk Sync Functions
# =============================================================================

@require_erpnext
def bulk_sync_listings_to_items(filters=None, limit=100):
    """
    Bulk synchronize Listings to ERPNext Items.

    Args:
        filters: Optional filters for Listing query
        limit: Maximum number of records to process

    Returns:
        dict: Sync results summary
    """
    if filters is None:
        filters = {}

    # Get submitted listings without ERPNext Item
    filters["docstatus"] = 1
    filters["erpnext_item"] = ["is", "not set"]

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=["name"],
        limit_page_length=limit
    )

    results = {
        "total": len(listings),
        "success": 0,
        "failed": 0,
        "errors": []
    }

    for listing_data in listings:
        try:
            listing = frappe.get_doc("Listing", listing_data.name)
            item_name = create_item_from_listing(listing)
            if item_name:
                results["success"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "listing": listing_data.name,
                "error": str(e)
            })

    return results


@require_erpnext
def bulk_sync_sellers_to_suppliers(filters=None, limit=100):
    """
    Bulk synchronize Seller Profiles to ERPNext Suppliers.

    Args:
        filters: Optional filters for Seller Profile query
        limit: Maximum number of records to process

    Returns:
        dict: Sync results summary
    """
    if filters is None:
        filters = {}

    # Get active sellers without ERPNext Supplier
    filters["status"] = "Active"
    filters["erpnext_supplier"] = ["is", "not set"]

    sellers = frappe.get_all(
        "Seller Profile",
        filters=filters,
        fields=["name"],
        limit_page_length=limit
    )

    results = {
        "total": len(sellers),
        "success": 0,
        "failed": 0,
        "errors": []
    }

    for seller_data in sellers:
        try:
            seller = frappe.get_doc("Seller Profile", seller_data.name)
            supplier_name = create_supplier_from_seller(seller)
            if supplier_name:
                results["success"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "seller": seller_data.name,
                "error": str(e)
            })

    return results


@require_erpnext
def bulk_sync_marketplace_orders_to_sales_orders(filters=None, limit=100):
    """
    Bulk synchronize Marketplace Orders to ERPNext Sales Orders.

    Args:
        filters: Optional filters for Marketplace Order query
        limit: Maximum number of records to process

    Returns:
        dict: Sync results summary
    """
    if filters is None:
        filters = {}

    # Get submitted orders without ERPNext Sales Order
    filters["docstatus"] = 1
    filters["erpnext_sales_order"] = ["is", "not set"]

    orders = frappe.get_all(
        "Marketplace Order",
        filters=filters,
        fields=["name"],
        limit_page_length=limit,
        order_by="creation DESC"
    )

    results = {
        "total": len(orders),
        "success": 0,
        "failed": 0,
        "errors": []
    }

    for order_data in orders:
        try:
            order = frappe.get_doc("Marketplace Order", order_data.name)
            so_name = create_sales_order_from_marketplace_order(order)
            if so_name:
                results["success"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "order": order_data.name,
                "error": str(e)
            })

    return results


# =============================================================================
# API Endpoints
# =============================================================================

@frappe.whitelist()
def sync_listing_to_erpnext(listing_name):
    """
    API endpoint to manually trigger Listing -> Item sync.

    Args:
        listing_name: Name of the Listing document

    Returns:
        dict: Sync result
    """
    if not frappe.has_permission("Listing", "write"):
        frappe.throw(_("Not permitted to sync listings"))

    listing = frappe.get_doc("Listing", listing_name)

    if listing.erpnext_item:
        # Update existing
        success = sync_item_from_listing(listing)
        return {
            "status": "success" if success else "failed",
            "action": "updated",
            "item": listing.erpnext_item
        }
    else:
        # Create new
        item_name = create_item_from_listing(listing)
        return {
            "status": "success" if item_name else "failed",
            "action": "created",
            "item": item_name
        }


@frappe.whitelist()
def sync_marketplace_order_to_erpnext(order_name):
    """
    API endpoint to manually trigger Marketplace Order -> Sales Order sync.

    Args:
        order_name: Name of the Marketplace Order document

    Returns:
        dict: Sync result
    """
    if not frappe.has_permission("Marketplace Order", "write"):
        frappe.throw(_("Not permitted to sync marketplace orders"))

    order = frappe.get_doc("Marketplace Order", order_name)

    if order.erpnext_sales_order:
        # Update existing
        success = sync_sales_order_from_marketplace_order(order)
        return {
            "status": "success" if success else "failed",
            "action": "updated",
            "sales_order": order.erpnext_sales_order
        }
    else:
        # Create new
        so_name = create_sales_order_from_marketplace_order(order)
        return {
            "status": "success" if so_name else "failed",
            "action": "created",
            "sales_order": so_name
        }


@frappe.whitelist()
def get_erpnext_sync_status():
    """
    Get ERPNext sync status for the platform.

    Returns:
        dict: Sync status summary
    """
    status = {
        "erpnext_installed": is_erpnext_installed(),
        "listings_total": 0,
        "listings_synced": 0,
        "sellers_total": 0,
        "sellers_synced": 0,
        "organizations_total": 0,
        "organizations_synced": 0,
        "marketplace_orders_total": 0,
        "marketplace_orders_synced": 0,
    }

    # Count Listings
    status["listings_total"] = frappe.db.count("Listing", {"docstatus": 1})
    status["listings_synced"] = frappe.db.count(
        "Listing",
        {"docstatus": 1, "erpnext_item": ["is", "set"]}
    )

    # Count Sellers
    status["sellers_total"] = frappe.db.count("Seller Profile", {"status": "Active"})
    status["sellers_synced"] = frappe.db.count(
        "Seller Profile",
        {"status": "Active", "erpnext_supplier": ["is", "set"]}
    )

    # Count Organizations
    if frappe.db.exists("DocType", "Organization"):
        status["organizations_total"] = frappe.db.count("Organization", {"status": "Active"})
        status["organizations_synced"] = frappe.db.count(
            "Organization",
            {"status": "Active", "erpnext_customer": ["is", "set"]}
        )

    # Count Marketplace Orders
    if frappe.db.exists("DocType", "Marketplace Order"):
        status["marketplace_orders_total"] = frappe.db.count(
            "Marketplace Order", {"docstatus": 1}
        )
        status["marketplace_orders_synced"] = frappe.db.count(
            "Marketplace Order",
            {"docstatus": 1, "erpnext_sales_order": ["is", "set"]}
        )

    return status


@frappe.whitelist()
def run_bulk_sync(sync_type, limit=100):
    """
    API endpoint to run bulk sync operations.

    Args:
        sync_type: Type of sync (listings, sellers, organizations, marketplace_orders)
        limit: Maximum records to process

    Returns:
        dict: Sync results
    """
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can run bulk sync"))

    if sync_type == "listings":
        return bulk_sync_listings_to_items(limit=cint(limit))
    elif sync_type == "marketplace_orders":
        return bulk_sync_marketplace_orders_to_sales_orders(limit=cint(limit))
    elif sync_type == "sellers":
        return bulk_sync_sellers_to_suppliers(limit=cint(limit))
    else:
        frappe.throw(_("Invalid sync type: {0}").format(sync_type))
