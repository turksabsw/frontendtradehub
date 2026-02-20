#!/usr/bin/env python3
"""
JSON dosyalarindaki "module" degerini yeni app'in modul adiyla gunceller.
"""

import os
import json

BASE = "/home/ali/Masaüstü/İstoç Güncel Proje/Frappe_Mock_Data/Frappe_Marketplace/frappe-bench/apps"

# App dizini -> Modul adi eslesmesi
APP_MODULE_MAP = {
    f"{BASE}/tradehub_catalog/tradehub_catalog/tradehub_catalog/doctype": "TradeHub Catalog",
    f"{BASE}/tradehub_commerce/tradehub_commerce/tradehub_commerce/doctype": "TradeHub Commerce",
    f"{BASE}/tradehub_compliance/tradehub_compliance/tradehub_compliance/doctype": "TradeHub Compliance",
    f"{BASE}/tradehub_core/tradehub_core/tradehub_core/doctype": "TradeHub Core",
    f"{BASE}/tradehub_logistics/tradehub_logistics/tradehub_logistics/doctype": "TradeHub Logistics",
    f"{BASE}/tradehub_marketing/tradehub_marketing/tradehub_marketing/doctype": "TradeHub Marketing",
    f"{BASE}/tradehub_seller/tradehub_seller/tradehub_seller/doctype": "TradeHub Seller",
}

fixed = 0
skipped = 0
errors = 0

for doctype_base, module_name in APP_MODULE_MAP.items():
    if not os.path.exists(doctype_base):
        print(f"UYARI: {doctype_base} bulunamadi")
        continue

    for dt_folder in sorted(os.listdir(doctype_base)):
        dt_path = os.path.join(doctype_base, dt_folder)
        if not os.path.isdir(dt_path) or dt_folder == "__pycache__":
            continue

        json_file = os.path.join(dt_path, f"{dt_folder}.json")
        if not os.path.exists(json_file):
            continue

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            old_module = data.get("module", "")
            if old_module != module_name:
                data["module"] = module_name
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=1, ensure_ascii=False)
                    f.write("\n")
                print(f"  DUZELTILDI: {dt_folder}.json | '{old_module}' -> '{module_name}'")
                fixed += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  HATA: {dt_folder}.json | {e}")
            errors += 1

print(f"\n{'=' * 50}")
print(f"Duzeltilen: {fixed}")
print(f"Zaten dogru: {skipped}")
print(f"Hata: {errors}")
print(f"{'=' * 50}")
print("Simdi: bench migrate")
