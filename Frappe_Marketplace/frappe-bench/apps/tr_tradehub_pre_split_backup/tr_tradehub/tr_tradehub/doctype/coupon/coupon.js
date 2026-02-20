// Copyright (c) 2026, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Coupon', {
    refresh: function(frm) {
        // Set up form styling and indicators
        frm.trigger('set_status_indicator');
        frm.trigger('add_action_buttons');
        frm.trigger('setup_bogo_preview');

        // Auto-uppercase coupon code on blur
        if (frm.fields_dict.coupon_code) {
            frm.fields_dict.coupon_code.$input.on('blur', function() {
                let val = $(this).val();
                if (val) {
                    frm.set_value('coupon_code', val.toUpperCase());
                }
            });
        }
    },

    discount_type: function(frm) {
        // Update discount_value label based on type
        frm.trigger('update_discount_labels');
        frm.trigger('toggle_bogo_sections');
    },

    onload: function(frm) {
        // Set up query filters for related fields
        frm.set_query('seller', function() {
            return {
                filters: {
                    'status': 'Active'
                }
            };
        });

        frm.set_query('campaign', function() {
            return {
                filters: {
                    'status': ['in', ['Active', 'Scheduled']]
                }
            };
        });

        // Initial setup
        frm.trigger('update_discount_labels');
        frm.trigger('toggle_bogo_sections');
    },

    set_status_indicator: function(frm) {
        // Add visual indicator based on status
        let status = frm.doc.status;
        let indicator_color = {
            'Draft': 'orange',
            'Active': 'green',
            'Expired': 'grey',
            'Used Up': 'red',
            'Deactivated': 'darkgrey'
        };

        if (indicator_color[status]) {
            frm.page.set_indicator(status, indicator_color[status]);
        }
    },

    add_action_buttons: function(frm) {
        if (!frm.is_new()) {
            // Add "Deactivate" button if active
            if (frm.doc.is_active && frm.doc.status === 'Active') {
                frm.add_custom_button(__('Deactivate'), function() {
                    frappe.confirm(
                        __('Are you sure you want to deactivate this coupon?'),
                        function() {
                            frm.set_value('is_active', 0);
                            frm.save();
                        }
                    );
                }, __('Actions'));
            }

            // Add "Activate" button if deactivated
            if (!frm.doc.is_active) {
                frm.add_custom_button(__('Activate'), function() {
                    frm.set_value('is_active', 1);
                    frm.save();
                }, __('Actions'));
            }

            // Add "Duplicate" button
            frm.add_custom_button(__('Duplicate'), function() {
                frappe.prompt([
                    {
                        fieldname: 'new_code',
                        fieldtype: 'Data',
                        label: __('New Coupon Code'),
                        reqd: 1
                    }
                ], function(values) {
                    frappe.call({
                        method: 'frappe.client.insert',
                        args: {
                            doc: {
                                doctype: 'Coupon',
                                coupon_code: values.new_code.toUpperCase(),
                                title: frm.doc.title + ' (Copy)',
                                discount_type: frm.doc.discount_type,
                                discount_value: frm.doc.discount_value,
                                max_discount_amount: frm.doc.max_discount_amount,
                                min_order_amount: frm.doc.min_order_amount,
                                valid_from: frm.doc.valid_from,
                                valid_until: frm.doc.valid_until,
                                usage_limit: frm.doc.usage_limit,
                                usage_per_customer: frm.doc.usage_per_customer,
                                seller: frm.doc.seller,
                                applies_to: frm.doc.applies_to,
                                buy_quantity: frm.doc.buy_quantity,
                                get_quantity: frm.doc.get_quantity,
                                get_discount_percent: frm.doc.get_discount_percent,
                                same_product_only: frm.doc.same_product_only,
                                is_active: 1
                            }
                        },
                        callback: function(r) {
                            if (r.message) {
                                frappe.set_route('Form', 'Coupon', r.message.name);
                            }
                        }
                    });
                }, __('Duplicate Coupon'), __('Create'));
            }, __('Actions'));

            // Add usage statistics button
            frm.add_custom_button(__('View Usage'), function() {
                frappe.set_route('List', 'Marketplace Order', {
                    'coupon_code': frm.doc.coupon_code
                });
            }, __('Actions'));
        }
    },

    update_discount_labels: function(frm) {
        let discount_type = frm.doc.discount_type;

        if (discount_type === 'Percentage') {
            frm.set_df_property('discount_value', 'label', __('Discount Percentage'));
            frm.set_df_property('discount_value', 'description', __('Percentage to discount (0-100)'));
        } else if (discount_type === 'Fixed Amount') {
            frm.set_df_property('discount_value', 'label', __('Discount Amount'));
            frm.set_df_property('discount_value', 'description', __('Fixed amount to discount'));
        } else if (discount_type === 'Free Shipping') {
            frm.set_df_property('discount_value', 'label', __('Discount Value'));
            frm.set_df_property('discount_value', 'description', __('Not used for Free Shipping'));
        } else if (discount_type === 'Buy X Get Y') {
            frm.set_df_property('discount_value', 'label', __('Discount Value'));
            frm.set_df_property('discount_value', 'description', __('Not used for BOGO - configure in BOGO section'));
        }
    },

    toggle_bogo_sections: function(frm) {
        let is_bogo = frm.doc.discount_type === 'Buy X Get Y';

        // Toggle BOGO sections visibility
        frm.toggle_display('bogo_section', is_bogo);
        frm.toggle_display('buy_quantity', is_bogo);
        frm.toggle_display('get_quantity', is_bogo);
        frm.toggle_display('get_discount_percent', is_bogo);
        frm.toggle_display('same_product_only', is_bogo);

        // Toggle BOGO product section based on same_product_only
        let show_product_section = is_bogo && !frm.doc.same_product_only;
        frm.toggle_display('bogo_product_section', show_product_section);
        frm.toggle_display('bogo_buy_products', show_product_section);
        frm.toggle_display('bogo_get_products', show_product_section);
        frm.toggle_display('bogo_categories', is_bogo);

        // Hide discount_value for BOGO (it's not used)
        if (is_bogo) {
            frm.set_df_property('discount_value', 'hidden', 1);
        } else {
            frm.set_df_property('discount_value', 'hidden', 0);
        }
    },

    same_product_only: function(frm) {
        frm.trigger('toggle_bogo_sections');
    },

    setup_bogo_preview: function(frm) {
        if (frm.doc.discount_type === 'Buy X Get Y' && !frm.is_new()) {
            // Add BOGO preview section in the form
            let buy_qty = frm.doc.buy_quantity || 1;
            let get_qty = frm.doc.get_quantity || 1;
            let get_pct = frm.doc.get_discount_percent || 100;

            let promo_text = '';
            if (get_pct >= 100) {
                promo_text = __('Buy {0}, Get {1} FREE', [buy_qty, get_qty]);
            } else {
                promo_text = __('Buy {0}, Get {1} at {2}% off', [buy_qty, get_qty, get_pct]);
            }

            // Show the promotion text as an intro
            frm.set_intro(promo_text, 'green');
        }
    },

    buy_quantity: function(frm) {
        frm.trigger('setup_bogo_preview');
    },

    get_quantity: function(frm) {
        frm.trigger('setup_bogo_preview');
    },

    get_discount_percent: function(frm) {
        frm.trigger('setup_bogo_preview');
    },

    // Auto-populate seller fields
    seller: function(frm) {
        if (frm.doc.seller) {
            frappe.db.get_value('Seller Profile', frm.doc.seller, ['seller_name', 'tenant'], function(r) {
                if (r) {
                    frm.set_value('seller_name', r.seller_name);
                    frm.set_value('tenant', r.tenant);
                }
            });
        } else {
            frm.set_value('seller_name', '');
            frm.set_value('tenant', '');
        }
    },

    // Validate coupon code format
    coupon_code: function(frm) {
        if (frm.doc.coupon_code) {
            let code = frm.doc.coupon_code.toUpperCase().replace(/[^A-Z0-9_-]/g, '');
            if (code !== frm.doc.coupon_code) {
                frm.set_value('coupon_code', code);
                frappe.show_alert({
                    message: __('Coupon code formatted: Only uppercase letters, numbers, underscores, and hyphens allowed'),
                    indicator: 'orange'
                }, 3);
            }
        }
    }
});

// Child table handlers for BOGO products
frappe.ui.form.on('Coupon Product Item', {
    product: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.product) {
            // Fetch product details
            frappe.db.get_value('Listing', row.product, ['listing_title', 'selling_price'], function(r) {
                if (r) {
                    frappe.model.set_value(cdt, cdn, 'product_name', r.listing_title);
                }
            });
        }
    }
});

// Child table handlers for BOGO categories
frappe.ui.form.on('Coupon Category Item', {
    category: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.category) {
            // Fetch category details
            frappe.db.get_value('Category', row.category, 'category_name', function(r) {
                if (r) {
                    frappe.model.set_value(cdt, cdn, 'category_name', r.category_name);
                }
            });
        }
    }
});
