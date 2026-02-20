#!/usr/bin/env python3
"""
Eski backup vs Yeni app'ler field sayisi karsilastirmasi.
"""

import os
import json

BASE = "/home/ali/Masaüstü/İstoç Güncel Proje/Frappe_Mock_Data/Frappe_Marketplace/frappe-bench/apps"

OLD_DOCTYPE_DIR = f"{BASE}/tr_tradehub_pre_split_backup/tr_tradehub/tr_tradehub/doctype"

NEW_APP_DOCTYPE_DIRS = [
    f"{BASE}/tradehub_catalog/tradehub_catalog/tradehub_catalog/doctype",
    f"{BASE}/tradehub_commerce/tradehub_commerce/tradehub_commerce/doctype",
    f"{BASE}/tradehub_compliance/tradehub_compliance/tradehub_compliance/doctype",
    f"{BASE}/tradehub_core/tradehub_core/tradehub_core/doctype",
    f"{BASE}/tradehub_logistics/tradehub_logistics/tradehub_logistics/doctype",
    f"{BASE}/tradehub_marketing/tradehub_marketing/tradehub_marketing/doctype",
    f"{BASE}/tradehub_seller/tradehub_seller/tradehub_seller/doctype",
]

def count_fields(json_path):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return len(data.get("fields", []))
    except:
        return -1

def get_file_size(path):
    try:
        return os.path.getsize(path)
    except:
        return 0

# Eski doctypes tara
old_doctypes = {}
for entry in sorted(os.listdir(OLD_DOCTYPE_DIR)):
    full = os.path.join(OLD_DOCTYPE_DIR, entry)
    if os.path.isdir(full) and entry != "__pycache__":
        old_doctypes[entry] = full

# Yeni doctypes tara
new_map = {}
for app_dir in NEW_APP_DOCTYPE_DIRS:
    if not os.path.exists(app_dir):
        continue
    for entry in os.listdir(app_dir):
        full = os.path.join(app_dir, entry)
        if os.path.isdir(full) and entry != "__pycache__":
            new_map[entry] = full

# Karsilastir
perfect = 0
mismatch = 0
missing_new = 0
missing_js = 0
total = len(old_doctypes)

print("=" * 80)
print("FIELD DOGRULAMA RAPORU")
print("=" * 80)

problems = []

for dt_name, old_path in sorted(old_doctypes.items()):
    old_json = os.path.join(old_path, f"{dt_name}.json")
    old_js = os.path.join(old_path, f"{dt_name}.js")
    old_fields = count_fields(old_json)
    old_json_size = get_file_size(old_json)
    old_js_exists = os.path.exists(old_js)
    old_js_size = get_file_size(old_js) if old_js_exists else 0

    if dt_name not in new_map:
        missing_new += 1
        problems.append(f"  EKSIK DOCTYPE: {dt_name} - yeni app'lerde bulunamadi!")
        continue

    new_path = new_map[dt_name]
    new_json = os.path.join(new_path, f"{dt_name}.json")
    new_js = os.path.join(new_path, f"{dt_name}.js")
    new_fields = count_fields(new_json)
    new_json_size = get_file_size(new_json)
    new_js_exists = os.path.exists(new_js)
    new_js_size = get_file_size(new_js) if new_js_exists else 0

    # Field sayisi kontrolu
    if old_fields != new_fields:
        mismatch += 1
        problems.append(f"  FIELD UYUMSUZ: {dt_name} | eski={old_fields} yeni={new_fields} (fark={old_fields - new_fields})")
    else:
        # JSON boyut kontrolu
        if old_json_size != new_json_size:
            problems.append(f"  JSON BOYUT FARKI: {dt_name} | eski={old_json_size}B yeni={new_json_size}B (field sayisi ayni: {old_fields})")
        perfect += 1

    # JS dosya kontrolu
    if old_js_exists and not new_js_exists:
        missing_js += 1
        problems.append(f"  JS EKSIK: {dt_name}.js - eski app'te var, yeni app'te yok")

if problems:
    print("\nSORUNLAR:")
    print("-" * 80)
    for p in problems:
        print(p)

print(f"\n{'=' * 80}")
print(f"OZET")
print(f"{'=' * 80}")
print(f"  Toplam eski DocType   : {total}")
print(f"  Field sayisi esit     : {perfect}")
print(f"  Field uyumsuz         : {mismatch}")
print(f"  Yeni app'te yok       : {missing_new}")
print(f"  JS dosyasi eksik      : {missing_js}")

if mismatch == 0 and missing_new == 0:
    print(f"\n  SONUC: BASARILI - Tum field'lar dogru sekilde geri yuklendi!")
else:
    print(f"\n  SONUC: SORUN VAR - Yukaridaki detaylari incele.")
print("=" * 80)
