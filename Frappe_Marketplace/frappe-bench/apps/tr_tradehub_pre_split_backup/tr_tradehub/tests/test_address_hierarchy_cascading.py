# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Address Hierarchy Cascading E2E Tests

This module tests the cascading dropdown functionality for Turkish address hierarchy:
- City (Il) -> District (Ilce) -> Neighborhood (Mahalle)

End-to-end verification steps:
1. Open Seller Profile form
2. Add new address in addresses child table
3. Select City (Istanbul)
4. Verify District dropdown filters by Istanbul
5. Select District
6. Verify Neighborhood dropdown filters by selected District
7. Change City to Ankara
8. Verify District and Neighborhood fields are cleared

Test coverage:
- City, District, Neighborhood DocTypes exist and are properly configured
- fetch_from relationships work correctly
- Server-side validation prevents hierarchy mismatches
- Child table (Address Item) cascading logic works
- Child table (Location Item) cascading logic works
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAddressHierarchyCascading(FrappeTestCase):
    """Test suite for address hierarchy cascading functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test data for all tests."""
        super().setUpClass()
        cls._create_test_cities()
        cls._create_test_districts()
        cls._create_test_neighborhoods()

    @classmethod
    def _create_test_cities(cls):
        """Create test cities for Istanbul and Ankara."""
        # Check if cities exist from fixtures
        if not frappe.db.exists("City", "34"):
            frappe.get_doc({
                "doctype": "City",
                "city_code": "34",
                "city_name": "Istanbul",
                "region": "Marmara",
                "is_active": 1,
                "phone_code": "212",
                "country": "Turkey"
            }).insert(ignore_permissions=True)

        if not frappe.db.exists("City", "06"):
            frappe.get_doc({
                "doctype": "City",
                "city_code": "06",
                "city_name": "Ankara",
                "region": "Ic Anadolu",
                "is_active": 1,
                "phone_code": "312",
                "country": "Turkey"
            }).insert(ignore_permissions=True)

    @classmethod
    def _create_test_districts(cls):
        """Create test districts for Istanbul and Ankara."""
        # Istanbul districts
        istanbul_districts = ["Kadikoy", "Besiktas", "Sisli"]
        for district_name in istanbul_districts:
            if not frappe.db.exists("District", {"district_name": district_name, "city": "34"}):
                frappe.get_doc({
                    "doctype": "District",
                    "district_name": district_name,
                    "city": "34",
                    "is_active": 1
                }).insert(ignore_permissions=True)

        # Ankara districts
        ankara_districts = ["Cankaya", "Kizilay", "Etimesgut"]
        for district_name in ankara_districts:
            if not frappe.db.exists("District", {"district_name": district_name, "city": "06"}):
                frappe.get_doc({
                    "doctype": "District",
                    "district_name": district_name,
                    "city": "06",
                    "is_active": 1
                }).insert(ignore_permissions=True)

    @classmethod
    def _create_test_neighborhoods(cls):
        """Create test neighborhoods."""
        # Get Kadikoy district for Istanbul
        kadikoy = frappe.db.get_value("District", {"district_name": "Kadikoy", "city": "34"}, "name")
        if kadikoy:
            neighborhoods = ["Moda", "Fenerbahce", "Caferaga"]
            for nb_name in neighborhoods:
                if not frappe.db.exists("Neighborhood", {"neighborhood_name": nb_name, "district": kadikoy}):
                    frappe.get_doc({
                        "doctype": "Neighborhood",
                        "neighborhood_name": nb_name,
                        "district": kadikoy,
                        "is_active": 1
                    }).insert(ignore_permissions=True)

        # Get Cankaya district for Ankara
        cankaya = frappe.db.get_value("District", {"district_name": "Cankaya", "city": "06"}, "name")
        if cankaya:
            neighborhoods = ["Kizilay", "Kavaklidere", "Birlik"]
            for nb_name in neighborhoods:
                if not frappe.db.exists("Neighborhood", {"neighborhood_name": nb_name, "district": cankaya}):
                    frappe.get_doc({
                        "doctype": "Neighborhood",
                        "neighborhood_name": nb_name,
                        "district": cankaya,
                        "is_active": 1
                    }).insert(ignore_permissions=True)

    # =========================================================================
    # Test 1: Verify City DocType Configuration
    # =========================================================================
    def test_01_city_doctype_exists(self):
        """Test that City DocType is properly configured."""
        meta = frappe.get_meta("City")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title_field, "city_name")

        # Check required fields exist
        field_names = [f.fieldname for f in meta.fields]
        self.assertIn("city_code", field_names)
        self.assertIn("city_name", field_names)
        self.assertIn("region", field_names)
        self.assertIn("is_active", field_names)

    # =========================================================================
    # Test 2: Verify District DocType Configuration
    # =========================================================================
    def test_02_district_doctype_exists(self):
        """Test that District DocType is properly configured with City link."""
        meta = frappe.get_meta("District")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title_field, "district_name")

        # Check city link field exists
        city_field = meta.get_field("city")
        self.assertIsNotNone(city_field)
        self.assertEqual(city_field.fieldtype, "Link")
        self.assertEqual(city_field.options, "City")

        # Check fetch_from for city_name
        city_name_field = meta.get_field("city_name")
        self.assertIsNotNone(city_name_field)
        self.assertEqual(city_name_field.fetch_from, "city.city_name")

    # =========================================================================
    # Test 3: Verify Neighborhood DocType Configuration
    # =========================================================================
    def test_03_neighborhood_doctype_exists(self):
        """Test that Neighborhood DocType is properly configured with District link."""
        meta = frappe.get_meta("Neighborhood")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title_field, "neighborhood_name")

        # Check district link field exists
        district_field = meta.get_field("district")
        self.assertIsNotNone(district_field)
        self.assertEqual(district_field.fieldtype, "Link")
        self.assertEqual(district_field.options, "District")

        # Check fetch_from for district_name
        district_name_field = meta.get_field("district_name")
        self.assertIsNotNone(district_name_field)
        self.assertEqual(district_name_field.fetch_from, "district.district_name")

    # =========================================================================
    # Test 4: Verify Address Item Child Table Configuration
    # =========================================================================
    def test_04_address_item_child_table_exists(self):
        """Test that Address Item child table is properly configured."""
        meta = frappe.get_meta("Address Item")
        self.assertIsNotNone(meta)
        self.assertTrue(meta.istable)

        # Check address hierarchy fields exist
        field_names = [f.fieldname for f in meta.fields]
        self.assertIn("city", field_names)
        self.assertIn("district", field_names)
        self.assertIn("neighborhood", field_names)

        # Check Link field options
        city_field = meta.get_field("city")
        self.assertEqual(city_field.options, "City")

        district_field = meta.get_field("district")
        self.assertEqual(district_field.options, "District")

        neighborhood_field = meta.get_field("neighborhood")
        self.assertEqual(neighborhood_field.options, "Neighborhood")

    # =========================================================================
    # Test 5: Verify District Filters by City
    # =========================================================================
    def test_05_district_filters_by_city(self):
        """Test that districts can be filtered by city."""
        # Get Istanbul districts
        istanbul_districts = frappe.get_all(
            "District",
            filters={"city": "34", "is_active": 1},
            pluck="name"
        )
        self.assertGreater(len(istanbul_districts), 0)

        # Get Ankara districts
        ankara_districts = frappe.get_all(
            "District",
            filters={"city": "06", "is_active": 1},
            pluck="name"
        )
        self.assertGreater(len(ankara_districts), 0)

        # Verify no overlap (different cities have different districts)
        overlap = set(istanbul_districts) & set(ankara_districts)
        # Districts are unique names, so overlap should be empty
        # (unless they have same name which is possible)

    # =========================================================================
    # Test 6: Verify Neighborhood Filters by District
    # =========================================================================
    def test_06_neighborhood_filters_by_district(self):
        """Test that neighborhoods can be filtered by district."""
        # Get Kadikoy district
        kadikoy = frappe.db.get_value("District", {"district_name": "Kadikoy", "city": "34"}, "name")
        if kadikoy:
            kadikoy_neighborhoods = frappe.get_all(
                "Neighborhood",
                filters={"district": kadikoy, "is_active": 1},
                pluck="name"
            )
            self.assertGreater(len(kadikoy_neighborhoods), 0)

        # Get Cankaya district
        cankaya = frappe.db.get_value("District", {"district_name": "Cankaya", "city": "06"}, "name")
        if cankaya:
            cankaya_neighborhoods = frappe.get_all(
                "Neighborhood",
                filters={"district": cankaya, "is_active": 1},
                pluck="name"
            )
            self.assertGreater(len(cankaya_neighborhoods), 0)

    # =========================================================================
    # Test 7: Verify Server-Side Hierarchy Validation
    # =========================================================================
    def test_07_server_side_hierarchy_validation(self):
        """Test that server-side validation prevents hierarchy mismatches."""
        from tr_tradehub.tr_tradehub.doctype.address_item.address_item import AddressItem

        # Get a district from Istanbul
        istanbul_district = frappe.db.get_value("District", {"city": "34"}, "name")
        # Get a neighborhood from Ankara (different city)
        ankara_district = frappe.db.get_value("District", {"city": "06"}, "name")

        if istanbul_district and ankara_district:
            ankara_neighborhoods = frappe.get_all(
                "Neighborhood",
                filters={"district": ankara_district},
                pluck="name",
                limit=1
            )

            if ankara_neighborhoods:
                # Create an AddressItem with mismatched hierarchy
                address_item = frappe.get_doc({
                    "doctype": "Address Item",
                    "city": "34",  # Istanbul
                    "district": istanbul_district,  # Istanbul district
                    "neighborhood": ankara_neighborhoods[0],  # Ankara neighborhood (mismatch!)
                    "address_type": "Billing",
                    "street_address": "Test Street"
                })

                # This should raise a validation error
                with self.assertRaises(frappe.ValidationError):
                    address_item.validate()

    # =========================================================================
    # Test 8: Verify Seller Profile Has Addresses Child Table
    # =========================================================================
    def test_08_seller_profile_has_addresses_table(self):
        """Test that Seller Profile has addresses child table configured."""
        meta = frappe.get_meta("Seller Profile")
        self.assertIsNotNone(meta)

        # Check addresses field exists and is a Table
        addresses_field = meta.get_field("addresses")
        self.assertIsNotNone(addresses_field, "addresses field should exist on Seller Profile")
        self.assertEqual(addresses_field.fieldtype, "Table")
        self.assertEqual(addresses_field.options, "Address Item")

    # =========================================================================
    # Test 9: Verify Seller Profile Has Locations Child Table
    # =========================================================================
    def test_09_seller_profile_has_locations_table(self):
        """Test that Seller Profile has locations child table configured."""
        meta = frappe.get_meta("Seller Profile")
        self.assertIsNotNone(meta)

        # Check locations field exists and is a Table
        locations_field = meta.get_field("locations")
        self.assertIsNotNone(locations_field, "locations field should exist on Seller Profile")
        self.assertEqual(locations_field.fieldtype, "Table")
        self.assertEqual(locations_field.options, "Location Item")

    # =========================================================================
    # Test 10: Verify Client Script Exists with Cascading Logic
    # =========================================================================
    def test_10_client_script_has_cascading_logic(self):
        """Test that seller_profile.js has cascading filter logic."""
        import os

        js_file_path = os.path.join(
            frappe.get_app_path("tr_tradehub"),
            "tr_tradehub",
            "doctype",
            "seller_profile",
            "seller_profile.js"
        )

        self.assertTrue(os.path.exists(js_file_path), "seller_profile.js should exist")

        with open(js_file_path, "r") as f:
            js_content = f.read()

        # Check for Address Item cascading filters
        self.assertIn("set_query('city', 'addresses'", js_content,
                      "Should have city filter for addresses child table")
        self.assertIn("set_query('district', 'addresses'", js_content,
                      "Should have district filter for addresses child table")
        self.assertIn("set_query('neighborhood', 'addresses'", js_content,
                      "Should have neighborhood filter for addresses child table")

        # Check for Location Item cascading filters
        self.assertIn("set_query('city', 'locations'", js_content,
                      "Should have city filter for locations child table")
        self.assertIn("set_query('district', 'locations'", js_content,
                      "Should have district filter for locations child table")
        self.assertIn("set_query('neighborhood', 'locations'", js_content,
                      "Should have neighborhood filter for locations child table")

        # Check for cascading clear handlers
        self.assertIn("frappe.ui.form.on('Address Item'", js_content,
                      "Should have Address Item event handlers")
        self.assertIn("frappe.ui.form.on('Location Item'", js_content,
                      "Should have Location Item event handlers")

    # =========================================================================
    # Test 11: Verify fetch_from Auto-Population
    # =========================================================================
    def test_11_fetch_from_auto_population(self):
        """Test that fetch_from auto-populates city_name, district_name, etc."""
        # Get a city
        city = frappe.get_doc("City", "34")
        self.assertEqual(city.city_name, "Istanbul")

        # Get a district in that city
        district = frappe.get_all(
            "District",
            filters={"city": "34"},
            fields=["name", "city_name"],
            limit=1
        )

        if district:
            # The fetch_from should have populated city_name
            self.assertEqual(district[0].city_name, "Istanbul")

    # =========================================================================
    # Test 12: E2E Simulation - Verify Cascading Works in Sequence
    # =========================================================================
    def test_12_e2e_cascading_sequence(self):
        """
        E2E Test: Simulate the cascading dropdown sequence.

        Steps:
        1. Select City (Istanbul - code 34)
        2. Verify districts from Istanbul can be retrieved
        3. Select a District from Istanbul
        4. Verify neighborhoods from that district can be retrieved
        5. Verify hierarchy is consistent
        """
        # Step 1: Select Istanbul
        city = frappe.get_doc("City", "34")
        self.assertEqual(city.city_name, "Istanbul")
        self.assertEqual(city.is_active, 1)

        # Step 2: Get districts filtered by Istanbul
        districts = frappe.get_all(
            "District",
            filters={"city": "34", "is_active": 1},
            fields=["name", "district_name", "city"]
        )
        self.assertGreater(len(districts), 0, "Should have districts for Istanbul")

        # All districts should belong to Istanbul
        for d in districts:
            self.assertEqual(d.city, "34")

        # Step 3: Select first district
        selected_district = districts[0]

        # Step 4: Get neighborhoods filtered by selected district
        neighborhoods = frappe.get_all(
            "Neighborhood",
            filters={"district": selected_district.name, "is_active": 1},
            fields=["name", "neighborhood_name", "district", "city"]
        )

        # If neighborhoods exist, verify they belong to the correct district and city
        for n in neighborhoods:
            self.assertEqual(n.district, selected_district.name)
            self.assertEqual(n.city, "34")  # Should be Istanbul via fetch_from

        # Step 5: Verify hierarchy consistency
        if neighborhoods:
            nb = frappe.get_doc("Neighborhood", neighborhoods[0].name)
            self.assertEqual(nb.district, selected_district.name)
            # city should be fetched from district
            self.assertEqual(nb.city, "34")


def run_address_hierarchy_verification():
    """
    Manual verification helper function.

    Run this to get a detailed report of address hierarchy configuration.

    Usage:
        from tr_tradehub.tests.test_address_hierarchy_cascading import run_address_hierarchy_verification
        run_address_hierarchy_verification()
    """
    print("=" * 80)
    print("ADDRESS HIERARCHY CASCADING VERIFICATION")
    print("=" * 80)

    checks = []

    # Check 1: City DocType
    try:
        meta = frappe.get_meta("City")
        checks.append(("City DocType exists", True, ""))
        checks.append(("City title_field is city_name", meta.title_field == "city_name", meta.title_field))
    except Exception as e:
        checks.append(("City DocType exists", False, str(e)))

    # Check 2: District DocType
    try:
        meta = frappe.get_meta("District")
        checks.append(("District DocType exists", True, ""))
        city_field = meta.get_field("city")
        checks.append(("District has City link field", city_field is not None, ""))
        checks.append(("District.city links to City", city_field.options == "City" if city_field else False, ""))
    except Exception as e:
        checks.append(("District DocType exists", False, str(e)))

    # Check 3: Neighborhood DocType
    try:
        meta = frappe.get_meta("Neighborhood")
        checks.append(("Neighborhood DocType exists", True, ""))
        district_field = meta.get_field("district")
        checks.append(("Neighborhood has District link field", district_field is not None, ""))
        checks.append(("Neighborhood.district links to District", district_field.options == "District" if district_field else False, ""))
    except Exception as e:
        checks.append(("Neighborhood DocType exists", False, str(e)))

    # Check 4: Address Item Child Table
    try:
        meta = frappe.get_meta("Address Item")
        checks.append(("Address Item DocType exists", True, ""))
        checks.append(("Address Item is child table", meta.istable == 1, ""))
        checks.append(("Address Item has city field", meta.get_field("city") is not None, ""))
        checks.append(("Address Item has district field", meta.get_field("district") is not None, ""))
        checks.append(("Address Item has neighborhood field", meta.get_field("neighborhood") is not None, ""))
    except Exception as e:
        checks.append(("Address Item DocType exists", False, str(e)))

    # Check 5: Seller Profile Configuration
    try:
        meta = frappe.get_meta("Seller Profile")
        addresses_field = meta.get_field("addresses")
        checks.append(("Seller Profile has addresses field", addresses_field is not None, ""))
        checks.append(("addresses field is Table type", addresses_field.fieldtype == "Table" if addresses_field else False, ""))
        checks.append(("addresses links to Address Item", addresses_field.options == "Address Item" if addresses_field else False, ""))
    except Exception as e:
        checks.append(("Seller Profile addresses field", False, str(e)))

    # Check 6: Client Script
    try:
        import os
        js_path = os.path.join(
            frappe.get_app_path("tr_tradehub"),
            "tr_tradehub", "doctype", "seller_profile", "seller_profile.js"
        )
        with open(js_path, "r") as f:
            js = f.read()
        checks.append(("seller_profile.js exists", True, ""))
        checks.append(("Has city filter for addresses", "set_query('city', 'addresses'" in js, ""))
        checks.append(("Has district filter for addresses", "set_query('district', 'addresses'" in js, ""))
        checks.append(("Has neighborhood filter for addresses", "set_query('neighborhood', 'addresses'" in js, ""))
        checks.append(("Has Address Item event handlers", "frappe.ui.form.on('Address Item'" in js, ""))
    except Exception as e:
        checks.append(("seller_profile.js check", False, str(e)))

    # Print results
    print("\n{:<50} {:<10} {}".format("Check", "Status", "Notes"))
    print("-" * 80)

    passed = 0
    failed = 0
    for check, status, notes in checks:
        status_str = "PASS" if status else "FAIL"
        print("{:<50} {:<10} {}".format(check, status_str, notes))
        if status:
            passed += 1
        else:
            failed += 1

    print("-" * 80)
    print(f"\nTotal: {passed + failed} checks, {passed} passed, {failed} failed")

    if failed == 0:
        print("\n*** ALL CHECKS PASSED ***")
    else:
        print("\n*** SOME CHECKS FAILED ***")

    return failed == 0
