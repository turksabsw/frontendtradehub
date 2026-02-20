// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Seller KPI', {
    refresh: function(frm) {
        // Ensure tenant field is read-only when seller is set
        if (frm.doc.seller) {
            frm.set_df_property('tenant', 'read_only', 1);
        }

        // Add Calculate KPI button for draft records
        if (frm.doc.docstatus === 0 && frm.doc.status === 'Draft') {
            frm.add_custom_button(__('Calculate KPI'), function() {
                frm.call({
                    method: 'calculate_kpi',
                    doc: frm.doc,
                    callback: function(r) {
                        if (!r.exc) {
                            frm.reload_doc();
                            frappe.show_alert({
                                message: __('KPI calculation completed'),
                                indicator: 'green'
                            });
                        }
                    }
                });
            }, __('Actions'));
        }
    },

    seller: function(frm) {
        // When seller is selected, fetch tenant from seller profile
        if (frm.doc.seller) {
            frappe.db.get_value('Seller Profile', frm.doc.seller, ['tenant', 'seller_name'], function(r) {
                if (r) {
                    if (r.tenant) {
                        frm.set_value('tenant', r.tenant);
                    }
                    if (r.seller_name) {
                        frm.set_value('seller_name', r.seller_name);
                    }
                    // Make tenant read-only after auto-populating
                    frm.set_df_property('tenant', 'read_only', 1);
                }
            });
        } else {
            // Clear tenant when seller is cleared
            frm.set_value('tenant', '');
            frm.set_value('seller_name', '');
            frm.set_df_property('tenant', 'read_only', 0);
        }
    },

    kpi_period: function(frm) {
        // Auto-set date range based on selected period
        if (frm.doc.kpi_period) {
            let today = frappe.datetime.get_today();
            let start_date, end_date;

            switch(frm.doc.kpi_period) {
                case 'Daily':
                    start_date = today;
                    end_date = today;
                    break;
                case 'Weekly':
                    start_date = frappe.datetime.add_days(today, -7);
                    end_date = today;
                    break;
                case 'Monthly':
                    start_date = frappe.datetime.add_months(today, -1);
                    end_date = today;
                    break;
                case 'Quarterly':
                    start_date = frappe.datetime.add_months(today, -3);
                    end_date = today;
                    break;
                case 'Yearly':
                    start_date = frappe.datetime.add_months(today, -12);
                    end_date = today;
                    break;
            }

            if (start_date && end_date) {
                frm.set_value('start_date', start_date);
                frm.set_value('end_date', end_date);
            }
        }
    }
});
