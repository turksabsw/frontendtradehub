// Copyright (c) 2026, Trade Hub and contributors
// For license information, please see license.txt

/**
 * Product Variant Client Script
 *
 * Handles client-side behavior for Product Variant DocType including:
 * - Form actions (Activate, Deactivate, Discontinue)
 * - Dynamic field behaviors
 * - fetch_from refresh handling for parent product
 * - Variant code and name generation
 * - Price calculation from base price
 */

frappe.ui.form.on('Product Variant', {
    /**
     * Called when form is refreshed/loaded
     */
    refresh: function(frm) {
        // Add custom buttons based on status
        frm.events.add_status_buttons(frm);

        // Setup dashboard
        frm.events.setup_dashboard(frm);

        // Show stock indicator
        frm.events.show_stock_indicator(frm);

        // Setup field filters
        frm.events.setup_filters(frm);
    },

    /**
     * Called before form is saved
     */
    before_save: function(frm) {
        // Auto-generate variant code if empty
        if (!frm.doc.variant_code && frm.doc.sku_product) {
            frm.events.generate_variant_code(frm);
        }

        // Auto-generate variant name if empty
        if (!frm.doc.variant_name && frm.doc.sku_product) {
            frm.events.generate_variant_name(frm);
        }

        // Calculate final price if not set
        if (!frm.doc.variant_price || frm.doc.variant_price === 0) {
            frm.events.calculate_price(frm);
        }
    },

    /**
     * Called when sku_product field changes
     */
    sku_product: function(frm) {
        // Refresh fetch_from fields
        frm.events.refresh_parent_fields(frm);

        // Regenerate variant code if empty
        if (!frm.doc.variant_code) {
            frm.events.generate_variant_code(frm);
        }

        // Calculate price
        frm.events.calculate_price(frm);
    },

    /**
     * Called when color changes
     */
    color: function(frm) {
        frm.events.update_variant_fields(frm);
    },

    /**
     * Called when size changes
     */
    size: function(frm) {
        frm.events.update_variant_fields(frm);
    },

    /**
     * Called when material changes
     */
    material: function(frm) {
        frm.events.update_variant_fields(frm);
    },

    /**
     * Called when packaging changes
     */
    packaging: function(frm) {
        frm.events.update_variant_fields(frm);
    },

    /**
     * Called when price_adjustment changes
     */
    price_adjustment: function(frm) {
        frm.events.calculate_price(frm);
    },

    /**
     * Called when price_adjustment_type changes
     */
    price_adjustment_type: function(frm) {
        frm.events.calculate_price(frm);
    },

    /**
     * Called when variant_price changes
     */
    variant_price: function(frm) {
        // Validate price is not negative
        if (frm.doc.variant_price < 0) {
            frappe.msgprint(__('Price cannot be negative'));
            frm.set_value('variant_price', 0);
        }
    },

    /**
     * Called when variant_stock changes
     */
    variant_stock: function(frm) {
        // Update stock indicator
        frm.events.show_stock_indicator(frm);

        // Warn if negative and not allowed
        if (frm.doc.variant_stock < 0 && !frm.doc.allow_negative_stock) {
            frappe.msgprint(__('Stock quantity is negative. Enable "Allow Negative Stock" or correct the quantity.'));
        }
    },

    /**
     * Called when status changes
     */
    status: function(frm) {
        // If discontinuing, ensure not default
        if (frm.doc.status === 'Discontinued' && frm.doc.is_default) {
            frm.set_value('is_default', 0);
            frappe.msgprint(__('Default status removed from discontinued variant'));
        }
    },

    // =========================================================================
    // CUSTOM METHODS
    // =========================================================================

    /**
     * Add status action buttons
     */
    add_status_buttons: function(frm) {
        if (frm.is_new()) return;

        // Activate button (for Inactive variants)
        if (frm.doc.status === 'Inactive') {
            frm.add_custom_button(__('Activate'), function() {
                frappe.call({
                    method: 'tr_tradehub.doctype.product_variant.product_variant.activate_variant',
                    args: { variant_name: frm.doc.name },
                    callback: function(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));
        }

        // Deactivate button (for Active variants)
        if (frm.doc.status === 'Active') {
            frm.add_custom_button(__('Deactivate'), function() {
                frappe.call({
                    method: 'tr_tradehub.doctype.product_variant.product_variant.deactivate_variant',
                    args: { variant_name: frm.doc.name },
                    callback: function(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'orange'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));
        }

        // Discontinue button (for non-discontinued variants)
        if (frm.doc.status !== 'Discontinued') {
            frm.add_custom_button(__('Discontinue'), function() {
                frappe.confirm(
                    __('Are you sure you want to discontinue this variant? This action is permanent.'),
                    function() {
                        frappe.call({
                            method: 'tr_tradehub.doctype.product_variant.product_variant.discontinue_variant',
                            args: { variant_name: frm.doc.name },
                            callback: function(r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({
                                        message: r.message.message,
                                        indicator: 'red'
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }, __('Actions'));
        }

        // Set as Default button (for non-default active variants)
        if (!frm.doc.is_default && frm.doc.status === 'Active') {
            frm.add_custom_button(__('Set as Default'), function() {
                frappe.call({
                    method: 'tr_tradehub.doctype.product_variant.product_variant.set_default_variant',
                    args: { variant_name: frm.doc.name },
                    callback: function(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'blue'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));
        }

        // View Parent Product button
        frm.add_custom_button(__('View Parent Product'), function() {
            if (frm.doc.sku_product) {
                frappe.set_route('Form', 'SKU Product', frm.doc.sku_product);
            }
        }, __('Actions'));

        // Duplicate button
        frm.add_custom_button(__('Duplicate'), function() {
            frappe.new_doc('Product Variant', {
                sku_product: frm.doc.sku_product,
                color: frm.doc.color,
                material: frm.doc.material,
                packaging: frm.doc.packaging,
                price_adjustment: frm.doc.price_adjustment,
                price_adjustment_type: frm.doc.price_adjustment_type,
                allow_negative_stock: frm.doc.allow_negative_stock
            });
        }, __('Actions'));
    },

    /**
     * Setup dashboard with stats
     */
    setup_dashboard: function(frm) {
        if (frm.is_new()) return;

        // Add links section
        frm.dashboard.add_comment(__('Variant Details'), 'blue', true);
    },

    /**
     * Show stock availability indicator
     */
    show_stock_indicator: function(frm) {
        if (frm.is_new()) return;

        var stock = flt(frm.doc.variant_stock);
        var indicator = 'green';
        var message = __('In Stock') + ': ' + stock;

        if (!frm.doc.is_stock_item) {
            indicator = 'blue';
            message = __('Non-Stock Item');
        } else if (stock <= 0 && !frm.doc.allow_negative_stock) {
            indicator = 'red';
            message = __('Out of Stock');
        } else if (stock < 10) {
            indicator = 'orange';
            message = __('Low Stock') + ': ' + stock;
        }

        frm.dashboard.add_indicator(message, indicator);

        // Show default indicator if applicable
        if (frm.doc.is_default) {
            frm.dashboard.add_indicator(__('Default Variant'), 'blue');
        }
    },

    /**
     * Setup field filters
     */
    setup_filters: function(frm) {
        // Filter SKU products by tenant if tenant context exists
        frm.set_query('sku_product', function() {
            return {
                filters: {
                    'status': ['!=', 'Archive']
                }
            };
        });
    },

    /**
     * Refresh parent product fetch_from fields
     */
    refresh_parent_fields: function(frm) {
        if (!frm.doc.sku_product) {
            // Clear all fetch_from fields
            frm.set_value('product_name', '');
            frm.set_value('product_sku_code', '');
            frm.set_value('product_status', '');
            frm.set_value('seller', '');
            frm.set_value('seller_name', '');
            frm.set_value('tenant', '');
            frm.set_value('tenant_name', '');
            frm.set_value('currency', '');
            frm.set_value('stock_uom', '');
            frm.set_value('is_stock_item', 0);
            frm.set_value('weight_uom', '');
            frm.set_value('dimension_uom', '');
            return;
        }

        // Fetch parent product data to populate fetch_from fields
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'SKU Product',
                name: frm.doc.sku_product
            },
            callback: function(r) {
                if (r.message) {
                    var parent = r.message;
                    frm.set_value('product_name', parent.product_name || '');
                    frm.set_value('product_sku_code', parent.sku_code || '');
                    frm.set_value('product_status', parent.status || '');
                    frm.set_value('seller', parent.seller || '');
                    frm.set_value('seller_name', parent.seller_name || '');
                    frm.set_value('tenant', parent.tenant || '');
                    frm.set_value('tenant_name', parent.tenant_name || '');
                    frm.set_value('currency', parent.currency || '');
                    frm.set_value('stock_uom', parent.stock_uom || '');
                    frm.set_value('is_stock_item', parent.is_stock_item || 0);
                    frm.set_value('weight_uom', parent.weight_uom || '');
                    frm.set_value('dimension_uom', parent.dimension_uom || '');
                }
            }
        });
    },

    /**
     * Update variant code and name when attributes change
     */
    update_variant_fields: function(frm) {
        // Regenerate variant code and name if they haven't been manually set
        if (frm.is_new() || !frm.doc.variant_code) {
            frm.events.generate_variant_code(frm);
        }
        if (frm.is_new() || !frm.doc.variant_name) {
            frm.events.generate_variant_name(frm);
        }
    },

    /**
     * Generate variant code from parent SKU and attributes
     */
    generate_variant_code: function(frm) {
        if (!frm.doc.sku_product) return;

        var product_sku = frm.doc.product_sku_code || '';
        var parts = [product_sku];

        // Add attribute codes
        if (frm.doc.color) {
            parts.push(frm.events.sanitize_code_part(frm.doc.color.substring(0, 10)));
        }
        if (frm.doc.size) {
            parts.push(frm.events.sanitize_code_part(frm.doc.size.substring(0, 10)));
        }
        if (frm.doc.material) {
            parts.push(frm.events.sanitize_code_part(frm.doc.material.substring(0, 10)));
        }

        var code = parts.filter(function(p) { return p; }).join('-').toUpperCase();
        frm.set_value('variant_code', code);
    },

    /**
     * Generate variant name from parent product and attributes
     */
    generate_variant_name: function(frm) {
        if (!frm.doc.sku_product) return;

        var product_name = frm.doc.product_name || '';
        var attributes = [];

        if (frm.doc.color) attributes.push(frm.doc.color);
        if (frm.doc.size) attributes.push(frm.doc.size);
        if (frm.doc.material) attributes.push(frm.doc.material);
        if (frm.doc.packaging) attributes.push(frm.doc.packaging);

        var name = product_name;
        if (attributes.length > 0) {
            name += ' - ' + attributes.join(' / ');
        }

        frm.set_value('variant_name', name);
    },

    /**
     * Sanitize text for use in variant code
     */
    sanitize_code_part: function(text) {
        if (!text) return '';

        // Convert to uppercase and remove special characters
        var code = text.toUpperCase().trim();

        // Replace Turkish characters
        var turkishMap = {
            'C': 'C', 'S': 'S', 'G': 'G', 'I': 'I', 'O': 'O', 'U': 'U'
        };
        for (var tr in turkishMap) {
            code = code.replace(new RegExp(tr, 'g'), turkishMap[tr]);
        }

        // Keep only alphanumeric
        code = code.replace(/[^A-Z0-9]/g, '');

        return code;
    },

    /**
     * Calculate variant price from base price and adjustment
     */
    calculate_price: function(frm) {
        if (!frm.doc.sku_product) return;

        // Get base price from parent (already fetched)
        frappe.call({
            method: 'frappe.client.get_value',
            args: {
                doctype: 'SKU Product',
                filters: { name: frm.doc.sku_product },
                fieldname: ['base_price']
            },
            callback: function(r) {
                if (r.message) {
                    var base_price = flt(r.message.base_price) || 0;
                    var adjustment = flt(frm.doc.price_adjustment) || 0;

                    var final_price;
                    if (frm.doc.price_adjustment_type === 'Percentage') {
                        final_price = base_price * (1 + adjustment / 100);
                    } else {
                        final_price = base_price + adjustment;
                    }

                    // Only set if variant_price is 0 or this is a new form
                    if (frm.is_new() || flt(frm.doc.variant_price) === 0) {
                        frm.set_value('variant_price', Math.max(0, final_price));
                    }
                }
            }
        });
    }
});
