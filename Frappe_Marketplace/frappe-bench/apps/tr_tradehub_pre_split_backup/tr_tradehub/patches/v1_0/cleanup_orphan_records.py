# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Patch to identify and clean up orphan records in TR TradeHub.

This patch scans for:
1. Child table records without valid parents
2. Records with broken Link field references
3. Stale data from deleted parent records

Can be run in dry_run mode to report issues without modifying data.
"""

import frappe
from frappe import _
from typing import Dict, List, Tuple


def execute(dry_run: bool = True):
    """
    Execute orphan record cleanup.

    Args:
        dry_run: If True, only report issues without deleting records
    """
    print(f"\n{'='*60}")
    print("TR TradeHub Orphan Record Cleanup")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will delete records)'}")
    print(f"{'='*60}\n")

    total_orphans = 0
    total_fixed = 0

    # Check child table orphans
    child_orphans, child_fixed = check_child_table_orphans(dry_run)
    total_orphans += child_orphans
    total_fixed += child_fixed

    # Check Link field orphans
    link_orphans, link_fixed = check_link_field_orphans(dry_run)
    total_orphans += link_orphans
    total_fixed += link_fixed

    # Check tenant consistency
    tenant_issues, tenant_fixed = check_tenant_consistency(dry_run)
    total_orphans += tenant_issues
    total_fixed += tenant_fixed

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total issues found: {total_orphans}")
    print(f"Total issues fixed: {total_fixed}")

    if dry_run and total_orphans > 0:
        print("\nTo fix these issues, run:")
        print("  bench --site [site-name] execute 'tr_tradehub.patches.v1_0.cleanup_orphan_records.execute' --kwargs '{\"dry_run\": false}'")

    frappe.db.commit()

    return {
        "total_orphans": total_orphans,
        "total_fixed": total_fixed,
        "dry_run": dry_run
    }


def check_child_table_orphans(dry_run: bool) -> Tuple[int, int]:
    """
    Check for child table records without valid parent documents.

    Returns:
        tuple: (orphan_count, fixed_count)
    """
    print("Checking child table orphans...")

    orphan_count = 0
    fixed_count = 0

    # Common child tables to check
    child_tables = [
        # (child_doctype, parent_doctype, parent_field)
        ("Marketplace Order Item", "Marketplace Order", "parent"),
        ("Sub Order Item", "Sub Order", "parent"),
        ("Cart Line", "Cart", "parent"),
        ("Address Item", "Seller Profile", "parent"),
        ("Seller Bank Account", "Seller Profile", "parent"),
        ("Seller Badge", "Seller Profile", "parent"),
        ("Listing Image", "Listing", "parent"),
        ("Listing Attribute Value", "Listing", "parent"),
        ("Listing Bulk Pricing Tier", "Listing", "parent"),
        ("Tax Rate Category", "Tax Rate", "parent"),
        ("Commission Plan Rate", "Commission Plan", "parent"),
        ("Shipping Rule Zone", "Shipping Rule", "parent"),
        ("Buyer Interest Category", "Buyer Profile", "parent"),
        ("Attribute Value", "Attribute", "parent"),
        ("Attribute Set Item", "Attribute Set", "parent"),
        ("RFQ Item", "RFQ", "parent"),
        ("Quotation Item", "Quotation", "parent"),
    ]

    for child_dt, parent_dt, parent_field in child_tables:
        if not frappe.db.exists("DocType", child_dt):
            continue
        if not frappe.db.exists("DocType", parent_dt):
            continue

        # Find orphans
        try:
            orphans = frappe.db.sql(f"""
                SELECT c.name, c.{parent_field}
                FROM `tab{child_dt}` c
                LEFT JOIN `tab{parent_dt}` p ON c.{parent_field} = p.name
                WHERE p.name IS NULL AND c.{parent_field} IS NOT NULL
                LIMIT 100
            """, as_dict=True)

            if orphans:
                print(f"  Found {len(orphans)} orphan {child_dt} records")
                orphan_count += len(orphans)

                if not dry_run:
                    for orphan in orphans:
                        frappe.delete_doc(child_dt, orphan.name, force=True)
                        fixed_count += 1
                    print(f"    Deleted {len(orphans)} orphan records")

        except Exception as e:
            print(f"  Error checking {child_dt}: {str(e)}")

    return orphan_count, fixed_count


def check_link_field_orphans(dry_run: bool) -> Tuple[int, int]:
    """
    Check for records with broken Link field references.

    Returns:
        tuple: (orphan_count, fixed_count)
    """
    print("\nChecking Link field orphans...")

    orphan_count = 0
    fixed_count = 0

    # Critical Link fields to check
    link_checks = [
        # (doctype, field_name, linked_doctype)
        ("Listing", "seller", "Seller Profile"),
        ("Listing", "category", "Category"),
        ("Marketplace Order", "buyer", "Buyer Profile"),
        ("Sub Order", "seller", "Seller Profile"),
        ("Sub Order", "marketplace_order", "Marketplace Order"),
        ("Coupon", "seller", "Seller Profile"),
        ("Coupon", "campaign", "Campaign"),
        ("Campaign", "seller", "Seller Profile"),
        ("Shipment", "carrier", "Carrier"),
        ("Review", "listing", "Listing"),
        ("Review", "buyer", "Buyer Profile"),
        ("Cart", "buyer", "Buyer Profile"),
        ("Seller Balance", "seller", "Seller Profile"),
        ("Seller KPI", "seller_profile", "Seller Profile"),
        ("Seller Score", "seller", "Seller Profile"),
    ]

    for doctype, field, linked_dt in link_checks:
        if not frappe.db.exists("DocType", doctype):
            continue
        if not frappe.db.exists("DocType", linked_dt):
            continue

        try:
            # Find broken links
            broken = frappe.db.sql(f"""
                SELECT d.name, d.{field}
                FROM `tab{doctype}` d
                LEFT JOIN `tab{linked_dt}` l ON d.{field} = l.name
                WHERE l.name IS NULL AND d.{field} IS NOT NULL AND d.{field} != ''
                LIMIT 50
            """, as_dict=True)

            if broken:
                print(f"  Found {len(broken)} {doctype} records with broken {field} links")
                orphan_count += len(broken)

                if not dry_run:
                    # Clear the broken link (don't delete the record)
                    for record in broken:
                        frappe.db.set_value(doctype, record.name, field, None, update_modified=False)
                        fixed_count += 1
                    print(f"    Cleared {len(broken)} broken links")

        except Exception as e:
            print(f"  Error checking {doctype}.{field}: {str(e)}")

    return orphan_count, fixed_count


def check_tenant_consistency(dry_run: bool) -> Tuple[int, int]:
    """
    Check for tenant consistency issues.

    Returns:
        tuple: (issue_count, fixed_count)
    """
    print("\nChecking tenant consistency...")

    issue_count = 0
    fixed_count = 0

    # DocTypes that should have tenant field matching their seller's tenant
    tenant_checks = [
        # (doctype, tenant_field, seller_field)
        ("Listing", "tenant", "seller"),
        ("Coupon", "tenant", "seller"),
        ("Marketplace Order", "tenant", None),  # Orders may have their own tenant
    ]

    for doctype, tenant_field, seller_field in tenant_checks:
        if not frappe.db.exists("DocType", doctype):
            continue

        if seller_field:
            try:
                # Find records where tenant doesn't match seller's tenant
                mismatched = frappe.db.sql(f"""
                    SELECT d.name, d.{tenant_field}, d.{seller_field}, s.tenant as seller_tenant
                    FROM `tab{doctype}` d
                    INNER JOIN `tabSeller Profile` s ON d.{seller_field} = s.name
                    WHERE d.{tenant_field} != s.tenant
                    AND d.{seller_field} IS NOT NULL
                    LIMIT 50
                """, as_dict=True)

                if mismatched:
                    print(f"  Found {len(mismatched)} {doctype} records with mismatched tenant")
                    issue_count += len(mismatched)

                    if not dry_run:
                        for record in mismatched:
                            frappe.db.set_value(
                                doctype, record.name,
                                tenant_field, record.seller_tenant,
                                update_modified=False
                            )
                            fixed_count += 1
                        print(f"    Fixed {len(mismatched)} tenant mismatches")

            except Exception as e:
                print(f"  Error checking {doctype} tenant: {str(e)}")

    return issue_count, fixed_count


@frappe.whitelist()
def run_cleanup(dry_run: bool = True) -> Dict:
    """
    API endpoint to run orphan cleanup.

    Args:
        dry_run: If True, only report issues

    Returns:
        dict: Cleanup results
    """
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can run cleanup"))

    return execute(dry_run=dry_run)


@frappe.whitelist()
def get_orphan_report() -> Dict:
    """
    Get a report of orphan records without fixing them.

    Returns:
        dict: Report of orphan issues
    """
    return execute(dry_run=True)
