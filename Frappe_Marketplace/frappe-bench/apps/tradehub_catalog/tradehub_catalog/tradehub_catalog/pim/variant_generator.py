# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
PIM Variant Generator

Generates product variants based on variant axes defined in Product Family.
Creates cartesian product of all axis value combinations and generates
PIM Product Variant records with inherited parent data.

Example:
    A product with variant axes Color (Red, Blue) and Size (S, M, L) will
    generate 6 variants: Red-S, Red-M, Red-L, Blue-S, Blue-M, Blue-L
"""

import itertools
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime


class VariantGenerator:
    """
    Generates product variants based on Product Family variant axes.

    The generator:
    1. Retrieves variant axes from the Product Family
    2. Gets possible values for each axis from PIM Attribute options
    3. Creates cartesian product of all value combinations
    4. Generates PIM Product Variant records with inherited parent data

    Attributes:
        product: The parent PIM Product document
        family: The linked Product Family document
        variant_axes: List of variant axis configurations
        axis_values: Dict mapping axis attributes to their possible values
    """

    # Fields to inherit from parent product to variants
    DEFAULT_INHERIT_FIELDS = [
        'weight', 'weight_uom', 'length', 'width', 'height', 'dimension_uom',
        'package_weight', 'package_length', 'package_width', 'package_height',
        'brand', 'manufacturer', 'country_of_origin'
    ]

    def __init__(self, product: Any, axis_values: Optional[Dict] = None):
        """
        Initialize variant generator for a product.

        Args:
            product: PIM Product document or product name/code
            axis_values: Optional dict of axis attribute codes to list of values.
                        If provided, overrides values from PIM Attribute options.
                        Format: {'color': ['red', 'blue'], 'size': ['S', 'M', 'L']}
        """
        if isinstance(product, str):
            self.product = frappe.get_doc("PIM Product", product)
        else:
            self.product = product

        self.family = None
        self.variant_axes = []
        self.axis_values = axis_values or {}
        self.generated_variants = []

        # Load product family
        if self.product.product_family:
            try:
                self.family = frappe.get_doc("Product Family", self.product.product_family)
                self.variant_axes = self.family.get_variant_axes()
            except frappe.DoesNotExistError:
                pass

    def can_generate_variants(self) -> Tuple[bool, str]:
        """
        Check if variant generation is possible for this product.

        Returns:
            Tuple of (can_generate: bool, reason: str)
        """
        if not self.family:
            return False, _("Product has no Product Family assigned")

        if not self.variant_axes:
            return False, _("Product Family has no variant axes defined")

        # Check Product Class allows variants
        if self.family.product_class:
            try:
                product_class = frappe.get_doc("Product Class", self.family.product_class)
                if hasattr(product_class, 'allow_variants') and not product_class.allow_variants:
                    return False, _("Product Class does not allow variants")
            except frappe.DoesNotExistError:
                pass

        # Check each axis has values
        for axis in self.variant_axes:
            attr_code = axis['attribute']
            values = self._get_axis_values(attr_code)
            if not values:
                return False, _("Variant axis '{0}' has no values defined").format(attr_code)

        return True, ""

    def _get_axis_values(self, attribute_code: str) -> List[Dict]:
        """
        Get possible values for a variant axis attribute.

        Args:
            attribute_code: The PIM Attribute code

        Returns:
            List of value dicts with 'value', 'label', 'color_hex', 'image', 'sort_order'
        """
        # Check if custom values were provided
        if attribute_code in self.axis_values:
            custom_values = self.axis_values[attribute_code]
            return [
                {
                    'value': v if isinstance(v, str) else v.get('value', str(v)),
                    'label': v if isinstance(v, str) else v.get('label', v.get('value', str(v))),
                    'color_hex': None if isinstance(v, str) else v.get('color_hex'),
                    'image': None if isinstance(v, str) else v.get('image'),
                    'sort_order': idx
                }
                for idx, v in enumerate(custom_values)
            ]

        # Get values from PIM Attribute options
        try:
            attribute = frappe.get_doc("PIM Attribute", attribute_code)
        except frappe.DoesNotExistError:
            return []

        # Check if attribute has options (Select, Multiselect, Color, Size types)
        if attribute.attribute_type not in ['Select', 'Multiselect', 'Color', 'Size']:
            frappe.msgprint(
                _("Warning: Attribute '{0}' is type '{1}' which may not have predefined options").format(
                    attribute_code, attribute.attribute_type
                ),
                indicator='orange'
            )
            return []

        if not attribute.options:
            return []

        values = []
        for opt in attribute.options:
            values.append({
                'value': opt.option_value,
                'label': opt.option_label or opt.option_value,
                'color_hex': opt.color_hex,
                'image': opt.image,
                'sort_order': cint(opt.sort_order)
            })

        # Sort by sort_order
        values.sort(key=lambda x: x['sort_order'])
        return values

    def get_all_axis_values(self) -> Dict[str, List[Dict]]:
        """
        Get all possible values for all variant axes.

        Returns:
            Dict mapping attribute codes to lists of value dicts
        """
        result = {}
        for axis in self.variant_axes:
            attr_code = axis['attribute']
            result[attr_code] = self._get_axis_values(attr_code)
        return result

    def get_combinations(self) -> List[List[Dict]]:
        """
        Generate cartesian product of all axis values.

        Returns:
            List of combinations, where each combination is a list of
            (attribute_code, value_dict) tuples
        """
        if not self.variant_axes:
            return []

        # Collect values for each axis in order
        axis_value_lists = []
        for axis in self.variant_axes:
            attr_code = axis['attribute']
            values = self._get_axis_values(attr_code)
            if values:
                axis_value_lists.append([
                    {'attribute': attr_code, **v} for v in values
                ])

        if not axis_value_lists:
            return []

        # Generate cartesian product
        combinations = list(itertools.product(*axis_value_lists))
        return [list(combo) for combo in combinations]

    def get_combination_count(self) -> int:
        """
        Calculate total number of variant combinations.

        Returns:
            int: Number of possible variants
        """
        if not self.variant_axes:
            return 0

        count = 1
        for axis in self.variant_axes:
            attr_code = axis['attribute']
            values = self._get_axis_values(attr_code)
            count *= len(values) if values else 0

        return count

    def generate_variant_code(self, combination: List[Dict]) -> str:
        """
        Generate a unique variant code from axis values.

        Args:
            combination: List of axis value dicts

        Returns:
            str: Generated variant code (e.g., 'prod-001-red-xl')
        """
        base_code = self.product.product_code or self.product.name or 'variant'
        base_code = base_code.lower().replace(' ', '-')

        value_parts = []
        for axis_value in combination:
            value = axis_value.get('value', '')
            # Clean value for use in code
            clean_value = value.lower().replace(' ', '-').replace('/', '-')
            clean_value = ''.join(c for c in clean_value if c.isalnum() or c == '-')
            if clean_value:
                value_parts.append(clean_value)

        if value_parts:
            return f"{base_code}-{'-'.join(value_parts)}"
        return base_code

    def generate_variant_name(self, combination: List[Dict]) -> str:
        """
        Generate a human-readable variant name from axis values.

        Args:
            combination: List of axis value dicts

        Returns:
            str: Generated variant name (e.g., 'Product Name - Red / XL')
        """
        product_name = self.product.product_name or self.product.name or 'Variant'

        # Get axis values that should be shown in name
        name_parts = []
        for axis_value in combination:
            attr_code = axis_value.get('attribute')
            # Check if axis should show in variant name
            show_in_name = True
            for axis in self.variant_axes:
                if axis['attribute'] == attr_code:
                    show_in_name = axis.get('show_in_name', True)
                    break

            if show_in_name:
                label = axis_value.get('label') or axis_value.get('value', '')
                if label:
                    name_parts.append(label)

        if name_parts:
            return f"{product_name} - {' / '.join(name_parts)}"
        return product_name

    def generate_sku(self, combination: List[Dict], counter: int = 0) -> str:
        """
        Generate a SKU for the variant.

        Args:
            combination: List of axis value dicts
            counter: Optional counter for uniqueness

        Returns:
            str: Generated SKU
        """
        base_sku = self.product.sku or self.product.product_code or 'SKU'

        value_parts = []
        for axis_value in combination:
            value = axis_value.get('value', '')
            # Create short code from value
            short = value[:3].upper() if len(value) >= 3 else value.upper()
            if short:
                value_parts.append(short)

        sku = f"{base_sku}-{'-'.join(value_parts)}"

        if counter > 0:
            sku = f"{sku}-{counter}"

        return sku

    def create_variant(
        self,
        combination: List[Dict],
        inherit_fields: Optional[List[str]] = None,
        additional_data: Optional[Dict] = None
    ) -> Any:
        """
        Create a single PIM Product Variant from a combination.

        Args:
            combination: List of axis value dicts
            inherit_fields: Fields to copy from parent product
            additional_data: Additional data to set on variant

        Returns:
            The created PIM Product Variant document
        """
        inherit_fields = inherit_fields or self.DEFAULT_INHERIT_FIELDS
        additional_data = additional_data or {}

        # Generate identifiers
        variant_code = self.generate_variant_code(combination)
        variant_name = self.generate_variant_name(combination)
        sku = self.generate_sku(combination)

        # Check for existing variant with same code
        existing = frappe.db.exists("PIM Product Variant", {"variant_code": variant_code})
        if existing:
            # Add counter to make unique
            counter = 1
            while frappe.db.exists("PIM Product Variant", {"variant_code": f"{variant_code}-{counter}"}):
                counter += 1
            variant_code = f"{variant_code}-{counter}"
            sku = self.generate_sku(combination, counter)

        # Create variant document
        variant = frappe.new_doc("PIM Product Variant")
        variant.product = self.product.name
        variant.variant_code = variant_code
        variant.variant_name = variant_name
        variant.sku = sku
        variant.is_active = 1

        # Add axis values as child table entries
        for axis_value in combination:
            variant.append("axis_values", {
                "pim_attribute": axis_value.get('attribute'),
                "value": axis_value.get('value'),
                "value_label": axis_value.get('label'),
                "color_hex": axis_value.get('color_hex'),
                "image": axis_value.get('image'),
                "sort_order": axis_value.get('sort_order', 0)
            })

        # Inherit fields from parent
        for field in inherit_fields:
            parent_value = getattr(self.product, field, None)
            if parent_value and hasattr(variant, field):
                setattr(variant, field, parent_value)

        # Apply additional data
        for key, value in additional_data.items():
            if hasattr(variant, key):
                setattr(variant, key, value)

        return variant

    def generate(
        self,
        save: bool = True,
        inherit_fields: Optional[List[str]] = None,
        skip_existing: bool = True,
        additional_data: Optional[Dict] = None
    ) -> Dict:
        """
        Generate all variant combinations and optionally save them.

        Args:
            save: If True, save variants to database
            inherit_fields: Fields to copy from parent product
            skip_existing: If True, skip variants that already exist
            additional_data: Additional data to set on all variants

        Returns:
            dict: {
                'success': bool,
                'total_combinations': int,
                'created': int,
                'skipped': int,
                'errors': int,
                'variants': list of variant names/docs
            }
        """
        result = {
            'success': True,
            'total_combinations': 0,
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'variants': [],
            'error_details': []
        }

        # Check if generation is possible
        can_generate, reason = self.can_generate_variants()
        if not can_generate:
            result['success'] = False
            result['error_details'].append(reason)
            return result

        combinations = self.get_combinations()
        result['total_combinations'] = len(combinations)

        if not combinations:
            result['success'] = False
            result['error_details'].append(_("No variant combinations generated"))
            return result

        for combination in combinations:
            try:
                # Check for existing variant
                if skip_existing:
                    variant_code = self.generate_variant_code(combination)
                    existing = frappe.db.exists(
                        "PIM Product Variant",
                        {"product": self.product.name, "variant_code": variant_code}
                    )
                    if existing:
                        result['skipped'] += 1
                        result['variants'].append(existing)
                        continue

                # Create variant
                variant = self.create_variant(
                    combination,
                    inherit_fields=inherit_fields,
                    additional_data=additional_data
                )

                if save:
                    variant.insert()
                    result['variants'].append(variant.name)
                else:
                    result['variants'].append(variant)

                result['created'] += 1
                self.generated_variants.append(variant)

            except Exception as e:
                result['errors'] += 1
                result['error_details'].append(str(e))
                frappe.log_error(
                    f"Variant generation error for {self.product.name}: {str(e)}"
                )

        if result['errors'] > 0:
            result['success'] = result['created'] > 0

        return result


def generate_variants(
    product: Any,
    axis_values: Optional[Dict] = None,
    save: bool = True,
    inherit_fields: Optional[List[str]] = None,
    skip_existing: bool = True,
    additional_data: Optional[Dict] = None
) -> Dict:
    """
    Generate variants for a PIM Product based on its Family's variant axes.

    This is the main entry point for variant generation.

    Args:
        product: PIM Product document, name, or product_code
        axis_values: Optional dict of axis attribute codes to list of values.
                    Format: {'color': ['red', 'blue'], 'size': ['S', 'M', 'L']}
        save: If True, save variants to database
        inherit_fields: Fields to copy from parent product
        skip_existing: If True, skip variants that already exist
        additional_data: Additional data to set on all variants

    Returns:
        dict: Generation result with counts and variant list

    Example:
        >>> result = generate_variants("PROD-001")
        >>> print(f"Created {result['created']} variants")

        >>> result = generate_variants(
        ...     "PROD-001",
        ...     axis_values={'color': ['red', 'blue'], 'size': ['S', 'M']}
        ... )
    """
    generator = VariantGenerator(product, axis_values=axis_values)
    return generator.generate(
        save=save,
        inherit_fields=inherit_fields,
        skip_existing=skip_existing,
        additional_data=additional_data
    )


def get_variant_matrix(product: Any) -> Dict:
    """
    Get variant matrix data for UI display (grid/table view).

    Args:
        product: PIM Product document or name

    Returns:
        dict: {
            'axes': [{'code': str, 'name': str, 'values': list}],
            'existing_variants': list of existing variant data,
            'possible_combinations': int,
            'matrix': nested structure for grid display
        }
    """
    generator = VariantGenerator(product)

    # Get axes info
    axes = []
    for axis in generator.variant_axes:
        attr_code = axis['attribute']
        try:
            attr_doc = frappe.get_doc("PIM Attribute", attr_code)
            attr_name = attr_doc.attribute_name
        except frappe.DoesNotExistError:
            attr_name = attr_code

        values = generator._get_axis_values(attr_code)
        axes.append({
            'code': attr_code,
            'name': attr_name,
            'order': axis.get('order', 0),
            'is_primary': axis.get('is_primary', False),
            'values': values
        })

    # Get existing variants
    existing_variants = []
    if generator.product:
        variants = frappe.get_all(
            "PIM Product Variant",
            filters={"product": generator.product.name},
            fields=["name", "variant_code", "variant_name", "sku", "is_active",
                   "stock_qty", "price_override", "main_image"]
        )

        for v in variants:
            # Get axis values for this variant
            axis_values = frappe.get_all(
                "PIM Variant Axis Value",
                filters={"parent": v.name},
                fields=["pim_attribute", "attribute_code", "value", "value_label"]
            )
            v['axis_values'] = {av['pim_attribute']: av['value'] for av in axis_values}
            existing_variants.append(v)

    # Build matrix structure
    matrix = _build_variant_matrix(axes, existing_variants)

    return {
        'product': generator.product.name if generator.product else None,
        'product_name': generator.product.product_name if generator.product else None,
        'family': generator.family.name if generator.family else None,
        'axes': axes,
        'existing_variants': existing_variants,
        'possible_combinations': generator.get_combination_count(),
        'existing_count': len(existing_variants),
        'matrix': matrix
    }


def _build_variant_matrix(axes: List[Dict], existing_variants: List[Dict]) -> Dict:
    """
    Build a nested matrix structure for variant display.

    For 2 axes (e.g., Color x Size), creates a 2D grid.
    For 3+ axes, creates a nested structure.

    Args:
        axes: List of axis configurations with values
        existing_variants: List of existing variant data

    Returns:
        dict: Matrix structure
    """
    if not axes:
        return {}

    # Create lookup for existing variants
    variant_lookup = {}
    for v in existing_variants:
        key = tuple(sorted(v.get('axis_values', {}).items()))
        variant_lookup[key] = v

    # For simple 2D case (2 axes)
    if len(axes) == 2:
        primary_axis = axes[0]
        secondary_axis = axes[1]

        matrix = {
            'type': '2d',
            'rows': primary_axis['values'],
            'columns': secondary_axis['values'],
            'row_axis': primary_axis['code'],
            'col_axis': secondary_axis['code'],
            'cells': {}
        }

        for row_val in primary_axis['values']:
            for col_val in secondary_axis['values']:
                key = tuple(sorted([
                    (primary_axis['code'], row_val['value']),
                    (secondary_axis['code'], col_val['value'])
                ]))
                cell_key = f"{row_val['value']}_{col_val['value']}"
                matrix['cells'][cell_key] = variant_lookup.get(key)

        return matrix

    # For 1 axis
    if len(axes) == 1:
        axis = axes[0]
        matrix = {
            'type': '1d',
            'axis': axis['code'],
            'values': axis['values'],
            'cells': {}
        }

        for val in axis['values']:
            key = tuple([(axis['code'], val['value'])])
            matrix['cells'][val['value']] = variant_lookup.get(key)

        return matrix

    # For 3+ axes, use flat list with all combinations
    combinations = list(itertools.product(*[a['values'] for a in axes]))
    matrix = {
        'type': 'multi',
        'axes': [a['code'] for a in axes],
        'combinations': []
    }

    for combo in combinations:
        combo_dict = {}
        for i, axis in enumerate(axes):
            combo_dict[axis['code']] = combo[i]

        key = tuple(sorted([(axes[i]['code'], combo[i]['value']) for i in range(len(axes))]))
        variant = variant_lookup.get(key)

        matrix['combinations'].append({
            'values': combo_dict,
            'variant': variant
        })

    return matrix


def preview_variants(
    product: Any,
    axis_values: Optional[Dict] = None
) -> List[Dict]:
    """
    Preview variant combinations without creating them.

    Args:
        product: PIM Product document or name
        axis_values: Optional custom axis values

    Returns:
        list: List of variant preview dicts with code, name, sku, axis_values
    """
    generator = VariantGenerator(product, axis_values=axis_values)

    can_generate, reason = generator.can_generate_variants()
    if not can_generate:
        return []

    combinations = generator.get_combinations()
    previews = []

    for combination in combinations:
        previews.append({
            'variant_code': generator.generate_variant_code(combination),
            'variant_name': generator.generate_variant_name(combination),
            'sku': generator.generate_sku(combination),
            'axis_values': {av['attribute']: av['value'] for av in combination},
            'axis_labels': {av['attribute']: av['label'] for av in combination}
        })

    return previews


def bulk_generate_variants(
    products: List[Any],
    save: bool = True,
    skip_existing: bool = True
) -> Dict:
    """
    Generate variants for multiple products.

    Args:
        products: List of product names or documents
        save: If True, save variants to database
        skip_existing: If True, skip variants that already exist

    Returns:
        dict: Summary of bulk generation results
    """
    results = {
        'total_products': len(products),
        'successful': 0,
        'failed': 0,
        'total_variants_created': 0,
        'details': []
    }

    for product in products:
        try:
            result = generate_variants(
                product,
                save=save,
                skip_existing=skip_existing
            )

            product_name = product if isinstance(product, str) else product.name
            results['details'].append({
                'product': product_name,
                'result': result
            })

            if result['success']:
                results['successful'] += 1
                results['total_variants_created'] += result['created']
            else:
                results['failed'] += 1

        except Exception as e:
            product_name = product if isinstance(product, str) else getattr(product, 'name', str(product))
            results['failed'] += 1
            results['details'].append({
                'product': product_name,
                'error': str(e)
            })
            frappe.log_error(f"Bulk variant generation error for {product_name}: {str(e)}")

    return results


def delete_variants(
    product: Any,
    variant_codes: Optional[List[str]] = None,
    delete_all: bool = False
) -> Dict:
    """
    Delete variants for a product.

    Args:
        product: PIM Product document or name
        variant_codes: Specific variant codes to delete
        delete_all: If True, delete all variants for the product

    Returns:
        dict: Deletion result with count
    """
    if isinstance(product, str):
        product_name = product
    else:
        product_name = product.name

    result = {
        'deleted': 0,
        'errors': 0,
        'deleted_variants': []
    }

    filters = {"product": product_name}
    if variant_codes and not delete_all:
        filters["variant_code"] = ["in", variant_codes]

    if not delete_all and not variant_codes:
        return result

    variants = frappe.get_all("PIM Product Variant", filters=filters, pluck="name")

    for variant_name in variants:
        try:
            frappe.delete_doc("PIM Product Variant", variant_name, force=True)
            result['deleted'] += 1
            result['deleted_variants'].append(variant_name)
        except Exception as e:
            result['errors'] += 1
            frappe.log_error(f"Error deleting variant {variant_name}: {str(e)}")

    return result


def regenerate_variants(
    product: Any,
    axis_values: Optional[Dict] = None,
    delete_existing: bool = True
) -> Dict:
    """
    Regenerate all variants for a product (delete existing and create new).

    Args:
        product: PIM Product document or name
        axis_values: Optional custom axis values
        delete_existing: If True, delete existing variants first

    Returns:
        dict: Combined deletion and generation result
    """
    result = {
        'deleted': 0,
        'created': 0,
        'errors': 0
    }

    if delete_existing:
        delete_result = delete_variants(product, delete_all=True)
        result['deleted'] = delete_result['deleted']

    gen_result = generate_variants(product, axis_values=axis_values, skip_existing=False)
    result['created'] = gen_result['created']
    result['errors'] = gen_result['errors']
    result['variants'] = gen_result['variants']
    result['success'] = gen_result['success']

    return result
