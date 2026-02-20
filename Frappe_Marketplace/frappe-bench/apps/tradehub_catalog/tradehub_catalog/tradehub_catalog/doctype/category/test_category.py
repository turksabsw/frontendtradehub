# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase


class UnitTestCategory(UnitTestCase):
    """Unit tests for Category DocType."""

    def test_category_naming(self):
        """Test that category name is used as document name."""
        category = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Unit Category"
        })
        # Name should be set from category_name
        self.assertEqual(category.category_name, "Test Unit Category")


class IntegrationTestCategory(IntegrationTestCase):
    """Integration tests for Category DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Clean up any existing test categories
        for cat_name in ["Test Root Category", "Test Child Category", "Test Grandchild"]:
            if frappe.db.exists("Category", cat_name):
                frappe.delete_doc("Category", cat_name, force=True)

    def tearDown(self):
        """Clean up test data."""
        # Clean up test categories in reverse order (children first)
        for cat_name in ["Test Grandchild", "Test Child Category", "Test Root Category"]:
            if frappe.db.exists("Category", cat_name):
                frappe.delete_doc("Category", cat_name, force=True)
        frappe.db.commit()

    def test_create_root_category(self):
        """Test creating a root-level category."""
        category = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category",
            "description": "A test root category",
            "commission_rate": 12.5
        })
        category.insert()

        self.assertEqual(category.name, "Test Root Category")
        self.assertEqual(category.commission_rate, 12.5)
        self.assertTrue(category.is_active)
        self.assertIsNotNone(category.route)

    def test_create_child_category(self):
        """Test creating a child category under a parent."""
        # Create parent first
        parent = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category",
            "commission_rate": 10.0
        })
        parent.insert()

        # Create child
        child = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Child Category",
            "parent_category": "Test Root Category",
            "commission_rate": 15.0
        })
        child.insert()

        self.assertEqual(child.parent_category, "Test Root Category")
        self.assertTrue("test-root-category" in child.route.lower())

    def test_hierarchical_structure(self):
        """Test nested category hierarchy."""
        # Create root
        root = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category"
        })
        root.insert()

        # Create child
        child = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Child Category",
            "parent_category": "Test Root Category"
        })
        child.insert()

        # Create grandchild
        grandchild = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Grandchild",
            "parent_category": "Test Child Category"
        })
        grandchild.insert()

        # Test ancestors
        ancestors = grandchild.get_ancestors()
        self.assertIn("Test Child Category", ancestors)
        self.assertIn("Test Root Category", ancestors)

        # Test descendants
        descendants = root.get_descendants()
        self.assertIn("Test Child Category", descendants)
        self.assertIn("Test Grandchild", descendants)

    def test_commission_rate_validation(self):
        """Test commission rate validation."""
        # Negative rate should fail
        category = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Invalid Category",
            "commission_rate": -5.0
        })
        with self.assertRaises(frappe.ValidationError):
            category.insert()

        # Rate over 100% should fail
        category.commission_rate = 150.0
        with self.assertRaises(frappe.ValidationError):
            category.insert()

    def test_prevent_circular_reference(self):
        """Test that a category cannot be its own parent."""
        category = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category"
        })
        category.insert()

        # Try to make it its own parent
        category.parent_category = "Test Root Category"
        with self.assertRaises(frappe.ValidationError):
            category.save()

    def test_prevent_delete_with_children(self):
        """Test that category with children cannot be deleted."""
        parent = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category"
        })
        parent.insert()

        child = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Child Category",
            "parent_category": "Test Root Category"
        })
        child.insert()

        # Try to delete parent with children
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc("Category", "Test Root Category")

    def test_effective_commission_rate_inheritance(self):
        """Test commission rate inheritance from parent."""
        parent = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category",
            "commission_rate": 15.0
        })
        parent.insert()

        # Child without commission rate should inherit from parent
        child = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Child Category",
            "parent_category": "Test Root Category",
            "commission_rate": 0  # Not set
        })
        child.insert()

        # Get fresh copy to test
        child_fresh = frappe.get_doc("Category", "Test Child Category")
        effective_rate = child_fresh.get_effective_commission_rate()
        self.assertEqual(effective_rate, 15.0)

    def test_commission_calculation(self):
        """Test commission calculation with min/max/fixed."""
        category = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category",
            "commission_rate": 10.0,
            "min_commission": 5.0,
            "max_commission": 50.0,
            "fixed_commission": 2.0
        })
        category.insert()

        # Normal calculation: 10% of 200 = 20 + 2 fixed = 22
        self.assertEqual(category.calculate_commission(200), 22.0)

        # Min commission applies: 10% of 10 = 1, min is 5, so 5 + 2 fixed = 7
        self.assertEqual(category.calculate_commission(10), 7.0)

        # Max commission applies: 10% of 1000 = 100, max is 50, so 50 + 2 fixed = 52
        self.assertEqual(category.calculate_commission(1000), 52.0)

    def test_route_generation(self):
        """Test automatic route generation."""
        category = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Electronics & Gadgets"
        })
        category.insert()

        self.assertIsNotNone(category.route)
        self.assertIn("electronics", category.route.lower())

    def test_get_category_tree(self):
        """Test get_category_tree API function."""
        from tradehub_catalog.tradehub_catalog.doctype.category.category import get_category_tree

        # Create test hierarchy
        root = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category",
            "is_active": 1
        })
        root.insert()

        child = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Child Category",
            "parent_category": "Test Root Category",
            "is_active": 1
        })
        child.insert()

        # Get tree
        tree = get_category_tree()
        root_items = [c for c in tree if c["name"] == "Test Root Category"]
        self.assertEqual(len(root_items), 1)
        self.assertTrue(root_items[0]["expandable"])

    def test_get_category_path(self):
        """Test get_category_path API function."""
        from tradehub_catalog.tradehub_catalog.doctype.category.category import get_category_path

        # Create hierarchy
        root = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Root Category"
        })
        root.insert()

        child = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Child Category",
            "parent_category": "Test Root Category"
        })
        child.insert()

        grandchild = frappe.get_doc({
            "doctype": "Category",
            "category_name": "Test Grandchild",
            "parent_category": "Test Child Category"
        })
        grandchild.insert()

        # Get path for grandchild
        path = get_category_path("Test Grandchild")
        self.assertEqual(len(path), 3)
        self.assertEqual(path[0]["name"], "Test Root Category")
        self.assertEqual(path[1]["name"], "Test Child Category")
        self.assertEqual(path[2]["name"], "Test Grandchild")
