"""Test ERPNext Webhook Handlers for Reverse Sync

This test suite verifies that all ERPNext webhook handlers are correctly
configured and fire appropriately for reverse synchronization between
ERPNext and TradeHub.

ERPNext -> TradeHub Mapping:
1. Supplier -> Seller Profile (tradehub_seller)
2. Customer -> Buyer Profile (tradehub_core)
3. Sales Order -> Order/Marketplace Order (tradehub_commerce)
4. Stock Entry -> Inventory/SKU (tradehub_commerce)
5. Delivery Note -> Shipment (tradehub_logistics via tradehub_commerce)

Test Coverage:
- Handler configuration in hooks.py for each app
- Handler function signatures and error handling
- Field mapping verification
- Cross-app integration points
"""

import unittest
import json
import os


class TestERPNextWebhookHandlerConfiguration(unittest.TestCase):
    """Test that ERPNext webhook handlers are properly configured in hooks.py files."""

    def setUp(self):
        """Set up test environment."""
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.apps_path = self.base_path

    def test_supplier_to_seller_profile_hooks_configured(self):
        """Verify Supplier -> Seller Profile handlers are configured in tradehub_seller."""
        hooks_path = os.path.join(self.apps_path, "tradehub_seller", "tradehub_seller", "hooks.py")
        self.assertTrue(os.path.exists(hooks_path), "tradehub_seller hooks.py should exist")

        with open(hooks_path, "r") as f:
            content = f.read()

        # Verify Supplier handlers are registered
        self.assertIn('"Supplier"', content, "Supplier doc_events should be configured")
        self.assertIn("on_supplier_update", content, "on_supplier_update handler should be registered")
        self.assertIn("on_supplier_insert", content, "on_supplier_insert handler should be registered")
        self.assertIn("on_supplier_delete", content, "on_supplier_delete handler should be registered")
        self.assertIn("tradehub_seller.tradehub_seller.webhooks.erpnext_hooks", content,
                     "Handler path should reference webhooks.erpnext_hooks module")

    def test_customer_to_buyer_profile_hooks_configured(self):
        """Verify Customer -> Buyer Profile handlers are configured in tradehub_core."""
        hooks_path = os.path.join(self.apps_path, "tradehub_core", "tradehub_core", "hooks.py")
        self.assertTrue(os.path.exists(hooks_path), "tradehub_core hooks.py should exist")

        with open(hooks_path, "r") as f:
            content = f.read()

        # Verify Customer handlers are registered
        self.assertIn('"Customer"', content, "Customer doc_events should be configured")
        self.assertIn("on_customer_update", content, "on_customer_update handler should be registered")
        self.assertIn("on_customer_insert", content, "on_customer_insert handler should be registered")
        self.assertIn("on_customer_delete", content, "on_customer_delete handler should be registered")
        self.assertIn("tradehub_core.tradehub_core.webhooks.erpnext_hooks", content,
                     "Handler path should reference webhooks.erpnext_hooks module")

    def test_sales_order_to_order_hooks_configured(self):
        """Verify Sales Order -> Order handlers are configured in tradehub_commerce."""
        hooks_path = os.path.join(self.apps_path, "tradehub_commerce", "tradehub_commerce", "hooks.py")
        self.assertTrue(os.path.exists(hooks_path), "tradehub_commerce hooks.py should exist")

        with open(hooks_path, "r") as f:
            content = f.read()

        # Verify Sales Order handlers are registered
        self.assertIn('"Sales Order"', content, "Sales Order doc_events should be configured")
        self.assertIn("on_sales_order_update", content, "on_sales_order_update handler should be registered")
        self.assertIn("on_sales_order_submit", content, "on_sales_order_submit handler should be registered")
        self.assertIn("tradehub_commerce.webhooks.erpnext_hooks", content,
                     "Handler path should reference webhooks.erpnext_hooks module")

    def test_stock_entry_to_inventory_hooks_configured(self):
        """Verify Stock Entry -> Inventory handlers are configured in tradehub_commerce."""
        hooks_path = os.path.join(self.apps_path, "tradehub_commerce", "tradehub_commerce", "hooks.py")
        self.assertTrue(os.path.exists(hooks_path), "tradehub_commerce hooks.py should exist")

        with open(hooks_path, "r") as f:
            content = f.read()

        # Verify Stock Entry handlers are registered
        self.assertIn('"Stock Entry"', content, "Stock Entry doc_events should be configured")
        self.assertIn("on_stock_entry_submit", content, "on_stock_entry_submit handler should be registered")

    def test_delivery_note_hooks_configured(self):
        """Verify Delivery Note handlers are configured in tradehub_commerce."""
        hooks_path = os.path.join(self.apps_path, "tradehub_commerce", "tradehub_commerce", "hooks.py")
        self.assertTrue(os.path.exists(hooks_path), "tradehub_commerce hooks.py should exist")

        with open(hooks_path, "r") as f:
            content = f.read()

        # Verify Delivery Note handlers are registered
        self.assertIn('"Delivery Note"', content, "Delivery Note doc_events should be configured")
        self.assertIn("on_delivery_note_submit", content, "on_delivery_note_submit handler should be registered")


class TestERPNextWebhookHandlerModules(unittest.TestCase):
    """Test that ERPNext webhook handler modules exist and have required functions."""

    def setUp(self):
        """Set up test environment."""
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.apps_path = self.base_path

    def test_seller_webhooks_module_exists(self):
        """Verify tradehub_seller webhooks module exists with required handlers."""
        module_path = os.path.join(
            self.apps_path, "tradehub_seller", "tradehub_seller", "webhooks", "erpnext_hooks.py"
        )
        self.assertTrue(os.path.exists(module_path), "tradehub_seller webhooks/erpnext_hooks.py should exist")

        with open(module_path, "r") as f:
            content = f.read()

        # Verify required handlers exist
        self.assertIn("def on_supplier_update(", content, "on_supplier_update function should exist")
        self.assertIn("def on_supplier_insert(", content, "on_supplier_insert function should exist")
        self.assertIn("def on_supplier_delete(", content, "on_supplier_delete function should exist")

        # Verify handler docstrings explain the mapping
        self.assertIn("Supplier", content, "Module should mention Supplier")
        self.assertIn("Seller Profile", content, "Module should mention Seller Profile")

    def test_core_webhooks_module_exists(self):
        """Verify tradehub_core webhooks module exists with required handlers."""
        module_path = os.path.join(
            self.apps_path, "tradehub_core", "tradehub_core", "webhooks", "erpnext_hooks.py"
        )
        self.assertTrue(os.path.exists(module_path), "tradehub_core webhooks/erpnext_hooks.py should exist")

        with open(module_path, "r") as f:
            content = f.read()

        # Verify required handlers exist
        self.assertIn("def on_customer_update(", content, "on_customer_update function should exist")
        self.assertIn("def on_customer_insert(", content, "on_customer_insert function should exist")
        self.assertIn("def on_customer_delete(", content, "on_customer_delete function should exist")

        # Verify handler docstrings explain the mapping
        self.assertIn("Customer", content, "Module should mention Customer")
        self.assertIn("Buyer Profile", content, "Module should mention Buyer Profile")

    def test_commerce_webhooks_module_exists(self):
        """Verify tradehub_commerce webhooks module exists with required handlers."""
        module_path = os.path.join(
            self.apps_path, "tradehub_commerce", "tradehub_commerce", "webhooks", "erpnext_hooks.py"
        )
        self.assertTrue(os.path.exists(module_path), "tradehub_commerce webhooks/erpnext_hooks.py should exist")

        with open(module_path, "r") as f:
            content = f.read()

        # Verify required handlers exist
        self.assertIn("def on_sales_order_update(", content, "on_sales_order_update function should exist")
        self.assertIn("def on_sales_order_submit(", content, "on_sales_order_submit function should exist")
        self.assertIn("def on_stock_entry_submit(", content, "on_stock_entry_submit function should exist")
        self.assertIn("def on_delivery_note_submit(", content, "on_delivery_note_submit function should exist")

        # Verify handler docstrings explain the mappings
        self.assertIn("Sales Order", content, "Module should mention Sales Order")
        self.assertIn("Marketplace Order", content, "Module should mention Marketplace Order")
        self.assertIn("Stock Entry", content, "Module should mention Stock Entry")


class TestERPNextFieldMappings(unittest.TestCase):
    """Test that field mappings between ERPNext and TradeHub are correct."""

    def setUp(self):
        """Set up test environment."""
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.apps_path = self.base_path

    def test_supplier_to_seller_field_mappings(self):
        """Verify Supplier -> Seller Profile field mappings."""
        module_path = os.path.join(
            self.apps_path, "tradehub_seller", "tradehub_seller", "webhooks", "erpnext_hooks.py"
        )
        with open(module_path, "r") as f:
            content = f.read()

        # Verify key field mappings
        self.assertIn("supplier_name", content, "supplier_name field should be mapped")
        self.assertIn("company_name", content, "Should map to company_name")
        self.assertIn("tax_id", content, "tax_id field should be mapped")
        self.assertIn("contact_email", content, "contact_email should be synced")
        self.assertIn("contact_phone", content, "contact_phone should be synced")

    def test_customer_to_buyer_field_mappings(self):
        """Verify Customer -> Buyer Profile field mappings."""
        module_path = os.path.join(
            self.apps_path, "tradehub_core", "tradehub_core", "webhooks", "erpnext_hooks.py"
        )
        with open(module_path, "r") as f:
            content = f.read()

        # Verify key field mappings
        self.assertIn("customer_name", content, "customer_name field should be mapped")
        self.assertIn("company_name", content, "Should map to company_name")
        self.assertIn("tax_id", content, "tax_id field should be mapped")
        self.assertIn("address", content, "address should be synced")
        self.assertIn("phone", content, "phone should be synced")

    def test_sales_order_to_order_field_mappings(self):
        """Verify Sales Order -> Order field mappings."""
        module_path = os.path.join(
            self.apps_path, "tradehub_commerce", "tradehub_commerce", "webhooks", "erpnext_hooks.py"
        )
        with open(module_path, "r") as f:
            content = f.read()

        # Verify key field mappings
        self.assertIn("custom_marketplace_order_id", content, "Should use custom link field")
        self.assertIn("erpnext_status", content, "erpnext_status should be synced")
        self.assertIn("grand_total", content, "grand_total should be synced")
        self.assertIn("last_erpnext_sync", content, "Should track sync timestamp")

    def test_stock_entry_to_inventory_field_mappings(self):
        """Verify Stock Entry -> Inventory field mappings."""
        module_path = os.path.join(
            self.apps_path, "tradehub_commerce", "tradehub_commerce", "webhooks", "erpnext_hooks.py"
        )
        with open(module_path, "r") as f:
            content = f.read()

        # Verify key field mappings
        self.assertIn("custom_tradehub_sku", content, "Should use custom SKU link")
        self.assertIn("available_qty", content, "available_qty should be updated")
        self.assertIn("Material Receipt", content, "Should handle Material Receipt")
        self.assertIn("Material Issue", content, "Should handle Material Issue")


class TestERPNextWebhookErrorHandling(unittest.TestCase):
    """Test that ERPNext webhook handlers have proper error handling."""

    def setUp(self):
        """Set up test environment."""
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.apps_path = self.base_path

    def test_seller_handlers_have_error_handling(self):
        """Verify tradehub_seller handlers have try/except blocks."""
        module_path = os.path.join(
            self.apps_path, "tradehub_seller", "tradehub_seller", "webhooks", "erpnext_hooks.py"
        )
        with open(module_path, "r") as f:
            content = f.read()

        self.assertIn("try:", content, "Handlers should use try/except")
        self.assertIn("except Exception", content, "Should catch exceptions")
        self.assertIn("frappe.log_error", content, "Should log errors")
        self.assertIn("ERPNext Sync Error", content, "Should use consistent error title")

    def test_core_handlers_have_error_handling(self):
        """Verify tradehub_core handlers have try/except blocks."""
        module_path = os.path.join(
            self.apps_path, "tradehub_core", "tradehub_core", "webhooks", "erpnext_hooks.py"
        )
        with open(module_path, "r") as f:
            content = f.read()

        self.assertIn("try:", content, "Handlers should use try/except")
        self.assertIn("except Exception", content, "Should catch exceptions")
        self.assertIn("frappe.log_error", content, "Should log errors")
        self.assertIn("ERPNext Sync Error", content, "Should use consistent error title")

    def test_commerce_handlers_have_error_handling(self):
        """Verify tradehub_commerce handlers have try/except blocks."""
        module_path = os.path.join(
            self.apps_path, "tradehub_commerce", "tradehub_commerce", "webhooks", "erpnext_hooks.py"
        )
        with open(module_path, "r") as f:
            content = f.read()

        self.assertIn("try:", content, "Handlers should use try/except")
        self.assertIn("except Exception", content, "Should catch exceptions")
        self.assertIn("frappe.log_error", content, "Should log errors")


class TestERPNextReverseyncMatrix(unittest.TestCase):
    """Test the complete ERPNext reverse sync matrix."""

    def setUp(self):
        """Set up test environment."""
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.apps_path = self.base_path

        # Define the complete reverse sync matrix
        self.sync_matrix = {
            "Supplier -> Seller Profile": {
                "erpnext_doctype": "Supplier",
                "tradehub_doctype": "Seller Profile",
                "tradehub_app": "tradehub_seller",
                "events": ["on_update", "after_insert", "on_trash"],
                "handler_prefix": "on_supplier"
            },
            "Customer -> Buyer Profile": {
                "erpnext_doctype": "Customer",
                "tradehub_doctype": "Buyer Profile",
                "tradehub_app": "tradehub_core",
                "events": ["on_update", "after_insert", "on_trash"],
                "handler_prefix": "on_customer"
            },
            "Sales Order -> Order": {
                "erpnext_doctype": "Sales Order",
                "tradehub_doctype": "Marketplace Order",
                "tradehub_app": "tradehub_commerce",
                "events": ["on_update", "on_submit"],
                "handler_prefix": "on_sales_order"
            },
            "Stock Entry -> Inventory": {
                "erpnext_doctype": "Stock Entry",
                "tradehub_doctype": "SKU",
                "tradehub_app": "tradehub_commerce",
                "events": ["on_submit"],
                "handler_prefix": "on_stock_entry"
            },
            "Delivery Note -> Shipment": {
                "erpnext_doctype": "Delivery Note",
                "tradehub_doctype": "Marketplace Shipment",
                "tradehub_app": "tradehub_commerce",
                "events": ["on_submit"],
                "handler_prefix": "on_delivery_note"
            }
        }

    def test_all_sync_mappings_configured(self):
        """Verify all sync mappings are properly configured."""
        for mapping_name, config in self.sync_matrix.items():
            app = config["tradehub_app"]
            hooks_path = os.path.join(self.apps_path, app, app, "hooks.py")

            with open(hooks_path, "r") as f:
                content = f.read()

            # Verify the ERPNext DocType is registered in doc_events
            self.assertIn(
                f'"{config["erpnext_doctype"]}"',
                content,
                f"{mapping_name}: {config['erpnext_doctype']} should be in {app} doc_events"
            )

    def test_all_handler_modules_exist(self):
        """Verify all handler modules exist."""
        apps_checked = set()
        for mapping_name, config in self.sync_matrix.items():
            app = config["tradehub_app"]
            if app in apps_checked:
                continue
            apps_checked.add(app)

            module_path = os.path.join(self.apps_path, app, app, "webhooks", "erpnext_hooks.py")
            self.assertTrue(
                os.path.exists(module_path),
                f"{mapping_name}: webhooks/erpnext_hooks.py should exist in {app}"
            )

    def test_all_handlers_have_logging(self):
        """Verify all handlers have proper logging."""
        apps_checked = set()
        for mapping_name, config in self.sync_matrix.items():
            app = config["tradehub_app"]
            if app in apps_checked:
                continue
            apps_checked.add(app)

            module_path = os.path.join(self.apps_path, app, app, "webhooks", "erpnext_hooks.py")
            with open(module_path, "r") as f:
                content = f.read()

            self.assertIn("frappe.logger()", content, f"{app} handlers should use frappe.logger()")


def run_tests():
    """Run all ERPNext webhook handler tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestERPNextWebhookHandlerConfiguration))
    suite.addTests(loader.loadTestsFromTestCase(TestERPNextWebhookHandlerModules))
    suite.addTests(loader.loadTestsFromTestCase(TestERPNextFieldMappings))
    suite.addTests(loader.loadTestsFromTestCase(TestERPNextWebhookErrorHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestERPNextReverseyncMatrix))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    run_tests()
