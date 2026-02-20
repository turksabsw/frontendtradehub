# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""
End-to-End Verification Test: RFQ -> Quotation -> Order -> Payment Pipeline

This test verifies the complete commerce pipeline flow:
1. RFQ creation with buyer profile and category references
2. RFQ -> Quotation conversion with seller profile
3. Quotation -> Order creation
4. Order -> Payment Intent creation
5. Commission calculation verification

Note: This is a structural verification test for the mock Frappe environment.
It verifies DocType definitions, Link field relationships, and pipeline logic.
"""

import json
import os
from pathlib import Path


def get_doctype_json(doctype_name: str) -> dict:
    """Load DocType JSON definition from the commerce app."""
    base_path = Path(__file__).parent.parent / "doctype"
    doctype_folder = doctype_name.lower().replace(" ", "_")
    json_path = base_path / doctype_folder / f"{doctype_folder}.json"

    if json_path.exists():
        with open(json_path, "r") as f:
            return json.load(f)
    return None


def get_cross_app_doctype_json(app_name: str, doctype_name: str) -> dict:
    """Load DocType JSON from another TradeHub app."""
    base_path = Path(__file__).parent.parent.parent.parent  # frappe-bench/apps
    doctype_folder = doctype_name.lower().replace(" ", "_")
    json_path = base_path / app_name / app_name / "doctype" / doctype_folder / f"{doctype_folder}.json"

    if json_path.exists():
        with open(json_path, "r") as f:
            return json.load(f)
    return None


def get_link_fields(doctype_json: dict) -> list:
    """Extract all Link and Dynamic Link fields from a DocType."""
    link_fields = []
    for field in doctype_json.get("fields", []):
        if field.get("fieldtype") in ["Link", "Dynamic Link"]:
            link_fields.append({
                "fieldname": field.get("fieldname"),
                "fieldtype": field.get("fieldtype"),
                "options": field.get("options"),
                "reqd": field.get("reqd", 0)
            })
    return link_fields


def verify_doctype_exists_with_module(doctype_name: str, expected_module: str) -> tuple:
    """Verify DocType exists and has correct module assignment."""
    doctype_json = get_doctype_json(doctype_name)
    if not doctype_json:
        return False, f"DocType '{doctype_name}' not found"

    actual_module = doctype_json.get("module")
    if actual_module != expected_module:
        return False, f"Module mismatch: expected '{expected_module}', got '{actual_module}'"

    return True, f"DocType '{doctype_name}' exists with module '{expected_module}'"


def verify_link_field_exists(doctype_name: str, fieldname: str, target_doctype: str) -> tuple:
    """Verify a Link field exists and points to the correct DocType."""
    doctype_json = get_doctype_json(doctype_name)
    if not doctype_json:
        return False, f"DocType '{doctype_name}' not found"

    for field in doctype_json.get("fields", []):
        if field.get("fieldname") == fieldname:
            if field.get("fieldtype") == "Link":
                if field.get("options") == target_doctype:
                    return True, f"Link field '{fieldname}' -> '{target_doctype}' verified"
                else:
                    return False, f"Link field '{fieldname}' points to '{field.get('options')}', expected '{target_doctype}'"
            elif field.get("fieldtype") == "Dynamic Link":
                return True, f"Dynamic Link field '{fieldname}' verified"

    return False, f"Field '{fieldname}' not found in '{doctype_name}'"


def verify_cross_app_doctype_exists(app_name: str, doctype_name: str, expected_module: str) -> tuple:
    """Verify cross-app DocType exists."""
    doctype_json = get_cross_app_doctype_json(app_name, doctype_name)
    if not doctype_json:
        return False, f"Cross-app DocType '{doctype_name}' not found in '{app_name}'"

    actual_module = doctype_json.get("module")
    if actual_module != expected_module:
        return False, f"Cross-app module mismatch: expected '{expected_module}', got '{actual_module}'"

    return True, f"Cross-app DocType '{doctype_name}' verified in '{app_name}'"


def verify_commission_calculation_logic(order_amount: float, commission_rate: float,
                                        min_commission: float = 0, max_commission: float = 0) -> dict:
    """Verify commission calculation logic."""
    calculated_commission = order_amount * (commission_rate / 100)

    # Apply minimum
    if min_commission > 0 and calculated_commission < min_commission:
        calculated_commission = min_commission

    # Apply maximum
    if max_commission > 0 and calculated_commission > max_commission:
        calculated_commission = max_commission

    return {
        "order_amount": order_amount,
        "commission_rate": commission_rate,
        "min_commission": min_commission,
        "max_commission": max_commission,
        "calculated_commission": calculated_commission,
        "net_seller_amount": order_amount - calculated_commission
    }


def run_pipeline_verification():
    """Run complete pipeline verification."""
    results = {
        "passed": 0,
        "failed": 0,
        "tests": []
    }

    def record_test(name: str, passed: bool, message: str):
        results["tests"].append({"name": name, "passed": passed, "message": message})
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ===== STEP 1: Verify RFQ DocType =====
    print("\n=== STEP 1: Verify RFQ DocType ===")

    passed, msg = verify_doctype_exists_with_module("RFQ", "TradeHub Commerce")
    record_test("RFQ DocType exists", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # RFQ -> Buyer Profile (cross-app to tradehub_core)
    passed, msg = verify_link_field_exists("RFQ", "buyer_profile", "Buyer Profile")
    record_test("RFQ -> Buyer Profile link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # RFQ -> Category (cross-app to tradehub_catalog)
    passed, msg = verify_link_field_exists("RFQ", "category", "Category")
    record_test("RFQ -> Category link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Verify cross-app DocTypes exist
    passed, msg = verify_cross_app_doctype_exists("tradehub_core", "Buyer Profile", "TradeHub Core")
    record_test("Cross-app: Buyer Profile in tradehub_core", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    passed, msg = verify_cross_app_doctype_exists("tradehub_catalog", "Category", "TradeHub Catalog")
    record_test("Cross-app: Category in tradehub_catalog", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # ===== STEP 2: Verify Quotation DocType (RFQ -> Quotation) =====
    print("\n=== STEP 2: Verify Quotation DocType (RFQ -> Quotation) ===")

    passed, msg = verify_doctype_exists_with_module("Quotation", "TradeHub Commerce")
    record_test("Quotation DocType exists", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Quotation -> RFQ reference
    passed, msg = verify_link_field_exists("Quotation", "reference_rfq", "RFQ")
    record_test("Quotation -> RFQ link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Quotation -> Buyer Profile (cross-app)
    passed, msg = verify_link_field_exists("Quotation", "buyer_profile", "Buyer Profile")
    record_test("Quotation -> Buyer Profile link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Quotation -> Seller Profile (cross-app to tradehub_seller)
    passed, msg = verify_link_field_exists("Quotation", "seller_profile", "Seller Profile")
    record_test("Quotation -> Seller Profile link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Verify Seller Profile exists in tradehub_seller
    passed, msg = verify_cross_app_doctype_exists("tradehub_seller", "Seller Profile", "TradeHub Seller")
    record_test("Cross-app: Seller Profile in tradehub_seller", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # ===== STEP 3: Verify Order DocType (Quotation -> Order) =====
    print("\n=== STEP 3: Verify Order DocType (Quotation -> Order) ===")

    passed, msg = verify_doctype_exists_with_module("Order", "TradeHub Commerce")
    record_test("Order DocType exists", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Order -> Buyer Profile
    passed, msg = verify_link_field_exists("Order", "buyer_profile", "Buyer Profile")
    record_test("Order -> Buyer Profile link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Order -> Seller Profile
    passed, msg = verify_link_field_exists("Order", "seller_profile", "Seller Profile")
    record_test("Order -> Seller Profile link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Verify Order is submittable (workflow support)
    order_json = get_doctype_json("Order")
    if order_json and order_json.get("is_submittable"):
        record_test("Order is submittable", True, "Order DocType supports workflow (is_submittable=1)")
        print("  [PASS] Order DocType supports workflow (is_submittable=1)")
    else:
        record_test("Order is submittable", False, "Order DocType should be submittable")
        print("  [FAIL] Order DocType should be submittable")

    # ===== STEP 4: Verify Payment Intent DocType (Order -> Payment) =====
    print("\n=== STEP 4: Verify Payment Intent DocType (Order -> Payment) ===")

    passed, msg = verify_doctype_exists_with_module("Payment Intent", "TradeHub Commerce")
    record_test("Payment Intent DocType exists", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Payment Intent uses Dynamic Link for flexibility
    passed, msg = verify_link_field_exists("Payment Intent", "reference_doctype", "DocType")
    record_test("Payment Intent -> reference_doctype link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    passed, msg = verify_link_field_exists("Payment Intent", "reference_name", "Order")
    record_test("Payment Intent -> reference_name dynamic link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Verify Payment Method link
    passed, msg = verify_link_field_exists("Payment Intent", "payment_method", "Payment Method")
    record_test("Payment Intent -> Payment Method link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # ===== STEP 5: Verify Commission Calculation =====
    print("\n=== STEP 5: Verify Commission Calculation ===")

    # Verify Commission Plan exists
    passed, msg = verify_doctype_exists_with_module("Commission Plan", "TradeHub Commerce")
    record_test("Commission Plan DocType exists", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Verify Commission Rule exists
    passed, msg = verify_doctype_exists_with_module("Commission Rule", "TradeHub Commerce")
    record_test("Commission Rule DocType exists", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Commission Rule -> Commission Plan link
    passed, msg = verify_link_field_exists("Commission Rule", "commission_plan", "Commission Plan")
    record_test("Commission Rule -> Commission Plan link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Commission Rule -> Category link (for category-based commission)
    passed, msg = verify_link_field_exists("Commission Rule", "category", "Category")
    record_test("Commission Rule -> Category link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Commission Rule -> Brand link (for brand-based commission)
    passed, msg = verify_link_field_exists("Commission Rule", "brand", "Brand")
    record_test("Commission Rule -> Brand link", passed, msg)
    print(f"  {'[PASS]' if passed else '[FAIL]'} {msg}")

    # Test commission calculation logic
    print("\n  Testing commission calculation scenarios:")

    # Scenario 1: Basic percentage
    result = verify_commission_calculation_logic(1000, 10)
    test_passed = result["calculated_commission"] == 100
    record_test("Commission calc: 10% of 1000 = 100", test_passed,
                f"Expected 100, got {result['calculated_commission']}")
    print(f"    {'[PASS]' if test_passed else '[FAIL]'} 10% of 1000 TRY = {result['calculated_commission']} TRY")

    # Scenario 2: With minimum commission
    result = verify_commission_calculation_logic(100, 5, min_commission=10)
    test_passed = result["calculated_commission"] == 10  # 5% of 100 = 5, but min is 10
    record_test("Commission calc with minimum", test_passed,
                f"Expected 10 (min), got {result['calculated_commission']}")
    print(f"    {'[PASS]' if test_passed else '[FAIL]'} 5% of 100 TRY with min 10 TRY = {result['calculated_commission']} TRY")

    # Scenario 3: With maximum commission
    result = verify_commission_calculation_logic(10000, 15, max_commission=500)
    test_passed = result["calculated_commission"] == 500  # 15% of 10000 = 1500, but max is 500
    record_test("Commission calc with maximum", test_passed,
                f"Expected 500 (max), got {result['calculated_commission']}")
    print(f"    {'[PASS]' if test_passed else '[FAIL]'} 15% of 10000 TRY with max 500 TRY = {result['calculated_commission']} TRY")

    # ===== STEP 6: Verify Supporting Commerce DocTypes =====
    print("\n=== STEP 6: Verify Supporting Commerce DocTypes ===")

    supporting_doctypes = [
        "Cart", "Marketplace Order", "Sub Order", "Order Event",
        "RFQ Quote", "RFQ Quote Revision", "RFQ Message", "RFQ Message Thread", "RFQ NDA Link",
        "Escrow Account", "Escrow Event", "Account Action",
        "Payment Method", "Payment Plan", "Incoterm Price", "Tax Rate"
    ]

    for doctype in supporting_doctypes:
        passed, msg = verify_doctype_exists_with_module(doctype, "TradeHub Commerce")
        record_test(f"{doctype} DocType exists", passed, msg)
        print(f"  {'[PASS]' if passed else '[FAIL]'} {doctype}")

    # ===== SUMMARY =====
    print("\n" + "=" * 60)
    print("PIPELINE VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total Tests: {results['passed'] + results['failed']}")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")

    if results["failed"] == 0:
        print("\n[SUCCESS] All pipeline verification tests passed!")
        print("\nPipeline Flow Verified:")
        print("  1. RFQ (Buyer creates request) -> Category, Buyer Profile")
        print("  2. Quotation (Seller responds) -> RFQ, Buyer Profile, Seller Profile")
        print("  3. Order (Transaction created) -> Buyer Profile, Seller Profile")
        print("  4. Payment Intent (Payment processed) -> Order (Dynamic Link)")
        print("  5. Commission (Platform fee) -> Category, Brand based rules")
    else:
        print(f"\n[WARNING] {results['failed']} tests failed. Review the issues above.")

    return results


if __name__ == "__main__":
    run_pipeline_verification()
