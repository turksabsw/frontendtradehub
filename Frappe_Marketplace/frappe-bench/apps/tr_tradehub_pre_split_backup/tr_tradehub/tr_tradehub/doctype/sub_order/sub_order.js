// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Sub Order', {
    refresh: function(frm) {
        // Ensure read-only fields when marketplace_order is set
        if (frm.doc.marketplace_order) {
            set_parent_order_fields_readonly(frm, true);
        }

        // Ensure tenant field is read-only when seller is set
        if (frm.doc.seller) {
            frm.set_df_property('tenant', 'read_only', 1);
        }

        // Add custom buttons for saved records
        if (!frm.is_new() && frm.doc.docstatus === 0) {
            // Add button to view parent order
            if (frm.doc.marketplace_order) {
                frm.add_custom_button(__('View Parent Order'), function() {
                    frappe.set_route('Form', 'Marketplace Order', frm.doc.marketplace_order);
                }, __('Actions'));
            }
        }

        // Show parent order info in dashboard
        if (frm.doc.marketplace_order && frm.doc.parent_order_id) {
            frm.dashboard.add_comment(
                __('Sub order of Marketplace Order: {0}', [frm.doc.parent_order_id]),
                'blue',
                true
            );
        }
    },

    marketplace_order: function(frm) {
        // When marketplace order is selected, auto-populate fields
        if (frm.doc.marketplace_order) {
            frappe.call({
                method: 'tr_tradehub.tr_tradehub.doctype.sub_order.sub_order.get_parent_order_details',
                args: {
                    marketplace_order: frm.doc.marketplace_order
                },
                callback: function(r) {
                    if (r.message && r.message.order) {
                        populate_from_parent_order(frm, r.message.order);
                    }
                }
            });
        } else {
            // Clear fields when marketplace order is cleared
            clear_parent_order_fields(frm);
        }
    },

    seller: function(frm) {
        // When seller is selected, fetch tenant from seller profile
        if (frm.doc.seller) {
            frappe.db.get_value('Seller Profile', frm.doc.seller, ['tenant', 'seller_name', 'commission_plan'], function(r) {
                if (r) {
                    if (r.tenant) {
                        frm.set_value('tenant', r.tenant);
                    }
                    // Make tenant read-only after auto-populating
                    frm.set_df_property('tenant', 'read_only', 1);

                    // Get commission rate from commission plan
                    if (r.commission_plan) {
                        frappe.db.get_value('Commission Plan', r.commission_plan, 'default_rate', function(plan_r) {
                            if (plan_r && plan_r.default_rate) {
                                frm.set_value('commission_rate', plan_r.default_rate);
                            }
                        });
                    }
                }
            });
        } else {
            // Clear tenant when seller is cleared
            frm.set_value('tenant', '');
            frm.set_df_property('tenant', 'read_only', 0);
        }
    }
});

/**
 * Populate Sub Order fields from parent Marketplace Order
 */
function populate_from_parent_order(frm, order) {
    // Parent order ID for display
    frm.set_value('parent_order_id', order.order_id);

    // Order date from parent
    if (!frm.doc.order_date && order.order_date) {
        frm.set_value('order_date', order.order_date);
    }

    // Buyer information
    if (!frm.doc.buyer && order.buyer) {
        frm.set_value('buyer', order.buyer);
    }
    frm.set_value('buyer_name', order.buyer_name || '');
    frm.set_value('buyer_email', order.buyer_email || '');
    frm.set_value('buyer_phone', order.buyer_phone || '');
    frm.set_value('buyer_tax_id', order.buyer_tax_id || '');

    // Currency
    if (!frm.doc.currency && order.currency) {
        frm.set_value('currency', order.currency);
    }

    // Shipping address
    frm.set_value('shipping_address_name', order.shipping_address_name || '');
    frm.set_value('shipping_address_line1', order.shipping_address_line1 || '');
    frm.set_value('shipping_address_line2', order.shipping_address_line2 || '');
    frm.set_value('shipping_city', order.shipping_city || '');
    frm.set_value('shipping_state', order.shipping_state || '');
    frm.set_value('shipping_postal_code', order.shipping_postal_code || '');
    frm.set_value('shipping_country', order.shipping_country || 'Turkey');
    frm.set_value('shipping_phone', order.shipping_phone || '');

    // Set fields as read-only since they come from parent order
    set_parent_order_fields_readonly(frm, true);

    // Show success message
    frappe.show_alert({
        message: __('Buyer and shipping information populated from parent order'),
        indicator: 'green'
    }, 3);
}

/**
 * Set parent order fields as read-only or editable
 */
function set_parent_order_fields_readonly(frm, read_only) {
    // Buyer fields
    frm.set_df_property('buyer', 'read_only', read_only);
    frm.set_df_property('buyer_name', 'read_only', 1); // Always read-only
    frm.set_df_property('buyer_email', 'read_only', 1);
    frm.set_df_property('buyer_phone', 'read_only', 1);
    frm.set_df_property('buyer_tax_id', 'read_only', 1);

    // Currency
    frm.set_df_property('currency', 'read_only', read_only);

    // Shipping address fields
    frm.set_df_property('shipping_address_name', 'read_only', read_only);
    frm.set_df_property('shipping_address_line1', 'read_only', read_only);
    frm.set_df_property('shipping_address_line2', 'read_only', read_only);
    frm.set_df_property('shipping_city', 'read_only', read_only);
    frm.set_df_property('shipping_state', 'read_only', read_only);
    frm.set_df_property('shipping_postal_code', 'read_only', read_only);
    frm.set_df_property('shipping_country', 'read_only', read_only);
    frm.set_df_property('shipping_phone', 'read_only', read_only);
}

/**
 * Clear fields populated from parent order
 */
function clear_parent_order_fields(frm) {
    // Clear parent order ID
    frm.set_value('parent_order_id', '');

    // Clear buyer info
    frm.set_value('buyer', '');
    frm.set_value('buyer_name', '');
    frm.set_value('buyer_email', '');
    frm.set_value('buyer_phone', '');
    frm.set_value('buyer_tax_id', '');

    // Clear shipping address
    frm.set_value('shipping_address_name', '');
    frm.set_value('shipping_address_line1', '');
    frm.set_value('shipping_address_line2', '');
    frm.set_value('shipping_city', '');
    frm.set_value('shipping_state', '');
    frm.set_value('shipping_postal_code', '');
    frm.set_value('shipping_country', 'Turkey');
    frm.set_value('shipping_phone', '');

    // Make fields editable again
    set_parent_order_fields_readonly(frm, false);

    // Show info message
    frappe.show_alert({
        message: __('Parent order cleared - please select a marketplace order'),
        indicator: 'yellow'
    }, 3);
}
