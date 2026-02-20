// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Listing', {
    refresh: function(frm) {
        // =====================================================
        // Seller Field - Filter by Tenant
        // =====================================================
        // Only show sellers belonging to the selected tenant
        frm.set_query('seller', function() {
            if (frm.doc.tenant) {
                return {
                    filters: {
                        'tenant': frm.doc.tenant
                    }
                };
            }
            // If no tenant selected, show all sellers
            // (user should select tenant first, or seller will auto-populate tenant)
            return {};
        });

        // Make tenant field read-only when seller is selected
        // (since tenant is auto-populated from seller via fetch_from or validation)
        frm.set_df_property('tenant', 'read_only', frm.doc.seller ? 1 : 0);

        // =====================================================
        // Category Field - Filter Active Categories
        // =====================================================
        // Only show active categories
        frm.set_query('category', function() {
            return {
                filters: {
                    'is_active': 1
                }
            };
        });

        // =====================================================
        // Subcategory Field - Cascading Filter by Parent Category
        // =====================================================
        // Only show subcategories that belong to the selected category
        frm.set_query('subcategory', function() {
            let filters = {
                'is_active': 1
            };

            if (frm.doc.category) {
                filters['parent_category'] = frm.doc.category;
            }

            return {
                filters: filters
            };
        });

        // =====================================================
        // Attribute Set Field - Filter by Category
        // =====================================================
        // Filter attribute sets relevant to the selected category
        frm.set_query('attribute_set', function() {
            if (frm.doc.category) {
                return {
                    filters: {
                        'category': frm.doc.category
                    }
                };
            }
            return {};
        });

        // =====================================================
        // Variant Of Field - Filter by Same Seller
        // =====================================================
        // Only show parent listings from the same seller
        frm.set_query('variant_of', function() {
            let filters = {
                'has_variants': 1
            };

            if (frm.doc.seller) {
                filters['seller'] = frm.doc.seller;
            }

            if (frm.doc.tenant) {
                filters['tenant'] = frm.doc.tenant;
            }

            return {
                filters: filters
            };
        });
    },

    tenant: function(frm) {
        // When tenant changes, check if current seller belongs to new tenant
        // If not, clear the seller field
        if (frm.doc.seller) {
            if (frm.doc.tenant) {
                frappe.db.get_value('Seller Profile', frm.doc.seller, 'tenant', function(r) {
                    if (r && r.tenant !== frm.doc.tenant) {
                        // Seller doesn't belong to new tenant, clear it
                        frm.set_value('seller', null);
                        frappe.show_alert({
                            message: __('Seller cleared because it does not belong to the selected Tenant'),
                            indicator: 'orange'
                        });
                    }
                });
            } else {
                // Tenant was cleared, also clear seller for consistency
                frm.set_value('seller', null);
            }
        }
    },

    seller: function(frm) {
        // When seller changes, update read-only state of tenant field
        frm.set_df_property('tenant', 'read_only', frm.doc.seller ? 1 : 0);

        // If seller is selected, auto-populate tenant from seller
        if (frm.doc.seller) {
            frappe.db.get_value('Seller Profile', frm.doc.seller, 'tenant', function(r) {
                if (r && r.tenant) {
                    if (!frm.doc.tenant || frm.doc.tenant !== r.tenant) {
                        frm.set_value('tenant', r.tenant);
                    }
                }
            });
        } else {
            // If seller is cleared, allow tenant to be edited again
            frm.set_df_property('tenant', 'read_only', 0);
        }
    },

    category: function(frm) {
        // When category changes, handle cascading updates
        if (frm.doc.category) {
            // Auto-fetch attribute_set from category if not already set
            frappe.db.get_value('Category', frm.doc.category, 'attribute_set', function(r) {
                if (r && r.attribute_set) {
                    // Only auto-fill if attribute_set is empty or different category
                    if (!frm.doc.attribute_set) {
                        frm.set_value('attribute_set', r.attribute_set);
                        frappe.show_alert({
                            message: __('Attribute Set auto-filled from Category'),
                            indicator: 'green'
                        });
                    }
                }
            });

            // Check if current subcategory belongs to new category
            if (frm.doc.subcategory) {
                frappe.db.get_value('Category', frm.doc.subcategory, 'parent_category', function(r) {
                    if (r && r.parent_category !== frm.doc.category) {
                        frm.set_value('subcategory', null);
                        frappe.show_alert({
                            message: __('Subcategory cleared because it does not belong to the selected Category'),
                            indicator: 'blue'
                        });
                    }
                });
            }

            // Check if current attribute_set matches new category
            if (frm.doc.attribute_set) {
                frappe.db.get_value('Attribute Set', frm.doc.attribute_set, 'category', function(r) {
                    if (r && r.category && r.category !== frm.doc.category) {
                        frm.set_value('attribute_set', null);
                        frappe.show_alert({
                            message: __('Attribute Set cleared because it does not belong to the selected Category'),
                            indicator: 'blue'
                        });
                        // Try to auto-fill from new category
                        frappe.db.get_value('Category', frm.doc.category, 'attribute_set', function(r2) {
                            if (r2 && r2.attribute_set) {
                                frm.set_value('attribute_set', r2.attribute_set);
                            }
                        });
                    }
                });
            }

            // Load attributes child table based on category's attribute_set
            load_category_attributes(frm);
        } else {
            // Category was cleared, clear dependent fields
            frm.set_value('subcategory', null);
            frm.set_value('attribute_set', null);
        }
    },

    attribute_set: function(frm) {
        // When attribute_set changes, load attributes for the listing
        if (frm.doc.attribute_set) {
            load_attribute_set_attributes(frm);
        }
    }
});

/**
 * Load attributes from category's attribute_set into the listing attributes child table
 */
function load_category_attributes(frm) {
    if (!frm.doc.category) return;

    frappe.db.get_value('Category', frm.doc.category, 'attribute_set', function(r) {
        if (r && r.attribute_set) {
            // Get attributes from the attribute set
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Attribute Set',
                    name: r.attribute_set
                },
                callback: function(response) {
                    if (response.message && response.message.attributes) {
                        // Only populate if attributes table is empty
                        if (!frm.doc.attributes || frm.doc.attributes.length === 0) {
                            populate_attributes_table(frm, response.message.attributes);
                        }
                    }
                }
            });
        }
    });
}

/**
 * Load attributes from selected attribute_set
 */
function load_attribute_set_attributes(frm) {
    if (!frm.doc.attribute_set) return;

    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Attribute Set',
            name: frm.doc.attribute_set
        },
        callback: function(response) {
            if (response.message && response.message.attributes) {
                // Ask user if they want to replace existing attributes
                if (frm.doc.attributes && frm.doc.attributes.length > 0) {
                    frappe.confirm(
                        __('Replace existing attributes with attributes from the selected Attribute Set?'),
                        function() {
                            // Yes - replace
                            frm.clear_table('attributes');
                            populate_attributes_table(frm, response.message.attributes);
                        },
                        function() {
                            // No - keep existing
                        }
                    );
                } else {
                    populate_attributes_table(frm, response.message.attributes);
                }
            }
        }
    });
}

/**
 * Populate the attributes child table from attribute set items
 */
function populate_attributes_table(frm, attribute_items) {
    attribute_items.forEach(function(item) {
        let row = frm.add_child('attributes');
        row.attribute = item.attribute;
        // Fetch additional attribute info
        frappe.db.get_value('Attribute', item.attribute,
            ['attribute_label', 'attribute_type', 'is_required'],
            function(r) {
                if (r) {
                    frappe.model.set_value(row.doctype, row.name, 'attribute_label', r.attribute_label);
                    frappe.model.set_value(row.doctype, row.name, 'attribute_type', r.attribute_type);
                    frappe.model.set_value(row.doctype, row.name, 'is_required', r.is_required);
                }
            }
        );
    });
    frm.refresh_field('attributes');

    if (attribute_items.length > 0) {
        frappe.show_alert({
            message: __('Loaded {0} attributes from Attribute Set', [attribute_items.length]),
            indicator: 'green'
        });
    }
}
