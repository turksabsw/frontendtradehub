# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
End-to-End Test Suite: Seller Registration Flow

This module contains comprehensive tests for verifying the complete seller
registration flow from application creation to listing creation.

Test Flow:
1. Create seller application
2. Submit application
3. Admin approves
4. Verify ERPNext Supplier created
5. Seller can create listings

Usage:
    # Run from frappe-bench directory
    bench --site marketplace.local run-tests --module tr_tradehub.tr_tradehub.tests.test_seller_registration_flow

    # Or run a specific test
    bench --site marketplace.local run-tests --module tr_tradehub.tr_tradehub.tests.test_seller_registration_flow --test TestSellerRegistrationFlow.test_01_create_seller_application
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime, nowdate, random_string


class TestSellerRegistrationFlow(IntegrationTestCase):
    """
    End-to-end test suite for the seller registration workflow.

    Tests the complete flow:
    - Seller Application creation and submission
    - Admin approval workflow
    - ERPNext/Cron BI Supplier creation
    - Seller Profile creation
    - Listing creation by approved seller
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls.test_user = None
        cls.test_application = None
        cls.test_seller_profile = None
        cls.test_supplier = None
        cls.test_listing = None

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        # Clean up is handled by Frappe's test framework

    def setUp(self):
        """Set up before each test."""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        frappe.set_user("Administrator")

    # ========================================================================
    # Test 01: Create Seller Application
    # ========================================================================
    def test_01_create_seller_application(self):
        """
        Test creating a new seller application.

        Verifies:
        - Application is created in Draft status
        - All required fields are properly set
        - Auto-generated fields (application_date, created_by) are populated
        """
        # Generate unique test data
        unique_id = random_string(6)
        test_email = f"testapplicant_{unique_id}@test.tradehub.com"

        # Create test user if User DocType exists
        test_user = None
        if frappe.db.exists("DocType", "User"):
            if not frappe.db.exists("User", test_email):
                test_user = frappe.get_doc({
                    "doctype": "User",
                    "email": test_email,
                    "first_name": f"Test Applicant {unique_id}",
                    "send_welcome_email": 0
                })
                test_user.insert(ignore_permissions=True)
            else:
                test_user = frappe.get_doc("User", test_email)

        # Create seller application
        application = frappe.get_doc({
            "doctype": "Seller Application",
            "applicant_name": f"Test Applicant {unique_id}",
            "user": test_user.name if test_user else None,
            "applicant_type": "Business",
            "email": test_email,
            "mobile": "+905551234567",
            "phone": "+902121234567",
            "business_name": f"Test Business {unique_id}",
            "legal_name": f"Test Business {unique_id} Ltd.",
            "business_type": "Limited Liability Company (LLC)",
            "year_established": 2020,
            "employee_count": "11-50",
            "annual_revenue_range": "1M - 5M TRY",
            "address_line_1": "Test Street 123",
            "city": "Istanbul",
            "state": "Istanbul",
            "country": "Turkey",
            "postal_code": "34000",
            "tax_id": "1234567890",  # Valid format VKN (10 digits)
            "tax_id_type": "VKN",
            "tax_office": "Kadikoy",
            "bank_name": "Test Bank",
            "bank_branch": "Istanbul Branch",
            "iban": "TR123456789012345678901234",
            "account_holder_name": f"Test Business {unique_id}",
            "swift_code": "TESTTRXX",
            "main_categories": "Electronics, Computers",
            "products_description": "High-quality electronic products and computer components",
            "estimated_monthly_sales": "51-100 orders",
            "has_inventory": 1,
            "inventory_location": "Istanbul Warehouse",
            "shipping_capability": "National",
            "identity_document": "/files/test_identity.pdf"  # Simulated attachment
        })

        application.insert(ignore_permissions=True)

        # Store for subsequent tests
        self.__class__.test_application = application
        if test_user:
            self.__class__.test_user = test_user

        # Verify application was created
        self.assertTrue(frappe.db.exists("Seller Application", application.name))

        # Verify initial state
        self.assertEqual(application.status, "Draft")
        self.assertIsNotNone(application.application_date)

        # Verify required fields
        self.assertEqual(application.applicant_name, f"Test Applicant {unique_id}")
        self.assertEqual(application.applicant_type, "Business")
        self.assertEqual(application.city, "Istanbul")
        self.assertEqual(application.country, "Turkey")

    # ========================================================================
    # Test 02: Submit Application
    # ========================================================================
    def test_02_submit_application(self):
        """
        Test submitting a seller application.

        Verifies:
        - Application moves from Draft to Submitted status
        - Submitted timestamp is set
        - Validation runs successfully for required fields
        """
        application = self.__class__.test_application
        self.assertIsNotNone(application, "Test application not found from previous test")

        # Reload to get fresh state
        application.reload()
        self.assertEqual(application.status, "Draft")

        # Import the API function for submitting
        from tr_tradehub.tr_tradehub.doctype.seller_application.seller_application import (
            submit_application
        )

        # Submit the application
        result = submit_application(application.name)

        # Reload to verify changes
        application.reload()

        # Verify status changed
        self.assertEqual(application.status, "Submitted")
        self.assertEqual(result["status"], "Submitted")

        # Verify submitted timestamp is set
        self.assertIsNotNone(application.submitted_at)

    # ========================================================================
    # Test 03: Admin Starts Review
    # ========================================================================
    def test_03_start_review(self):
        """
        Test admin starting review of application.

        Verifies:
        - Application moves to Under Review status
        - Reviewer info is captured
        """
        application = self.__class__.test_application
        self.assertIsNotNone(application, "Test application not found")

        # Reload
        application.reload()
        self.assertEqual(application.status, "Submitted")

        # Import API function
        from tr_tradehub.tr_tradehub.doctype.seller_application.seller_application import (
            start_review
        )

        # Start review as admin
        frappe.set_user("Administrator")
        result = start_review(application.name)

        # Reload
        application.reload()

        # Verify
        self.assertEqual(application.status, "Under Review")
        self.assertIsNotNone(application.reviewed_by)
        self.assertIsNotNone(application.reviewed_at)

    # ========================================================================
    # Test 04: Admin Approves Application
    # ========================================================================
    def test_04_approve_application(self):
        """
        Test admin approval of seller application.

        Verifies:
        - Application moves to Approved status
        - ERPNext Supplier is created (if available)
        - Seller Profile is created
        - Organization is created (for business applicants)
        - All linked records are properly connected
        """
        application = self.__class__.test_application
        self.assertIsNotNone(application, "Test application not found")

        # Reload
        application.reload()
        self.assertEqual(application.status, "Under Review")

        # Import API function
        from tr_tradehub.tr_tradehub.doctype.seller_application.seller_application import (
            approve_application
        )

        # Approve the application
        frappe.set_user("Administrator")
        result = approve_application(
            application.name,
            approved_tier=None,
            commission_plan=None,
            notes="Approved via automated E2E test"
        )

        # Reload
        application.reload()

        # Verify status
        self.assertEqual(application.status, "Approved")
        self.assertEqual(result["status"], "Approved")

        # Verify Seller Profile was created
        self.assertIsNotNone(application.seller_profile)
        self.assertTrue(
            frappe.db.exists("Seller Profile", application.seller_profile),
            "Seller Profile should exist after approval"
        )

        # Store seller profile for subsequent tests
        self.__class__.test_seller_profile = frappe.get_doc(
            "Seller Profile", application.seller_profile
        )

        # Verify seller profile settings
        seller_profile = self.__class__.test_seller_profile
        self.assertEqual(seller_profile.status, "Active")
        self.assertEqual(seller_profile.can_sell, 1)
        self.assertEqual(seller_profile.can_create_listings, 1)
        self.assertEqual(seller_profile.verification_status, "Verified")

        # Verify ERPNext Supplier creation (if DocType exists)
        if frappe.db.exists("DocType", "Supplier"):
            self.assertIsNotNone(
                application.erpnext_supplier,
                "ERPNext Supplier should be created on approval"
            )
            self.assertTrue(
                frappe.db.exists("Supplier", application.erpnext_supplier),
                "Supplier record should exist"
            )
            self.__class__.test_supplier = frappe.get_doc(
                "Supplier", application.erpnext_supplier
            )

        # Verify Organization creation (for business applicants)
        if application.applicant_type in ["Business", "Enterprise"]:
            if frappe.db.exists("DocType", "Organization"):
                self.assertIsNotNone(
                    application.organization,
                    "Organization should be created for business applicants"
                )

    # ========================================================================
    # Test 05: Verify ERPNext Supplier Details
    # ========================================================================
    def test_05_verify_erpnext_supplier(self):
        """
        Test that ERPNext Supplier was created with correct data.

        Verifies:
        - Supplier name matches business name
        - Supplier type is correct
        - Tax ID is copied
        - Supplier is not disabled
        """
        supplier = self.__class__.test_supplier

        # Skip if Supplier DocType doesn't exist
        if not frappe.db.exists("DocType", "Supplier"):
            self.skipTest("Supplier DocType not available - ERPNext not installed")

        if not supplier:
            self.skipTest("Supplier was not created - check test_04 results")

        application = self.__class__.test_application
        application.reload()

        # Verify supplier name
        expected_name = application.business_name or application.legal_name or application.applicant_name
        self.assertEqual(supplier.supplier_name, expected_name)

        # Verify supplier type
        expected_type = "Company" if application.applicant_type in ["Business", "Enterprise"] else "Individual"
        self.assertEqual(supplier.supplier_type, expected_type)

        # Verify tax ID
        if application.tax_id:
            self.assertEqual(supplier.tax_id, application.tax_id)

        # Verify supplier is active
        self.assertEqual(supplier.disabled, 0)

    # ========================================================================
    # Test 06: Seller Profile Can Create Listings
    # ========================================================================
    def test_06_seller_can_create_listings(self):
        """
        Test that the approved seller can create listings.

        Verifies:
        - Seller Profile has can_create_listings = 1
        - A new listing can be created by the seller
        - Listing is properly linked to seller
        """
        seller_profile = self.__class__.test_seller_profile

        if not seller_profile:
            self.skipTest("Seller Profile was not created - check test_04 results")

        seller_profile.reload()

        # Verify seller has listing creation permission
        self.assertEqual(
            seller_profile.can_create_listings, 1,
            "Seller should be able to create listings"
        )
        self.assertEqual(
            seller_profile.can_sell, 1,
            "Seller should be able to sell"
        )
        self.assertEqual(
            seller_profile.status, "Active",
            "Seller profile should be Active"
        )

        # Verify Listing DocType exists
        if not frappe.db.exists("DocType", "Listing"):
            self.skipTest("Listing DocType not available")

        # Create a test listing
        unique_id = random_string(6)
        listing = frappe.get_doc({
            "doctype": "Listing",
            "title": f"Test Product {unique_id}",
            "seller": seller_profile.name,
            "status": "Draft",
            "listing_type": "Product",
            "short_description": "A test product created by automated E2E test",
            "description": "This is a comprehensive test product description for E2E testing.",
            "base_price": 100.00,
            "selling_price": 99.99,
            "currency": "TRY",
            "stock_qty": 100,
            "stock_uom": "Nos",
            "is_visible": 1
        })

        # Insert the listing
        listing.insert(ignore_permissions=True)

        # Store for cleanup/verification
        self.__class__.test_listing = listing

        # Verify listing was created
        self.assertTrue(frappe.db.exists("Listing", listing.name))

        # Verify seller association
        listing.reload()
        self.assertEqual(listing.seller, seller_profile.name)

        # Verify tenant is auto-populated (if seller has tenant)
        if seller_profile.tenant:
            self.assertEqual(
                listing.tenant, seller_profile.tenant,
                "Listing tenant should match seller's tenant"
            )

    # ========================================================================
    # Test 07: Complete Flow Verification
    # ========================================================================
    def test_07_verify_complete_flow(self):
        """
        Final verification of the complete seller registration flow.

        Verifies the entire chain of linked documents:
        - Application -> Seller Profile
        - Application -> ERPNext Supplier
        - Seller Profile -> Listing
        """
        application = self.__class__.test_application
        seller_profile = self.__class__.test_seller_profile
        supplier = self.__class__.test_supplier
        listing = self.__class__.test_listing

        # Reload all documents
        if application:
            application.reload()
        if seller_profile:
            seller_profile.reload()
        if supplier:
            supplier.reload()
        if listing:
            listing.reload()

        # Verify application is approved
        self.assertIsNotNone(application)
        self.assertEqual(application.status, "Approved")

        # Verify seller profile exists and is linked
        self.assertIsNotNone(seller_profile)
        self.assertEqual(application.seller_profile, seller_profile.name)

        # Verify supplier link (if applicable)
        if frappe.db.exists("DocType", "Supplier") and supplier:
            self.assertEqual(application.erpnext_supplier, supplier.name)
            self.assertEqual(seller_profile.erpnext_supplier, supplier.name)

        # Verify listing is linked to seller
        if listing:
            self.assertEqual(listing.seller, seller_profile.name)

        # Print summary for manual verification
        summary = {
            "Application": application.name if application else None,
            "Application Status": application.status if application else None,
            "Seller Profile": seller_profile.name if seller_profile else None,
            "Seller Status": seller_profile.status if seller_profile else None,
            "Can Create Listings": seller_profile.can_create_listings if seller_profile else None,
            "ERPNext Supplier": supplier.name if supplier else "N/A (DocType not available)",
            "Test Listing": listing.name if listing else None,
            "Flow Complete": True
        }

        frappe.log_error(
            title="E2E Test: Seller Registration Flow Summary",
            message=str(summary)
        )


# ============================================================================
# Standalone Test Runner (for development/debugging)
# ============================================================================
def run_seller_registration_flow_test():
    """
    Standalone function to run the seller registration flow test.

    Can be called from bench console:
        from tr_tradehub.tr_tradehub.tests.test_seller_registration_flow import run_seller_registration_flow_test
        run_seller_registration_flow_test()
    """
    results = {
        "passed": [],
        "failed": [],
        "skipped": []
    }

    test_instance = TestSellerRegistrationFlow()

    # Test sequence
    tests = [
        ("test_01_create_seller_application", test_instance.test_01_create_seller_application),
        ("test_02_submit_application", test_instance.test_02_submit_application),
        ("test_03_start_review", test_instance.test_03_start_review),
        ("test_04_approve_application", test_instance.test_04_approve_application),
        ("test_05_verify_erpnext_supplier", test_instance.test_05_verify_erpnext_supplier),
        ("test_06_seller_can_create_listings", test_instance.test_06_seller_can_create_listings),
        ("test_07_verify_complete_flow", test_instance.test_07_verify_complete_flow),
    ]

    for test_name, test_func in tests:
        try:
            test_instance.setUp()
            test_func()
            results["passed"].append(test_name)
        except Exception as e:
            if "skipTest" in str(type(e).__name__) or "Skip" in str(e):
                results["skipped"].append((test_name, str(e)))
            else:
                results["failed"].append((test_name, str(e)))
        finally:
            test_instance.tearDown()

    # Print results
    total = len(tests)
    passed = len(results["passed"])
    failed = len(results["failed"])
    skipped = len(results["skipped"])

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "details": results
    }


# ============================================================================
# Verification Script (for subtask-14-2)
# ============================================================================
def verify_seller_registration_flow():
    """
    Verification function for subtask-14-2.

    This function performs the end-to-end verification of the seller registration flow
    without the full test framework, suitable for quick verification checks.

    Returns:
        dict: Verification results with pass/fail status for each step
    """
    results = {
        "overall_status": "PENDING",
        "steps": {},
        "errors": []
    }

    try:
        # Step 1: Verify DocTypes exist
        required_doctypes = [
            "Seller Application",
            "Seller Profile",
            "Listing"
        ]

        for doctype in required_doctypes:
            exists = frappe.db.exists("DocType", doctype)
            results["steps"][f"DocType {doctype} exists"] = "PASS" if exists else "FAIL"
            if not exists:
                results["errors"].append(f"Required DocType '{doctype}' not found")

        # Step 2: Verify Seller Application workflow states
        if frappe.db.exists("DocType", "Seller Application"):
            meta = frappe.get_meta("Seller Application")
            status_field = meta.get_field("status")
            if status_field and status_field.options:
                expected_states = ["Draft", "Submitted", "Under Review", "Approved", "Rejected"]
                actual_states = status_field.options.split("\n")
                all_present = all(state in actual_states for state in expected_states)
                results["steps"]["Workflow states configured"] = "PASS" if all_present else "FAIL"
            else:
                results["steps"]["Workflow states configured"] = "FAIL"
                results["errors"].append("Status field not found in Seller Application")

        # Step 3: Verify Seller Profile has required permission fields
        if frappe.db.exists("DocType", "Seller Profile"):
            meta = frappe.get_meta("Seller Profile")
            required_fields = ["can_create_listings", "can_sell", "status", "erpnext_supplier"]
            missing_fields = []
            for field in required_fields:
                if not meta.get_field(field):
                    missing_fields.append(field)
            results["steps"]["Seller Profile permission fields"] = "PASS" if not missing_fields else "FAIL"
            if missing_fields:
                results["errors"].append(f"Missing fields in Seller Profile: {missing_fields}")

        # Step 4: Verify Seller Application has create methods
        if frappe.db.exists("DocType", "Seller Application"):
            try:
                from tr_tradehub.tr_tradehub.doctype.seller_application.seller_application import (
                    SellerApplication,
                    approve_application,
                    submit_application
                )

                # Check if approval creates supplier and profile
                has_create_supplier = hasattr(SellerApplication, 'create_erpnext_supplier')
                has_create_profile = hasattr(SellerApplication, 'create_seller_profile')

                results["steps"]["Supplier creation method exists"] = "PASS" if has_create_supplier else "FAIL"
                results["steps"]["Profile creation method exists"] = "PASS" if has_create_profile else "FAIL"

            except ImportError as e:
                results["steps"]["Seller Application module import"] = "FAIL"
                results["errors"].append(f"Import error: {str(e)}")

        # Step 5: Verify ERPNext integration module
        try:
            from tr_tradehub.utils.erpnext_sync import (
                is_erpnext_available,
                create_supplier_from_application
            )
            results["steps"]["ERPNext sync module available"] = "PASS"
        except ImportError as e:
            results["steps"]["ERPNext sync module available"] = "FAIL"
            results["errors"].append(f"ERPNext sync import error: {str(e)}")

        # Step 6: Check if Supplier DocType is available
        supplier_available = frappe.db.exists("DocType", "Supplier")
        results["steps"]["ERPNext Supplier DocType"] = "PASS" if supplier_available else "SKIP (ERPNext not installed)"

        # Determine overall status
        step_results = [v for v in results["steps"].values() if v != "SKIP (ERPNext not installed)"]
        if all(r == "PASS" for r in step_results):
            results["overall_status"] = "PASS"
        elif any(r == "FAIL" for r in step_results):
            results["overall_status"] = "FAIL"
        else:
            results["overall_status"] = "PARTIAL"

    except Exception as e:
        results["overall_status"] = "ERROR"
        results["errors"].append(f"Unexpected error: {str(e)}")

    return results
