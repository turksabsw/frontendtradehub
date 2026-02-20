import frappe


def execute():
    """Create default Turkish carriers."""

    # 1. Guard: DocType yoksa cik
    if not frappe.db.exists("DocType", "Carrier"):
        return

    # 2. Semayi guncelle (Select field options vs.)
    frappe.reload_doc("tr_tradehub", "doctype", "carrier")

    carriers = [
        {
            "carrier_name": "Yurtici Kargo",
            "carrier_code": "YURTICI",
            "api_provider": "Yurtici",
        },
        {
            "carrier_name": "Aras Kargo",
            "carrier_code": "ARAS",
            "api_provider": "Aras",
        },
        {
            "carrier_name": "MNG Kargo",
            "carrier_code": "MNG",
            "api_provider": "MNG",
        },
        {
            "carrier_name": "PTT Kargo",
            "carrier_code": "PTT",
            "api_provider": "PTT",
        },
        {
            "carrier_name": "Surat Kargo",
            "carrier_code": "SURAT",
            "api_provider": "Surat",
        },
    ]

    created, skipped = [], []

    for data in carriers:
        # 3. Idempotency: zaten varsa atla
        if frappe.db.exists("Carrier", {"carrier_code": data["carrier_code"]}):
            skipped.append(data["carrier_name"])
            continue

        try:
            doc = frappe.get_doc({
                "doctype": "Carrier",
                **data,
                "enabled": 1,
            })
            doc.insert(ignore_permissions=True)
            created.append(data["carrier_name"])
        except Exception as e:
            frappe.log_error(
                title=f"Carrier setup failed: {data['carrier_code']}"[:140],
                message=str(e),
            )

    if created:
        print(f"  Created: {', '.join(created)}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
