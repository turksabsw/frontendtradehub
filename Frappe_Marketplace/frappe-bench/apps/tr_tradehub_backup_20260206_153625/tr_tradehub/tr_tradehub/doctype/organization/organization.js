// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Organization', {
    refresh: function(frm) {
        // Set up query filter for tenant dropdown
        // Only show active tenants that the user has permission to access
        frm.set_query('tenant', function() {
            return {
                filters: {
                    'status': 'Active'
                }
            };
        });

        // Add indicator for tenant-related warnings
        if (frm.doc.tenant && !frm.is_new()) {
            // Check if organization has linked seller profiles
            frappe.db.count('Seller Profile', {
                filters: { 'organization': frm.doc.name }
            }).then(count => {
                if (count > 0) {
                    frm.dashboard.add_comment(
                        __('This organization has {0} linked seller profile(s). Changing the tenant is not allowed.', [count]),
                        'blue',
                        true
                    );
                }
            });
        }
    },

    tenant: function(frm) {
        // When tenant changes on an existing organization, warn the user
        // The server-side validation in organization.py will prevent invalid changes
        if (!frm.is_new() && frm.doc.__onload && frm.doc.__onload.original_tenant) {
            if (frm.doc.tenant !== frm.doc.__onload.original_tenant) {
                // Check if there are linked seller profiles
                frappe.db.count('Seller Profile', {
                    filters: { 'organization': frm.doc.name }
                }).then(count => {
                    if (count > 0) {
                        frappe.show_alert({
                            message: __('Warning: This organization has {0} linked seller profile(s). Tenant change will be blocked on save.', [count]),
                            indicator: 'orange'
                        });
                    }
                });
            }
        }
    },

    onload: function(frm) {
        // Store original tenant value for change detection
        if (!frm.is_new() && frm.doc.tenant) {
            frm.doc.__onload = frm.doc.__onload || {};
            frm.doc.__onload.original_tenant = frm.doc.tenant;
        }
    },

    validate: function(frm) {
        // Client-side validation: Ensure tenant is selected
        if (!frm.doc.tenant) {
            frappe.validated = false;
            frappe.throw(__('Tenant is required for data isolation. Please select a Tenant.'));
        }
    }
});
