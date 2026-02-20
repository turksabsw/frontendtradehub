// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Marketplace Order', {
    refresh: function(frm) {
        // Ensure buyer detail fields are read-only when buyer is set
        if (frm.doc.buyer) {
            frm.set_df_property('buyer_name', 'read_only', 1);
            frm.set_df_property('buyer_email', 'read_only', 1);
            frm.set_df_property('buyer_phone', 'read_only', 1);
        }

        // Ensure organization fields are read-only when organization is set
        if (frm.doc.organization) {
            frm.set_df_property('buyer_tax_id', 'read_only', 1);
            frm.set_df_property('buyer_company_name', 'read_only', 1);
            frm.set_df_property('tenant', 'read_only', 1);
        }

        // Add "Get Items From Cart" button for new or draft orders
        // Show for new orders or saved but not submitted orders (docstatus === 0)
        if (frm.is_new() || frm.doc.docstatus === 0) {
            // Add the button if buyer is selected
            if (frm.doc.buyer) {
                frm.add_custom_button(__('Get Items From Cart'), function() {
                    get_items_from_cart(frm);
                }, __('Actions'));
            }
        }

        // Show cart validation warnings if cart is linked
        if (frm.doc.cart) {
            show_cart_info(frm);
        }
    },

    buyer: function(frm) {
        // When buyer is selected, fetch user details
        if (frm.doc.buyer) {
            frappe.db.get_value('User', frm.doc.buyer, ['full_name', 'email', 'mobile_no'], function(r) {
                if (r) {
                    if (r.full_name) {
                        frm.set_value('buyer_name', r.full_name);
                    }
                    if (r.email) {
                        frm.set_value('buyer_email', r.email);
                    }
                    if (r.mobile_no) {
                        frm.set_value('buyer_phone', r.mobile_no);
                    }
                    // Make buyer detail fields read-only after auto-populating
                    frm.set_df_property('buyer_name', 'read_only', 1);
                    frm.set_df_property('buyer_email', 'read_only', 1);
                    frm.set_df_property('buyer_phone', 'read_only', 1);
                }
            });

            // Check if buyer has an active cart
            check_buyer_cart(frm);
        } else {
            // Clear buyer details when buyer is cleared
            frm.set_value('buyer_name', '');
            frm.set_value('buyer_email', '');
            frm.set_value('buyer_phone', '');
            frm.set_df_property('buyer_name', 'read_only', 0);
            frm.set_df_property('buyer_email', 'read_only', 0);
            frm.set_df_property('buyer_phone', 'read_only', 0);
        }
    },

    organization: function(frm) {
        // When organization is selected, fetch organization details
        if (frm.doc.organization) {
            frappe.db.get_value('Organization', frm.doc.organization,
                ['organization_name', 'tax_id', 'tenant'], function(r) {
                if (r) {
                    if (r.organization_name) {
                        frm.set_value('buyer_company_name', r.organization_name);
                    }
                    if (r.tax_id) {
                        frm.set_value('buyer_tax_id', r.tax_id);
                    }
                    if (r.tenant) {
                        frm.set_value('tenant', r.tenant);
                    }
                    // Make organization fields read-only after auto-populating
                    frm.set_df_property('buyer_company_name', 'read_only', 1);
                    frm.set_df_property('buyer_tax_id', 'read_only', 1);
                    frm.set_df_property('tenant', 'read_only', 1);
                }
            });
        } else {
            // Clear organization details when organization is cleared
            frm.set_value('buyer_company_name', '');
            frm.set_value('buyer_tax_id', '');
            frm.set_value('tenant', '');
            frm.set_df_property('buyer_company_name', 'read_only', 0);
            frm.set_df_property('buyer_tax_id', 'read_only', 0);
            frm.set_df_property('tenant', 'read_only', 0);
        }
    },

    buyer_type: function(frm) {
        // Clear organization-related fields when buyer type changes from Organization
        if (frm.doc.buyer_type !== 'Organization') {
            frm.set_value('organization', '');
            frm.set_value('buyer_company_name', '');
            frm.set_value('buyer_tax_id', '');
            frm.set_value('tenant', '');
            frm.set_df_property('buyer_company_name', 'read_only', 0);
            frm.set_df_property('buyer_tax_id', 'read_only', 0);
            frm.set_df_property('tenant', 'read_only', 0);
        }
    }
});

/**
 * Check if the buyer has an active cart and show notification
 */
function check_buyer_cart(frm) {
    frappe.call({
        method: 'tr_tradehub.tr_tradehub.doctype.marketplace_order.marketplace_order.get_buyer_active_cart',
        args: {
            buyer: frm.doc.buyer
        },
        callback: function(r) {
            if (r.message) {
                let cart = r.message;
                let msg = __('Buyer has an active cart with {0} item(s). Total: {1}', [
                    cart.item_count,
                    format_currency(cart.grand_total, frm.doc.currency || 'TRY')
                ]);

                // Show indicator based on cart status
                let indicator = 'green';
                if (cart.has_price_changes || cart.has_stock_issues) {
                    indicator = 'orange';
                    msg += ' ' + __('(Has warnings)');
                }

                frappe.show_alert({
                    message: msg,
                    indicator: indicator
                }, 5);

                // Add button to get items from this cart
                frm.page.set_inner_btn_group_as_primary(__('Actions'));
            }
        }
    });
}

/**
 * Get items from buyer's cart and populate order items
 */
function get_items_from_cart(frm) {
    if (!frm.doc.buyer) {
        frappe.msgprint(__('Please select a buyer first'));
        return;
    }

    // First, check if buyer has an active cart
    frappe.call({
        method: 'tr_tradehub.tr_tradehub.doctype.marketplace_order.marketplace_order.get_buyer_active_cart',
        args: {
            buyer: frm.doc.buyer
        },
        callback: function(r) {
            if (!r.message) {
                frappe.msgprint(__('No active cart found for this buyer'));
                return;
            }

            let cart = r.message;

            // Confirm with user
            let msg = __('Found cart with {0} item(s). Total: {1}', [
                cart.item_count,
                format_currency(cart.grand_total, frm.doc.currency || 'TRY')
            ]);

            if (cart.has_price_changes) {
                msg += '<br><span class="text-warning">' + __('Warning: Cart has price changes') + '</span>';
            }
            if (cart.has_stock_issues) {
                msg += '<br><span class="text-warning">' + __('Warning: Cart has stock issues') + '</span>';
            }

            // Check if order already has items
            if (frm.doc.items && frm.doc.items.length > 0) {
                msg += '<br><br><strong>' + __('This will replace existing order items.') + '</strong>';
            }

            frappe.confirm(
                msg,
                function() {
                    // User confirmed - fetch cart items
                    fetch_and_populate_cart_items(frm, cart.name);
                },
                function() {
                    // User cancelled
                }
            );
        }
    });
}

/**
 * Fetch cart items and populate order
 */
function fetch_and_populate_cart_items(frm, cart_name) {
    frappe.call({
        method: 'tr_tradehub.tr_tradehub.doctype.marketplace_order.marketplace_order.get_cart_items_for_order',
        args: {
            cart_name: cart_name
        },
        freeze: true,
        freeze_message: __('Loading cart items...'),
        callback: function(r) {
            if (r.message) {
                let data = r.message;

                // Clear existing items
                frm.clear_table('items');

                // Add items from cart
                data.items.forEach(function(item) {
                    let row = frm.add_child('items');
                    Object.assign(row, {
                        listing: item.listing,
                        listing_variant: item.listing_variant,
                        seller: item.seller,
                        title: item.title,
                        sku: item.sku,
                        primary_image: item.primary_image,
                        qty: item.qty,
                        stock_uom: item.stock_uom,
                        currency: item.currency || frm.doc.currency,
                        unit_price: item.unit_price,
                        compare_at_price: item.compare_at_price,
                        tax_rate: item.tax_rate || 18,
                        commission_rate: item.commission_rate,
                        weight: item.weight,
                        weight_uom: item.weight_uom,
                        fulfillment_status: 'Pending'
                    });
                });

                // Update cart reference and related fields
                frm.set_value('cart', cart_name);
                frm.set_value('source_channel', data.cart.source_channel || 'Website');

                // Copy buyer info from cart if not set
                if (!frm.doc.buyer_type && data.cart.buyer_type) {
                    frm.set_value('buyer_type', data.cart.buyer_type);
                }
                if (!frm.doc.organization && data.cart.organization) {
                    frm.set_value('organization', data.cart.organization);
                }

                // Copy coupon/promotion info
                if (data.cart.coupon_code) {
                    frm.set_value('coupon_code', data.cart.coupon_code);
                    frm.set_value('coupon_discount', data.cart.coupon_discount || 0);
                }
                if (data.cart.promotion_code) {
                    frm.set_value('promotion_code', data.cart.promotion_code);
                    frm.set_value('promotion_discount', data.cart.promotion_discount || 0);
                }

                // Copy shipping info
                if (data.cart.shipping_country) {
                    frm.set_value('shipping_country', data.cart.shipping_country);
                }
                if (data.cart.shipping_postal_code) {
                    frm.set_value('shipping_postal_code', data.cart.shipping_postal_code);
                }

                // Refresh the items table
                frm.refresh_field('items');

                // Show success message
                let msg = __('Added {0} item(s) from cart', [data.items.length]);

                if (!data.can_checkout) {
                    frappe.msgprint({
                        title: __('Cart Items Added'),
                        message: msg + '<br><br><span class="text-warning">' +
                            __('Note: {0}', [data.error]) + '</span>',
                        indicator: 'orange'
                    });
                } else {
                    frappe.show_alert({
                        message: msg,
                        indicator: 'green'
                    }, 5);
                }

                // Mark form as dirty
                frm.dirty();
            }
        }
    });
}

/**
 * Show cart information if cart is linked
 */
function show_cart_info(frm) {
    if (!frm.doc.cart) return;

    frappe.db.get_value('Cart', frm.doc.cart,
        ['status', 'validation_status', 'has_price_changes', 'has_stock_issues', 'converted_to_order'],
        function(r) {
            if (r) {
                if (r.converted_to_order && r.status === 'Converted') {
                    frm.dashboard.add_comment(
                        __('This order was created from cart {0}', [frm.doc.cart]),
                        'blue',
                        true
                    );
                }
            }
        }
    );
}
