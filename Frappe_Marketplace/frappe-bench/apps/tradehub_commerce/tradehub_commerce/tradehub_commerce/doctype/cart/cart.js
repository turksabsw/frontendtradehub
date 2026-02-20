// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Cart', {
    refresh: function(frm) {
        // =====================================================
        // Organization Field - Filter by Tenant
        // =====================================================
        // Only show organizations belonging to the selected tenant
        frm.set_query('organization', function() {
            if (frm.doc.tenant) {
                return {
                    filters: {
                        'tenant': frm.doc.tenant
                    }
                };
            }
            // If no tenant selected, return empty to show all
            return {};
        });

        // Make tenant field read-only when organization is selected
        // (since tenant is auto-populated from organization)
        frm.set_df_property('tenant', 'read_only', frm.doc.organization ? 1 : 0);

        // =====================================================
        // Buyer Field - Filter Users with Buyer Profile in Same Tenant
        // =====================================================
        // Filter buyers to show only users who have a Buyer Profile
        // belonging to the same tenant
        frm.set_query('buyer', function() {
            if (frm.doc.tenant) {
                // Return users who have a Buyer Profile with matching tenant
                return {
                    query: 'tr_tradehub.tr_tradehub.doctype.cart.cart.get_buyers_for_tenant',
                    filters: {
                        'tenant': frm.doc.tenant
                    }
                };
            }
            // If no tenant, show all users
            return {};
        });

        // =====================================================
        // Cart Line Child Table - Cascading Dropdown Filters
        // =====================================================

        // Listing filter - show only active listings from same tenant
        frm.set_query('listing', 'items', function(doc, cdt, cdn) {
            let filters = {
                'status': 'Active'
            };

            if (doc.tenant) {
                filters['tenant'] = doc.tenant;
            }

            return {
                filters: filters
            };
        });

        // Listing Variant filter - show only variants belonging to selected listing
        frm.set_query('listing_variant', 'items', function(doc, cdt, cdn) {
            let row = locals[cdt][cdn];
            if (row.listing) {
                return {
                    filters: {
                        'listing': row.listing
                    }
                };
            }
            return {
                filters: {
                    'name': ''  // Return nothing if no listing selected
                }
            };
        });

        // =====================================================
        // Marketplace Order Field - Filter by tenant
        // =====================================================
        frm.set_query('marketplace_order', function() {
            if (frm.doc.tenant) {
                return {
                    filters: {
                        'tenant': frm.doc.tenant
                    }
                };
            }
            return {};
        });

        // =====================================================
        // UI Updates for Cart Status
        // =====================================================
        // Disable editing for converted/expired/merged carts
        if (frm.doc.status && ['Converted', 'Expired', 'Merged'].includes(frm.doc.status)) {
            frm.disable_save();
            frm.set_intro(__('This cart is {0} and cannot be modified.', [frm.doc.status.toLowerCase()]), 'yellow');
        }

        // Show cart summary info
        if (!frm.is_new() && frm.doc.items && frm.doc.items.length > 0) {
            let seller_count = new Set(frm.doc.items.map(item => item.seller)).size;
            frm.set_intro(__('Cart contains {0} items from {1} seller(s).',
                [frm.doc.items.length, seller_count]), 'blue');
        }
    },

    tenant: function(frm) {
        // When tenant changes, validate organization still belongs to new tenant
        if (frm.doc.organization) {
            if (frm.doc.tenant) {
                frappe.db.get_value('Organization', frm.doc.organization, 'tenant', function(r) {
                    if (r && r.tenant !== frm.doc.tenant) {
                        // Organization doesn't belong to new tenant, clear it
                        frm.set_value('organization', null);
                        frappe.show_alert({
                            message: __('Organization cleared because it does not belong to the selected Tenant'),
                            indicator: 'orange'
                        });
                    }
                });
            } else {
                // Tenant was cleared, also clear organization
                frm.set_value('organization', null);
            }
        }

        // Also validate buyer belongs to new tenant
        if (frm.doc.buyer && frm.doc.tenant) {
            // Check if buyer has a Buyer Profile in the new tenant
            frappe.call({
                method: 'frappe.client.get_count',
                args: {
                    doctype: 'Buyer Profile',
                    filters: {
                        'user': frm.doc.buyer,
                        'tenant': frm.doc.tenant
                    }
                },
                callback: function(r) {
                    if (r && r.message === 0) {
                        // No Buyer Profile found for this user in the new tenant
                        frm.set_value('buyer', null);
                        frappe.show_alert({
                            message: __('Buyer cleared because they do not have a profile in the selected Tenant'),
                            indicator: 'orange'
                        });
                    }
                }
            });
        }

        // Validate cart items - check if sellers belong to new tenant
        if (frm.doc.tenant && frm.doc.items && frm.doc.items.length > 0) {
            let invalid_items = [];
            let promises = [];

            frm.doc.items.forEach(function(item, idx) {
                if (item.seller) {
                    let promise = new Promise(function(resolve) {
                        frappe.db.get_value('Seller Profile', item.seller, 'tenant', function(r) {
                            if (r && r.tenant && r.tenant !== frm.doc.tenant) {
                                invalid_items.push(item.title || item.listing);
                            }
                            resolve();
                        });
                    });
                    promises.push(promise);
                }
            });

            Promise.all(promises).then(function() {
                if (invalid_items.length > 0) {
                    frappe.msgprint({
                        title: __('Tenant Mismatch Warning'),
                        indicator: 'orange',
                        message: __('The following cart items have sellers from a different tenant and may cause validation errors on save:<br><br>{0}',
                            [invalid_items.join('<br>')])
                    });
                }
            });
        }
    },

    organization: function(frm) {
        // When organization changes, update read-only state of tenant field
        frm.set_df_property('tenant', 'read_only', frm.doc.organization ? 1 : 0);

        // If organization is selected, auto-populate tenant from organization
        if (frm.doc.organization) {
            frappe.db.get_value('Organization', frm.doc.organization, 'tenant', function(r) {
                if (r && r.tenant) {
                    if (!frm.doc.tenant || frm.doc.tenant !== r.tenant) {
                        frm.set_value('tenant', r.tenant);
                    }
                }
            });

            // Also set buyer_type to Organization if not already
            if (frm.doc.buyer_type !== 'Organization') {
                frm.set_value('buyer_type', 'Organization');
            }
        } else {
            // If organization is cleared, allow tenant to be edited again
            frm.set_df_property('tenant', 'read_only', 0);
        }
    },

    buyer_type: function(frm) {
        // When buyer type changes, clear organization if not Organization type
        if (frm.doc.buyer_type !== 'Organization' && frm.doc.organization) {
            frm.set_value('organization', null);
            frappe.show_alert({
                message: __('Organization cleared because buyer type is not Organization'),
                indicator: 'blue'
            });
        }

        // Enable/disable is_b2b_cart based on buyer type
        if (frm.doc.buyer_type === 'Organization') {
            frm.set_value('is_b2b_cart', 1);
        }
    },

    buyer: function(frm) {
        // When buyer changes, optionally auto-populate tenant from buyer's Buyer Profile
        if (frm.doc.buyer && !frm.doc.tenant) {
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'Buyer Profile',
                    filters: {
                        'user': frm.doc.buyer
                    },
                    fieldname: ['tenant', 'organization']
                },
                callback: function(r) {
                    if (r && r.message) {
                        if (r.message.tenant && !frm.doc.tenant) {
                            frm.set_value('tenant', r.message.tenant);
                        }
                        // If buyer has an organization and buyer_type is Organization
                        if (r.message.organization && frm.doc.buyer_type === 'Organization' && !frm.doc.organization) {
                            frm.set_value('organization', r.message.organization);
                        }
                    }
                }
            });
        }
    },

    is_b2b_cart: function(frm) {
        // When B2B cart flag changes, update related settings
        if (frm.doc.is_b2b_cart && frm.doc.buyer_type !== 'Organization') {
            frm.set_value('buyer_type', 'Organization');
        }
    }
});

// =====================================================
// Cart Line Child Table - Event Handlers
// =====================================================

frappe.ui.form.on('Cart Line', {
    listing: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // When listing changes, clear listing_variant
        // because it may not belong to the new listing
        if (row.listing_variant) {
            frappe.model.set_value(cdt, cdn, 'listing_variant', '');
            frappe.show_alert({
                message: __('Listing Variant cleared due to listing change'),
                indicator: 'blue'
            });
        }

        // Auto-populate seller and other fields from listing
        if (row.listing) {
            frappe.db.get_value('Listing', row.listing,
                ['seller', 'title', 'sku', 'price', 'compare_at_price', 'primary_image',
                 'stock_uom', 'tax_rate', 'weight', 'weight_uom', 'tenant'],
                function(r) {
                    if (r) {
                        // Validate listing tenant matches cart tenant
                        if (frm.doc.tenant && r.tenant && r.tenant !== frm.doc.tenant) {
                            frappe.model.set_value(cdt, cdn, 'listing', '');
                            frappe.msgprint({
                                title: __('Tenant Mismatch'),
                                indicator: 'red',
                                message: __('This listing belongs to a different tenant and cannot be added to this cart.')
                            });
                            return;
                        }

                        // Set auto-populated fields
                        frappe.model.set_value(cdt, cdn, 'seller', r.seller);
                        frappe.model.set_value(cdt, cdn, 'title', r.title);
                        frappe.model.set_value(cdt, cdn, 'sku', r.sku);
                        frappe.model.set_value(cdt, cdn, 'unit_price', r.price);
                        frappe.model.set_value(cdt, cdn, 'compare_at_price', r.compare_at_price);
                        frappe.model.set_value(cdt, cdn, 'primary_image', r.primary_image);
                        frappe.model.set_value(cdt, cdn, 'stock_uom', r.stock_uom);
                        frappe.model.set_value(cdt, cdn, 'tax_rate', r.tax_rate);
                        frappe.model.set_value(cdt, cdn, 'weight', r.weight);
                        frappe.model.set_value(cdt, cdn, 'weight_uom', r.weight_uom);
                    }
                }
            );
        }
    },

    qty: function(frm, cdt, cdn) {
        // Recalculate line totals when quantity changes
        calculate_line_totals(frm, cdt, cdn);
    },

    unit_price: function(frm, cdt, cdn) {
        // Recalculate line totals when price changes
        calculate_line_totals(frm, cdt, cdn);
    },

    discount_value: function(frm, cdt, cdn) {
        // Recalculate line totals when discount changes
        calculate_line_totals(frm, cdt, cdn);
    },

    discount_type: function(frm, cdt, cdn) {
        // Recalculate line totals when discount type changes
        calculate_line_totals(frm, cdt, cdn);
    },

    tax_rate: function(frm, cdt, cdn) {
        // Recalculate line totals when tax rate changes
        calculate_line_totals(frm, cdt, cdn);
    },

    // When row is added, recalculate totals
    items_add: function(frm, cdt, cdn) {
        calculate_cart_totals(frm);
    },

    // When row is removed, recalculate totals
    items_remove: function(frm) {
        calculate_cart_totals(frm);
    }
});

// =====================================================
// Helper Functions
// =====================================================

/**
 * Calculate line totals for a cart line item.
 * CRITICAL: Always use frappe.model.set_value for child table updates
 */
function calculate_line_totals(frm, cdt, cdn) {
    let row = locals[cdt][cdn];

    let qty = flt(row.qty);
    let unit_price = flt(row.unit_price);
    let discount_value = flt(row.discount_value);
    let tax_rate = flt(row.tax_rate);

    // Calculate discount based on type
    let discount_amount_per_unit = 0;
    if (row.discount_type === 'Percentage' && discount_value > 0) {
        discount_amount_per_unit = unit_price * (discount_value / 100);
    } else if (row.discount_type === 'Fixed Amount' && discount_value > 0) {
        discount_amount_per_unit = discount_value;
    }

    let discounted_price = Math.max(0, unit_price - discount_amount_per_unit);
    let line_subtotal = qty * discounted_price;
    let total_discount = discount_amount_per_unit * qty;

    // Calculate tax
    let taxable_amount = line_subtotal;
    let tax_amount = 0;

    if (row.price_includes_tax) {
        // Extract tax from price (VAT inclusive)
        taxable_amount = line_subtotal / (1 + tax_rate / 100);
        tax_amount = line_subtotal - taxable_amount;
    } else {
        // Add tax to price (VAT exclusive)
        tax_amount = line_subtotal * (tax_rate / 100);
    }

    // Final line total (subtotal + tax for VAT exclusive, or just subtotal for VAT inclusive)
    let line_total = row.price_includes_tax ? line_subtotal : (line_subtotal + tax_amount);

    // Update all calculated fields using frappe.model.set_value
    // CRITICAL: Never use direct assignment for child table fields
    frappe.model.set_value(cdt, cdn, 'discount_amount', total_discount);
    frappe.model.set_value(cdt, cdn, 'discounted_price', discounted_price);
    frappe.model.set_value(cdt, cdn, 'line_total', line_total);
    frappe.model.set_value(cdt, cdn, 'taxable_amount', taxable_amount);
    frappe.model.set_value(cdt, cdn, 'tax_amount', tax_amount);

    // Recalculate cart totals
    calculate_cart_totals(frm);
}

/**
 * Calculate cart totals from all items
 */
function calculate_cart_totals(frm) {
    let items = frm.doc.items || [];

    let subtotal = 0;
    let total_discount = 0;
    let total_tax = 0;
    let total_qty = 0;
    let total_weight = 0;
    let item_count = items.length;

    items.forEach(function(item) {
        let line_subtotal = flt(item.qty) * flt(item.discounted_price || item.unit_price);
        subtotal += line_subtotal;
        total_discount += flt(item.discount_amount);
        total_tax += flt(item.tax_amount);
        total_qty += flt(item.qty);
        total_weight += flt(item.weight) * flt(item.qty);
    });

    // Apply cart-level discounts (coupon, promotion)
    let coupon_discount = flt(frm.doc.coupon_discount);
    let promotion_discount = flt(frm.doc.promotion_discount);
    let order_discount = coupon_discount + promotion_discount;

    // Calculate shipping (estimated)
    let shipping_total = flt(frm.doc.shipping_estimate);

    // Calculate grand total
    let grand_total = subtotal - order_discount + total_tax + shipping_total;

    // Update parent totals
    frm.set_value('subtotal', subtotal);
    frm.set_value('total_discount', total_discount + order_discount);
    frm.set_value('tax_total', total_tax);
    frm.set_value('grand_total', grand_total);
    frm.set_value('item_count', item_count);
    frm.set_value('total_qty', total_qty);
    frm.set_value('total_weight', total_weight);
}
