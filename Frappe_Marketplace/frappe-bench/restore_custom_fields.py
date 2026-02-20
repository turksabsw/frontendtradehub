import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def restore_custom_fields():
    print("Starting Custom Field Restoration...")
    
    custom_fields = {
        "User": [
            {
                "fieldname": "tenant",
                "label": "Tenant",
                "fieldtype": "Link",
                "options": "Tenant",
                "insert_after": "language",
                "reqd": 0,
                "in_list_view": 1,
                "in_standard_filter": 1
            }
        ],
        "Workspace": [
             {
                "fieldname": "tenant",
                "label": "Tenant",
                "fieldtype": "Link",
                "options": "Tenant",
                "insert_after": "is_hidden",
                "reqd": 0
            }
        ]
    }
    
    create_custom_fields(custom_fields, ignore_validate=True)
    frappe.db.commit()
    print("Custom Fields successfully injected.")

if __name__ == "__main__":
    restore_custom_fields()
