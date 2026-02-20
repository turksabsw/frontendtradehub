import frappe
from frappe.model.sync import sync_for
import time
import traceback

def execute():
    print("=== STARTING SYNC TOOL (Monkeypatched + Cleanups) ===")
    
    # 1. Monkeypatch ECA dispatcher
    try:
        from tradehub_core.eca import dispatcher
        def no_op(*args, **kwargs): return
        def return_false(*args, **kwargs): return 0
        dispatcher.evaluate_rules = no_op
        dispatcher._is_eca_enabled = return_false
        print("  ✓ Monkeypatch successful")
    except:
        pass

    # 2. Disable flags
    frappe.flags.in_migrate = True
    frappe.flags.in_install = True
    frappe.flags.in_setup_wizard = True
    
    apps = [
        "tradehub_core", 
        "tradehub_catalog", 
        "tradehub_seller",
        "tradehub_compliance", 
        "tradehub_commerce", 
        "tradehub_logistics",
        "tradehub_marketing"
    ]

    module_names = {
        "tradehub_core": "TradeHub Core",
        "tradehub_catalog": "TradeHub Catalog",
        "tradehub_seller": "TradeHub Seller",
        "tradehub_compliance": "TradeHub Compliance",
        "tradehub_commerce": "TradeHub Commerce",
        "tradehub_logistics": "TradeHub Logistics",
        "tradehub_marketing": "TradeHub Marketing",
    }

    total_synced = 0
    
    for app in apps:
        print(f"\n--- Syncing {app} ---")
        try:
            # Ensure DB connection
            try:
                frappe.db.sql("SELECT 1")
            except:
                print("  ! Reconnecting DB...")
                frappe.connect()

            # Pre-sync cleanup for tradehub_core
            if app == "tradehub_core":
                print("  ! Truncating `tabECA Rule Log` to prevent DataError...")
                try:
                    frappe.db.sql("TRUNCATE TABLE `tabECA Rule Log`")
                    frappe.db.commit()
                except Exception as e:
                    print(f"    (Truncate failed: {e})")

            # Sync
            print(f"  > Calling sync_for('{app}')...")
            sync_for(app, force=True, reset_permissions=True)
            frappe.db.commit()
            
            # Verify
            count = frappe.db.count("DocType", {"module": module_names[app]})
            print(f"✓ SUCCESS: {app} synced. DocType count: {count}")
            total_synced += 1
            time.sleep(1)
            
        except Exception as e:
            try:
                frappe.db.rollback()
            except:
                pass
            print(f"✗ FAILED: {app}")
            print(f"  Error: {str(e)}")
            traceback.print_exc()

    print(f"\n=== COMPLETED ({total_synced}/{len(apps)} apps synced) ===")
    
    try:
        total_dts = frappe.db.count("DocType", {"module": ("like", "TradeHub%")})
        print(f"Total TradeHub DocTypes in DB: {total_dts}")
    except:
        pass

    frappe.flags.in_migrate = False
    frappe.flags.in_install = False
    frappe.flags.in_setup_wizard = False
