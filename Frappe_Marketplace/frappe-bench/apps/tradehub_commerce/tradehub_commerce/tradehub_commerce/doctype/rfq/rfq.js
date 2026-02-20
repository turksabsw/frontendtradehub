// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('RFQ', {
    refresh: function(frm) {
        // Update views remaining display
        frm.trigger('calculate_views_remaining');

        // Add viewing stats indicator
        if (!frm.is_new()) {
            frm.trigger('show_viewing_stats');
        }

        // Add custom buttons based on status
        if (!frm.is_new() && frm.doc.status === 'Draft') {
            frm.add_custom_button(__('Open for Quotes'), function() {
                frm.set_value('status', 'Open');
                frm.save();
            }, __('Actions'));
        }

        if (!frm.is_new() && ['Open', 'In Progress', 'Quotes Received'].includes(frm.doc.status)) {
            frm.add_custom_button(__('Close RFQ'), function() {
                frappe.confirm(
                    __('Are you sure you want to close this RFQ?'),
                    function() {
                        frm.set_value('status', 'Closed');
                        frm.save();
                    }
                );
            }, __('Actions'));
        }

        // Add button to refresh quote statistics
        if (!frm.is_new() && frm.doc.quote_count > 0) {
            frm.add_custom_button(__('Refresh Quote Statistics'), function() {
                frm.call({
                    doc: frm.doc,
                    method: 'update_quote_statistics',
                    callback: function(r) {
                        frm.reload_doc();
                    }
                });
            }, __('Actions'));
        }

        // Show warning if view limit reached
        if (frm.doc.is_view_limited && frm.doc.max_views > 0 && frm.doc.current_views >= frm.doc.max_views) {
            frm.dashboard.add_comment(
                __('Maximum viewing limit reached. No new sellers can view this RFQ.'),
                'yellow',
                true
            );
        }

        // Show deadline warning
        if (frm.doc.submission_deadline) {
            const deadline = frappe.datetime.str_to_obj(frm.doc.submission_deadline);
            const now = new Date();
            const diff_days = Math.ceil((deadline - now) / (1000 * 60 * 60 * 24));

            if (diff_days < 0 && ['Open', 'In Progress'].includes(frm.doc.status)) {
                frm.dashboard.add_comment(
                    __('Submission deadline has passed. Consider closing this RFQ.'),
                    'red',
                    true
                );
            } else if (diff_days <= 3 && diff_days > 0) {
                frm.dashboard.add_comment(
                    __('Submission deadline is in {0} days.', [diff_days]),
                    'orange',
                    true
                );
            }
        }
    },

    is_view_limited: function(frm) {
        frm.trigger('calculate_views_remaining');
        frm.trigger('toggle_viewing_fields');
    },

    max_views: function(frm) {
        frm.trigger('calculate_views_remaining');
    },

    calculate_views_remaining: function(frm) {
        if (frm.doc.is_view_limited && frm.doc.max_views > 0) {
            const remaining = Math.max(0, frm.doc.max_views - (frm.doc.current_views || 0));
            frm.set_value('views_remaining', remaining);
        } else {
            frm.set_value('views_remaining', 0);
        }
    },

    toggle_viewing_fields: function(frm) {
        const is_limited = frm.doc.is_view_limited;
        frm.set_df_property('max_views', 'reqd', is_limited ? 1 : 0);
    },

    show_viewing_stats: function(frm) {
        if (frm.doc.is_view_limited && frm.doc.max_views > 0) {
            const percent_used = Math.round((frm.doc.current_views / frm.doc.max_views) * 100);
            let color = 'blue';
            if (percent_used >= 90) {
                color = 'red';
            } else if (percent_used >= 70) {
                color = 'orange';
            } else if (percent_used >= 50) {
                color = 'yellow';
            }

            frm.dashboard.add_indicator(
                __('Views: {0}/{1} ({2}%)', [frm.doc.current_views, frm.doc.max_views, percent_used]),
                color
            );
        }
    },

    organization: function(frm) {
        // Auto-populate tenant from organization
        if (frm.doc.organization) {
            frappe.db.get_value('Organization', frm.doc.organization, 'tenant', function(r) {
                if (r && r.tenant) {
                    frm.set_value('tenant', r.tenant);
                    frm.set_df_property('tenant', 'read_only', 1);
                }
            });
        } else {
            frm.set_value('tenant', '');
            frm.set_df_property('tenant', 'read_only', 0);
        }
    },

    require_all_items: function(frm) {
        // If require all items is checked, uncheck allow partial quotes
        if (frm.doc.require_all_items) {
            frm.set_value('allow_partial_quotes', 0);
        }
    },

    allow_partial_quotes: function(frm) {
        // If allow partial quotes is checked, uncheck require all items
        if (frm.doc.allow_partial_quotes) {
            frm.set_value('require_all_items', 0);
        }
    },

    before_save: function(frm) {
        // Set created_date if new
        if (frm.is_new() && !frm.doc.created_date) {
            frm.set_value('created_date', frappe.datetime.get_today());
        }
    }
});

// RFQ Item child table events
frappe.ui.form.on('RFQ Item', {
    listing: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.listing) {
            frappe.db.get_value('Listing', row.listing, ['title', 'category', 'selling_price', 'currency', 'stock_uom'], function(r) {
                if (r) {
                    frappe.model.set_value(cdt, cdn, 'item_name', r.title || '');
                    frappe.model.set_value(cdt, cdn, 'category', r.category || '');
                    frappe.model.set_value(cdt, cdn, 'target_price', r.selling_price || 0);
                    frappe.model.set_value(cdt, cdn, 'currency', r.currency || 'TRY');
                    frappe.model.set_value(cdt, cdn, 'uom', r.stock_uom || 'Nos');
                }
            });
        }
    },

    qty: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.qty <= 0) {
            frappe.model.set_value(cdt, cdn, 'qty', 1);
            frappe.msgprint(__('Quantity must be greater than zero'));
        }
    }
});
