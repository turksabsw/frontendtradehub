# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate


class TestSellerTier(FrappeTestCase):
    """Test cases for Seller Tier DocType."""

    def setUp(self):
        """Set up test data."""
        # Clean up any existing test tiers
        for tier_code in ["TEST_BRONZE", "TEST_SILVER", "TEST_GOLD"]:
            if frappe.db.exists("Seller Tier", tier_code):
                frappe.delete_doc("Seller Tier", tier_code, force=True)

    def tearDown(self):
        """Clean up test data."""
        for tier_code in ["TEST_BRONZE", "TEST_SILVER", "TEST_GOLD"]:
            if frappe.db.exists("Seller Tier", tier_code):
                frappe.delete_doc("Seller Tier", tier_code, force=True)

    def test_create_seller_tier(self):
        """Test creating a basic seller tier."""
        tier = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Bronze",
            "tier_code": "TEST_BRONZE",
            "tier_level": 1,
            "status": "Active",
            "badge_color": "#cd7f32"
        })
        tier.insert()

        self.assertEqual(tier.tier_name, "Test Bronze")
        self.assertEqual(tier.tier_code, "TEST_BRONZE")
        self.assertEqual(tier.tier_level, 1)

    def test_tier_code_uppercase(self):
        """Test that tier code is converted to uppercase."""
        tier = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Silver",
            "tier_code": "test_silver",
            "tier_level": 2,
            "status": "Active"
        })
        tier.insert()

        self.assertEqual(tier.tier_code, "TEST_SILVER")

    def test_tier_requirements_validation(self):
        """Test that tier requirements are validated."""
        tier = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Gold",
            "tier_code": "TEST_GOLD",
            "tier_level": 3,
            "status": "Active",
            "min_seller_score": 150  # Invalid: should be 0-100
        })

        self.assertRaises(frappe.ValidationError, tier.insert)

    def test_tier_benefits_summary(self):
        """Test getting tier benefits summary."""
        tier = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Gold",
            "tier_code": "TEST_GOLD",
            "tier_level": 3,
            "status": "Active",
            "commission_discount_percent": 10,
            "priority_support": 1,
            "featured_placement": 1
        })
        tier.insert()

        benefits = tier.get_benefits_summary()
        self.assertIn("10% commission discount", benefits[0])
        self.assertTrue(any("Priority support" in b for b in benefits))

    def test_tier_requirements_summary(self):
        """Test getting tier requirements summary."""
        tier = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Gold",
            "tier_code": "TEST_GOLD",
            "tier_level": 3,
            "status": "Active",
            "min_seller_score": 80,
            "min_total_sales_count": 100
        })
        tier.insert()

        requirements = tier.get_requirements_summary()
        self.assertTrue(any("80" in r for r in requirements))
        self.assertTrue(any("100" in r for r in requirements))

    def test_tier_card(self):
        """Test getting tier card for display."""
        tier = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Bronze",
            "tier_code": "TEST_BRONZE",
            "tier_level": 1,
            "status": "Active",
            "badge_color": "#cd7f32"
        })
        tier.insert()

        card = tier.get_tier_card()
        self.assertEqual(card["tier_name"], "Test Bronze")
        self.assertEqual(card["tier_code"], "TEST_BRONZE")
        self.assertEqual(card["badge_color"], "#cd7f32")

    def test_default_tier_uniqueness(self):
        """Test that only one default tier can exist."""
        tier1 = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Bronze",
            "tier_code": "TEST_BRONZE",
            "tier_level": 1,
            "status": "Active",
            "is_default": 1
        })
        tier1.insert()

        tier2 = frappe.get_doc({
            "doctype": "Seller Tier",
            "tier_name": "Test Silver",
            "tier_code": "TEST_SILVER",
            "tier_level": 2,
            "status": "Active",
            "is_default": 1
        })
        tier2.insert()

        # Reload tier1 to check if is_default was unset
        tier1.reload()
        self.assertEqual(tier1.is_default, 0)
        self.assertEqual(tier2.is_default, 1)
