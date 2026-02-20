// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Seller Profile', {
    refresh: function(frm) {
        // Set up query filter for organization dropdown
        // Only show organizations belonging to the selected tenant
        frm.set_query('organization', function() {
            if (frm.doc.tenant) {
                return {
                    filters: {
                        'tenant': frm.doc.tenant
                    }
                };
            }
            // If no tenant selected, return empty to prevent selection
            // User should select tenant first, or organization will auto-populate tenant
            return {};
        });

        // Make tenant field read-only when organization is selected
        // (since tenant is auto-populated from organization via fetch_from)
        frm.set_df_property('tenant', 'read_only', frm.doc.organization ? 1 : 0);

        // =====================================================
        // Address Item Child Table - Cascading Dropdown Filters
        // =====================================================

        // City filter - show only active cities
        frm.set_query('city', 'addresses', function(doc, cdt, cdn) {
            return {
                filters: {
                    is_active: 1
                }
            };
        });

        // District filter - show only districts belonging to selected city
        frm.set_query('district', 'addresses', function(doc, cdt, cdn) {
            let row = locals[cdt][cdn];
            return {
                filters: {
                    city: row.city || '',
                    is_active: 1
                }
            };
        });

        // Neighborhood filter - show only neighborhoods belonging to selected district
        frm.set_query('neighborhood', 'addresses', function(doc, cdt, cdn) {
            let row = locals[cdt][cdn];
            return {
                filters: {
                    district: row.district || '',
                    is_active: 1
                }
            };
        });

        // =====================================================
        // Location Item Child Table - Cascading Dropdown Filters
        // =====================================================

        // City filter - show only active cities
        frm.set_query('city', 'locations', function(doc, cdt, cdn) {
            return {
                filters: {
                    is_active: 1
                }
            };
        });

        // District filter - show only districts belonging to selected city
        frm.set_query('district', 'locations', function(doc, cdt, cdn) {
            let row = locals[cdt][cdn];
            return {
                filters: {
                    city: row.city || '',
                    is_active: 1
                }
            };
        });

        // Neighborhood filter - show only neighborhoods belonging to selected district
        frm.set_query('neighborhood', 'locations', function(doc, cdt, cdn) {
            let row = locals[cdt][cdn];
            return {
                filters: {
                    district: row.district || '',
                    is_active: 1
                }
            };
        });
    },

    tenant: function(frm) {
        // When tenant changes, clear the organization field
        // because the previously selected organization may not belong to the new tenant
        if (frm.doc.organization) {
            // Check if current organization belongs to new tenant
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
    },

    organization: function(frm) {
        // When organization changes, update read-only state of tenant field
        frm.set_df_property('tenant', 'read_only', frm.doc.organization ? 1 : 0);

        // If organization is cleared, allow tenant to be edited again
        if (!frm.doc.organization) {
            frm.set_df_property('tenant', 'read_only', 0);
        }
    }
});

// =====================================================
// Address Item Child Table - Cascading Clear on Change
// =====================================================

frappe.ui.form.on('Address Item', {
    city: function(frm, cdt, cdn) {
        // When city changes, clear district and neighborhood
        // because they may not belong to the new city
        let row = locals[cdt][cdn];
        if (row.district || row.neighborhood) {
            frappe.model.set_value(cdt, cdn, 'district', '');
            frappe.model.set_value(cdt, cdn, 'district_name', '');
            frappe.model.set_value(cdt, cdn, 'neighborhood', '');
            frappe.model.set_value(cdt, cdn, 'neighborhood_name', '');

            if (row.city) {
                frappe.show_alert({
                    message: __('District and Neighborhood cleared due to city change'),
                    indicator: 'blue'
                });
            }
        }
    },

    district: function(frm, cdt, cdn) {
        // When district changes, clear neighborhood
        // because it may not belong to the new district
        let row = locals[cdt][cdn];
        if (row.neighborhood) {
            frappe.model.set_value(cdt, cdn, 'neighborhood', '');
            frappe.model.set_value(cdt, cdn, 'neighborhood_name', '');

            if (row.district) {
                frappe.show_alert({
                    message: __('Neighborhood cleared due to district change'),
                    indicator: 'blue'
                });
            }
        }
    }
});

// =====================================================
// Location Item Child Table - Cascading Clear on Change
// =====================================================

frappe.ui.form.on('Location Item', {
    city: function(frm, cdt, cdn) {
        // When city changes, clear district and neighborhood
        // because they may not belong to the new city
        let row = locals[cdt][cdn];
        if (row.district || row.neighborhood) {
            frappe.model.set_value(cdt, cdn, 'district', '');
            frappe.model.set_value(cdt, cdn, 'district_name', '');
            frappe.model.set_value(cdt, cdn, 'neighborhood', '');
            frappe.model.set_value(cdt, cdn, 'neighborhood_name', '');

            if (row.city) {
                frappe.show_alert({
                    message: __('District and Neighborhood cleared due to city change'),
                    indicator: 'blue'
                });
            }
        }
    },

    district: function(frm, cdt, cdn) {
        // When district changes, clear neighborhood
        // because it may not belong to the new district
        let row = locals[cdt][cdn];
        if (row.neighborhood) {
            frappe.model.set_value(cdt, cdn, 'neighborhood', '');
            frappe.model.set_value(cdt, cdn, 'neighborhood_name', '');

            if (row.district) {
                frappe.show_alert({
                    message: __('Neighborhood cleared due to district change'),
                    indicator: 'blue'
                });
            }
        }
    }
});
