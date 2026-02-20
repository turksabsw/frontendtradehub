# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
PIM to ERPNext Item Sync Module

Provides functionality to synchronize PIM Products with ERPNext Items.
Creates or updates ERPNext Items based on PIM Product data.

Key Features:
    - Create ERPNext Item from PIM Product
    - Update existing ERPNext Item when PIM Product changes
    - Sync product variants to ERPNext Item Variants
    - Map PIM attributes to Item custom fields
    - Track sync status with timestamps

Example:
    >>> from tr_tradehub.pim.erpnext_sync import sync_product_to_item
    >>> result = sync_product_to_item("PROD-001")
    >>> print(result['item_code'])  # Created/updated ERPNext Item code
"""

import json
from typing import Any, Dict, List, Optional, Tuple, Union

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, cstr


class ERPNextSyncer:
    """
    Synchronizes PIM Products with ERPNext Items.

    The syncer:
    1. Maps PIM Product fields to ERPNext Item fields
    2. Creates or updates ERPNext Item
    3. Handles variant sync if applicable
    4. Tracks sync status on the PIM Product

    Attributes:
        product: The PIM Product document to sync
        item: The ERPNext Item document (existing or new)
        product_class: The Product Class for sync configuration
        is_new_item: Whether creating a new Item or updating existing
    """

    # Default field mapping from PIM Product to ERPNext Item
    FIELD_MAPPING = {
        # PIM Product field -> ERPNext Item field
        'product_name': 'item_name',
        'product_code': 'item_code',
        'short_description': 'description',
        'brand': 'brand',
        'country_of_origin': 'country_of_origin',
        'weight': 'weight_per_unit',
        'base_price': 'standard_rate',
        'main_image': 'image',
        'barcode': 'barcodes',  # Special handling for child table
        'hscode': 'customs_tariff_number',
    }

    # Fields that require special handling
    SPECIAL_FIELDS = ['barcode', 'gtin', 'ean', 'upc']

    def __init__(self, product: Union[str, Any]):
        """
        Initialize syncer for a PIM Product.

        Args:
            product: PIM Product document or product name/code
        """
        # Load product
        if isinstance(product, str):
            self.product = frappe.get_doc("PIM Product", product)
        else:
            self.product = product

        self.item = None
        self.product_class = None
        self.is_new_item = True
        self.sync_config = {}
        self.errors = []
        self.warnings = []

        # Load product class for sync configuration
        if self.product.product_class:
            try:
                self.product_class = frappe.get_doc("Product Class", self.product.product_class)
                self._load_sync_config()
            except frappe.DoesNotExistError:
                pass

    def _load_sync_config(self):
        """Load sync configuration from Product Class."""
        if not self.product_class:
            return

        self.sync_config = {
            'sync_enabled': getattr(self.product_class, 'sync_to_erpnext', False),
            'item_group': getattr(self.product_class, 'erpnext_item_group', None),
            'auto_create': getattr(self.product_class, 'auto_create_item', False),
        }

    def can_sync(self) -> Tuple[bool, str]:
        """
        Check if sync is possible for this product.

        Returns:
            Tuple of (can_sync: bool, reason: str)
        """
        if not self.product:
            return False, _("Product not found")

        # Check if ERPNext Item DocType exists
        if not frappe.db.exists("DocType", "Item"):
            return False, _("ERPNext Item DocType not found. Is ERPNext installed?")

        # Check if product has minimum required data
        if not self.product.product_name:
            return False, _("Product name is required for sync")

        # Check if product is in a syncable status
        if hasattr(self.product, 'status') and self.product.status in ['Draft', 'Archived']:
            return False, _("Product status '{0}' is not syncable").format(self.product.status)

        return True, ""

    def get_item_code(self) -> str:
        """
        Determine the ERPNext Item code to use.

        Priority:
        1. Existing linked item code (erpnext_item_code)
        2. Product SKU
        3. Product code
        4. Product name (sanitized)

        Returns:
            str: The item code to use
        """
        # Use existing linked item
        if self.product.erpnext_item_code:
            return self.product.erpnext_item_code

        # Use SKU if available
        if self.product.sku:
            return self.product.sku

        # Use product_code
        if self.product.product_code:
            return self.product.product_code

        # Fallback to sanitized product name
        return frappe.scrub(self.product.product_name)[:140]

    def _check_existing_item(self) -> bool:
        """
        Check if an ERPNext Item already exists for this product.

        Sets self.item if found and returns True.
        """
        item_code = self.get_item_code()

        # First check by linked item code
        if self.product.erpnext_item_code:
            if frappe.db.exists("Item", self.product.erpnext_item_code):
                self.item = frappe.get_doc("Item", self.product.erpnext_item_code)
                self.is_new_item = False
                return True

        # Then check by computed item code
        if frappe.db.exists("Item", item_code):
            self.item = frappe.get_doc("Item", item_code)
            self.is_new_item = False
            return True

        # Check by product_code or SKU in custom field if exists
        if self.product.product_code:
            existing = frappe.db.get_value(
                "Item",
                {"pim_product_code": self.product.product_code},
                "name"
            )
            if existing:
                self.item = frappe.get_doc("Item", existing)
                self.is_new_item = False
                return True

        return False

    def _prepare_item_data(self) -> Dict:
        """
        Prepare ERPNext Item data from PIM Product.

        Returns:
            dict: Item field values
        """
        item_code = self.get_item_code()

        # Basic Item data
        data = {
            'doctype': 'Item',
            'item_code': item_code,
            'item_name': self.product.product_name,
            'item_group': self._get_item_group(),
            'stock_uom': self._get_stock_uom(),
            'is_stock_item': 1,
            'include_item_in_manufacturing': 0,
        }

        # Map standard fields
        if self.product.short_description:
            data['description'] = self.product.short_description

        if self.product.brand:
            data['brand'] = self.product.brand

        if self.product.country_of_origin:
            data['country_of_origin'] = self.product.country_of_origin

        if self.product.hscode:
            data['customs_tariff_number'] = self.product.hscode

        if self.product.main_image:
            data['image'] = self.product.main_image

        # Weight and dimensions
        if self.product.weight:
            data['weight_per_unit'] = flt(self.product.weight)

        # Standard rate (base price)
        if self.product.base_price:
            data['standard_rate'] = flt(self.product.base_price)

        # Valuation rate (cost price)
        if self.product.cost_price:
            data['valuation_rate'] = flt(self.product.cost_price)

        # Product identifiers for tracking
        data['pim_product_code'] = self.product.product_code
        data['pim_product_name'] = self.product.name

        return data

    def _get_item_group(self) -> str:
        """
        Determine the ERPNext Item Group.

        Priority:
        1. Product Class setting
        2. Primary category mapping
        3. Default 'Products'

        Returns:
            str: Item Group name
        """
        # From Product Class config
        if self.sync_config.get('item_group'):
            item_group = self.sync_config['item_group']
            if frappe.db.exists("Item Group", item_group):
                return item_group

        # From primary category
        if self.product.primary_category:
            # Try to find matching Item Group
            category_name = self.product.primary_category
            if frappe.db.exists("Item Group", category_name):
                return category_name

        # Default fallback - use 'Products' or 'All Item Groups'
        if frappe.db.exists("Item Group", "Products"):
            return "Products"

        # Fallback to first available item group
        first_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
        return first_group or "All Item Groups"

    def _get_stock_uom(self) -> str:
        """
        Determine the stock UOM.

        Returns:
            str: Stock UOM name
        """
        # Check if product has weight_uom or similar
        if hasattr(self.product, 'weight_uom') and self.product.weight_uom:
            if frappe.db.exists("UOM", self.product.weight_uom):
                return self.product.weight_uom

        # Default to 'Nos' or 'Unit'
        if frappe.db.exists("UOM", "Nos"):
            return "Nos"
        if frappe.db.exists("UOM", "Unit"):
            return "Unit"

        # Fallback to first available UOM
        first_uom = frappe.db.get_value("UOM", {}, "name")
        return first_uom or "Nos"

    def _prepare_barcodes(self) -> List[Dict]:
        """
        Prepare barcode child table entries.

        Returns:
            list: Barcode entries for Item Barcode child table
        """
        barcodes = []

        # Add barcode
        if self.product.barcode:
            barcodes.append({
                'barcode': self.product.barcode,
                'barcode_type': 'CODE-128'
            })

        # Add GTIN (EAN-13 or EAN-8)
        if self.product.gtin:
            gtin = cstr(self.product.gtin).replace(" ", "").replace("-", "")
            barcode_type = 'EAN-13' if len(gtin) >= 12 else 'EAN-8'
            barcodes.append({
                'barcode': gtin,
                'barcode_type': barcode_type
            })

        # Add EAN
        if self.product.ean and self.product.ean != self.product.gtin:
            barcodes.append({
                'barcode': self.product.ean,
                'barcode_type': 'EAN-13'
            })

        # Add UPC
        if self.product.upc:
            barcodes.append({
                'barcode': self.product.upc,
                'barcode_type': 'UPC-A'
            })

        return barcodes

    def _sync_barcodes(self, item: Any, barcodes: List[Dict]):
        """
        Sync barcodes to Item's barcodes child table.

        Args:
            item: The ERPNext Item document
            barcodes: List of barcode dicts
        """
        if not barcodes:
            return

        # Check if Item has barcodes child table
        if not hasattr(item, 'barcodes'):
            return

        # Get existing barcodes
        existing_barcodes = {b.barcode: b for b in item.barcodes}

        for barcode_data in barcodes:
            barcode = barcode_data['barcode']
            if barcode not in existing_barcodes:
                item.append('barcodes', barcode_data)

    def _map_attributes_to_item(self, item: Any):
        """
        Map PIM attributes to ERPNext Item custom fields.

        This maps attribute values to corresponding Item fields
        if custom fields exist with matching names.

        Args:
            item: The ERPNext Item document
        """
        if not self.product.attribute_values:
            return

        # Get Item meta to check for custom fields
        item_meta = frappe.get_meta("Item")

        for attr_val in self.product.attribute_values:
            attr_code = attr_val.attribute_code

            # Check if Item has a field with this name
            if item_meta.has_field(attr_code):
                value = self.product.get_attribute_value(attr_code)
                if value is not None:
                    try:
                        setattr(item, attr_code, value)
                    except Exception:
                        pass  # Skip if field type doesn't match

    def sync(self, create_if_missing: bool = True, update_existing: bool = True) -> Dict:
        """
        Perform the sync operation.

        Args:
            create_if_missing: Create new Item if not found
            update_existing: Update existing Item if found

        Returns:
            dict: Sync result with status and details
        """
        result = {
            'success': False,
            'action': None,
            'item_code': None,
            'item_name': None,
            'errors': [],
            'warnings': [],
            'synced_at': None
        }

        # Check if sync is possible
        can_sync, reason = self.can_sync()
        if not can_sync:
            result['errors'].append(reason)
            return result

        try:
            # Check for existing Item
            exists = self._check_existing_item()

            if exists and not update_existing:
                result['action'] = 'skipped'
                result['item_code'] = self.item.item_code
                result['warnings'].append(_("Item exists but update_existing is False"))
                return result

            if not exists and not create_if_missing:
                result['action'] = 'skipped'
                result['warnings'].append(_("Item not found and create_if_missing is False"))
                return result

            # Prepare Item data
            item_data = self._prepare_item_data()

            if exists:
                # Update existing Item
                result['action'] = 'updated'
                self._update_item(item_data)
            else:
                # Create new Item
                result['action'] = 'created'
                self._create_item(item_data)

            result['success'] = True
            result['item_code'] = self.item.item_code
            result['item_name'] = self.item.item_name
            result['synced_at'] = str(now_datetime())
            result['errors'] = self.errors
            result['warnings'] = self.warnings

            # Update PIM Product with sync info
            self._update_product_sync_status()

        except Exception as e:
            result['success'] = False
            result['errors'].append(str(e))
            frappe.log_error(
                title=f"ERPNext Sync Error: {self.product.name}",
                message=frappe.get_traceback()
            )

        return result

    def _create_item(self, item_data: Dict):
        """
        Create a new ERPNext Item.

        Args:
            item_data: Item field values
        """
        self.item = frappe.new_doc("Item")

        for field, value in item_data.items():
            if field != 'doctype' and hasattr(self.item, field):
                setattr(self.item, field, value)

        # Add barcodes
        barcodes = self._prepare_barcodes()
        self._sync_barcodes(self.item, barcodes)

        # Map attributes
        self._map_attributes_to_item(self.item)

        # Save with ignore_permissions if configured
        self.item.insert(ignore_permissions=True)
        self.is_new_item = True

    def _update_item(self, item_data: Dict):
        """
        Update an existing ERPNext Item.

        Args:
            item_data: Item field values
        """
        # Don't update item_code on existing item
        item_data.pop('item_code', None)

        for field, value in item_data.items():
            if field not in ['doctype', 'item_code'] and hasattr(self.item, field):
                setattr(self.item, field, value)

        # Update barcodes
        barcodes = self._prepare_barcodes()
        self._sync_barcodes(self.item, barcodes)

        # Map attributes
        self._map_attributes_to_item(self.item)

        # Save
        self.item.save(ignore_permissions=True)
        self.is_new_item = False

    def _update_product_sync_status(self):
        """Update the PIM Product with sync status."""
        try:
            frappe.db.set_value(
                "PIM Product",
                self.product.name,
                {
                    'erpnext_item_code': self.item.item_code,
                    'erpnext_last_sync': now_datetime()
                },
                update_modified=False
            )
        except Exception as e:
            self.warnings.append(f"Failed to update sync status: {str(e)}")


def sync_product_to_item(
    product: Union[str, Any],
    create_if_missing: bool = True,
    update_existing: bool = True
) -> Dict:
    """
    Sync a PIM Product to ERPNext Item.

    This is the main entry point for ERPNext sync.

    Args:
        product: PIM Product document, name, or product_code
        create_if_missing: Create new Item if not found
        update_existing: Update existing Item if found

    Returns:
        dict: Sync result with status and details

    Example:
        >>> result = sync_product_to_item("PROD-001")
        >>> if result['success']:
        ...     print(f"Synced to Item: {result['item_code']}")
        >>> else:
        ...     print(f"Sync failed: {result['errors']}")
    """
    syncer = ERPNextSyncer(product)
    return syncer.sync(
        create_if_missing=create_if_missing,
        update_existing=update_existing
    )


def bulk_sync_products_to_items(
    products: List[Union[str, Any]],
    create_if_missing: bool = True,
    update_existing: bool = True,
    batch_size: int = 50,
    continue_on_error: bool = True
) -> Dict:
    """
    Sync multiple PIM Products to ERPNext Items.

    Args:
        products: List of product names or documents
        create_if_missing: Create new Items if not found
        update_existing: Update existing Items if found
        batch_size: Number of products per batch (for committing)
        continue_on_error: Continue if a product sync fails

    Returns:
        dict: Bulk sync summary with results
    """
    results = {
        'total': len(products),
        'successful': 0,
        'failed': 0,
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'details': [],
        'errors': []
    }

    for i, product in enumerate(products):
        try:
            result = sync_product_to_item(
                product,
                create_if_missing=create_if_missing,
                update_existing=update_existing
            )

            product_name = product if isinstance(product, str) else product.name

            if result['success']:
                results['successful'] += 1
                if result['action'] == 'created':
                    results['created'] += 1
                elif result['action'] == 'updated':
                    results['updated'] += 1
                elif result['action'] == 'skipped':
                    results['skipped'] += 1

                results['details'].append({
                    'product': product_name,
                    'status': 'success',
                    'action': result['action'],
                    'item_code': result['item_code']
                })
            else:
                results['failed'] += 1
                results['details'].append({
                    'product': product_name,
                    'status': 'failed',
                    'errors': result.get('errors', [])
                })

                if not continue_on_error:
                    break

        except Exception as e:
            results['failed'] += 1
            product_name = product if isinstance(product, str) else getattr(product, 'name', str(product))
            results['errors'].append({
                'product': product_name,
                'error': str(e)
            })

            if not continue_on_error:
                break

        # Commit after each batch
        if (i + 1) % batch_size == 0:
            frappe.db.commit()

    # Final commit
    frappe.db.commit()

    return results


def sync_product_variants_to_items(
    product: Union[str, Any],
    create_if_missing: bool = True,
    update_existing: bool = True
) -> Dict:
    """
    Sync PIM Product Variants to ERPNext Item Variants.

    Args:
        product: PIM Product document or name (parent product)
        create_if_missing: Create new Item Variants if not found
        update_existing: Update existing Item Variants if found

    Returns:
        dict: Sync result with variant details
    """
    if isinstance(product, str):
        product_doc = frappe.get_doc("PIM Product", product)
    else:
        product_doc = product

    results = {
        'product': product_doc.name,
        'variants_synced': 0,
        'variants_failed': 0,
        'details': [],
        'errors': []
    }

    # First sync the parent product
    parent_result = sync_product_to_item(
        product_doc,
        create_if_missing=create_if_missing,
        update_existing=update_existing
    )

    if not parent_result['success']:
        results['errors'].append(f"Parent product sync failed: {parent_result['errors']}")
        return results

    # Get variants for this product
    variants = frappe.get_all(
        "PIM Product Variant",
        filters={"product": product_doc.name, "is_active": 1},
        pluck="name"
    )

    for variant_name in variants:
        try:
            variant_result = _sync_variant_to_item(
                variant_name,
                parent_item_code=parent_result['item_code'],
                create_if_missing=create_if_missing,
                update_existing=update_existing
            )

            if variant_result['success']:
                results['variants_synced'] += 1
            else:
                results['variants_failed'] += 1

            results['details'].append(variant_result)

        except Exception as e:
            results['variants_failed'] += 1
            results['errors'].append({
                'variant': variant_name,
                'error': str(e)
            })

    return results


def _sync_variant_to_item(
    variant: Union[str, Any],
    parent_item_code: str,
    create_if_missing: bool = True,
    update_existing: bool = True
) -> Dict:
    """
    Sync a single PIM Product Variant to ERPNext.

    Args:
        variant: PIM Product Variant document or name
        parent_item_code: Parent ERPNext Item code
        create_if_missing: Create new if not found
        update_existing: Update existing if found

    Returns:
        dict: Sync result
    """
    if isinstance(variant, str):
        variant_doc = frappe.get_doc("PIM Product Variant", variant)
    else:
        variant_doc = variant

    result = {
        'success': False,
        'variant': variant_doc.name,
        'item_code': None,
        'action': None,
        'errors': []
    }

    # Check if Item Variant exists
    item_code = variant_doc.sku or variant_doc.variant_code

    if frappe.db.exists("Item", item_code):
        if not update_existing:
            result['action'] = 'skipped'
            result['item_code'] = item_code
            return result

        # Update existing
        item = frappe.get_doc("Item", item_code)
        item.item_name = f"{variant_doc.variant_name or variant_doc.variant_code}"

        if variant_doc.price_override:
            item.standard_rate = flt(variant_doc.price_override)
        if variant_doc.weight:
            item.weight_per_unit = flt(variant_doc.weight)

        item.save(ignore_permissions=True)
        result['action'] = 'updated'
        result['item_code'] = item.item_code
        result['success'] = True

    elif create_if_missing:
        # Create new Item for variant
        try:
            # Get parent item for defaults
            parent_item = frappe.get_doc("Item", parent_item_code)

            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = variant_doc.variant_name or variant_doc.variant_code
            item.item_group = parent_item.item_group
            item.stock_uom = parent_item.stock_uom
            item.is_stock_item = 1
            item.variant_of = parent_item_code

            # Price and dimensions
            if variant_doc.price_override:
                item.standard_rate = flt(variant_doc.price_override)
            else:
                item.standard_rate = parent_item.standard_rate

            if variant_doc.weight:
                item.weight_per_unit = flt(variant_doc.weight)

            # Add barcodes
            if variant_doc.barcode:
                item.append('barcodes', {
                    'barcode': variant_doc.barcode,
                    'barcode_type': 'CODE-128'
                })
            if variant_doc.gtin:
                item.append('barcodes', {
                    'barcode': variant_doc.gtin,
                    'barcode_type': 'EAN-13'
                })

            item.insert(ignore_permissions=True)
            result['action'] = 'created'
            result['item_code'] = item.item_code
            result['success'] = True

            # Update variant with sync status
            frappe.db.set_value(
                "PIM Product Variant",
                variant_doc.name,
                {
                    'erpnext_item_code': item.item_code,
                    'erpnext_last_sync': now_datetime()
                },
                update_modified=False
            )

        except Exception as e:
            result['errors'].append(str(e))
    else:
        result['action'] = 'skipped'
        result['errors'].append(_("Variant Item not found and create_if_missing is False"))

    return result


@frappe.whitelist()
def sync_to_erpnext(product: str, create_if_missing: int = 1, include_variants: int = 0) -> Dict:
    """
    API endpoint to sync a PIM Product to ERPNext.

    Args:
        product: PIM Product name
        create_if_missing: Create new Item if not found (1/0)
        include_variants: Also sync variants (1/0)

    Returns:
        dict: Sync result
    """
    result = sync_product_to_item(
        product,
        create_if_missing=bool(cint(create_if_missing)),
        update_existing=True
    )

    if result['success'] and cint(include_variants):
        variant_result = sync_product_variants_to_items(
            product,
            create_if_missing=bool(cint(create_if_missing)),
            update_existing=True
        )
        result['variants'] = variant_result

    return result


# ECA Action Handler for automated sync
def execute_erpnext_sync_action(action: Any, doc: Any) -> Dict:
    """
    ECA action handler for ERPNext sync.

    This function is called by the ECA dispatcher when an ECA Rule
    with action_type 'Sync to ERPNext' is triggered.

    Args:
        action: ECA Rule Action child document
        doc: The trigger document (expected to be PIM Product)

    Returns:
        dict: Execution result
    """
    result = {
        'success': False,
        'message': None,
        'error': None
    }

    try:
        # Check if trigger doc is a PIM Product
        if doc.doctype != "PIM Product":
            result['error'] = f"Expected PIM Product, got {doc.doctype}"
            return result

        # Get sync options from action config
        config = {}
        if hasattr(action, 'custom_args') and action.custom_args:
            try:
                config = json.loads(action.custom_args)
            except json.JSONDecodeError:
                config = {}

        create_if_missing = config.get('create_if_missing', True)
        include_variants = config.get('include_variants', False)

        # Perform sync
        sync_result = sync_product_to_item(
            doc,
            create_if_missing=create_if_missing,
            update_existing=True
        )

        if sync_result['success']:
            result['success'] = True
            result['message'] = f"Synced to ERPNext Item: {sync_result['item_code']} ({sync_result['action']})"

            # Sync variants if requested
            if include_variants:
                variant_result = sync_product_variants_to_items(
                    doc,
                    create_if_missing=create_if_missing,
                    update_existing=True
                )
                result['message'] += f", {variant_result['variants_synced']} variants synced"
        else:
            result['error'] = "; ".join(sync_result.get('errors', ['Unknown error']))

    except Exception as e:
        result['error'] = str(e)
        frappe.log_error(
            title="ECA ERPNext Sync Action Error",
            message=frappe.get_traceback()
        )

    return result
