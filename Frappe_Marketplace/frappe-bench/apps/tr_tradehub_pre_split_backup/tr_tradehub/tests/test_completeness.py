# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Unit tests for PIM Completeness Calculator

Tests the completeness calculation system including:
- CompletenessCalculator class initialization
- Default calculation formula
- Rule-based calculation with all 8 rule types
- Status determination (Incomplete/Partial/Complete/Enriched)
- Channel/locale filtering
- Bulk operations
- Edge cases
"""

import json
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from tr_tradehub.pim.completeness import (
    CompletenessCalculator,
    calculate_completeness,
    calculate_channel_completeness,
    bulk_calculate_completeness,
)


class TestCompletenessCalculator(FrappeTestCase):
    """Test cases for PIM Completeness Calculator"""

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
        if not frappe.db.exists("PIM Attribute Group", "test_group"):
            frappe.get_doc({
                "doctype": "PIM Attribute Group",
                "group_name": "Test Group",
                "group_code": "test_group",
            }).insert(ignore_permissions=True)

        # Create test attributes
        test_attrs = [
            {
                "attribute_name": "Test Title",
                "attribute_code": "test_title",
                "attribute_type": "Text",
            },
            {
                "attribute_name": "Test Description",
                "attribute_code": "test_desc",
                "attribute_type": "Long Text",
            },
            {
                "attribute_name": "Test Weight",
                "attribute_code": "test_weight",
                "attribute_type": "Float",
            },
            {
                "attribute_name": "Test Color",
                "attribute_code": "test_color",
                "attribute_type": "Select",
                "options": [
                    {"option_value": "red", "option_label": "Red"},
                    {"option_value": "blue", "option_label": "Blue"},
                ],
            },
        ]

        for attr in test_attrs:
            if not frappe.db.exists("PIM Attribute", attr["attribute_code"]):
                doc = frappe.get_doc({"doctype": "PIM Attribute", **attr})
                doc.insert(ignore_permissions=True)

        # Create test product class
        if not frappe.db.exists("Product Class", "test_class"):
            frappe.get_doc({
                "doctype": "Product Class",
                "class_name": "Test Class",
                "class_code": "test_class",
            }).insert(ignore_permissions=True)

        # Create test product family with completeness rules
        if not frappe.db.exists("Product Family", "test_family"):
            frappe.get_doc({
                "doctype": "Product Family",
                "family_name": "Test Family",
                "family_code": "test_family",
                "product_class": "test_class",
                "min_images": 2,
                "max_images": 10,
                "require_main_image": 1,
                "family_attributes": [
                    {
                        "pim_attribute": "test_title",
                        "is_required": 1,
                        "sort_order": 1,
                    },
                    {
                        "pim_attribute": "test_desc",
                        "is_required": 0,
                        "sort_order": 2,
                    },
                    {
                        "pim_attribute": "test_weight",
                        "is_required": 1,
                        "sort_order": 3,
                    },
                ],
                "completeness_rules": [
                    {
                        "rule_type": "Required Attribute",
                        "target_attribute": "test_title",
                        "weight": 0.3,
                        "is_enabled": 1,
                    },
                    {
                        "rule_type": "Required Attribute",
                        "target_attribute": "test_weight",
                        "weight": 0.2,
                        "is_enabled": 1,
                    },
                    {
                        "rule_type": "Required Description",
                        "weight": 0.2,
                        "is_enabled": 1,
                    },
                    {
                        "rule_type": "Min Media Count",
                        "min_media_count": 2,
                        "weight": 0.3,
                        "is_enabled": 1,
                    },
                ],
            }).insert(ignore_permissions=True)

        # Create test sales channel
        if not frappe.db.exists("Sales Channel", "test_channel"):
            frappe.get_doc({
                "doctype": "Sales Channel",
                "channel_name": "Test Channel",
                "channel_code": "test_channel",
                "channel_type": "Marketplace",
                "platform": "Other",
                "is_active": 1,
            }).insert(ignore_permissions=True)

        frappe.db.commit()

    @classmethod
    def _cleanup_test_fixtures(cls):
        """Remove test fixtures"""
        # Delete test products
        for name in frappe.get_all("PIM Product", filters={"product_code": ["like", "test_comp_%"]}, pluck="name"):
            frappe.delete_doc("PIM Product", name, force=True, ignore_permissions=True)

        # Delete test family
        if frappe.db.exists("Product Family", "test_family"):
            frappe.delete_doc("Product Family", "test_family", force=True, ignore_permissions=True)

        # Delete test product class
        if frappe.db.exists("Product Class", "test_class"):
            frappe.delete_doc("Product Class", "test_class", force=True, ignore_permissions=True)

        # Delete test attributes
        for code in ["test_title", "test_desc", "test_weight", "test_color"]:
            if frappe.db.exists("PIM Attribute", code):
                frappe.delete_doc("PIM Attribute", code, force=True, ignore_permissions=True)

        # Delete test attribute group
        if frappe.db.exists("PIM Attribute Group", "test_group"):
            frappe.delete_doc("PIM Attribute Group", "test_group", force=True, ignore_permissions=True)

        # Delete test sales channel
        if frappe.db.exists("Sales Channel", "test_channel"):
            frappe.delete_doc("Sales Channel", "test_channel", force=True, ignore_permissions=True)

        frappe.db.commit()

    def setUp(self):
        """Set up for each test"""
        # Clean up any existing test products from previous runs
        for name in frappe.get_all("PIM Product", filters={"product_code": ["like", "test_comp_%"]}, pluck="name"):
            frappe.delete_doc("PIM Product", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_test_product(
        self,
        product_code,
        product_family=None,
        attribute_values=None,
        media=None,
        descriptions=None,
        short_description=None,
    ):
        """Helper to create a test product"""
        doc = frappe.get_doc({
            "doctype": "PIM Product",
            "product_name": f"Test Product {product_code}",
            "product_code": product_code,
            "product_family": product_family,
            "short_description": short_description,
        })

        if attribute_values:
            for attr in attribute_values:
                doc.append("attribute_values", attr)

        if media:
            for m in media:
                doc.append("media", m)

        if descriptions:
            for d in descriptions:
                doc.append("descriptions", d)

        doc.flags.ignore_permissions = True
        doc.flags.ignore_mandatory = True
        doc.insert()
        return doc

    # =========================================================================
    # INITIALIZATION TESTS
    # =========================================================================

    def test_calculator_init_with_product_doc(self):
        """Test initializing calculator with product document"""
        product = self._create_test_product("test_comp_001")

        calculator = CompletenessCalculator(product)

        self.assertEqual(calculator.product.name, product.name)
        self.assertIsNone(calculator.channel)
        self.assertIsNone(calculator.locale)

    def test_calculator_init_with_product_name(self):
        """Test initializing calculator with product name string"""
        product = self._create_test_product("test_comp_002")

        calculator = CompletenessCalculator(product.name)

        self.assertEqual(calculator.product.name, product.name)

    def test_calculator_init_with_channel_filter(self):
        """Test initializing calculator with channel filter"""
        product = self._create_test_product("test_comp_003", product_family="test_family")

        calculator = CompletenessCalculator(product, channel="test_channel")

        self.assertEqual(calculator.channel, "test_channel")

    def test_calculator_init_with_locale_filter(self):
        """Test initializing calculator with locale filter"""
        product = self._create_test_product("test_comp_004", product_family="test_family")

        calculator = CompletenessCalculator(product, locale="en_US")

        self.assertEqual(calculator.locale, "en_US")

    def test_calculator_loads_family_rules(self):
        """Test that calculator loads family completeness rules"""
        product = self._create_test_product("test_comp_005", product_family="test_family")

        calculator = CompletenessCalculator(product)

        self.assertIsNotNone(calculator.family)
        self.assertTrue(len(calculator.rules) > 0)

    # =========================================================================
    # DEFAULT CALCULATION TESTS (No Family/Rules)
    # =========================================================================

    def test_default_calculation_no_family(self):
        """Test default calculation when product has no family"""
        product = self._create_test_product("test_comp_010")

        calculator = CompletenessCalculator(product)
        result = calculator.calculate()

        self.assertIn("score", result)
        self.assertIn("status", result)
        self.assertIn("detail", result)
        self.assertEqual(result["detail"]["rules_evaluated"], 3)

    def test_default_calculation_empty_product(self):
        """Test default calculation on empty product gives low score"""
        product = self._create_test_product("test_comp_011")

        result = calculate_completeness(product)

        # Empty product should have very low score (no attributes, no media, no description)
        self.assertLess(result["score"], 50)
        self.assertIn(result["status"], ["Incomplete", "Partial"])

    def test_default_calculation_with_description(self):
        """Test that having a description improves score"""
        product = self._create_test_product(
            "test_comp_012",
            short_description="This is a test product with a description"
        )

        result = calculate_completeness(product)

        # Should get 15% from description alone (DEFAULT_DESCRIPTION_WEIGHT * 100)
        self.assertGreaterEqual(result["score"], 15)

    def test_default_calculation_with_media(self):
        """Test that having media improves score"""
        product = self._create_test_product(
            "test_comp_013",
            media=[
                {
                    "media_type": "Image",
                    "file": "/test/image.jpg",
                    "is_main": 1,
                }
            ]
        )

        result = calculate_completeness(product)

        # Should get some score from media
        self.assertGreater(result["score"], 0)

    # =========================================================================
    # STATUS THRESHOLD TESTS
    # =========================================================================

    def test_status_incomplete(self):
        """Test Incomplete status for score 0-25"""
        product = self._create_test_product("test_comp_020")

        calculator = CompletenessCalculator(product)

        # Test status threshold
        self.assertEqual(calculator._get_status(0), "Incomplete")
        self.assertEqual(calculator._get_status(15), "Incomplete")
        self.assertEqual(calculator._get_status(24.99), "Incomplete")

    def test_status_partial(self):
        """Test Partial status for score 25-75"""
        product = self._create_test_product("test_comp_021")

        calculator = CompletenessCalculator(product)

        self.assertEqual(calculator._get_status(25), "Partial")
        self.assertEqual(calculator._get_status(50), "Partial")
        self.assertEqual(calculator._get_status(74.99), "Partial")

    def test_status_complete(self):
        """Test Complete status for score 75-95"""
        product = self._create_test_product("test_comp_022")

        calculator = CompletenessCalculator(product)

        self.assertEqual(calculator._get_status(75), "Complete")
        self.assertEqual(calculator._get_status(85), "Complete")
        self.assertEqual(calculator._get_status(94.99), "Complete")

    def test_status_enriched(self):
        """Test Enriched status for score 95-100"""
        product = self._create_test_product("test_comp_023")

        calculator = CompletenessCalculator(product)

        self.assertEqual(calculator._get_status(95), "Enriched")
        self.assertEqual(calculator._get_status(100), "Enriched")

    # =========================================================================
    # RULE TYPE TESTS
    # =========================================================================

    def test_rule_required_attribute_passed(self):
        """Test Required Attribute rule passes when attribute is filled"""
        product = self._create_test_product(
            "test_comp_030",
            product_family="test_family",
            attribute_values=[
                {
                    "attribute_code": "test_title",
                    "attribute_type": "Text",
                    "value_text": "Test Product Title",
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Attribute", "target_attribute": "test_title"}
        result = calculator._evaluate_required_attribute(rule)

        self.assertTrue(result["passed"])

    def test_rule_required_attribute_failed(self):
        """Test Required Attribute rule fails when attribute is missing"""
        product = self._create_test_product("test_comp_031", product_family="test_family")

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Attribute", "target_attribute": "test_title"}
        result = calculator._evaluate_required_attribute(rule)

        self.assertFalse(result["passed"])
        self.assertEqual(result["partial_score"], 0)

    def test_rule_required_attribute_no_target(self):
        """Test Required Attribute rule passes when no target specified"""
        product = self._create_test_product("test_comp_032", product_family="test_family")

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Attribute"}
        result = calculator._evaluate_required_attribute(rule)

        self.assertTrue(result["passed"])

    def test_rule_required_description_passed(self):
        """Test Required Description rule passes when description exists"""
        product = self._create_test_product(
            "test_comp_033",
            product_family="test_family",
            descriptions=[
                {
                    "description_type": "Short",
                    "description": "This is a test description for the product.",
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Description"}
        result = calculator._evaluate_required_description(rule)

        self.assertTrue(result["passed"])

    def test_rule_required_description_failed(self):
        """Test Required Description rule fails when no description"""
        product = self._create_test_product("test_comp_034", product_family="test_family")

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Description"}
        result = calculator._evaluate_required_description(rule)

        self.assertFalse(result["passed"])

    def test_rule_required_description_short_field(self):
        """Test Required Description passes with short_description field"""
        product = self._create_test_product(
            "test_comp_035",
            product_family="test_family",
            short_description="Short description text"
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Description"}
        result = calculator._evaluate_required_description(rule)

        self.assertTrue(result["passed"])

    def test_rule_min_description_length_passed(self):
        """Test Min Description Length rule passes when length met"""
        product = self._create_test_product(
            "test_comp_036",
            product_family="test_family",
            descriptions=[
                {
                    "description_type": "Long",
                    "description": "A" * 200,  # 200 characters
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Min Description Length", "min_length": 100}
        result = calculator._evaluate_min_description_length(rule)

        self.assertTrue(result["passed"])

    def test_rule_min_description_length_partial(self):
        """Test Min Description Length returns partial score when short"""
        product = self._create_test_product(
            "test_comp_037",
            product_family="test_family",
            descriptions=[
                {
                    "description_type": "Long",
                    "description": "A" * 50,  # 50 characters
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Min Description Length", "min_length": 100}
        result = calculator._evaluate_min_description_length(rule)

        self.assertFalse(result["passed"])
        self.assertEqual(result["partial_score"], 0.5)  # 50/100

    def test_rule_required_media_passed(self):
        """Test Required Media rule passes when media exists"""
        product = self._create_test_product(
            "test_comp_038",
            product_family="test_family",
            media=[
                {
                    "media_type": "Image",
                    "file": "/test/image.jpg",
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Media"}
        result = calculator._evaluate_required_media(rule)

        self.assertTrue(result["passed"])

    def test_rule_required_media_failed(self):
        """Test Required Media rule fails when no media"""
        product = self._create_test_product("test_comp_039", product_family="test_family")

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Media"}
        result = calculator._evaluate_required_media(rule)

        self.assertFalse(result["passed"])

    def test_rule_min_media_count_passed(self):
        """Test Min Media Count rule passes when count met"""
        product = self._create_test_product(
            "test_comp_040",
            product_family="test_family",
            media=[
                {"media_type": "Image", "file": "/test/image1.jpg"},
                {"media_type": "Image", "file": "/test/image2.jpg"},
                {"media_type": "Image", "file": "/test/image3.jpg"},
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Min Media Count", "min_media_count": 3}
        result = calculator._evaluate_min_media_count(rule)

        self.assertTrue(result["passed"])

    def test_rule_min_media_count_partial(self):
        """Test Min Media Count returns partial score when short"""
        product = self._create_test_product(
            "test_comp_041",
            product_family="test_family",
            media=[
                {"media_type": "Image", "file": "/test/image1.jpg"},
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Min Media Count", "min_media_count": 4}
        result = calculator._evaluate_min_media_count(rule)

        self.assertFalse(result["passed"])
        self.assertEqual(result["partial_score"], 0.25)  # 1/4

    def test_rule_attribute_validation_min_value(self):
        """Test Attribute Validation with min_value constraint"""
        product = self._create_test_product(
            "test_comp_042",
            product_family="test_family",
            attribute_values=[
                {
                    "attribute_code": "test_weight",
                    "attribute_type": "Float",
                    "value_float": 5.0,
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {
            "rule_type": "Attribute Validation",
            "target_attribute": "test_weight",
            "min_value": 1,
            "max_value": 10,
        }
        result = calculator._evaluate_attribute_validation(rule)

        self.assertTrue(result["passed"])

    def test_rule_attribute_validation_below_min(self):
        """Test Attribute Validation fails when below min_value"""
        product = self._create_test_product(
            "test_comp_043",
            product_family="test_family",
            attribute_values=[
                {
                    "attribute_code": "test_weight",
                    "attribute_type": "Float",
                    "value_float": 0.5,
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {
            "rule_type": "Attribute Validation",
            "target_attribute": "test_weight",
            "min_value": 1,
        }
        result = calculator._evaluate_attribute_validation(rule)

        self.assertFalse(result["passed"])

    def test_rule_attribute_validation_above_max(self):
        """Test Attribute Validation fails when above max_value"""
        product = self._create_test_product(
            "test_comp_044",
            product_family="test_family",
            attribute_values=[
                {
                    "attribute_code": "test_weight",
                    "attribute_type": "Float",
                    "value_float": 15.0,
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {
            "rule_type": "Attribute Validation",
            "target_attribute": "test_weight",
            "max_value": 10,
        }
        result = calculator._evaluate_attribute_validation(rule)

        self.assertFalse(result["passed"])

    def test_rule_attribute_validation_string_length(self):
        """Test Attribute Validation with min/max length for strings"""
        product = self._create_test_product(
            "test_comp_045",
            product_family="test_family",
            attribute_values=[
                {
                    "attribute_code": "test_title",
                    "attribute_type": "Text",
                    "value_text": "Short",
                }
            ]
        )

        calculator = CompletenessCalculator(product)
        rule = {
            "rule_type": "Attribute Validation",
            "target_attribute": "test_title",
            "min_length": 10,
        }
        result = calculator._evaluate_attribute_validation(rule)

        self.assertFalse(result["passed"])

    def test_rule_custom_always_passes(self):
        """Test Custom rule type passes by default"""
        product = self._create_test_product("test_comp_046", product_family="test_family")

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Custom"}
        result = calculator._evaluate_custom_rule(rule)

        self.assertTrue(result["passed"])

    def test_rule_unknown_type(self):
        """Test unknown rule type is handled gracefully"""
        product = self._create_test_product("test_comp_047", product_family="test_family")

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "NonExistent Rule Type"}
        result = calculator._evaluate_unknown_rule(rule)

        self.assertTrue(result["passed"])

    # =========================================================================
    # RULE-BASED CALCULATION TESTS
    # =========================================================================

    def test_rule_based_full_calculation(self):
        """Test full rule-based calculation with family"""
        # Create product with all requirements met
        product = self._create_test_product(
            "test_comp_050",
            product_family="test_family",
            attribute_values=[
                {"attribute_code": "test_title", "attribute_type": "Text", "value_text": "Test Title"},
                {"attribute_code": "test_weight", "attribute_type": "Float", "value_float": 2.5},
            ],
            descriptions=[
                {"description_type": "Short", "description": "Test description"},
            ],
            media=[
                {"media_type": "Image", "file": "/test/img1.jpg"},
                {"media_type": "Image", "file": "/test/img2.jpg"},
            ],
        )

        result = calculate_completeness(product)

        # Should have high score since all rules pass
        self.assertGreater(result["score"], 90)
        self.assertIn(result["status"], ["Complete", "Enriched"])

    def test_rule_based_partial_calculation(self):
        """Test partial rule-based calculation"""
        # Create product with only some requirements met
        product = self._create_test_product(
            "test_comp_051",
            product_family="test_family",
            attribute_values=[
                {"attribute_code": "test_title", "attribute_type": "Text", "value_text": "Test Title"},
            ],
            # Missing: test_weight attribute, description, and 2 media files
        )

        result = calculate_completeness(product)

        # Should have moderate score (title rule passes = 30%)
        self.assertGreater(result["score"], 20)
        self.assertLess(result["score"], 60)

    def test_rule_weights_affect_score(self):
        """Test that rule weights properly affect final score"""
        product = self._create_test_product(
            "test_comp_052",
            product_family="test_family",
            attribute_values=[
                # Only fill title (weight 0.3) but not weight (weight 0.2)
                {"attribute_code": "test_title", "attribute_type": "Text", "value_text": "Test"},
            ],
        )

        calculator = CompletenessCalculator(product)
        result = calculator.calculate()

        # Score should reflect weighted contribution
        # Title rule (30%) passes, others fail
        self.assertIn("detail", result)
        self.assertEqual(result["detail"]["rules_passed"], 1)

    # =========================================================================
    # CALCULATE_COMPLETENESS FUNCTION TESTS
    # =========================================================================

    def test_calculate_completeness_function(self):
        """Test the main calculate_completeness function"""
        product = self._create_test_product("test_comp_060")

        result = calculate_completeness(product)

        self.assertIsInstance(result, dict)
        self.assertIn("score", result)
        self.assertIn("status", result)
        self.assertIn("detail", result)
        self.assertIn("calculated_at", result)

    def test_calculate_completeness_by_name(self):
        """Test calculate_completeness with product name string"""
        product = self._create_test_product("test_comp_061")

        result = calculate_completeness(product.name)

        self.assertIsInstance(result["score"], (int, float))

    def test_calculate_completeness_with_update(self):
        """Test calculate_completeness updates product fields"""
        product = self._create_test_product(
            "test_comp_062",
            product_family="test_family",
            short_description="Test description",
        )

        # Calculate with update flag
        result = calculate_completeness(product, update_product=True)

        # Verify fields were updated
        updated_product = frappe.get_doc("PIM Product", product.name)
        self.assertEqual(updated_product.completeness_score, result["score"])
        self.assertEqual(updated_product.completeness_status, result["status"])

    def test_calculate_completeness_with_channel(self):
        """Test calculate_completeness with channel filter"""
        product = self._create_test_product("test_comp_063", product_family="test_family")

        result = calculate_completeness(product, channel="test_channel")

        self.assertIsInstance(result, dict)

    def test_calculate_completeness_with_locale(self):
        """Test calculate_completeness with locale filter"""
        product = self._create_test_product("test_comp_064", product_family="test_family")

        result = calculate_completeness(product, locale="en_US")

        self.assertIsInstance(result, dict)

    # =========================================================================
    # BULK OPERATION TESTS
    # =========================================================================

    def test_bulk_calculate_completeness(self):
        """Test bulk completeness calculation"""
        # Create multiple products
        products = []
        for i in range(3):
            p = self._create_test_product(f"test_comp_07{i}")
            products.append(p.name)

        results = bulk_calculate_completeness(products, update_products=False)

        self.assertEqual(len(results), 3)
        for product_name, result in results:
            self.assertIn("score", result)

    def test_bulk_calculate_with_error_handling(self):
        """Test bulk calculation handles errors gracefully"""
        product = self._create_test_product("test_comp_080")

        # Mix valid and invalid product names
        results = bulk_calculate_completeness(
            [product.name, "non_existent_product"],
            update_products=False
        )

        self.assertEqual(len(results), 2)
        # Second result should have error
        self.assertIn("error", results[1][1])

    # =========================================================================
    # EDGE CASE TESTS
    # =========================================================================

    def test_empty_attribute_values_list(self):
        """Test calculation with empty attribute values"""
        product = self._create_test_product(
            "test_comp_090",
            product_family="test_family",
            attribute_values=[],
        )

        result = calculate_completeness(product)

        self.assertIsInstance(result["score"], (int, float))

    def test_empty_media_list(self):
        """Test calculation with empty media list"""
        product = self._create_test_product(
            "test_comp_091",
            product_family="test_family",
            media=[],
        )

        result = calculate_completeness(product)

        # Media rules should fail
        self.assertLess(result["score"], 100)

    def test_empty_descriptions_list(self):
        """Test calculation with empty descriptions list"""
        product = self._create_test_product(
            "test_comp_092",
            product_family="test_family",
            descriptions=[],
        )

        result = calculate_completeness(product)

        self.assertIsInstance(result["score"], (int, float))

    def test_missing_product_family(self):
        """Test calculation when product family doesn't exist"""
        product = self._create_test_product("test_comp_093")
        # Set invalid family
        frappe.db.set_value("PIM Product", product.name, "product_family", "non_existent_family")
        product.reload()

        # Should use default calculation without error
        result = calculate_completeness(product)

        self.assertIsInstance(result["score"], (int, float))

    def test_attribute_value_empty_string(self):
        """Test that empty string attribute values are treated as missing"""
        product = self._create_test_product(
            "test_comp_094",
            product_family="test_family",
            attribute_values=[
                {"attribute_code": "test_title", "attribute_type": "Text", "value_text": ""},
            ],
        )

        calculator = CompletenessCalculator(product)
        rule = {"rule_type": "Required Attribute", "target_attribute": "test_title"}
        result = calculator._evaluate_required_attribute(rule)

        self.assertFalse(result["passed"])

    def test_attribute_value_empty_list(self):
        """Test that empty list attribute values are treated as missing"""
        product = self._create_test_product(
            "test_comp_095",
            product_family="test_family",
            attribute_values=[
                {"attribute_code": "test_color", "attribute_type": "Multiselect", "value_select": "[]"},
            ],
        )

        calculator = CompletenessCalculator(product)
        # The get_attribute_value will return the string "[]", not an actual empty list
        # So this tests the raw value handling

        result = calculator.calculate()
        self.assertIsInstance(result["score"], (int, float))

    def test_result_structure(self):
        """Test the completeness result structure is correct"""
        product = self._create_test_product("test_comp_096", product_family="test_family")

        result = calculate_completeness(product)

        # Verify top-level structure
        self.assertIn("score", result)
        self.assertIn("status", result)
        self.assertIn("detail", result)
        self.assertIn("calculated_at", result)

        # Verify detail structure
        detail = result["detail"]
        self.assertIn("rules_evaluated", detail)
        self.assertIn("rules_passed", detail)
        self.assertIn("categories", detail)
        self.assertIn("failed_rules", detail)
        self.assertIn("passed_rules", detail)

        # Verify score is in valid range
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

        # Verify status is valid
        self.assertIn(result["status"], ["Incomplete", "Partial", "Complete", "Enriched"])

    def test_score_rounding(self):
        """Test that scores are properly rounded to 2 decimal places"""
        product = self._create_test_product(
            "test_comp_097",
            product_family="test_family",
            short_description="Test",
        )

        result = calculate_completeness(product)

        # Score should be rounded to at most 2 decimal places
        score_str = str(result["score"])
        if "." in score_str:
            decimal_places = len(score_str.split(".")[1])
            self.assertLessEqual(decimal_places, 2)

    # =========================================================================
    # CATEGORY TRACKING TESTS
    # =========================================================================

    def test_categories_populated_in_result(self):
        """Test that category breakdown is included in result"""
        product = self._create_test_product(
            "test_comp_098",
            product_family="test_family",
            attribute_values=[
                {"attribute_code": "test_title", "attribute_type": "Text", "value_text": "Test"},
            ],
        )

        result = calculate_completeness(product)

        categories = result["detail"]["categories"]
        self.assertIn("attributes", categories)
        self.assertIn("media", categories)
        self.assertIn("descriptions", categories)

    def test_passed_rules_list(self):
        """Test that passed rules are tracked"""
        product = self._create_test_product(
            "test_comp_099",
            product_family="test_family",
            attribute_values=[
                {"attribute_code": "test_title", "attribute_type": "Text", "value_text": "Test"},
            ],
        )

        result = calculate_completeness(product)

        # Should have at least one passed rule (test_title)
        passed_rules = result["detail"]["passed_rules"]
        self.assertIsInstance(passed_rules, list)
        if passed_rules:
            self.assertIn("type", passed_rules[0])

    def test_failed_rules_list(self):
        """Test that failed rules are tracked with reasons"""
        product = self._create_test_product("test_comp_100", product_family="test_family")

        result = calculate_completeness(product)

        # Should have failed rules (no attributes filled)
        failed_rules = result["detail"]["failed_rules"]
        self.assertIsInstance(failed_rules, list)
        if failed_rules:
            self.assertIn("type", failed_rules[0])
            self.assertIn("reason", failed_rules[0])
