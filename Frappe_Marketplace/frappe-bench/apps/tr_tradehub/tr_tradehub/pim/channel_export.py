# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
PIM Channel Export Engine

Exports product data to Sales Channels by applying Product Family channel mappings
and transform rules. Supports various transform types for flexible field mapping
between PIM attributes and channel-specific fields.

Transform Types:
    - None: Direct pass-through of attribute value
    - Map: Map value to a different value using a lookup dictionary
    - Concat: Concatenate multiple attributes with a separator
    - Split: Split a value into multiple parts
    - Lookup: Lookup value from a reference table
    - Format: Apply Jinja template formatting
    - Custom: Execute custom Python code (sandboxed)

Example:
    >>> result = export_to_channel("PROD-001", "amazon")
    >>> print(result['data'])  # Transformed data ready for Amazon API
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, get_datetime

# Use SandboxedEnvironment for user-provided Jinja templates
try:
    from jinja2.sandbox import SandboxedEnvironment
except ImportError:
    SandboxedEnvironment = None


class ChannelExporter:
    """
    Exports product data to Sales Channels with transform rules.

    The exporter:
    1. Retrieves channel field mappings from Product Family
    2. Gets product attribute values
    3. Applies transform rules to map PIM data to channel format
    4. Validates required fields
    5. Returns export-ready data structure

    Attributes:
        product: The PIM Product document to export
        channel: The target Sales Channel document
        family: The Product Family with channel mappings
        mappings: List of channel field mappings
        locale: Target locale for the export
    """

    # Supported transform types
    TRANSFORM_TYPES = ['None', 'Map', 'Concat', 'Split', 'Lookup', 'Format', 'Custom']

    def __init__(
        self,
        product: Any,
        channel: Union[str, Any],
        locale: Optional[str] = None
    ):
        """
        Initialize channel exporter for a product.

        Args:
            product: PIM Product document or product name/code
            channel: Sales Channel document or channel code
            locale: Optional locale to use for attribute values
        """
        # Load product
        if isinstance(product, str):
            self.product = frappe.get_doc("PIM Product", product)
        else:
            self.product = product

        # Load channel
        if isinstance(channel, str):
            self.channel = frappe.get_doc("Sales Channel", channel)
        else:
            self.channel = channel

        self.locale = locale or self.channel.default_locale
        self.family = None
        self.mappings = []
        self.transformed_data = {}
        self.validation_errors = []

        # Load product family and channel mappings
        if self.product.product_family:
            try:
                self.family = frappe.get_doc("Product Family", self.product.product_family)
                self.mappings = self.family.get_channel_mappings(channel=self.channel.name)
            except frappe.DoesNotExistError:
                pass

    def can_export(self) -> Tuple[bool, str]:
        """
        Check if export is possible for this product and channel.

        Returns:
            Tuple of (can_export: bool, reason: str)
        """
        if not self.product:
            return False, _("Product not found")

        if not self.channel:
            return False, _("Channel not found")

        if not self.channel.is_active:
            return False, _("Channel is not active")

        if not self.family:
            return False, _("Product has no Product Family assigned")

        if not self.mappings:
            return False, _("No channel mappings defined for this family and channel")

        # Check if product is publishable
        if hasattr(self.product, 'status') and self.product.status in ['Draft', 'Archived']:
            return False, _("Product status '{0}' is not exportable").format(self.product.status)

        return True, ""

    def get_source_value(self, attribute_code: str) -> Any:
        """
        Get source value from product for an attribute.

        Args:
            attribute_code: The PIM attribute code

        Returns:
            The attribute value or None
        """
        # First check if it's a direct product field
        direct_fields = [
            'product_name', 'product_code', 'sku', 'barcode', 'gtin', 'mpn',
            'ean', 'upc', 'isbn', 'hscode', 'brand', 'manufacturer',
            'weight', 'length', 'width', 'height', 'base_price', 'cost_price',
            'short_description', 'main_image', 'url_slug', 'meta_title',
            'meta_description', 'meta_keywords', 'country_of_origin'
        ]

        if attribute_code in direct_fields:
            return getattr(self.product, attribute_code, None)

        # Then check attribute_values child table
        value = self.product.get_attribute_value(
            attribute_code,
            locale=self.locale,
            channel=self.channel.name
        )

        return value

    def apply_transform(self, mapping: Dict, source_value: Any) -> Any:
        """
        Apply transform rule to convert source value to target format.

        Args:
            mapping: The channel field mapping configuration
            source_value: The source attribute value

        Returns:
            Transformed value for the channel
        """
        transform_type = mapping.get('transform_type', 'None')
        transform_config = mapping.get('transform_config')

        # Parse JSON config if string
        if transform_config and isinstance(transform_config, str):
            try:
                transform_config = json.loads(transform_config)
            except (json.JSONDecodeError, ValueError):
                transform_config = {}

        transform_config = transform_config or {}

        # Apply transform based on type
        transformers = {
            'None': self._transform_none,
            'Map': self._transform_map,
            'Concat': self._transform_concat,
            'Split': self._transform_split,
            'Lookup': self._transform_lookup,
            'Format': self._transform_format,
            'Custom': self._transform_custom
        }

        transformer = transformers.get(transform_type, self._transform_none)

        try:
            return transformer(source_value, transform_config, mapping)
        except Exception as e:
            frappe.log_error(
                f"Transform error for {mapping.get('attribute')} -> {mapping.get('target_field_name')}: {str(e)}"
            )
            return source_value

    def _transform_none(self, value: Any, config: Dict, mapping: Dict) -> Any:
        """
        Direct pass-through transform.

        Config: None required
        """
        return value

    def _transform_map(self, value: Any, config: Dict, mapping: Dict) -> Any:
        """
        Map value to a different value using lookup dictionary.

        Config:
            {
                "mapping": {"source_value": "target_value", ...},
                "default": "default_value"
            }

        Example:
            {"mapping": {"red": "Red Color", "blue": "Blue Color"}, "default": "Other"}
        """
        if value is None:
            return config.get('default')

        mapping_dict = config.get('mapping', {})
        str_value = str(value).lower() if value else ''

        # Try exact match first
        if str_value in mapping_dict:
            return mapping_dict[str_value]

        # Try case-insensitive match
        for key, mapped_value in mapping_dict.items():
            if str(key).lower() == str_value:
                return mapped_value

        return config.get('default', value)

    def _transform_concat(self, value: Any, config: Dict, mapping: Dict) -> Any:
        """
        Concatenate multiple attributes with a separator.

        Config:
            {
                "attributes": ["attr1", "attr2", ...],
                "separator": " - ",
                "include_labels": false,
                "skip_empty": true
            }

        Example:
            {"attributes": ["brand", "product_name", "color"], "separator": " | "}
        """
        attributes = config.get('attributes', [])
        separator = config.get('separator', ' ')
        include_labels = config.get('include_labels', False)
        skip_empty = config.get('skip_empty', True)

        parts = []

        for attr_code in attributes:
            attr_value = self.get_source_value(attr_code)

            if skip_empty and (attr_value is None or attr_value == ''):
                continue

            if include_labels:
                # Get attribute label
                try:
                    attr_doc = frappe.get_doc("PIM Attribute", attr_code)
                    label = attr_doc.attribute_name
                except frappe.DoesNotExistError:
                    label = attr_code.replace('_', ' ').title()

                parts.append(f"{label}: {attr_value}")
            else:
                parts.append(str(attr_value) if attr_value is not None else '')

        return separator.join(parts)

    def _transform_split(self, value: Any, config: Dict, mapping: Dict) -> Any:
        """
        Split a value into parts and return specific part(s).

        Config:
            {
                "separator": "-",
                "index": 0,          # Return single index
                "indices": [0, 2],   # Return multiple indices
                "join_with": " "     # Join multiple indices with this
            }

        Example:
            Split "Red-Large-Cotton" with separator "-" and index 1 returns "Large"
        """
        if value is None:
            return None

        separator = config.get('separator', '-')
        parts = str(value).split(separator)

        # Single index
        if 'index' in config:
            idx = cint(config['index'])
            if 0 <= idx < len(parts):
                return parts[idx].strip()
            return None

        # Multiple indices
        if 'indices' in config:
            indices = config['indices']
            join_with = config.get('join_with', ' ')
            selected_parts = []
            for idx in indices:
                if 0 <= cint(idx) < len(parts):
                    selected_parts.append(parts[cint(idx)].strip())
            return join_with.join(selected_parts)

        # Return all parts as list
        return [p.strip() for p in parts]

    def _transform_lookup(self, value: Any, config: Dict, mapping: Dict) -> Any:
        """
        Lookup value from a reference table or mapping.

        Config:
            {
                "doctype": "PIM Attribute Option",
                "filters": {"option_value": "{value}"},
                "field": "option_label",
                "default": null
            }

        Or static lookup:
            {
                "table": {"key1": "value1", "key2": "value2"},
                "default": "unknown"
            }
        """
        if value is None:
            return config.get('default')

        # Static table lookup
        if 'table' in config:
            table = config['table']
            str_value = str(value)
            return table.get(str_value, config.get('default', value))

        # DocType lookup
        if 'doctype' in config:
            doctype = config['doctype']
            filters = config.get('filters', {})
            field = config.get('field', 'name')

            # Replace {value} placeholder in filters
            processed_filters = {}
            for key, filter_value in filters.items():
                if isinstance(filter_value, str) and '{value}' in filter_value:
                    processed_filters[key] = filter_value.replace('{value}', str(value))
                else:
                    processed_filters[key] = filter_value

            try:
                result = frappe.db.get_value(doctype, processed_filters, field)
                return result if result else config.get('default', value)
            except Exception:
                return config.get('default', value)

        return value

    def _transform_format(self, value: Any, config: Dict, mapping: Dict) -> Any:
        """
        Apply Jinja template formatting.

        Config:
            {
                "template": "{{ value | upper }} - {{ product.brand }}"
            }

        Available context:
            - value: The source attribute value
            - product: The full product document
            - channel: The channel document
            - locale: The target locale
        """
        template_str = config.get('template')
        if not template_str:
            return value

        if SandboxedEnvironment is None:
            frappe.log_error("Jinja2 SandboxedEnvironment not available")
            return value

        try:
            env = SandboxedEnvironment()
            template = env.from_string(template_str)

            # Build context
            context = {
                'value': value,
                'product': self.product.as_dict(),
                'channel': self.channel.as_dict(),
                'locale': self.locale,
                # Add useful helpers
                'now': now_datetime(),
                'cint': cint,
                'flt': flt
            }

            return template.render(**context)
        except Exception as e:
            frappe.log_error(f"Format transform error: {str(e)}")
            return value

    def _transform_custom(self, value: Any, config: Dict, mapping: Dict) -> Any:
        """
        Execute custom Python code (sandboxed).

        Config:
            {
                "code": "value.upper() if value else ''"
            }

        Available variables:
            - value: The source attribute value
            - product: The product dict
            - channel: The channel dict
            - frappe: Limited frappe module

        Note: This is evaluated in a restricted environment.
        """
        code = config.get('code')
        if not code:
            return value

        try:
            # Build safe context with limited functionality
            safe_context = {
                'value': value,
                'product': self.product.as_dict(),
                'channel': self.channel.as_dict(),
                'locale': self.locale,
                # Safe built-ins
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'len': len,
                'list': list,
                'dict': dict,
                'round': round,
                'min': min,
                'max': max,
                'sum': sum,
                'abs': abs,
                'sorted': sorted,
                # String methods through value
                'upper': lambda v: str(v).upper() if v else '',
                'lower': lambda v: str(v).lower() if v else '',
                'strip': lambda v: str(v).strip() if v else '',
                'replace': lambda v, old, new: str(v).replace(old, new) if v else '',
                # Frappe helpers (limited)
                'cint': cint,
                'flt': flt,
                'now': now_datetime
            }

            # Evaluate code in restricted context
            result = eval(code, {"__builtins__": {}}, safe_context)
            return result
        except Exception as e:
            frappe.log_error(f"Custom transform error: {str(e)}\nCode: {code}")
            return value

    def transform(self) -> Dict:
        """
        Transform all product attributes according to channel mappings.

        Returns:
            dict: {
                'success': bool,
                'data': dict of transformed field values,
                'missing_required': list of missing required fields,
                'errors': list of transform errors
            }
        """
        result = {
            'success': True,
            'data': {},
            'missing_required': [],
            'errors': []
        }

        if not self.mappings:
            result['success'] = False
            result['errors'].append(_("No channel mappings found"))
            return result

        # Process each mapping
        for mapping in self.mappings:
            attribute_code = mapping.get('attribute')
            target_field = mapping.get('target_field_name')
            is_required = mapping.get('is_required', False)

            if not attribute_code or not target_field:
                continue

            try:
                # Get source value
                source_value = self.get_source_value(attribute_code)

                # Apply transform
                transformed_value = self.apply_transform(mapping, source_value)

                # Store transformed value
                result['data'][target_field] = transformed_value

                # Check required fields
                if is_required and (transformed_value is None or transformed_value == ''):
                    result['missing_required'].append({
                        'field': target_field,
                        'attribute': attribute_code
                    })

            except Exception as e:
                result['errors'].append({
                    'attribute': attribute_code,
                    'target_field': target_field,
                    'error': str(e)
                })

        # Set success based on required fields and errors
        if result['missing_required'] or result['errors']:
            result['success'] = len(result['missing_required']) == 0

        self.transformed_data = result['data']
        return result

    def add_standard_fields(self, data: Dict) -> Dict:
        """
        Add standard product fields to export data.

        Args:
            data: The transformed data dict

        Returns:
            dict with standard fields added
        """
        # Add core identifiers if not already mapped
        standard_fields = {
            'sku': self.product.sku,
            'product_code': self.product.product_code,
            'barcode': self.product.barcode,
            'gtin': self.product.gtin,
            'mpn': self.product.mpn,
            'brand': self.product.brand,
            'product_name': self.product.product_name,
            'main_image': self.product.main_image
        }

        for field, value in standard_fields.items():
            if field not in data and value:
                data[field] = value

        return data

    def add_channel_metadata(self, data: Dict) -> Dict:
        """
        Add channel-specific metadata to export data.

        Args:
            data: The export data dict

        Returns:
            dict with metadata added
        """
        data['_meta'] = {
            'channel': self.channel.name,
            'channel_code': self.channel.channel_code,
            'channel_type': self.channel.channel_type,
            'platform': self.channel.platform,
            'locale': self.locale,
            'currency': self.channel.default_currency,
            'exported_at': str(now_datetime()),
            'product_name': self.product.name,
            'product_code': self.product.product_code,
            'family': self.family.name if self.family else None
        }
        return data

    def get_images_for_channel(self) -> List[Dict]:
        """
        Get product images formatted for channel export.

        Returns:
            List of image dicts with URL, alt text, and sort order
        """
        images = []
        for media in (self.product.media or []):
            if media.media_type == 'Image' and media.file:
                images.append({
                    'url': media.file,
                    'alt_text': media.alt_text,
                    'is_main': media.is_main,
                    'sort_order': media.sort_order,
                    'angle': media.image_angle
                })

        # Sort by main first, then sort_order
        images.sort(key=lambda x: (0 if x['is_main'] else 1, x['sort_order'] or 0))
        return images

    def get_prices_for_channel(self) -> Dict:
        """
        Get product prices formatted for channel export.

        Returns:
            Dict of price types to price values
        """
        prices = {}
        channel_currency = self.channel.default_currency

        for price in (self.product.prices or []):
            # Filter by channel if specified
            if price.channel and price.channel != self.channel.name:
                continue

            # Match currency if specified
            if channel_currency and price.currency and price.currency != channel_currency:
                continue

            price_type = price.price_type or 'Standard'
            prices[price_type] = {
                'amount': flt(price.price),
                'currency': price.currency,
                'min_qty': price.min_quantity,
                'valid_from': str(price.valid_from) if price.valid_from else None,
                'valid_to': str(price.valid_to) if price.valid_to else None
            }

        return prices

    def export(self, include_images: bool = True, include_prices: bool = True) -> Dict:
        """
        Perform full export transformation for the channel.

        Args:
            include_images: Include product images in export
            include_prices: Include product prices in export

        Returns:
            dict: Full export result with data and status
        """
        result = {
            'success': False,
            'product': self.product.name,
            'channel': self.channel.name,
            'data': {},
            'images': [],
            'prices': {},
            'errors': [],
            'warnings': []
        }

        # Check if export is possible
        can_export, reason = self.can_export()
        if not can_export:
            result['errors'].append(reason)
            return result

        # Transform attribute data
        transform_result = self.transform()
        result['data'] = transform_result['data']

        if transform_result['missing_required']:
            result['warnings'].extend([
                f"Missing required field: {m['field']} (from attribute: {m['attribute']})"
                for m in transform_result['missing_required']
            ])

        if transform_result['errors']:
            result['errors'].extend([
                f"Transform error for {e['attribute']}: {e['error']}"
                for e in transform_result['errors']
            ])

        # Add standard fields
        result['data'] = self.add_standard_fields(result['data'])

        # Add images
        if include_images:
            result['images'] = self.get_images_for_channel()

        # Add prices
        if include_prices:
            result['prices'] = self.get_prices_for_channel()

        # Add metadata
        result['data'] = self.add_channel_metadata(result['data'])

        # Set success if no blocking errors
        result['success'] = len([e for e in result['errors'] if not e.startswith('Transform')]) == 0

        return result


def export_to_channel(
    product: Any,
    channel: Union[str, Any],
    locale: Optional[str] = None,
    include_images: bool = True,
    include_prices: bool = True,
    save_log: bool = False
) -> Dict:
    """
    Export product data to a Sales Channel.

    This is the main entry point for channel export.

    Args:
        product: PIM Product document, name, or product_code
        channel: Sales Channel document or channel code
        locale: Optional locale for attribute values
        include_images: Include product images in export
        include_prices: Include product prices in export
        save_log: If True, save export log entry

    Returns:
        dict: Export result with transformed data and status

    Example:
        >>> result = export_to_channel("PROD-001", "amazon")
        >>> if result['success']:
        ...     send_to_amazon_api(result['data'])
        >>> print(f"Exported with {len(result['warnings'])} warnings")
    """
    exporter = ChannelExporter(product, channel, locale=locale)
    result = exporter.export(
        include_images=include_images,
        include_prices=include_prices
    )

    if save_log:
        _save_export_log(exporter.product, exporter.channel, result)

    return result


def get_channel_export_data(
    product: Any,
    channel: Union[str, Any],
    locale: Optional[str] = None
) -> Dict:
    """
    Get transformed data for channel without full export.

    Useful for previewing export data or validating mappings.

    Args:
        product: PIM Product document or name
        channel: Sales Channel document or channel code
        locale: Optional locale

    Returns:
        dict: Just the transformed field data
    """
    exporter = ChannelExporter(product, channel, locale=locale)
    transform_result = exporter.transform()
    return {
        'data': transform_result['data'],
        'missing_required': transform_result['missing_required'],
        'valid': len(transform_result['missing_required']) == 0
    }


def validate_channel_export(
    product: Any,
    channel: Union[str, Any],
    locale: Optional[str] = None
) -> Dict:
    """
    Validate product export data without performing export.

    Checks:
    - All required mappings have values
    - Transform rules are valid
    - Data meets channel requirements

    Args:
        product: PIM Product document or name
        channel: Sales Channel document or channel code
        locale: Optional locale

    Returns:
        dict: Validation result with errors and warnings
    """
    exporter = ChannelExporter(product, channel, locale=locale)

    result = {
        'valid': True,
        'errors': [],
        'warnings': [],
        'field_coverage': 0.0
    }

    # Check exportability
    can_export, reason = exporter.can_export()
    if not can_export:
        result['valid'] = False
        result['errors'].append(reason)
        return result

    # Transform and check
    transform_result = exporter.transform()

    if transform_result['missing_required']:
        result['valid'] = False
        for missing in transform_result['missing_required']:
            result['errors'].append(
                f"Required field '{missing['field']}' is empty (source: {missing['attribute']})"
            )

    if transform_result['errors']:
        for error in transform_result['errors']:
            result['warnings'].append(
                f"Transform error for '{error['attribute']}': {error['error']}"
            )

    # Calculate field coverage
    total_mappings = len(exporter.mappings)
    filled_fields = sum(1 for v in transform_result['data'].values() if v is not None and v != '')
    result['field_coverage'] = (filled_fields / total_mappings * 100) if total_mappings > 0 else 0

    return result


def bulk_export_to_channel(
    products: List[Any],
    channel: Union[str, Any],
    locale: Optional[str] = None,
    batch_size: int = 100,
    continue_on_error: bool = True
) -> Dict:
    """
    Export multiple products to a Sales Channel.

    Args:
        products: List of product names or documents
        channel: Sales Channel document or channel code
        locale: Optional locale
        batch_size: Number of products per batch
        continue_on_error: Continue if a product export fails

    Returns:
        dict: Bulk export summary with results
    """
    results = {
        'total': len(products),
        'successful': 0,
        'failed': 0,
        'exports': [],
        'errors': []
    }

    # Load channel once
    if isinstance(channel, str):
        channel_doc = frappe.get_doc("Sales Channel", channel)
    else:
        channel_doc = channel

    for i, product in enumerate(products):
        try:
            result = export_to_channel(
                product,
                channel_doc,
                locale=locale,
                save_log=True
            )

            product_name = product if isinstance(product, str) else product.name

            if result['success']:
                results['successful'] += 1
                results['exports'].append({
                    'product': product_name,
                    'status': 'success',
                    'warnings': result.get('warnings', [])
                })
            else:
                results['failed'] += 1
                results['exports'].append({
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


def get_channel_mapping_preview(
    product: Any,
    channel: Union[str, Any],
    locale: Optional[str] = None
) -> List[Dict]:
    """
    Get a preview of how each mapping would transform data.

    Useful for debugging and visualizing the export transformation.

    Args:
        product: PIM Product document or name
        channel: Sales Channel document or channel code
        locale: Optional locale

    Returns:
        list: Preview of each mapping with source and target values
    """
    exporter = ChannelExporter(product, channel, locale=locale)

    preview = []
    for mapping in exporter.mappings:
        attribute_code = mapping.get('attribute')
        source_value = exporter.get_source_value(attribute_code)
        transformed_value = exporter.apply_transform(mapping, source_value)

        preview.append({
            'source_attribute': attribute_code,
            'target_field': mapping.get('target_field_name'),
            'target_field_code': mapping.get('target_field_code'),
            'transform_type': mapping.get('transform_type', 'None'),
            'source_value': source_value,
            'transformed_value': transformed_value,
            'is_required': mapping.get('is_required', False),
            'is_valid': transformed_value is not None and transformed_value != ''
        })

    return preview


def get_available_channels_for_product(product: Any) -> List[Dict]:
    """
    Get list of channels that have mappings for a product's family.

    Args:
        product: PIM Product document or name

    Returns:
        list: Available channels with mapping info
    """
    if isinstance(product, str):
        product_doc = frappe.get_doc("PIM Product", product)
    else:
        product_doc = product

    if not product_doc.product_family:
        return []

    # Get channel mappings from family
    family = frappe.get_doc("Product Family", product_doc.product_family)
    mappings = family.channel_mappings or []

    # Get unique channels
    channel_codes = set(m.channel for m in mappings if m.channel)

    channels = []
    for channel_code in channel_codes:
        try:
            channel = frappe.get_doc("Sales Channel", channel_code)
            mapping_count = sum(1 for m in mappings if m.channel == channel_code)

            channels.append({
                'channel': channel.name,
                'channel_code': channel.channel_code,
                'channel_name': channel.channel_name,
                'platform': channel.platform,
                'is_active': channel.is_active,
                'mapping_count': mapping_count
            })
        except frappe.DoesNotExistError:
            continue

    return channels


def _save_export_log(product: Any, channel: Any, result: Dict):
    """
    Save export log entry for audit trail.

    Args:
        product: The product document
        channel: The channel document
        result: The export result
    """
    # This could create an export log DocType entry if needed
    # For now, just log to error log on failure
    if not result.get('success'):
        frappe.log_error(
            f"Channel export failed\n"
            f"Product: {product.name}\n"
            f"Channel: {channel.name}\n"
            f"Errors: {json.dumps(result.get('errors', []))}\n"
            f"Warnings: {json.dumps(result.get('warnings', []))}",
            "Channel Export Error"
        )
