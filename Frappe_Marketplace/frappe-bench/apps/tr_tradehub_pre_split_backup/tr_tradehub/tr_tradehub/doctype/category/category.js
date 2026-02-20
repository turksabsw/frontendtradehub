// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Category', {
    setup: function(frm) {
        // Set up query filters in setup for proper initialization
        // This is critical - frm.set_query MUST be in setup or onload

        // Parent category filter - exclude self and children to prevent circular references
        frm.set_query('parent_category', function() {
            let filters = {
                'is_active': 1
            };

            // Exclude self from parent selection
            if (frm.doc.name) {
                filters['name'] = ['!=', frm.doc.name];
            }

            return {
                filters: filters
            };
        });

        // Attribute set filter
        frm.set_query('attribute_set', function() {
            return {
                filters: {
                    // Show all attribute sets, or filter by category if needed
                }
            };
        });

        // ERPNext Item Group filter
        frm.set_query('erpnext_item_group', function() {
            return {
                filters: {
                    'is_group': 0  // Only leaf item groups
                }
            };
        });
    },

    refresh: function(frm) {
        // Display category path
        if (!frm.is_new() && frm.doc.route) {
            frm.dashboard.set_headline(
                __('Path: /{0}', [frm.doc.route])
            );
        }

        // Add custom buttons
        if (!frm.is_new()) {
            frm.add_custom_button(__('View Listings'), function() {
                frappe.set_route('List', 'Listing', {'category': frm.doc.name});
            }, __('View'));

            frm.add_custom_button(__('View Child Categories'), function() {
                frappe.set_route('List', 'Category', {'parent_category': frm.doc.name});
            }, __('View'));

            frm.add_custom_button(__('Tree View'), function() {
                frappe.set_route('Tree', 'Category');
            }, __('View'));

            // Add child category button
            frm.add_custom_button(__('Add Child Category'), function() {
                frappe.new_doc('Category', {
                    'parent_category': frm.doc.name
                });
            });
        }

        // Show attribute set info
        if (frm.doc.attribute_set) {
            frappe.db.get_value('Attribute Set', frm.doc.attribute_set, 'attributes', function(r) {
                // Note: This returns the count via client.get if needed
            });
        }
    },

    parent_category: function(frm) {
        // When parent category changes, update route suggestion
        if (frm.doc.parent_category && frm.doc.category_name) {
            frappe.db.get_value('Category', frm.doc.parent_category, 'route', function(r) {
                if (r && r.route) {
                    let suggested_route = r.route + '/' + frappe.scrub(frm.doc.category_name);
                    if (!frm.doc.route || frm.doc.route === '') {
                        frm.set_value('route', suggested_route);
                    }
                }
            });
        }

        // Also inherit commission settings from parent if not set
        if (frm.doc.parent_category) {
            frappe.db.get_value('Category', frm.doc.parent_category,
                ['commission_rate', 'attribute_set'],
                function(r) {
                    if (r) {
                        // Auto-fill commission rate if not set
                        if (!frm.doc.commission_rate && r.commission_rate) {
                            frm.set_value('commission_rate', r.commission_rate);
                            frappe.show_alert({
                                message: __('Commission rate inherited from parent category'),
                                indicator: 'blue'
                            });
                        }

                        // Auto-fill attribute set if not set
                        if (!frm.doc.attribute_set && r.attribute_set) {
                            frm.set_value('attribute_set', r.attribute_set);
                            frappe.show_alert({
                                message: __('Attribute set inherited from parent category'),
                                indicator: 'blue'
                            });
                        }
                    }
                }
            );
        }
    },

    category_name: function(frm) {
        // Auto-generate route from category name
        if (frm.doc.category_name && !frm.doc.route) {
            let route = frappe.scrub(frm.doc.category_name);

            // If there's a parent, include parent's route
            if (frm.doc.parent_category) {
                frappe.db.get_value('Category', frm.doc.parent_category, 'route', function(r) {
                    if (r && r.route) {
                        frm.set_value('route', r.route + '/' + route);
                    } else {
                        frm.set_value('route', route);
                    }
                });
            } else {
                frm.set_value('route', route);
            }
        }

        // Auto-fill meta_title if not set
        if (frm.doc.category_name && !frm.doc.meta_title) {
            frm.set_value('meta_title', frm.doc.category_name);
        }
    },

    attribute_set: function(frm) {
        // When attribute set is selected, show info about included attributes
        if (frm.doc.attribute_set) {
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Attribute Set',
                    name: frm.doc.attribute_set
                },
                callback: function(r) {
                    if (r.message && r.message.attributes) {
                        let attr_count = r.message.attributes.length;
                        frappe.show_alert({
                            message: __('Attribute Set contains {0} attributes', [attr_count]),
                            indicator: 'green'
                        });
                    }
                }
            });
        }
    },

    is_active: function(frm) {
        // Warn about deactivating category with active listings
        if (!frm.doc.is_active && !frm.is_new()) {
            frappe.call({
                method: 'frappe.client.get_count',
                args: {
                    doctype: 'Listing',
                    filters: {
                        'category': frm.doc.name,
                        'status': 'Active'
                    }
                },
                callback: function(r) {
                    if (r.message && r.message > 0) {
                        frappe.msgprint({
                            title: __('Warning'),
                            message: __('This category has {0} active listings. Deactivating it may affect visibility.', [r.message]),
                            indicator: 'orange'
                        });
                    }
                }
            });
        }
    },

    validate: function(frm) {
        // Validate that category doesn't reference itself as parent
        if (frm.doc.parent_category === frm.doc.name) {
            frappe.throw(__('A category cannot be its own parent'));
        }

        // Validate commission settings
        if (frm.doc.min_commission && frm.doc.max_commission) {
            if (flt(frm.doc.min_commission) > flt(frm.doc.max_commission)) {
                frappe.throw(__('Minimum commission cannot be greater than maximum commission'));
            }
        }
    }
});
