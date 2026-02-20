import os
import json

BASE_PATH = "apps/tr_tradehub/tr_tradehub/tr_tradehub/doctype"

def create_missing_controllers():
    if not os.path.exists(BASE_PATH):
        print(f"Path not found: {BASE_PATH}")
        return

    for folder_name in os.listdir(BASE_PATH):
        folder_path = os.path.join(BASE_PATH, folder_name)
        if not os.path.isdir(folder_path):
            continue

        # Ignore __pycache__
        if folder_name == "__pycache__":
            continue

        py_file = os.path.join(folder_path, f"{folder_name}.py")
        json_file = os.path.join(folder_path, f"{folder_name}.json")

        if os.path.exists(json_file) and not os.path.exists(py_file):
            print(f"Creating missing controller for: {folder_name}")
            
            # Convert snake_case to PascalCase for class name
            class_name = "".join(word.title() for word in folder_name.split("_"))
            
            content = f'''# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class {class_name}(Document):
	pass
'''
            with open(py_file, "w") as f:
                f.write(content)

if __name__ == "__main__":
    create_missing_controllers()
