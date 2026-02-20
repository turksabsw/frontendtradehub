# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, cint, flt


class PIMProduct(Document):
    """
    PIM Product DocType Controller

    The main product entity for the Product Information Management system.
    Supports dynamic attributes, multi-channel publishing, completeness tracking,
    and integration with various marketplaces (Amazon, eBay, Alibaba, Trendyol, etc.)
    """

    def before_insert(self):
        """Set creation metadata"""
        self.created_by_user = frappe.session.user
        if not self.creation_source:
            self.creation_source = "Manual"
        self.version_number = 1

    def validate(self):
        """Validation hooks"""
        self.validate_product_code()
        self.validate_identifiers()
        self.validate_pricing()
        self.validate_dimensions()
        self.generate_url_slug()
        self.set_product_class()
        self.update_audit_info()

    def before_save(self):
        """Before save processing"""
        self.update_main_image()
        self.update_primary_category()
        self.sync_short_description()

    def after_save(self):
        """After save processing"""
        self.update_completeness()

    def update_completeness(self):
        """Calculate and update completeness score after save"""
        from tradehub_catalog.tradehub_catalog.pim.completeness import calculate_completeness

        try:
            calculate_completeness(self, update_product=True)
        except Exception as e:
            # Log error but don't prevent save from completing
            frappe.log_error(
                f"Completeness calculation failed for {self.name}: {str(e)}",
                "PIM Product Completeness Error"
            )

    def on_update(self):
        """On update processing"""
        self.increment_version()

    def validate_product_code(self):
        """Validate product code format"""
        if not self.product_code:
            return

        # Allow lowercase, numbers, underscores, and hyphens
        pattern = r'^[a-z0-9_\-]+$'
        if not re.match(pattern, self.product_code):
            frappe.throw(
                _("Product Code must contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Product Code")
            )

        # Minimum length
        if len(self.product_code) < 3:
            frappe.throw(
                _("Product Code must be at least 3 characters long"),
                title=_("Invalid Product Code")
            )

    def validate_identifiers(self):
        """Validate product identifiers format"""
        # GTIN validation (8, 12, 13, or 14 digits)
        if self.gtin:
            gtin_clean = self.gtin.replace(" ", "").replace("-", "")
            if not gtin_clean.isdigit() or len(gtin_clean) not in [8, 12, 13, 14]:
                frappe.throw(
                    _("GTIN must be 8, 12, 13, or 14 digits"),
                    title=_("Invalid GTIN")
                )

        # EAN validation (13 digits)
        if self.ean:
            ean_clean = self.ean.replace(" ", "").replace("-", "")
            if not ean_clean.isdigit() or len(ean_clean) != 13:
                frappe.throw(
                    _("EAN must be 13 digits"),
                    title=_("Invalid EAN")
                )

        # UPC validation (12 digits)
        if self.upc:
            upc_clean = self.upc.replace(" ", "").replace("-", "")
            if not upc_clean.isdigit() or len(upc_clean) != 12:
                frappe.throw(
                    _("UPC must be 12 digits"),
                    title=_("Invalid UPC")
                )

        # ISBN validation (10 or 13 characters)
        if self.isbn:
            isbn_clean = self.isbn.replace(" ", "").replace("-", "")
            if len(isbn_clean) not in [10, 13]:
                frappe.throw(
                    _("ISBN must be 10 or 13 characters"),
                    title=_("Invalid ISBN")
                )

    def validate_pricing(self):
        """Validate pricing fields"""
        if self.base_price and self.base_price < 0:
            frappe.throw(
                _("Base Price cannot be negative"),
                title=_("Invalid Price")
            )

        if self.cost_price and self.cost_price < 0:
            frappe.throw(
                _("Cost Price cannot be negative"),
                title=_("Invalid Price")
            )

        if self.compare_at_price and self.compare_at_price < 0:
            frappe.throw(
                _("Compare At Price cannot be negative"),
                title=_("Invalid Price")
            )

        # Compare at price should be higher than base price
        if self.compare_at_price and self.base_price:
            if flt(self.compare_at_price) < flt(self.base_price):
                frappe.msgprint(
                    _("Compare At Price is lower than Base Price. This may not show discount correctly."),
                    indicator="orange"
                )

    def validate_dimensions(self):
        """Validate dimension fields"""
        for field in ['weight', 'length', 'width', 'height']:
            value = getattr(self, field, None)
            if value and flt(value) < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(field.title()),
                    title=_("Invalid Dimension")
                )

    def generate_url_slug(self):
        """Generate URL-friendly slug from product name"""
        if not self.url_slug and self.product_name:
            slug = self.product_name.lower()
            # Replace Turkish characters
            tr_map = {
                'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ş': 's', 'ü': 'u',
                'Ç': 'c', 'Ğ': 'g', 'İ': 'i', 'Ö': 'o', 'Ş': 's', 'Ü': 'u'
            }
            for tr_char, en_char in tr_map.items():
                slug = slug.replace(tr_char, en_char)
            # Replace non-alphanumeric with hyphens
            slug = re.sub(r'[^a-z0-9]+', '-', slug)
            # Remove leading/trailing hyphens
            slug = slug.strip('-')
            # Remove consecutive hyphens
            slug = re.sub(r'-+', '-', slug)
            self.url_slug = slug

    def set_product_class(self):
        """Fetch product class from product family if not set"""
        if self.product_family and not self.product_class:
            product_class = frappe.db.get_value(
                "Product Family", self.product_family, "product_class"
            )
            if product_class:
                self.product_class = product_class

    def update_audit_info(self):
        """Update audit trail information"""
        self.last_modified_by_user = frappe.session.user

    def update_main_image(self):
        """Sync main image from media table"""
        if not self.media:
            return

        for media_item in self.media:
            if media_item.is_main and media_item.file:
                self.main_image = media_item.file
                return

        # If no main image set, use first image
        for media_item in self.media:
            if media_item.media_type == "Image" and media_item.file:
                self.main_image = media_item.file
                return

    def update_primary_category(self):
        """Sync primary category from categories table"""
        if not self.categories:
            return

        for cat in self.categories:
            if cat.is_primary:
                self.primary_category = cat.category
                return

        # If no primary set, use first category
        if self.categories and len(self.categories) > 0:
            first_cat = self.categories[0]
            self.primary_category = first_cat.category
            first_cat.is_primary = 1

    def sync_short_description(self):
        """Sync default short description from descriptions table"""
        if self.short_description:
            return

        if not self.descriptions:
            return

        # Find default short description
        for desc in self.descriptions:
            if desc.description_type == "Short" and not desc.locale and not desc.channel:
                # Strip HTML and truncate
                import html
                plain = re.sub(r'<[^>]+>', '', desc.description or '')
                plain = html.unescape(plain)
                self.short_description = plain[:500] if len(plain) > 500 else plain
                return

    def increment_version(self):
        """Increment version number on update"""
        if not self.is_new():
            frappe.db.set_value(
                "PIM Product",
                self.name,
                "version_number",
                cint(self.version_number) + 1,
                update_modified=False
            )

    # ---- Helper Methods ----

    def get_attribute_value(self, attribute_code, locale=None, channel=None):
        """
        Get attribute value by code with optional locale/channel scope

        Args:
            attribute_code: The attribute code to retrieve
            locale: Optional locale code (e.g., 'tr_TR')
            channel: Optional sales channel name

        Returns:
            The attribute value or None
        """
        for attr_val in self.attribute_values:
            if attr_val.attribute_code == attribute_code:
                # Check scope match
                if locale and attr_val.locale and attr_val.locale != locale:
                    continue
                if channel and attr_val.channel and attr_val.channel != channel:
                    continue

                # Return appropriate value based on attribute type
                attr_type = attr_val.attribute_type
                if attr_type in ['Text', 'Data', 'URL', 'Color', 'Size', 'Select']:
                    return attr_val.value_text
                elif attr_type in ['Long Text']:
                    return attr_val.value_long_text
                elif attr_type in ['HTML']:
                    return attr_val.value_html
                elif attr_type in ['Int']:
                    return attr_val.value_int
                elif attr_type in ['Float', 'Currency', 'Percent', 'Rating', 'Measurement']:
                    return attr_val.value_float
                elif attr_type in ['Check']:
                    return attr_val.value_check
                elif attr_type in ['Multiselect']:
                    return attr_val.value_select
                elif attr_type in ['Date']:
                    return attr_val.value_date
                elif attr_type in ['Datetime']:
                    return attr_val.value_datetime
                elif attr_type in ['Link']:
                    return attr_val.value_link
                elif attr_type in ['JSON', 'Table', 'File', 'Image']:
                    return attr_val.value_json
                return attr_val.value_text

        return None

    def set_attribute_value(self, attribute_code, value, locale=None, channel=None):
        """
        Set attribute value by code with optional locale/channel scope

        Args:
            attribute_code: The attribute code to set
            value: The value to set
            locale: Optional locale code
            channel: Optional sales channel name
        """
        # Find existing row
        for attr_val in self.attribute_values:
            if attr_val.attribute_code == attribute_code:
                scope_match = True
                if locale and attr_val.locale != locale:
                    scope_match = False
                if channel and attr_val.channel != channel:
                    scope_match = False

                if scope_match:
                    self._set_attribute_value_field(attr_val, value)
                    return

        # Create new row
        new_row = self.append("attribute_values", {
            "attribute_code": attribute_code,
            "locale": locale,
            "channel": channel
        })
        self._set_attribute_value_field(new_row, value)

    def _set_attribute_value_field(self, attr_val, value):
        """Set the appropriate value field based on attribute type"""
        attr_type = attr_val.attribute_type

        if attr_type in ['Text', 'Data', 'URL', 'Color', 'Size', 'Select']:
            attr_val.value_text = value
        elif attr_type in ['Long Text']:
            attr_val.value_long_text = value
        elif attr_type in ['HTML']:
            attr_val.value_html = value
        elif attr_type in ['Int']:
            attr_val.value_int = cint(value)
        elif attr_type in ['Float', 'Currency', 'Percent', 'Rating', 'Measurement']:
            attr_val.value_float = flt(value)
        elif attr_type in ['Check']:
            attr_val.value_check = 1 if value else 0
        elif attr_type in ['Multiselect']:
            attr_val.value_select = value
        elif attr_type in ['Date']:
            attr_val.value_date = value
        elif attr_type in ['Datetime']:
            attr_val.value_datetime = value
        elif attr_type in ['Link']:
            attr_val.value_link = value
        elif attr_type in ['JSON', 'Table', 'File', 'Image']:
            attr_val.value_json = json.dumps(value) if isinstance(value, (dict, list)) else value
        else:
            attr_val.value_text = value

    def get_price(self, price_type="Standard", currency=None, channel=None):
        """
        Get price by type with optional currency/channel scope

        Args:
            price_type: Price type (Standard, Sale, MSRP, etc.)
            currency: Optional currency code
            channel: Optional sales channel name

        Returns:
            Price amount or None
        """
        for price in self.prices:
            if price.price_type == price_type:
                if currency and price.currency != currency:
                    continue
                if channel and price.channel != channel:
                    continue
                return price.price

        return None

    def get_description(self, desc_type="Short", locale=None, channel=None):
        """
        Get description by type with optional locale/channel scope

        Args:
            desc_type: Description type (Short, Long, Marketing, etc.)
            locale: Optional locale code
            channel: Optional sales channel name

        Returns:
            Description HTML or None
        """
        for desc in self.descriptions:
            if desc.description_type == desc_type:
                if locale and desc.locale and desc.locale != locale:
                    continue
                if channel and desc.channel and desc.channel != channel:
                    continue
                return desc.description

        return None

    def get_images(self, include_main_only=False):
        """
        Get product images

        Args:
            include_main_only: If True, only return main image

        Returns:
            List of image file paths
        """
        images = []
        for media in self.media:
            if media.media_type == "Image" and media.file:
                if include_main_only and not media.is_main:
                    continue
                images.append({
                    "file": media.file,
                    "is_main": media.is_main,
                    "alt_text": media.alt_text,
                    "sort_order": media.sort_order
                })

        # Sort by sort_order, main first
        images.sort(key=lambda x: (0 if x["is_main"] else 1, x["sort_order"]))
        return images

    def get_related_products(self, relation_type=None, limit=10):
        """
        Get related products

        Args:
            relation_type: Filter by relation type (Related, Cross-Sell, etc.)
            limit: Maximum number of products to return

        Returns:
            List of related product names
        """
        related = []
        for rel in self.relations:
            if relation_type and rel.relation_type != relation_type:
                continue
            related.append({
                "product": rel.related_product,
                "product_name": rel.related_product_name,
                "relation_type": rel.relation_type
            })
            if len(related) >= limit:
                break

        return related

    def get_family_config(self):
        """Get Product Family configuration for this product"""
        if not self.product_family:
            return None

        return frappe.get_doc("Product Family", self.product_family)

    def get_class_config(self):
        """Get Product Class configuration for this product"""
        if not self.product_class:
            return None

        return frappe.get_doc("Product Class", self.product_class)

    def publish(self):
        """Publish the product"""
        if self.status not in ["Approved", "Published"]:
            frappe.throw(
                _("Product must be approved before publishing"),
                title=_("Cannot Publish")
            )

        self.is_published = 1
        self.published_on = now_datetime()
        self.status = "Published"
        self.save()

        frappe.msgprint(_("Product published successfully"), indicator="green")

    def unpublish(self):
        """Unpublish the product"""
        self.is_published = 0
        self.unpublished_on = now_datetime()
        self.save()

        frappe.msgprint(_("Product unpublished"), indicator="orange")

    def duplicate(self, new_product_code=None):
        """
        Create a duplicate of this product

        Args:
            new_product_code: Optional new product code

        Returns:
            New PIM Product document
        """
        new_doc = frappe.copy_doc(self)
        new_doc.product_code = new_product_code or f"{self.product_code}_copy"
        new_doc.product_name = f"{self.product_name} (Copy)"
        new_doc.status = "Draft"
        new_doc.is_published = 0
        new_doc.is_active = 1
        new_doc.creation_source = "Duplicate"
        new_doc.sku = None
        new_doc.barcode = None
        new_doc.gtin = None

        # Clear marketplace IDs
        new_doc.amazon_asin = None
        new_doc.ebay_item_id = None
        new_doc.alibaba_product_id = None
        new_doc.trendyol_product_code = None
        new_doc.hepsiburada_sku = None
        new_doc.n11_product_id = None

        # Clear ERPNext link
        new_doc.erpnext_item_code = None
        new_doc.erpnext_last_sync = None

        # Clear completeness
        new_doc.completeness_score = 0
        new_doc.completeness_status = "Incomplete"
        new_doc.completeness_detail = None
        new_doc.channel_completeness = None

        # Clear origin fields
        new_doc.magento_product_id = None
        new_doc.drupal_product_id = None
        new_doc.external_id = None

        # Clear audit fields
        new_doc.approved_by = None
        new_doc.approved_on = None
        new_doc.published_on = None
        new_doc.unpublished_on = None

        new_doc.insert()
        return new_doc

    def sync_to_erpnext(self, create_if_missing=True, include_variants=False):
        """
        Sync this product to ERPNext Item.

        Creates or updates an ERPNext Item based on this PIM Product's data.
        Optionally syncs product variants as well.

        Args:
            create_if_missing: Create new Item if not found (default True)
            include_variants: Also sync product variants (default False)

        Returns:
            dict: Sync result with status and details
                - success: bool
                - action: 'created', 'updated', or 'skipped'
                - item_code: ERPNext Item code
                - item_name: ERPNext Item name
                - errors: list of error messages
                - warnings: list of warning messages
                - synced_at: timestamp of sync

        Example:
            >>> product = frappe.get_doc("PIM Product", "PROD-001")
            >>> result = product.sync_to_erpnext(include_variants=True)
            >>> if result['success']:
            ...     print(f"Synced to: {result['item_code']}")
        """
        from tradehub_catalog.tradehub_catalog.pim.erpnext_sync import sync_product_to_item, sync_product_variants_to_items

        result = sync_product_to_item(
            self,
            create_if_missing=create_if_missing,
            update_existing=True
        )

        if result['success'] and include_variants:
            variant_result = sync_product_variants_to_items(
                self,
                create_if_missing=create_if_missing,
                update_existing=True
            )
            result['variants'] = variant_result

        if result['success']:
            frappe.msgprint(
                _("Product synced to ERPNext Item: {0}").format(result['item_code']),
                indicator="green"
            )
        else:
            frappe.msgprint(
                _("Sync failed: {0}").format(", ".join(result.get('errors', []))),
                indicator="red"
            )

        return result
