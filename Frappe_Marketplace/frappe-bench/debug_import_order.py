
import sys
import traceback

print("Testing Marketplace Order imports...")

try:
    print("\nAttribute trying: tr_tradehub.utils.erpnext_sync.create_sales_order_from_marketplace_order")
    from tr_tradehub.utils.erpnext_sync import create_sales_order_from_marketplace_order
    print("SUCCESS: Imported create_sales_order_from_marketplace_order")
except Exception:
    traceback.print_exc()

print("\nDone.")
