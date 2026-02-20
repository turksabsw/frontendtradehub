import frappe
import json
import os

def sync_child_tables():
    """Migrate sonrası orphan olarak silinen child table'ları geri yükle"""
    
    base_path = frappe.get_app_path("tr_tradehub", "tr_tradehub", "doctype")
    
    child_tables = [
        "rfq_item", "rfq_attachment", "rfq_target_seller", 
        "rfq_target_category", "rfq_nda_link"
    ]
    
    for ct in child_tables:
        json_path = os.path.join(base_path, ct, f"{ct}.json")
        if os.path.exists(json_path):
            with open(json_path) as f:
                data = json.load(f)
            
            dt_name = data.get("name")
            if not frappe.db.exists("DocType", dt_name):
                doc = frappe.get_doc(data)
                doc.flags.ignore_permissions = True
                doc.flags.ignore_links = True
                doc.flags.ignore_mandatory = True
                doc.insert(ignore_if_duplicate=True)
                print(f"  Restored: {dt_name}")
    
    frappe.db.commit()
