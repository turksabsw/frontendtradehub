
import sys
import traceback

print("Testing imports...")

try:
    print("\nAttribute trying: tr_tradehub.utils.erpnext_sync")
    from tr_tradehub.utils import erpnext_sync
    print("SUCCESS: Imported tr_tradehub.utils.erpnext_sync")
except Exception:
    traceback.print_exc()

try:
    print("\nAttribute trying: tr_tradehub.tr_tradehub.doctype.listing.listing")
    from tr_tradehub.tr_tradehub.doctype.listing import listing
    print("SUCCESS: Imported tr_tradehub.tr_tradehub.doctype.listing.listing")
except Exception:
    traceback.print_exc()

print("\nDone.")
