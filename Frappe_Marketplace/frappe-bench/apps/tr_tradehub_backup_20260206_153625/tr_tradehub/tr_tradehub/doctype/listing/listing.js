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
        // When category changes, clear subcategory and attribute_set
        // because they may not be valid for the new category
        if (frm.doc.subcategory) {
            frappe.db.get_value('Category', frm.doc.subcategory, 'parent_category', function(r) {
                if (r && r.parent_category !== frm.doc.category) {
                    frm.set_value('subcategory', null);
                    if (frm.doc.category) {
                        frappe.show_alert({
                            message: __('Subcategory cleared because it does not belong to the selected Category'),
                            indicator: 'blue'
                        });
                    }
                }
            });
        }

        // Also clear attribute_set if it doesn't match new category
        if (frm.doc.attribute_set) {
            frappe.db.get_value('Attribute Set', frm.doc.attribute_set, 'category', function(r) {
                if (r && r.category !== frm.doc.category) {
                    frm.set_value('attribute_set', null);
                    if (frm.doc.category) {
                        frappe.show_alert({
                            message: __('Attribute Set cleared because it does not belong to the selected Category'),
                            indicator: 'blue'
                        });
                    }
                }
            });
        }
    }
});
