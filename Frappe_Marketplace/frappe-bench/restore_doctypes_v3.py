#!/usr/bin/env python3
"""
TR TradeHub DocType Restorer v3
Eski backup'taki DocType json/js dosyalarini yeni 7 app'e otomatik kopyalar.
"""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime

# ============================================================
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

FILE_EXTENSIONS = [".json", ".js", ".py"]

# DRY RUN: True = sadece rapor, False = gercek kopyalama
DRY_RUN = False
# ============================================================

def get_app_name(doctype_dir):
    parts = Path(doctype_dir).parts
    for i, part in enumerate(parts):
        if part == "doctype" and i > 0:
            return parts[i - 1]
    return doctype_dir

def scan_doctypes(base_dir):
    doctypes = {}
    if not os.path.exists(base_dir):
        print(f"  UYARI: Dizin bulunamadi: {base_dir}")
        return doctypes
    for entry in os.listdir(base_dir):
        full_path = os.path.join(base_dir, entry)
        if os.path.isdir(full_path):
            doctypes[entry] = full_path
    return doctypes

def count_fields_in_json(json_path):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return len(data.get("fields", []))
    except:
        return -1

def list_files_in_dir(dir_path):
    files = []
    if os.path.exists(dir_path):
        for f in os.listdir(dir_path):
            if os.path.isfile(os.path.join(dir_path, f)):
                files.append(f)
    return sorted(files)

def main():
    print("=" * 70)
    print("TR TradeHub DocType Restorer v3")
    print(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"MOD: {'DRY RUN (sadece rapor)' if DRY_RUN else 'GERCEK KOPYALAMA'}")
    print("=" * 70)

    print(f"\n[1/4] Eski backup taraniyor...")
    old_doctypes = scan_doctypes(OLD_DOCTYPE_DIR)
    print(f"  Bulunan DocType sayisi: {len(old_doctypes)}")

    print(f"\n[2/4] Yeni 7 app taraniyor...")
    new_doctype_map = {}
    for app_dir in NEW_APP_DOCTYPE_DIRS:
        app_name = get_app_name(app_dir)
        app_doctypes = scan_doctypes(app_dir)
        print(f"  {app_name}: {len(app_doctypes)} DocType")
        for dt_name, dt_path in app_doctypes.items():
            if dt_name in new_doctype_map:
                print(f"  UYARI: '{dt_name}' birden fazla app'te! ({new_doctype_map[dt_name][0]} ve {app_name})")
            new_doctype_map[dt_name] = (app_name, dt_path)
    print(f"  Toplam yeni DocType sayisi: {len(new_doctype_map)}")

    print(f"\n[3/4] {'Analiz (DRY RUN)...' if DRY_RUN else 'Kopyalaniyor...'}")
    print("-" * 70)

    matched = 0
    unmatched = []
    copied_files = 0
    field_report = []

    for dt_name, old_path in sorted(old_doctypes.items()):
        if dt_name in new_doctype_map:
            matched += 1
            app_name, new_path = new_doctype_map[dt_name]

            old_json = os.path.join(old_path, f"{dt_name}.json")
            new_json = os.path.join(new_path, f"{dt_name}.json")
            old_fields = count_fields_in_json(old_json) if os.path.exists(old_json) else -1
            new_fields = count_fields_in_json(new_json) if os.path.exists(new_json) else -1

            old_files = list_files_in_dir(old_path)
            new_files = list_files_in_dir(new_path)
            missing_in_new = [f for f in old_files if f not in new_files]

            dt_copied = 0
            for filename in os.listdir(old_path):
                old_file = os.path.join(old_path, filename)
                new_file = os.path.join(new_path, filename)
                if os.path.isfile(old_file):
                    ext = os.path.splitext(filename)[1]
                    if ext in FILE_EXTENSIONS or filename == "__init__.py":
                        if not DRY_RUN:
                            shutil.copy2(old_file, new_file)
                        copied_files += 1
                        dt_copied += 1

            diff = 0
            status = ""
            if old_fields >= 0 and new_fields >= 0:
                diff = old_fields - new_fields
                if diff > 0:
                    status = f"FIELD KAYBI: {new_fields} -> {old_fields} (+{diff})"
                elif diff == 0:
                    status = f"{old_fields} field (ayni)"
                else:
                    status = f"eski={old_fields}, yeni={new_fields}"

            missing_str = ""
            if missing_in_new:
                missing_str = f" | Eksik: {', '.join(missing_in_new)}"

            field_report.append((dt_name, app_name, status, missing_str, diff))
            tag = "ONIZLEME" if DRY_RUN else "KOPYALANDI"
            print(f"  [{tag}] {dt_name} -> {app_name} ({dt_copied} dosya) | {status}{missing_str}")
        else:
            unmatched.append(dt_name)

    print(f"\n{'=' * 70}")
    print(f"[4/4] OZET RAPOR")
    print(f"{'=' * 70}")
    print(f"  Eski DocType sayisi      : {len(old_doctypes)}")
    print(f"  Eslesen                  : {matched}")
    print(f"  Eslesmeyen               : {len(unmatched)}")
    print(f"  Dosya sayisi             : {copied_files}")

    fields_restored = [r for r in field_report if r[4] > 0]
    if fields_restored:
        total = sum(r[4] for r in fields_restored)
        print(f"\n  FIELD KAYBI OLAN DocType'LAR ({len(fields_restored)} adet, toplam +{total} field):")
        print(f"  {'-' * 60}")
        for dt_name, app_name, status, _, diff in sorted(fields_restored, key=lambda x: -x[4]):
            print(f"    {dt_name} ({app_name}): +{diff} field")

    if unmatched:
        print(f"\n  ESLESMEYEN DocType'LAR ({len(unmatched)} adet):")
        print(f"  {'-' * 60}")
        for dt in sorted(unmatched):
            old_path = old_doctypes[dt]
            old_json = os.path.join(old_path, f"{dt}.json")
            fc = count_fields_in_json(old_json)
            fc_str = f" ({fc} field)" if fc >= 0 else ""
            print(f"    {dt}{fc_str}")

    print(f"\n{'=' * 70}")
    if DRY_RUN:
        print("DRY RUN TAMAMLANDI!")
        print("Sorun yoksa: nano restore_doctypes_v3.py -> DRY_RUN = False -> tekrar calistir")
    else:
        print("KOPYALAMA TAMAMLANDI! Simdi: bench migrate")
    print("=" * 70)

if __name__ == "__main__":
    main()
