
# =============================================================================
# MARKETPLACE ORDER -> SALES ORDER SYNC
# =============================================================================


def create_sales_order_from_marketplace_order(marketplace_order: Document) -> str:
    """
    Create an ERPNext Sales Order from a Marketplace Order.
    """
    return make_sales_order(marketplace_order.name, target_doc=None)


def sync_sales_order_from_marketplace_order(marketplace_order: Document) -> bool:
    """
    Sync Marketplace Order changes to linked ERPNext Sales Order.
    """
    return sync_order_to_sales_order(marketplace_order.name)


def cancel_sales_order_for_marketplace_order(marketplace_order: Document) -> bool:
    """
    Cancel linked ERPNext Sales Order.
    """
    if not marketplace_order.erpnext_sales_order:
        return True
        
    try:
        sales_order = frappe.get_doc("Sales Order", marketplace_order.erpnext_sales_order)
        if sales_order.docstatus == 1:
            sales_order.cancel()
        return True
    except Exception as e:
        frappe.log_error(f"Failed to cancel Sales Order: {str(e)}")
        return False


def submit_sales_order_for_marketplace_order(marketplace_order: Document) -> bool:
    """
    Submit linked ERPNext Sales Order.
    """
    if not marketplace_order.erpnext_sales_order:
        return False
        
    try:
        sales_order = frappe.get_doc("Sales Order", marketplace_order.erpnext_sales_order)
        if sales_order.docstatus == 0:
            sales_order.submit()
        return True
    except Exception as e:
        frappe.log_error(f"Failed to submit Sales Order: {str(e)}")
        return False
