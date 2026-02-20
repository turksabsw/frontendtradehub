# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Unit tests for PIM Variant Generator Cartesian Product Logic

Tests the variant generation system including:
- VariantGenerator class initialization
- Cartesian product generation
- Variant code/name/SKU generation
- Single and multi-axis variant creation
- Bulk variant operations
- Edge cases and error handling
"""

import itertools
import frappe
from frappe.tests.utils import FrappeTestCase

from tr_tradehub.pim.variant_generator import (
    VariantGenerator,
    generate_variants,
    get_variant_matrix,
    preview_variants,
    bulk_generate_variants,
    delete_variants,
    regenerate_variants,
)


class TestVariantGenerator(FrappeTestCase):
    """Test cases for PIM Variant Generator"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures once for all tests"""
        super().setUpClass()
        cls._create_test_fixtures()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures after all tests"""
        cls._cleanup_test_fixtures()
        super().tearDownClass()

    @classmethod
    def _create_test_fixtures(cls):
        """Create test data fixtures"""
        # Create test attribute group
        if not frappe.db.exists("PIM Attribute Group", "test_variant_group"):
            frappe.get_doc({
                "doctype": "PIM Attribute Group",
                "group_name": "Test Variant Group",
                "group_code": "test_variant_group",
            }).insert(ignore_permissions=True)

        # Create test attributes for variant axes
        # Color attribute with options
        if not frappe.db.exists("PIM Attribute", "test_color"):
            frappe.get_doc({
                "doctype": "PIM Attribute",
                "attribute_name": "Test Color",
                "attribute_code": "test_color",
                "attribute_type": "Color",
                "use_for_variant": 1,
                "options": [
                    {"option_value": "red", "option_label": "Red", "color_hex": "#FF0000", "sort_order": 1},
                    {"option_value": "blue", "option_label": "Blue", "color_hex": "#0000FF", "sort_order": 2},
                    {"option_value": "green", "option_label": "Green", "color_hex": "#00FF00", "sort_order": 3},
                ]
            }).insert(ignore_permissions=True)

        # Size attribute with options
        if not frappe.db.exists("PIM Attribute", "test_size"):
            frappe.get_doc({
                "doctype": "PIM Attribute",
                "attribute_name": "Test Size",
                "attribute_code": "test_size",
                "attribute_type": "Size",
                "use_for_variant": 1,
                "options": [
                    {"option_value": "S", "option_label": "Small", "sort_order": 1},
                    {"option_value": "M", "option_label": "Medium", "sort_order": 2},
                    {"option_value": "L", "option_label": "Large", "sort_order": 3},
                ]
            }).insert(ignore_permissions=True)

        # Material attribute with options
        if not frappe.db.exists("PIM Attribute", "test_material"):
            frappe.get_doc({
                "doctype": "PIM Attribute",
                "attribute_name": "Test Material",
                "attribute_code": "test_material",
                "attribute_type": "Select",
                "use_for_variant": 1,
                "options": [
                    {"option_value": "cotton", "option_label": "Cotton", "sort_order": 1},
                    {"option_value": "polyester", "option_label": "Polyester", "sort_order": 2},
                ]
            }).insert(ignore_permissions=True)

        # Text attribute (non-variant type for testing)
        if not frappe.db.exists("PIM Attribute", "test_variant_text"):
            frappe.get_doc({
                "doctype": "PIM Attribute",
                "attribute_name": "Test Variant Text",
                "attribute_code": "test_variant_text",
                "attribute_type": "Text",
                "use_for_variant": 0,
            }).insert(ignore_permissions=True)

        # Create test product class
        if not frappe.db.exists("Product Class", "test_variant_class"):
            frappe.get_doc({
                "doctype": "Product Class",
                "class_name": "Test Variant Class",
                "class_code": "test_variant_class",
                "allow_variants": 1,
            }).insert(ignore_permissions=True)

        # Create test product class that doesn't allow variants
        if not frappe.db.exists("Product Class", "test_no_variant_class"):
            frappe.get_doc({
                "doctype": "Product Class",
                "class_name": "Test No Variant Class",
                "class_code": "test_no_variant_class",
                "allow_variants": 0,
            }).insert(ignore_permissions=True)

        # Create test product family with 2 variant axes (Color x Size)
        if not frappe.db.exists("Product Family", "test_variant_family"):
            frappe.get_doc({
                "doctype": "Product Family",
                "family_name": "Test Variant Family",
                "family_code": "test_variant_family",
                "product_class": "test_variant_class",
                "family_attributes": [
                    {"pim_attribute": "test_color", "is_variant": 1, "sort_order": 1},
                    {"pim_attribute": "test_size", "is_variant": 1, "sort_order": 2},
                ],
                "variant_axes": [
                    {"pim_attribute": "test_color", "axis_order": 1, "is_primary_axis": 1, "show_in_variant_name": 1},
                    {"pim_attribute": "test_size", "axis_order": 2, "is_primary_axis": 0, "show_in_variant_name": 1},
                ],
            }).insert(ignore_permissions=True)

        # Create test product family with 1 variant axis
        if not frappe.db.exists("Product Family", "test_single_axis_family"):
            frappe.get_doc({
                "doctype": "Product Family",
                "family_name": "Test Single Axis Family",
                "family_code": "test_single_axis_family",
                "product_class": "test_variant_class",
                "variant_axes": [
                    {"pim_attribute": "test_color", "axis_order": 1, "is_primary_axis": 1, "show_in_variant_name": 1},
                ],
            }).insert(ignore_permissions=True)

        # Create test product family with 3 variant axes
        if not frappe.db.exists("Product Family", "test_triple_axis_family"):
            frappe.get_doc({
                "doctype": "Product Family",
                "family_name": "Test Triple Axis Family",
                "family_code": "test_triple_axis_family",
                "product_class": "test_variant_class",
                "variant_axes": [
                    {"pim_attribute": "test_color", "axis_order": 1, "is_primary_axis": 1, "show_in_variant_name": 1},
                    {"pim_attribute": "test_size", "axis_order": 2, "is_primary_axis": 0, "show_in_variant_name": 1},
                    {"pim_attribute": "test_material", "axis_order": 3, "is_primary_axis": 0, "show_in_variant_name": 1},
                ],
            }).insert(ignore_permissions=True)

        # Create test product family with no variant axes
        if not frappe.db.exists("Product Family", "test_no_axis_family"):
            frappe.get_doc({
                "doctype": "Product Family",
                "family_name": "Test No Axis Family",
                "family_code": "test_no_axis_family",
                "product_class": "test_variant_class",
            }).insert(ignore_permissions=True)

        # Create test product family with non-variant class
        if not frappe.db.exists("Product Family", "test_no_variant_family"):
            frappe.get_doc({
                "doctype": "Product Family",
                "family_name": "Test No Variant Family",
                "family_code": "test_no_variant_family",
                "product_class": "test_no_variant_class",
                "variant_axes": [
                    {"pim_attribute": "test_color", "axis_order": 1, "is_primary_axis": 1},
                ],
            }).insert(ignore_permissions=True)

        frappe.db.commit()

    @classmethod
    def _cleanup_test_fixtures(cls):
        """Remove test fixtures"""
        # Delete test variants
        for name in frappe.get_all("PIM Product Variant", filters={"product": ["like", "test_vg_%"]}, pluck="name"):
            frappe.delete_doc("PIM Product Variant", name, force=True, ignore_permissions=True)

        # Delete test products
        for name in frappe.get_all("PIM Product", filters={"product_code": ["like", "test_vg_%"]}, pluck="name"):
            frappe.delete_doc("PIM Product", name, force=True, ignore_permissions=True)

        # Delete test families
        for code in ["test_variant_family", "test_single_axis_family", "test_triple_axis_family",
                     "test_no_axis_family", "test_no_variant_family"]:
            if frappe.db.exists("Product Family", code):
                frappe.delete_doc("Product Family", code, force=True, ignore_permissions=True)

        # Delete test product classes
        for code in ["test_variant_class", "test_no_variant_class"]:
            if frappe.db.exists("Product Class", code):
                frappe.delete_doc("Product Class", code, force=True, ignore_permissions=True)

        # Delete test attributes
        for code in ["test_color", "test_size", "test_material", "test_variant_text"]:
            if frappe.db.exists("PIM Attribute", code):
                frappe.delete_doc("PIM Attribute", code, force=True, ignore_permissions=True)

        # Delete test attribute group
        if frappe.db.exists("PIM Attribute Group", "test_variant_group"):
            frappe.delete_doc("PIM Attribute Group", "test_variant_group", force=True, ignore_permissions=True)

        frappe.db.commit()

    def setUp(self):
        """Set up for each test"""
        # Clean up any existing test products and variants from previous runs
        for name in frappe.get_all("PIM Product Variant", filters={"product": ["like", "test_vg_%"]}, pluck="name"):
            frappe.delete_doc("PIM Product Variant", name, force=True, ignore_permissions=True)
        for name in frappe.get_all("PIM Product", filters={"product_code": ["like", "test_vg_%"]}, pluck="name"):
            frappe.delete_doc("PIM Product", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_test_product(
        self,
        product_code,
        product_family=None,
        product_name=None,
        sku=None,
        weight=None,
        brand=None,
    ):
        """Helper to create a test product"""
        doc = frappe.get_doc({
            "doctype": "PIM Product",
            "product_name": product_name or f"Test Product {product_code}",
            "product_code": product_code,
            "product_family": product_family,
            "sku": sku,
            "weight": weight,
            "brand": brand,
        })
        doc.flags.ignore_permissions = True
        doc.flags.ignore_mandatory = True
        doc.insert()
        return doc

    # =========================================================================
    # INITIALIZATION TESTS
    # =========================================================================

    def test_generator_init_with_product_doc(self):
        """Test initializing generator with product document"""
        product = self._create_test_product("test_vg_001", product_family="test_variant_family")

        generator = VariantGenerator(product)

        self.assertEqual(generator.product.name, product.name)
        self.assertIsNotNone(generator.family)
        self.assertEqual(len(generator.variant_axes), 2)

    def test_generator_init_with_product_name(self):
        """Test initializing generator with product name string"""
        product = self._create_test_product("test_vg_002", product_family="test_variant_family")

        generator = VariantGenerator(product.name)

        self.assertEqual(generator.product.name, product.name)

    def test_generator_init_no_family(self):
        """Test generator with product that has no family"""
        product = self._create_test_product("test_vg_003")

        generator = VariantGenerator(product)

        self.assertIsNone(generator.family)
        self.assertEqual(len(generator.variant_axes), 0)

    def test_generator_init_with_custom_axis_values(self):
        """Test generator with custom axis values override"""
        product = self._create_test_product("test_vg_004", product_family="test_variant_family")

        custom_values = {
            "test_color": ["red", "blue"],
            "test_size": ["S", "M"],
        }
        generator = VariantGenerator(product, axis_values=custom_values)

        self.assertEqual(generator.axis_values, custom_values)

    # =========================================================================
    # CAN_GENERATE_VARIANTS TESTS
    # =========================================================================

    def test_can_generate_variants_true(self):
        """Test can_generate_variants returns True for valid setup"""
        product = self._create_test_product("test_vg_010", product_family="test_variant_family")

        generator = VariantGenerator(product)
        can_generate, reason = generator.can_generate_variants()

        self.assertTrue(can_generate)
        self.assertEqual(reason, "")

    def test_can_generate_variants_no_family(self):
        """Test can_generate_variants returns False when no family"""
        product = self._create_test_product("test_vg_011")

        generator = VariantGenerator(product)
        can_generate, reason = generator.can_generate_variants()

        self.assertFalse(can_generate)
        self.assertIn("no Product Family", reason)

    def test_can_generate_variants_no_axes(self):
        """Test can_generate_variants returns False when no variant axes"""
        product = self._create_test_product("test_vg_012", product_family="test_no_axis_family")

        generator = VariantGenerator(product)
        can_generate, reason = generator.can_generate_variants()

        self.assertFalse(can_generate)
        self.assertIn("no variant axes", reason)

    def test_can_generate_variants_class_disallows(self):
        """Test can_generate_variants returns False when class disallows variants"""
        product = self._create_test_product("test_vg_013", product_family="test_no_variant_family")

        generator = VariantGenerator(product)
        can_generate, reason = generator.can_generate_variants()

        self.assertFalse(can_generate)
        self.assertIn("does not allow variants", reason)

    # =========================================================================
    # CARTESIAN PRODUCT TESTS - CORE LOGIC
    # =========================================================================

    def test_cartesian_product_two_axes(self):
        """Test cartesian product with 2 axes (Color x Size = 3 x 3 = 9)"""
        product = self._create_test_product("test_vg_020", product_family="test_variant_family")

        generator = VariantGenerator(product)
        combinations = generator.get_combinations()

        # Color (3) x Size (3) = 9 combinations
        self.assertEqual(len(combinations), 9)

        # Verify each combination has 2 axis values
        for combo in combinations:
            self.assertEqual(len(combo), 2)

    def test_cartesian_product_single_axis(self):
        """Test cartesian product with 1 axis (Color = 3)"""
        product = self._create_test_product("test_vg_021", product_family="test_single_axis_family")

        generator = VariantGenerator(product)
        combinations = generator.get_combinations()

        # Color (3) = 3 combinations
        self.assertEqual(len(combinations), 3)

        # Verify each combination has 1 axis value
        for combo in combinations:
            self.assertEqual(len(combo), 1)

    def test_cartesian_product_three_axes(self):
        """Test cartesian product with 3 axes (Color x Size x Material = 3 x 3 x 2 = 18)"""
        product = self._create_test_product("test_vg_022", product_family="test_triple_axis_family")

        generator = VariantGenerator(product)
        combinations = generator.get_combinations()

        # Color (3) x Size (3) x Material (2) = 18 combinations
        self.assertEqual(len(combinations), 18)

        # Verify each combination has 3 axis values
        for combo in combinations:
            self.assertEqual(len(combo), 3)

    def test_cartesian_product_custom_values(self):
        """Test cartesian product with custom axis values"""
        product = self._create_test_product("test_vg_023", product_family="test_variant_family")

        custom_values = {
            "test_color": ["red", "blue"],  # 2 instead of 3
            "test_size": ["S"],  # 1 instead of 3
        }
        generator = VariantGenerator(product, axis_values=custom_values)
        combinations = generator.get_combinations()

        # 2 x 1 = 2 combinations
        self.assertEqual(len(combinations), 2)

    def test_cartesian_product_no_axes(self):
        """Test cartesian product returns empty for no axes"""
        product = self._create_test_product("test_vg_024", product_family="test_no_axis_family")

        generator = VariantGenerator(product)
        combinations = generator.get_combinations()

        self.assertEqual(len(combinations), 0)

    def test_cartesian_product_contains_all_permutations(self):
        """Test that cartesian product contains all expected permutations"""
        product = self._create_test_product("test_vg_025", product_family="test_variant_family")

        generator = VariantGenerator(product)
        combinations = generator.get_combinations()

        # Extract all (color, size) pairs
        pairs = set()
        for combo in combinations:
            color = None
            size = None
            for axis_val in combo:
                if axis_val['attribute'] == 'test_color':
                    color = axis_val['value']
                elif axis_val['attribute'] == 'test_size':
                    size = axis_val['value']
            pairs.add((color, size))

        # Verify all expected combinations exist
        expected_colors = {'red', 'blue', 'green'}
        expected_sizes = {'S', 'M', 'L'}
        expected_pairs = set(itertools.product(expected_colors, expected_sizes))

        self.assertEqual(pairs, expected_pairs)

    def test_get_combination_count(self):
        """Test get_combination_count returns correct count"""
        product = self._create_test_product("test_vg_026", product_family="test_variant_family")

        generator = VariantGenerator(product)
        count = generator.get_combination_count()

        # Color (3) x Size (3) = 9
        self.assertEqual(count, 9)

    def test_get_combination_count_single_axis(self):
        """Test get_combination_count for single axis"""
        product = self._create_test_product("test_vg_027", product_family="test_single_axis_family")

        generator = VariantGenerator(product)
        count = generator.get_combination_count()

        # Color (3)
        self.assertEqual(count, 3)

    def test_get_combination_count_no_axes(self):
        """Test get_combination_count returns 0 for no axes"""
        product = self._create_test_product("test_vg_028", product_family="test_no_axis_family")

        generator = VariantGenerator(product)
        count = generator.get_combination_count()

        self.assertEqual(count, 0)

    # =========================================================================
    # VARIANT CODE/NAME/SKU GENERATION TESTS
    # =========================================================================

    def test_generate_variant_code(self):
        """Test variant code generation from axis values"""
        product = self._create_test_product(
            "test_vg_030",
            product_code="test_vg_030",
            product_family="test_variant_family"
        )

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
            {"attribute": "test_size", "value": "M", "label": "Medium"},
        ]
        code = generator.generate_variant_code(combination)

        self.assertIn("test_vg_030", code.lower())
        self.assertIn("red", code.lower())
        self.assertIn("m", code.lower())

    def test_generate_variant_code_special_chars(self):
        """Test variant code strips special characters"""
        product = self._create_test_product("test_vg_031", product_family="test_variant_family")

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "navy/blue", "label": "Navy Blue"},
        ]
        code = generator.generate_variant_code(combination)

        # Special chars like '/' should be converted to '-' or removed
        self.assertNotIn("/", code)

    def test_generate_variant_name(self):
        """Test variant name generation"""
        product = self._create_test_product(
            "test_vg_032",
            product_name="Test Product 032",
            product_family="test_variant_family"
        )

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
            {"attribute": "test_size", "value": "M", "label": "Medium"},
        ]
        name = generator.generate_variant_name(combination)

        self.assertIn("Test Product 032", name)
        self.assertIn("Red", name)
        self.assertIn("Medium", name)

    def test_generate_variant_name_separator(self):
        """Test variant name uses proper separator"""
        product = self._create_test_product(
            "test_vg_033",
            product_name="Test Product",
            product_family="test_variant_family"
        )

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
            {"attribute": "test_size", "value": "M", "label": "Medium"},
        ]
        name = generator.generate_variant_name(combination)

        # Should contain separator between product name and variants
        self.assertIn(" - ", name)
        # Should contain separator between axis values
        self.assertIn(" / ", name)

    def test_generate_sku(self):
        """Test SKU generation"""
        product = self._create_test_product(
            "test_vg_034",
            sku="PROD-001",
            product_family="test_variant_family"
        )

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
            {"attribute": "test_size", "value": "M", "label": "Medium"},
        ]
        sku = generator.generate_sku(combination)

        self.assertIn("PROD-001", sku)
        self.assertIn("RED", sku)  # First 3 chars uppercase

    def test_generate_sku_with_counter(self):
        """Test SKU generation with counter for uniqueness"""
        product = self._create_test_product(
            "test_vg_035",
            sku="PROD-002",
            product_family="test_variant_family"
        )

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
        ]
        sku = generator.generate_sku(combination, counter=5)

        self.assertIn("-5", sku)

    # =========================================================================
    # CREATE_VARIANT TESTS
    # =========================================================================

    def test_create_variant_basic(self):
        """Test creating a single variant"""
        product = self._create_test_product("test_vg_040", product_family="test_variant_family")

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red", "sort_order": 1},
            {"attribute": "test_size", "value": "M", "label": "Medium", "sort_order": 2},
        ]
        variant = generator.create_variant(combination)

        self.assertEqual(variant.product, product.name)
        self.assertEqual(len(variant.axis_values), 2)
        self.assertEqual(variant.is_active, 1)

    def test_create_variant_inherits_fields(self):
        """Test that variant inherits parent product fields"""
        product = self._create_test_product(
            "test_vg_041",
            product_family="test_variant_family",
            weight=2.5,
            brand="Test Brand",
        )

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
        ]
        variant = generator.create_variant(combination)

        self.assertEqual(variant.weight, 2.5)
        self.assertEqual(variant.brand, "Test Brand")

    def test_create_variant_with_custom_inherit_fields(self):
        """Test creating variant with custom inherit field list"""
        product = self._create_test_product(
            "test_vg_042",
            product_family="test_variant_family",
            weight=3.0,
        )

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
        ]
        # Only inherit weight, not brand
        variant = generator.create_variant(combination, inherit_fields=["weight"])

        self.assertEqual(variant.weight, 3.0)

    def test_create_variant_with_additional_data(self):
        """Test creating variant with additional data"""
        product = self._create_test_product("test_vg_043", product_family="test_variant_family")

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red"},
        ]
        additional = {"stock_qty": 100}
        variant = generator.create_variant(combination, additional_data=additional)

        self.assertEqual(variant.stock_qty, 100)

    def test_create_variant_axis_values_stored(self):
        """Test that axis values are stored correctly in variant"""
        product = self._create_test_product("test_vg_044", product_family="test_variant_family")

        generator = VariantGenerator(product)
        combination = [
            {"attribute": "test_color", "value": "red", "label": "Red", "color_hex": "#FF0000"},
            {"attribute": "test_size", "value": "M", "label": "Medium"},
        ]
        variant = generator.create_variant(combination)

        # Check axis values are stored correctly
        axis_values = {av.pim_attribute: av.value for av in variant.axis_values}
        self.assertEqual(axis_values.get("test_color"), "red")
        self.assertEqual(axis_values.get("test_size"), "M")

    # =========================================================================
    # GENERATE (BULK) TESTS
    # =========================================================================

    def test_generate_all_variants(self):
        """Test generating all variant combinations"""
        product = self._create_test_product("test_vg_050", product_family="test_variant_family")

        generator = VariantGenerator(product)
        result = generator.generate(save=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["total_combinations"], 9)
        self.assertEqual(result["created"], 9)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(len(result["variants"]), 9)

    def test_generate_skip_existing(self):
        """Test that generate skips existing variants"""
        product = self._create_test_product("test_vg_051", product_family="test_variant_family")

        # Generate once
        generator = VariantGenerator(product)
        generator.generate(save=True)

        # Generate again with skip_existing=True (default)
        generator2 = VariantGenerator(product)
        result = generator2.generate(save=True, skip_existing=True)

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], 9)

    def test_generate_no_save(self):
        """Test generating variants without saving"""
        product = self._create_test_product("test_vg_052", product_family="test_variant_family")

        generator = VariantGenerator(product)
        result = generator.generate(save=False)

        # Should return variant docs, not names
        self.assertEqual(len(result["variants"]), 9)
        for variant in result["variants"]:
            self.assertIsNotNone(variant.variant_code)

        # Verify nothing was saved
        saved = frappe.get_all("PIM Product Variant", filters={"product": product.name})
        self.assertEqual(len(saved), 0)

    def test_generate_fails_without_family(self):
        """Test generate returns error without family"""
        product = self._create_test_product("test_vg_053")

        generator = VariantGenerator(product)
        result = generator.generate(save=True)

        self.assertFalse(result["success"])
        self.assertIn("no Product Family", result["error_details"][0])

    def test_generate_with_custom_axis_values(self):
        """Test generate with custom axis values"""
        product = self._create_test_product("test_vg_054", product_family="test_variant_family")

        custom_values = {
            "test_color": ["red"],
            "test_size": ["S", "M"],
        }
        generator = VariantGenerator(product, axis_values=custom_values)
        result = generator.generate(save=True)

        # 1 x 2 = 2 combinations
        self.assertEqual(result["total_combinations"], 2)
        self.assertEqual(result["created"], 2)

    # =========================================================================
    # GENERATE_VARIANTS FUNCTION TESTS
    # =========================================================================

    def test_generate_variants_function(self):
        """Test the main generate_variants function"""
        product = self._create_test_product("test_vg_060", product_family="test_variant_family")

        result = generate_variants(product)

        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 9)

    def test_generate_variants_by_name(self):
        """Test generate_variants with product name string"""
        product = self._create_test_product("test_vg_061", product_family="test_variant_family")

        result = generate_variants(product.name)

        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 9)

    def test_generate_variants_with_custom_values(self):
        """Test generate_variants with custom axis values"""
        product = self._create_test_product("test_vg_062", product_family="test_variant_family")

        result = generate_variants(
            product,
            axis_values={"test_color": ["red", "blue"]}
        )

        # Only color axis provided, but family has both color and size
        # Should use custom colors and original sizes from attribute options
        self.assertTrue(result["success"])
        # 2 colors x 3 sizes = 6
        self.assertEqual(result["created"], 6)

    # =========================================================================
    # GET_VARIANT_MATRIX TESTS
    # =========================================================================

    def test_get_variant_matrix_2d(self):
        """Test get_variant_matrix returns 2D matrix for 2 axes"""
        product = self._create_test_product("test_vg_070", product_family="test_variant_family")

        matrix = get_variant_matrix(product)

        self.assertEqual(matrix["axes"][0]["code"], "test_color")
        self.assertEqual(matrix["axes"][1]["code"], "test_size")
        self.assertEqual(matrix["possible_combinations"], 9)
        self.assertEqual(matrix["matrix"]["type"], "2d")

    def test_get_variant_matrix_1d(self):
        """Test get_variant_matrix returns 1D matrix for 1 axis"""
        product = self._create_test_product("test_vg_071", product_family="test_single_axis_family")

        matrix = get_variant_matrix(product)

        self.assertEqual(len(matrix["axes"]), 1)
        self.assertEqual(matrix["possible_combinations"], 3)
        self.assertEqual(matrix["matrix"]["type"], "1d")

    def test_get_variant_matrix_multi(self):
        """Test get_variant_matrix returns multi matrix for 3+ axes"""
        product = self._create_test_product("test_vg_072", product_family="test_triple_axis_family")

        matrix = get_variant_matrix(product)

        self.assertEqual(len(matrix["axes"]), 3)
        self.assertEqual(matrix["possible_combinations"], 18)
        self.assertEqual(matrix["matrix"]["type"], "multi")

    def test_get_variant_matrix_with_existing_variants(self):
        """Test get_variant_matrix includes existing variants"""
        product = self._create_test_product("test_vg_073", product_family="test_variant_family")

        # Generate variants first
        generate_variants(product)

        matrix = get_variant_matrix(product)

        self.assertEqual(matrix["existing_count"], 9)
        self.assertEqual(len(matrix["existing_variants"]), 9)

    # =========================================================================
    # PREVIEW_VARIANTS TESTS
    # =========================================================================

    def test_preview_variants(self):
        """Test preview_variants returns preview data without creating"""
        product = self._create_test_product("test_vg_080", product_family="test_variant_family")

        previews = preview_variants(product)

        self.assertEqual(len(previews), 9)

        # Verify preview structure
        for preview in previews:
            self.assertIn("variant_code", preview)
            self.assertIn("variant_name", preview)
            self.assertIn("sku", preview)
            self.assertIn("axis_values", preview)
            self.assertIn("axis_labels", preview)

        # Verify no variants were created
        saved = frappe.get_all("PIM Product Variant", filters={"product": product.name})
        self.assertEqual(len(saved), 0)

    def test_preview_variants_custom_values(self):
        """Test preview_variants with custom axis values"""
        product = self._create_test_product("test_vg_081", product_family="test_variant_family")

        custom_values = {"test_color": ["red"]}
        previews = preview_variants(product, axis_values=custom_values)

        # 1 color x 3 sizes = 3
        self.assertEqual(len(previews), 3)

    def test_preview_variants_no_family(self):
        """Test preview_variants returns empty list without family"""
        product = self._create_test_product("test_vg_082")

        previews = preview_variants(product)

        self.assertEqual(len(previews), 0)

    # =========================================================================
    # BULK_GENERATE_VARIANTS TESTS
    # =========================================================================

    def test_bulk_generate_variants(self):
        """Test bulk variant generation for multiple products"""
        products = []
        for i in range(3):
            p = self._create_test_product(f"test_vg_09{i}", product_family="test_variant_family")
            products.append(p.name)

        results = bulk_generate_variants(products)

        self.assertEqual(results["total_products"], 3)
        self.assertEqual(results["successful"], 3)
        self.assertEqual(results["failed"], 0)
        self.assertEqual(results["total_variants_created"], 27)  # 9 x 3

    def test_bulk_generate_with_errors(self):
        """Test bulk generate handles errors gracefully"""
        products = [
            self._create_test_product("test_vg_095", product_family="test_variant_family").name,
            "non_existent_product",
        ]

        results = bulk_generate_variants(products)

        self.assertEqual(results["successful"], 1)
        self.assertEqual(results["failed"], 1)

    # =========================================================================
    # DELETE_VARIANTS TESTS
    # =========================================================================

    def test_delete_all_variants(self):
        """Test deleting all variants for a product"""
        product = self._create_test_product("test_vg_100", product_family="test_variant_family")
        generate_variants(product)

        result = delete_variants(product, delete_all=True)

        self.assertEqual(result["deleted"], 9)

        # Verify deletion
        remaining = frappe.get_all("PIM Product Variant", filters={"product": product.name})
        self.assertEqual(len(remaining), 0)

    def test_delete_specific_variants(self):
        """Test deleting specific variants by code"""
        product = self._create_test_product("test_vg_101", product_family="test_variant_family")
        generate_variants(product)

        # Get variant codes
        variants = frappe.get_all(
            "PIM Product Variant",
            filters={"product": product.name},
            fields=["variant_code"],
            limit=2
        )
        codes_to_delete = [v.variant_code for v in variants]

        result = delete_variants(product, variant_codes=codes_to_delete)

        self.assertEqual(result["deleted"], 2)

        # Verify correct number remain
        remaining = frappe.get_all("PIM Product Variant", filters={"product": product.name})
        self.assertEqual(len(remaining), 7)

    def test_delete_variants_no_args(self):
        """Test delete_variants does nothing without delete_all or variant_codes"""
        product = self._create_test_product("test_vg_102", product_family="test_variant_family")
        generate_variants(product)

        result = delete_variants(product)

        self.assertEqual(result["deleted"], 0)

        # Verify nothing deleted
        remaining = frappe.get_all("PIM Product Variant", filters={"product": product.name})
        self.assertEqual(len(remaining), 9)

    # =========================================================================
    # REGENERATE_VARIANTS TESTS
    # =========================================================================

    def test_regenerate_variants(self):
        """Test regenerating variants (delete + create)"""
        product = self._create_test_product("test_vg_110", product_family="test_variant_family")
        generate_variants(product)

        # Get original variant names
        original_variants = frappe.get_all(
            "PIM Product Variant",
            filters={"product": product.name},
            pluck="name"
        )

        result = regenerate_variants(product)

        self.assertEqual(result["deleted"], 9)
        self.assertEqual(result["created"], 9)
        self.assertTrue(result["success"])

    def test_regenerate_variants_with_new_values(self):
        """Test regenerating with different axis values"""
        product = self._create_test_product("test_vg_111", product_family="test_variant_family")
        generate_variants(product)

        # Regenerate with fewer values
        result = regenerate_variants(
            product,
            axis_values={"test_color": ["red"], "test_size": ["S"]}
        )

        self.assertEqual(result["deleted"], 9)
        self.assertEqual(result["created"], 1)  # 1 x 1

    def test_regenerate_without_delete(self):
        """Test regenerate without deleting existing"""
        product = self._create_test_product("test_vg_112", product_family="test_variant_family")
        generate_variants(product)

        result = regenerate_variants(product, delete_existing=False)

        self.assertEqual(result["deleted"], 0)
        # No new variants created because skip_existing=False but all already exist
        self.assertEqual(result["created"], 0)

    # =========================================================================
    # EDGE CASE TESTS
    # =========================================================================

    def test_empty_axis_values(self):
        """Test handling of empty axis values"""
        product = self._create_test_product("test_vg_120", product_family="test_variant_family")

        generator = VariantGenerator(product, axis_values={"test_color": []})

        combinations = generator.get_combinations()

        # Empty color axis means no combinations possible
        self.assertEqual(len(combinations), 0)

    def test_axis_values_with_dict_format(self):
        """Test axis values with dict format (value + label)"""
        product = self._create_test_product("test_vg_121", product_family="test_variant_family")

        custom_values = {
            "test_color": [
                {"value": "custom_red", "label": "Custom Red"},
                {"value": "custom_blue", "label": "Custom Blue"},
            ]
        }
        generator = VariantGenerator(product, axis_values=custom_values)

        combinations = generator.get_combinations()
        # 2 colors x 3 sizes = 6
        self.assertEqual(len(combinations), 6)

        # Verify labels are preserved
        color_values = [c for combo in combinations for c in combo if c['attribute'] == 'test_color']
        labels = {c['label'] for c in color_values}
        self.assertIn("Custom Red", labels)
        self.assertIn("Custom Blue", labels)

    def test_non_option_attribute_warning(self):
        """Test that non-option attributes give warning"""
        product = self._create_test_product("test_vg_122", product_family="test_variant_family")

        # Create a family with a Text attribute as variant axis (unusual)
        if frappe.db.exists("Product Family", "test_text_axis_family"):
            frappe.delete_doc("Product Family", "test_text_axis_family", force=True)

        frappe.get_doc({
            "doctype": "Product Family",
            "family_name": "Test Text Axis Family",
            "family_code": "test_text_axis_family",
            "product_class": "test_variant_class",
            "variant_axes": [
                {"pim_attribute": "test_variant_text", "axis_order": 1},
            ],
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        product2 = self._create_test_product("test_vg_123", product_family="test_text_axis_family")
        generator = VariantGenerator(product2)

        # Text attributes have no options, so should return empty
        values = generator._get_axis_values("test_variant_text")
        self.assertEqual(len(values), 0)

        # Clean up
        frappe.delete_doc("Product Family", "test_text_axis_family", force=True)

    def test_variant_axis_sort_order(self):
        """Test that axis values respect sort_order"""
        product = self._create_test_product("test_vg_124", product_family="test_single_axis_family")

        generator = VariantGenerator(product)
        values = generator._get_axis_values("test_color")

        # Should be sorted by sort_order: red(1), blue(2), green(3)
        self.assertEqual(values[0]["value"], "red")
        self.assertEqual(values[1]["value"], "blue")
        self.assertEqual(values[2]["value"], "green")

    def test_duplicate_variant_handling(self):
        """Test that duplicate variants are handled with unique codes"""
        product = self._create_test_product("test_vg_125", product_family="test_single_axis_family")

        # Manually create a variant with expected code
        first_code = f"{product.product_code.lower()}-red"
        frappe.get_doc({
            "doctype": "PIM Product Variant",
            "product": product.name,
            "variant_code": first_code,
            "variant_name": "Test Variant",
            "sku": "TEST-SKU",
        }).insert(ignore_permissions=True)

        # Now generate - should handle the duplicate code
        generator = VariantGenerator(product)
        combination = [{"attribute": "test_color", "value": "red", "label": "Red"}]
        variant = generator.create_variant(combination)
        variant.insert()

        # Should have a different code
        self.assertNotEqual(variant.variant_code, first_code)
        self.assertIn("-1", variant.variant_code)

    def test_get_all_axis_values(self):
        """Test get_all_axis_values returns all axis values"""
        product = self._create_test_product("test_vg_126", product_family="test_variant_family")

        generator = VariantGenerator(product)
        all_values = generator.get_all_axis_values()

        self.assertIn("test_color", all_values)
        self.assertIn("test_size", all_values)
        self.assertEqual(len(all_values["test_color"]), 3)
        self.assertEqual(len(all_values["test_size"]), 3)
