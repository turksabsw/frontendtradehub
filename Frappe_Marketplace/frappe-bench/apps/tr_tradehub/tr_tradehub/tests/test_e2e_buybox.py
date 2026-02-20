# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
End-to-End Test: Buy Box Competition Flow

This module implements comprehensive end-to-end tests for the Buy Box competition
workflow in the Trade Hub B2B marketplace.

Test Workflow:
1. Multiple sellers list same SKU (create product and Buy Box entries)
2. Buy Box algorithm selects winner (score calculation and winner determination)
3. Rotation occurs after period (when prices/ratings change)
4. Brand gating restricts unauthorized sellers

Test Prerequisites:
- Tenant DocType must exist
- Seller Profile DocType must exist
- SKU Product DocType must exist
- Buy Box Entry DocType must exist
- Brand DocType must exist (optional for brand gating tests)
- Brand Gating DocType must exist (optional for brand gating tests)

Usage:
    Run with Frappe bench:
    bench --site {site} run-tests --module trade_hub.tests.test_e2e_buybox

    Run specific test:
    bench --site {site} run-tests --module trade_hub.tests.test_e2e_buybox --test test_complete_buybox_competition_flow
"""

import unittest
from unittest.mock import patch, MagicMock
from typing import Dict, Any, Optional, List

import frappe
from frappe.utils import (
    now_datetime, today, nowdate, random_string,
    add_days, getdate, flt, cint
)


class TestE2EBuyBoxCompetition(unittest.TestCase):
    """
    End-to-end tests for the complete Buy Box competition flow.

    This test class simulates the Buy Box marketplace where:
    1. Multiple sellers compete for the same product
    2. The algorithm determines the winner based on scoring factors
    3. Winners can change when offer conditions change
    4. Brand authorization controls seller eligibility
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures that are shared across all tests."""
        # Use Administrator for test operations
        frappe.set_user("Administrator")

        # Create test tenant if it doesn't exist
        cls.test_tenant = cls._get_or_create_test_tenant()

        # Create test category if Product Category exists
        cls.test_category = cls._get_or_create_test_category()

        # Create test brand if Brand exists
        cls.test_brand = cls._get_or_create_test_brand()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures after all tests complete."""
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def setUp(self):
        """Set up test fixtures before each test."""
        # Generate unique identifiers for this test run
        self.test_suffix = random_string(6).lower()
        self.test_product_name = f"Buy Box Test Product {self.test_suffix}"
        self.test_sku_code = f"BUYBOX-{self.test_suffix}".upper()

        # Seller data
        self.seller_configs = [
            {
                "email": f"seller_a_{self.test_suffix}@example.com",
                "name": f"Seller A {self.test_suffix}",
                "rating": 4.5,
                "reviews": 100,
                "price": 100.00,
                "delivery_days": 7,
                "stock": 500
            },
            {
                "email": f"seller_b_{self.test_suffix}@example.com",
                "name": f"Seller B {self.test_suffix}",
                "rating": 4.2,
                "reviews": 200,
                "price": 95.00,  # Cheapest
                "delivery_days": 10,
                "stock": 300
            },
            {
                "email": f"seller_c_{self.test_suffix}@example.com",
                "name": f"Seller C {self.test_suffix}",
                "rating": 4.8,  # Highest rating
                "reviews": 50,
                "price": 105.00,
                "delivery_days": 5,  # Fastest delivery
                "stock": 1000  # Most stock
            }
        ]

    def tearDown(self):
        """Clean up test data after each test."""
        frappe.set_user("Administrator")
        self._cleanup_test_data()
        frappe.db.rollback()

    # =========================================================================
    # MAIN END-TO-END TEST
    # =========================================================================

    def test_complete_buybox_competition_flow(self):
        """
        Test the complete Buy Box competition flow.

        This test covers:
        1. Multiple sellers list same SKU
        2. Buy Box algorithm selects winner
        3. Rotation occurs after period (price/rating change)
        4. Brand gating restricts unauthorized sellers

        This is the primary E2E test that validates the entire Buy Box journey.
        """
        # Step 1: Multiple sellers list same SKU
        product, sellers, entries = self._step_multiple_sellers_list_sku()
        self.assertIsNotNone(product, "Product should be created")
        self.assertEqual(len(sellers), 3, "Should have 3 sellers")
        self.assertEqual(len(entries), 3, "Should have 3 Buy Box entries")

        # Step 2: Buy Box algorithm selects winner
        winner_entry = self._step_buybox_selects_winner(product.name)
        self.assertIsNotNone(winner_entry, "Buy Box should have a winner")
        self.assertEqual(
            winner_entry.get("is_winner"),
            1,
            "Winner entry should have is_winner=1"
        )

        # Verify scoring factors are populated
        self.assertGreater(
            flt(winner_entry.get("buy_box_score")),
            0,
            "Winner should have a positive buy_box_score"
        )

        # Step 3: Rotation occurs when conditions change
        new_winner = self._step_rotation_after_price_change(product.name, entries)
        self.assertIsNotNone(new_winner, "New winner should be determined after changes")

        # Step 4: Brand gating restricts unauthorized sellers
        if self.test_brand and frappe.db.exists("DocType", "Brand Gating"):
            gating_result = self._step_brand_gating_restriction(product, sellers)
            self.assertTrue(
                gating_result["restriction_enforced"],
                "Brand gating should restrict unauthorized sellers"
            )

    # =========================================================================
    # STEP IMPLEMENTATIONS
    # =========================================================================

    def _step_multiple_sellers_list_sku(self) -> tuple:
        """
        Step 1: Multiple sellers list the same SKU.

        This step:
        1. Creates multiple verified sellers
        2. Creates a shared product (SKU)
        3. Each seller creates a Buy Box entry with different offers

        Returns:
            tuple: (product, list_of_sellers, list_of_buybox_entries)
        """
        frappe.set_user("Administrator")

        # Create sellers
        sellers = []
        for config in self.seller_configs:
            seller_user = self._create_test_user(
                config["email"],
                "Test",
                config["name"].split()[-1]
            )
            seller_profile = self._create_verified_seller(
                seller_user,
                config["name"],
                average_rating=config["rating"],
                total_reviews=config["reviews"]
            )
            sellers.append(seller_profile)

        # Create product (using first seller as the original lister)
        product = self._create_test_product(
            self.test_product_name,
            self.test_sku_code,
            sellers[0]
        )

        # Create Buy Box entries for each seller
        entries = []
        for i, (seller, config) in enumerate(zip(sellers, self.seller_configs)):
            entry = self._create_buybox_entry(
                product=product,
                seller=seller,
                offer_price=config["price"],
                delivery_days=config["delivery_days"],
                stock_available=config["stock"],
                seller_average_rating=config["rating"],
                seller_total_reviews=config["reviews"]
            )
            entries.append(entry)

        return product, sellers, entries

    def _step_buybox_selects_winner(self, sku_product: str) -> Optional[Dict]:
        """
        Step 2: Buy Box algorithm calculates and selects winner.

        This step:
        1. Triggers Buy Box recalculation for the product
        2. Verifies exactly one winner is selected
        3. Returns the winner entry details

        Args:
            sku_product: The SKU Product name

        Returns:
            dict: Winner entry details or None
        """
        # Trigger recalculation
        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(
                sku_product,
                use_locking=False,  # Skip locking in tests
                update_entries=True
            )

            if not result.get("success"):
                return None

        except ImportError:
            # Fallback to direct API call
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(sku_product)

        # Verify exactly one winner
        winners = frappe.get_all(
            "Buy Box Entry",
            filters={
                "sku_product": sku_product,
                "status": "Active",
                "is_winner": 1
            },
            fields=[
                "name", "seller", "seller_name", "offer_price",
                "delivery_days", "stock_available", "buy_box_score",
                "is_winner", "price_score", "delivery_score",
                "rating_score", "stock_score"
            ]
        )

        self.assertEqual(
            len(winners),
            1,
            f"Should have exactly 1 winner, found {len(winners)}"
        )

        return winners[0] if winners else None

    def _step_rotation_after_price_change(
        self,
        sku_product: str,
        entries: List[Any]
    ) -> Optional[Dict]:
        """
        Step 3: Buy Box winner rotates after conditions change.

        This step:
        1. Records the current winner
        2. Updates an entry to have significantly better price
        3. Recalculates Buy Box
        4. Verifies winner changed if appropriate

        Args:
            sku_product: The SKU Product name
            entries: List of Buy Box Entry documents

        Returns:
            dict: New winner entry details
        """
        # Get current winner
        current_winner = frappe.get_all(
            "Buy Box Entry",
            filters={
                "sku_product": sku_product,
                "is_winner": 1
            },
            fields=["name", "seller", "offer_price"],
            limit=1
        )
        current_winner_name = current_winner[0]["name"] if current_winner else None

        # Find a non-winner entry to improve significantly
        non_winner = None
        for entry in entries:
            if entry.name != current_winner_name:
                non_winner = entry
                break

        if non_winner:
            # Significantly lower the price to make this entry win
            frappe.db.set_value(
                "Buy Box Entry",
                non_winner.name,
                {
                    "offer_price": 50.00,  # Much cheaper
                    "delivery_days": 3,  # Faster delivery
                    "stock_available": 2000  # More stock
                }
            )
            frappe.db.commit()

            # Recalculate
            try:
                from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
                result = calculate_buybox_winner(
                    sku_product,
                    use_locking=False,
                    update_entries=True
                )
            except ImportError:
                from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                    recalculate_buy_box_for_product
                )
                result = recalculate_buy_box_for_product(sku_product)

            # Get new winner
            new_winner = frappe.get_all(
                "Buy Box Entry",
                filters={
                    "sku_product": sku_product,
                    "is_winner": 1
                },
                fields=["name", "seller", "offer_price", "buy_box_score"],
                limit=1
            )

            if new_winner:
                # Verify winner changed (the improved entry should win now)
                self.assertEqual(
                    new_winner[0]["name"],
                    non_winner.name,
                    "Winner should have changed to the improved entry"
                )
                return new_winner[0]

        return None

    def _step_brand_gating_restriction(
        self,
        product: Any,
        sellers: List[Any]
    ) -> Dict:
        """
        Step 4: Brand gating restricts unauthorized sellers.

        This step:
        1. Creates a brand-protected product
        2. Authorizes some sellers for the brand
        3. Attempts to create Buy Box entry for unauthorized seller
        4. Verifies authorization check works

        Args:
            product: SKU Product document
            sellers: List of Seller Profile documents

        Returns:
            dict: Result with restriction_enforced flag
        """
        result = {
            "restriction_enforced": False,
            "authorized_sellers": [],
            "unauthorized_sellers": []
        }

        if not self.test_brand or not frappe.db.exists("DocType", "Brand Gating"):
            return result

        # Update product with brand
        frappe.db.set_value("SKU Product", product.name, "brand", self.test_brand.name)

        # Authorize only the first seller for this brand
        authorized_seller = sellers[0]
        gating = frappe.new_doc("Brand Gating")
        gating.brand = self.test_brand.name
        gating.seller = authorized_seller.name
        gating.authorization_type = "Standard Reseller"
        gating.authorization_status = "Approved"
        gating.eligible_for_buybox = 1
        gating.is_active = 1
        gating.valid_from = today()
        gating.flags.ignore_permissions = True
        gating.insert()

        result["authorized_sellers"].append(authorized_seller.name)

        # Check authorization for each seller
        from tr_tradehub.trade_hub.doctype.brand_gating.brand_gating import (
            check_seller_authorization,
            get_buybox_eligibility
        )

        for seller in sellers:
            auth = check_seller_authorization(self.test_brand.name, seller.name)
            eligibility = get_buybox_eligibility(self.test_brand.name, seller.name)

            if seller.name == authorized_seller.name:
                self.assertIsNotNone(
                    auth,
                    f"Authorized seller {seller.seller_name} should have authorization"
                )
                self.assertTrue(
                    eligibility.get("eligible_for_buybox"),
                    "Authorized seller should be eligible for Buy Box"
                )
            else:
                self.assertIsNone(
                    auth,
                    f"Unauthorized seller {seller.seller_name} should not have authorization"
                )
                self.assertFalse(
                    eligibility.get("is_authorized"),
                    "Unauthorized seller should not be authorized"
                )
                result["unauthorized_sellers"].append(seller.name)
                result["restriction_enforced"] = True

        # Clean up gating
        frappe.delete_doc("Brand Gating", gating.name, force=True, ignore_permissions=True)

        return result

    # =========================================================================
    # INDIVIDUAL FLOW TESTS
    # =========================================================================

    def test_buybox_entry_creation_validation(self):
        """Test that Buy Box entry creation validates required fields."""
        seller_user = self._create_test_user(
            self.seller_configs[0]["email"],
            "Test",
            "Seller"
        )
        seller = self._create_verified_seller(seller_user, self.seller_configs[0]["name"])
        product = self._create_test_product(
            self.test_product_name,
            self.test_sku_code,
            seller
        )

        # Create valid entry
        entry = self._create_buybox_entry(
            product=product,
            seller=seller,
            offer_price=100.00,
            delivery_days=7,
            stock_available=100
        )

        self.assertIsNotNone(entry, "Entry should be created")
        self.assertEqual(entry.status, "Active", "Entry should be Active")

        # Verify fetch_from fields populated
        self.assertEqual(entry.tenant, seller.tenant, "Tenant should be fetched from seller")

    def test_buybox_score_calculation(self):
        """Test that Buy Box scores are calculated correctly."""
        # Create seller and product
        seller_user = self._create_test_user(
            self.seller_configs[0]["email"],
            "Test",
            "Seller"
        )
        seller = self._create_verified_seller(
            seller_user,
            self.seller_configs[0]["name"],
            average_rating=4.5,
            total_reviews=100
        )
        product = self._create_test_product(
            self.test_product_name,
            self.test_sku_code,
            seller
        )

        # Create Buy Box entry
        entry = self._create_buybox_entry(
            product=product,
            seller=seller,
            offer_price=100.00,
            delivery_days=7,
            stock_available=500,
            seller_average_rating=4.5,
            seller_total_reviews=100
        )

        # Trigger score calculation
        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(product.name, use_locking=False, update_entries=True)
        except ImportError:
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(product.name)

        # Reload entry to get updated scores
        entry.reload()

        # Verify all score components are set
        self.assertIsNotNone(entry.buy_box_score, "Buy box score should be set")
        self.assertGreater(flt(entry.buy_box_score), 0, "Buy box score should be positive")

        # With only one entry, it should be the winner
        self.assertEqual(entry.is_winner, 1, "Only entry should be winner")

    def test_buybox_winner_changes_on_better_offer(self):
        """Test that winner changes when a better offer is submitted."""
        # Set up multiple sellers and entries
        product, sellers, entries = self._step_multiple_sellers_list_sku()

        # Calculate initial winner
        initial_winner = self._step_buybox_selects_winner(product.name)
        initial_winner_name = initial_winner.get("name")

        # Find a non-winner and make their offer significantly better
        for entry in entries:
            if entry.name != initial_winner_name:
                # Make this entry have the best possible offer
                frappe.db.set_value(
                    "Buy Box Entry",
                    entry.name,
                    {
                        "offer_price": 10.00,  # Very cheap
                        "delivery_days": 1,  # Very fast
                        "stock_available": 10000,  # Lots of stock
                        "seller_average_rating": 5.0,  # Perfect rating
                        "seller_total_reviews": 1000  # Many reviews
                    }
                )
                expected_new_winner = entry.name
                break

        frappe.db.commit()

        # Recalculate
        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(product.name, use_locking=False, update_entries=True)
        except ImportError:
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(product.name)

        # Get new winner
        new_winner = frappe.get_all(
            "Buy Box Entry",
            filters={"sku_product": product.name, "is_winner": 1},
            fields=["name"],
            limit=1
        )

        self.assertEqual(
            new_winner[0]["name"],
            expected_new_winner,
            "Winner should change to entry with better offer"
        )

    def test_buybox_price_score_ranking(self):
        """Test that lower prices receive higher price scores."""
        product, sellers, entries = self._step_multiple_sellers_list_sku()

        # Recalculate scores
        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(product.name, use_locking=False, update_entries=True)
        except ImportError:
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(product.name)

        # Get all entries with scores
        scored_entries = frappe.get_all(
            "Buy Box Entry",
            filters={"sku_product": product.name, "status": "Active"},
            fields=["name", "offer_price", "price_score"],
            order_by="offer_price asc"
        )

        # Cheapest entry should have highest price score
        for i in range(len(scored_entries) - 1):
            self.assertGreaterEqual(
                flt(scored_entries[i]["price_score"]),
                flt(scored_entries[i + 1]["price_score"]),
                f"Entry with price {scored_entries[i]['offer_price']} should have "
                f">= price_score than entry with price {scored_entries[i + 1]['offer_price']}"
            )

    def test_buybox_delivery_score_ranking(self):
        """Test that faster delivery receives higher delivery scores."""
        product, sellers, entries = self._step_multiple_sellers_list_sku()

        # Recalculate scores
        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(product.name, use_locking=False, update_entries=True)
        except ImportError:
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(product.name)

        # Get all entries with scores
        scored_entries = frappe.get_all(
            "Buy Box Entry",
            filters={"sku_product": product.name, "status": "Active"},
            fields=["name", "delivery_days", "delivery_score"],
            order_by="delivery_days asc"
        )

        # Fastest delivery should have highest delivery score
        for i in range(len(scored_entries) - 1):
            self.assertGreaterEqual(
                flt(scored_entries[i]["delivery_score"]),
                flt(scored_entries[i + 1]["delivery_score"]),
                f"Entry with {scored_entries[i]['delivery_days']} days should have "
                f">= delivery_score than entry with {scored_entries[i + 1]['delivery_days']} days"
            )

    def test_buybox_inactive_entry_excluded(self):
        """Test that inactive entries are excluded from Buy Box calculation."""
        product, sellers, entries = self._step_multiple_sellers_list_sku()

        # Deactivate one entry
        entries[0].status = "Inactive"
        entries[0].is_active = 0
        entries[0].flags.ignore_permissions = True
        entries[0].save()

        # Recalculate
        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(product.name, use_locking=False, update_entries=True)
        except ImportError:
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(product.name)

        # Get winner
        winner = frappe.get_all(
            "Buy Box Entry",
            filters={"sku_product": product.name, "is_winner": 1},
            fields=["name"],
            limit=1
        )

        # Inactive entry should not be winner
        if winner:
            self.assertNotEqual(
                winner[0]["name"],
                entries[0].name,
                "Inactive entry should not be the winner"
            )

    def test_buybox_single_entry_auto_wins(self):
        """Test that a single entry automatically wins the Buy Box."""
        seller_user = self._create_test_user(
            self.seller_configs[0]["email"],
            "Test",
            "Seller"
        )
        seller = self._create_verified_seller(seller_user, self.seller_configs[0]["name"])
        product = self._create_test_product(
            self.test_product_name,
            self.test_sku_code,
            seller
        )

        # Create single entry
        entry = self._create_buybox_entry(
            product=product,
            seller=seller,
            offer_price=100.00,
            delivery_days=7,
            stock_available=500
        )

        # Recalculate
        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(product.name, use_locking=False, update_entries=True)
        except ImportError:
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(product.name)

        entry.reload()

        self.assertEqual(entry.is_winner, 1, "Single entry should automatically win")
        self.assertEqual(
            flt(entry.buy_box_score),
            100.0,
            "Single entry should have perfect score (100)"
        )

    def test_buybox_statistics_api(self):
        """Test Buy Box statistics API."""
        product, sellers, entries = self._step_multiple_sellers_list_sku()

        # Get statistics
        from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
            get_buy_box_statistics
        )
        stats = get_buy_box_statistics(sku_product=product.name)

        self.assertEqual(stats["total_entries"], 3, "Should have 3 total entries")
        self.assertEqual(stats["total_winners"], 0, "No winners yet before calculation")
        self.assertIsNotNone(stats["average_price"], "Average price should be calculated")

    def test_buybox_tenant_isolation(self):
        """Test that Buy Box entries respect tenant isolation."""
        product, sellers, entries = self._step_multiple_sellers_list_sku()

        # All entries should have same tenant as sellers
        for entry, seller in zip(entries, sellers):
            entry.reload()
            self.assertEqual(
                entry.tenant,
                seller.tenant,
                f"Entry tenant should match seller tenant"
            )

        # Query entries for this tenant only
        tenant_entries = frappe.get_all(
            "Buy Box Entry",
            filters={
                "tenant": self.test_tenant.name,
                "sku_product": product.name
            },
            pluck="name"
        )

        self.assertEqual(
            len(tenant_entries),
            3,
            "All entries should be in the test tenant"
        )

    def test_brand_authorization_check(self):
        """Test brand authorization check function."""
        if not self.test_brand or not frappe.db.exists("DocType", "Brand Gating"):
            self.skipTest("Brand or Brand Gating DocType not available")

        seller_user = self._create_test_user(
            self.seller_configs[0]["email"],
            "Test",
            "Seller"
        )
        seller = self._create_verified_seller(seller_user, self.seller_configs[0]["name"])

        # Check authorization before granting
        from tr_tradehub.trade_hub.doctype.brand_gating.brand_gating import (
            check_seller_authorization
        )

        auth = check_seller_authorization(self.test_brand.name, seller.name)
        self.assertIsNone(auth, "Seller should not be authorized initially")

        # Grant authorization
        gating = frappe.new_doc("Brand Gating")
        gating.brand = self.test_brand.name
        gating.seller = seller.name
        gating.authorization_type = "Standard Reseller"
        gating.authorization_status = "Approved"
        gating.is_active = 1
        gating.valid_from = today()
        gating.flags.ignore_permissions = True
        gating.insert()

        # Check again
        auth = check_seller_authorization(self.test_brand.name, seller.name)
        self.assertIsNotNone(auth, "Seller should now be authorized")

        # Clean up
        frappe.delete_doc("Brand Gating", gating.name, force=True, ignore_permissions=True)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _create_test_user(self, email: str, first_name: str, last_name: str) -> Any:
        """Create a test user."""
        if frappe.db.exists("User", email):
            return frappe.get_doc("User", email)

        user = frappe.new_doc("User")
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.username = email.split("@")[0]
        user.enabled = 1
        user.send_welcome_email = 0

        if hasattr(user, "tenant"):
            user.tenant = self.test_tenant.name

        user.flags.ignore_permissions = True
        user.flags.no_welcome_mail = True
        user.insert()

        return user

    def _create_verified_seller(
        self,
        user: Any,
        seller_name: str,
        average_rating: float = 4.0,
        total_reviews: int = 50
    ) -> Any:
        """Create a verified seller profile with rating metrics."""
        seller = frappe.new_doc("Seller Profile")
        seller.seller_name = seller_name
        seller.company_name = f"{seller_name} Ltd."
        seller.user = user.name
        seller.tenant = self.test_tenant.name
        seller.contact_email = user.email
        seller.contact_phone = "+1234567890"
        seller.city = "Istanbul"
        seller.country = "Turkey"
        seller.verification_status = "Verified"
        seller.status = "Active"

        # Set rating metrics if fields exist
        if hasattr(seller, "average_rating"):
            seller.average_rating = average_rating
        if hasattr(seller, "total_reviews"):
            seller.total_reviews = total_reviews

        seller.flags.ignore_permissions = True
        seller.insert()

        return seller

    def _create_test_product(
        self,
        product_name: str,
        sku_code: str,
        seller: Any,
        base_price: float = 100.00
    ) -> Any:
        """Create a test product."""
        product = frappe.new_doc("SKU Product")
        product.product_name = product_name
        product.sku_code = sku_code
        product.seller = seller.name
        product.tenant = seller.tenant
        product.status = "Active"
        product.is_published = 1
        product.base_price = base_price
        product.currency = "USD"
        product.min_order_quantity = 10
        product.max_order_quantity = 1000
        product.stock_quantity = 500
        product.stock_uom = "Unit"
        product.is_stock_item = 1
        product.description = f"Test product: {product_name}"

        if self.test_category:
            product.category = self.test_category.name

        if self.test_brand:
            product.brand = self.test_brand.name

        product.flags.ignore_permissions = True
        product.insert()

        return product

    def _create_buybox_entry(
        self,
        product: Any,
        seller: Any,
        offer_price: float,
        delivery_days: int,
        stock_available: float,
        seller_average_rating: float = 4.0,
        seller_total_reviews: int = 50
    ) -> Any:
        """Create a Buy Box entry."""
        entry = frappe.new_doc("Buy Box Entry")
        entry.sku_product = product.name
        entry.seller = seller.name
        entry.offer_price = offer_price
        entry.currency = "USD"
        entry.delivery_days = delivery_days
        entry.stock_available = stock_available
        entry.min_order_quantity = 1
        entry.status = "Active"
        entry.is_active = 1

        # Set seller rating info
        entry.seller_average_rating = seller_average_rating
        entry.seller_total_reviews = seller_total_reviews

        entry.flags.ignore_permissions = True
        entry.insert()

        return entry

    @classmethod
    def _get_or_create_test_tenant(cls) -> Any:
        """Get or create a test tenant for E2E tests."""
        tenant_name = "E2E-BUYBOX-TENANT"

        if frappe.db.exists("Tenant", tenant_name):
            return frappe.get_doc("Tenant", tenant_name)

        # Check if Tenant DocType exists
        if not frappe.db.exists("DocType", "Tenant"):
            # Create a mock tenant object for testing without Tenant DocType
            class MockTenant:
                name = tenant_name
            return MockTenant()

        tenant = frappe.new_doc("Tenant")
        tenant.tenant_name = tenant_name
        tenant.enabled = 1
        tenant.subscription_tier = "Professional"
        tenant.flags.ignore_permissions = True
        tenant.insert()

        return tenant

    @classmethod
    def _get_or_create_test_category(cls) -> Optional[Any]:
        """Get or create a test product category."""
        if not frappe.db.exists("DocType", "Product Category"):
            return None

        category_name = "E2E Buy Box Test Category"
        existing = frappe.db.get_value(
            "Product Category",
            {"category_name": category_name},
            "name"
        )

        if existing:
            return frappe.get_doc("Product Category", existing)

        category = frappe.new_doc("Product Category")
        category.category_name = category_name
        category.enabled = 1
        category.flags.ignore_permissions = True
        category.insert()

        return category

    @classmethod
    def _get_or_create_test_brand(cls) -> Optional[Any]:
        """Get or create a test brand."""
        if not frappe.db.exists("DocType", "Brand"):
            return None

        brand_name = "E2E Buy Box Test Brand"
        existing = frappe.db.get_value(
            "Brand",
            {"brand_name": brand_name},
            "name"
        )

        if existing:
            return frappe.get_doc("Brand", existing)

        brand = frappe.new_doc("Brand")
        brand.brand_name = brand_name
        brand.enabled = 1
        brand.verification_status = "Verified"
        brand.tenant = cls.test_tenant.name if hasattr(cls, 'test_tenant') else None
        brand.flags.ignore_permissions = True
        brand.insert()

        return brand

    def _cleanup_test_data(self):
        """Clean up test data created during tests."""
        # Delete in reverse order of dependencies

        # Delete Brand Gatings
        if frappe.db.exists("DocType", "Brand Gating"):
            gatings = frappe.get_all(
                "Brand Gating",
                filters={
                    "seller": ["like", f"%{self.test_suffix}%"]
                },
                pluck="name"
            )
            for gating in gatings:
                try:
                    frappe.delete_doc("Brand Gating", gating, force=True, ignore_permissions=True)
                except Exception:
                    pass

        # Delete Buy Box Entries
        entries = frappe.get_all(
            "Buy Box Entry",
            filters={
                "sku_product": ["like", f"%{self.test_suffix}%"]
            },
            pluck="name"
        )
        for entry in entries:
            try:
                frappe.delete_doc("Buy Box Entry", entry, force=True, ignore_permissions=True)
            except Exception:
                pass

        # Delete SKU Products
        products = frappe.get_all(
            "SKU Product",
            filters={"sku_code": ["like", f"%{self.test_suffix}%"]},
            pluck="name"
        )
        for product in products:
            try:
                frappe.delete_doc("SKU Product", product, force=True, ignore_permissions=True)
            except Exception:
                pass

        # Delete Seller Profiles
        sellers = frappe.get_all(
            "Seller Profile",
            filters={"seller_name": ["like", f"%{self.test_suffix}%"]},
            pluck="name"
        )
        for seller in sellers:
            try:
                frappe.delete_doc("Seller Profile", seller, force=True, ignore_permissions=True)
            except Exception:
                pass

        # Delete Users
        for config in self.seller_configs:
            if frappe.db.exists("User", config["email"]):
                try:
                    frappe.delete_doc("User", config["email"], force=True, ignore_permissions=True)
                except Exception:
                    pass


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================


class TestBuyBoxPerformance(unittest.TestCase):
    """
    Performance tests for Buy Box calculation.

    These tests ensure the Buy Box algorithm meets performance requirements.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        frappe.set_user("Administrator")
        cls.test_tenant = TestE2EBuyBoxCompetition._get_or_create_test_tenant()

    def test_buybox_calculation_performance(self):
        """Test that Buy Box calculation completes within acceptable time."""
        import time

        test_suffix = random_string(6).lower()

        # Create seller
        seller_email = f"perf_seller_{test_suffix}@example.com"

        user = frappe.new_doc("User")
        user.email = seller_email
        user.first_name = "Performance"
        user.last_name = "Test"
        user.enabled = 1
        user.send_welcome_email = 0
        user.flags.ignore_permissions = True
        user.insert()

        seller = frappe.new_doc("Seller Profile")
        seller.seller_name = f"Perf Seller {test_suffix}"
        seller.user = user.name
        seller.tenant = self.test_tenant.name
        seller.contact_email = seller_email
        seller.verification_status = "Verified"
        seller.status = "Active"
        seller.flags.ignore_permissions = True
        seller.insert()

        # Create product
        product = frappe.new_doc("SKU Product")
        product.product_name = f"Perf Product {test_suffix}"
        product.sku_code = f"PERF-{test_suffix}".upper()
        product.seller = seller.name
        product.tenant = seller.tenant
        product.status = "Active"
        product.base_price = 100.00
        product.currency = "USD"
        product.flags.ignore_permissions = True
        product.insert()

        # Create multiple Buy Box entries
        for i in range(10):
            entry = frappe.new_doc("Buy Box Entry")
            entry.sku_product = product.name
            entry.seller = seller.name
            entry.offer_price = 100 + i * 10
            entry.currency = "USD"
            entry.delivery_days = 5 + i
            entry.stock_available = 100 * (i + 1)
            entry.status = "Active"
            entry.is_active = 1
            entry.seller_average_rating = 4.0 + (i * 0.1)
            entry.seller_total_reviews = 50 + (i * 10)
            entry.flags.ignore_permissions = True
            entry.insert()

        # Measure calculation time
        start_time = time.time()

        try:
            from tr_tradehub.utils.buybox_algorithm import calculate_buybox_winner
            result = calculate_buybox_winner(product.name, use_locking=False, update_entries=True)
        except ImportError:
            from tr_tradehub.trade_hub.doctype.buy_box_entry.buy_box_entry import (
                recalculate_buy_box_for_product
            )
            result = recalculate_buy_box_for_product(product.name)

        elapsed_time = time.time() - start_time

        # Should complete within 1 second
        self.assertLess(
            elapsed_time,
            1.0,
            f"Buy Box calculation for 10 entries took {elapsed_time:.3f}s, expected < 1s"
        )

        # Cleanup
        frappe.db.rollback()


# =============================================================================
# TEST RUNNER
# =============================================================================


def run_tests():
    """Run all E2E Buy Box tests."""
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestE2EBuyBoxCompetition))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestBuyBoxPerformance))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    run_tests()
