// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('RFQ Quote', {
    setup: function(frm) {
        // Set up the critical filter for RFQ Quote Items
        // This ensures quote items can ONLY be selected from the parent RFQ
        setup_rfq_item_filter(frm);
    },

    refresh: function(frm) {
        // Re-apply filter on refresh
        setup_rfq_item_filter(frm);

        // Show status indicator
        update_status_indicator(frm);

        // Add action buttons based on status
        add_action_buttons(frm);

        // Show validation messages
        if (!frm.is_new() && frm.doc.rfq) {
            validate_rfq_deadline(frm);
        }

        // Make tenant read-only when seller is set
        if (frm.doc.seller) {
            frm.set_df_property('tenant', 'read_only', 1);
        }
    },

    rfq: function(frm) {
        // When RFQ changes, re-apply the item filter
        setup_rfq_item_filter(frm);

        // Clear existing items if RFQ changes (to prevent invalid items)
        if (frm.doc.items && frm.doc.items.length > 0) {
            frappe.confirm(
                __('Changing the RFQ will clear existing quote items. Continue?'),
                function() {
                    frm.clear_table('items');
                    frm.refresh_field('items');
                    show_available_rfq_items(frm);
                },
                function() {
                    // Revert RFQ change
                    frm.set_value('rfq', frm.doc.__last_rfq || '');
                }
            );
        } else if (frm.doc.rfq) {
            show_available_rfq_items(frm);
        }

        // Store the current RFQ for revert purposes
        frm.doc.__last_rfq = frm.doc.rfq;

        // Get RFQ currency and set it
        if (frm.doc.rfq) {
            frappe.db.get_value('RFQ', frm.doc.rfq, 'currency', function(r) {
                if (r && r.currency) {
                    frm.set_value('currency', r.currency);
                }
            });
        }
    },

    seller: function(frm) {
        // Auto-populate tenant when seller is selected
        if (frm.doc.seller) {
            frappe.db.get_value('Seller Profile', frm.doc.seller, ['tenant', 'seller_name'], function(r) {
                if (r) {
                    if (r.tenant) {
                        frm.set_value('tenant', r.tenant);
                    }
                    frm.set_df_property('tenant', 'read_only', 1);
                }
            });
        } else {
            frm.set_value('tenant', '');
            frm.set_df_property('tenant', 'read_only', 0);
        }
    },

    discount_amount: function(frm) {
        // Recalculate final amount when discount changes
        calculate_final_amount(frm);
    },

    before_save: function(frm) {
        // Recalculate totals before save
        calculate_totals(frm);
    }
});

// RFQ Quote Item child table events
frappe.ui.form.on('RFQ Quote Item', {
    rfq_item: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.rfq_item) {
            // Fetch item details from the RFQ Item
            frappe.db.get_value('RFQ Item', row.rfq_item,
                ['item_name', 'item_description', 'qty', 'uom', 'target_price', 'currency'],
                function(r) {
                    if (r) {
                        frappe.model.set_value(cdt, cdn, 'item_name', r.item_name || '');
                        frappe.model.set_value(cdt, cdn, 'item_description', r.item_description || '');
                        frappe.model.set_value(cdt, cdn, 'qty', r.qty || 1);
                        frappe.model.set_value(cdt, cdn, 'uom', r.uom || 'Nos');
                        frappe.model.set_value(cdt, cdn, 'currency', r.currency || frm.doc.currency || 'TRY');

                        // Set target price as initial unit price suggestion
                        if (r.target_price && !row.unit_price) {
                            frappe.model.set_value(cdt, cdn, 'unit_price', r.target_price);
                        }
                    }
                }
            );
        }
    },

    qty: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.qty <= 0) {
            frappe.model.set_value(cdt, cdn, 'qty', 1);
            frappe.msgprint(__('Quantity must be greater than zero'));
        }
        calculate_item_total(frm, cdt, cdn);
    },

    unit_price: function(frm, cdt, cdn) {
        calculate_item_total(frm, cdt, cdn);
    },

    items_remove: function(frm) {
        // Recalculate totals when items are removed
        calculate_totals(frm);
    }
});

/**
 * CRITICAL: Set up filter for RFQ Item selection
 * This ensures quote items can ONLY be selected from the parent RFQ's items
 */
function setup_rfq_item_filter(frm) {
    // Filter RFQ Item link field in the child table to only show items from the selected RFQ
    frm.set_query('rfq_item', 'items', function(doc, cdt, cdn) {
        if (!doc.rfq) {
            frappe.msgprint({
                title: __('Select RFQ First'),
                message: __('Please select an RFQ before adding items.'),
                indicator: 'orange'
            });
            return {
                filters: {
                    // Return impossible filter to prevent selection
                    name: 'NONE'
                }
            };
        }

        return {
            filters: {
                parent: doc.rfq,
                parenttype: 'RFQ'
            }
        };
    });
}

/**
 * Show available RFQ items in a dialog for easy selection
 */
function show_available_rfq_items(frm) {
    if (!frm.doc.rfq) return;

    frappe.call({
        method: 'tr_tradehub.tr_tradehub.doctype.rfq_quote.rfq_quote.get_rfq_items_for_quote',
        args: {
            rfq_name: frm.doc.rfq
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                const items = r.message;
                const item_count = items.length;

                frappe.show_alert({
                    message: __('RFQ has {0} items available for quoting.', [item_count]),
                    indicator: 'blue'
                }, 5);
            }
        }
    });
}

/**
 * Calculate item total price
 */
function calculate_item_total(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const total = flt(row.qty) * flt(row.unit_price);
    frappe.model.set_value(cdt, cdn, 'total_price', total);

    // Recalculate form totals
    calculate_totals(frm);
}

/**
 * Calculate total amount from all items
 */
function calculate_totals(frm) {
    let total = 0;

    if (frm.doc.items) {
        frm.doc.items.forEach(function(item) {
            // Ensure item total is calculated
            item.total_price = flt(item.qty) * flt(item.unit_price);
            total += flt(item.total_price);
        });
    }

    frm.set_value('total_amount', total);
    calculate_final_amount(frm);
}

/**
 * Calculate final amount after discount
 */
function calculate_final_amount(frm) {
    const final_amount = flt(frm.doc.total_amount) - flt(frm.doc.discount_amount || 0);
    frm.set_value('final_amount', final_amount);
}

/**
 * Add action buttons based on quote status
 */
function add_action_buttons(frm) {
    if (frm.is_new()) return;

    // Submit Quote button (for Draft quotes)
    if (frm.doc.status === 'Draft') {
        frm.add_custom_button(__('Submit Quote'), function() {
            frappe.confirm(
                __('Submit this quote for buyer review? You will not be able to edit it after submission.'),
                function() {
                    frappe.call({
                        method: 'tr_tradehub.tr_tradehub.doctype.rfq_quote.rfq_quote.submit_rfq_quote',
                        args: {
                            quote_name: frm.doc.name
                        },
                        callback: function(r) {
                            if (r.message && r.message.success) {
                                frappe.show_alert({
                                    message: __('Quote submitted successfully'),
                                    indicator: 'green'
                                });
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }, __('Actions'));
    }

    // Withdraw Quote button
    if (['Draft', 'Submitted', 'Under Review'].includes(frm.doc.status)) {
        frm.add_custom_button(__('Withdraw Quote'), function() {
            frappe.confirm(
                __('Are you sure you want to withdraw this quote?'),
                function() {
                    frappe.call({
                        method: 'tr_tradehub.tr_tradehub.doctype.rfq_quote.rfq_quote.withdraw_rfq_quote',
                        args: {
                            quote_name: frm.doc.name
                        },
                        callback: function(r) {
                            if (r.message && r.message.success) {
                                frappe.show_alert({
                                    message: __('Quote withdrawn'),
                                    indicator: 'orange'
                                });
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }, __('Actions'));
    }

    // Add All RFQ Items button (for Draft quotes)
    if (frm.doc.status === 'Draft' && frm.doc.rfq) {
        frm.add_custom_button(__('Add All RFQ Items'), function() {
            add_all_rfq_items(frm);
        }, __('Actions'));
    }
}

/**
 * Add all items from the RFQ to the quote
 */
function add_all_rfq_items(frm) {
    if (!frm.doc.rfq) {
        frappe.msgprint(__('Please select an RFQ first'));
        return;
    }

    frappe.call({
        method: 'tr_tradehub.tr_tradehub.doctype.rfq_quote.rfq_quote.get_rfq_items_for_quote',
        args: {
            rfq_name: frm.doc.rfq
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                // Get existing item names to avoid duplicates
                const existing_items = new Set();
                if (frm.doc.items) {
                    frm.doc.items.forEach(function(item) {
                        if (item.rfq_item) {
                            existing_items.add(item.rfq_item);
                        }
                    });
                }

                // Add items that are not already in the quote
                let added_count = 0;
                r.message.forEach(function(rfq_item) {
                    if (!existing_items.has(rfq_item.name)) {
                        const row = frm.add_child('items');
                        row.rfq_item = rfq_item.name;
                        row.item_name = rfq_item.item_name;
                        row.item_description = rfq_item.item_description;
                        row.qty = rfq_item.qty || 1;
                        row.uom = rfq_item.uom || 'Nos';
                        row.currency = rfq_item.currency || frm.doc.currency || 'TRY';
                        // Use target price as starting point
                        row.unit_price = rfq_item.target_price || 0;
                        row.total_price = flt(row.qty) * flt(row.unit_price);
                        added_count++;
                    }
                });

                frm.refresh_field('items');
                calculate_totals(frm);

                if (added_count > 0) {
                    frappe.show_alert({
                        message: __('Added {0} items from RFQ', [added_count]),
                        indicator: 'green'
                    });
                } else {
                    frappe.show_alert({
                        message: __('All RFQ items are already in the quote'),
                        indicator: 'blue'
                    });
                }
            } else {
                frappe.msgprint(__('No items found in the selected RFQ'));
            }
        }
    });
}

/**
 * Update status indicator on the form
 */
function update_status_indicator(frm) {
    const status_colors = {
        'Draft': 'gray',
        'Submitted': 'blue',
        'Under Review': 'yellow',
        'Shortlisted': 'orange',
        'Awarded': 'green',
        'Rejected': 'red',
        'Withdrawn': 'gray',
        'Expired': 'red',
        'Cancelled': 'red'
    };

    const color = status_colors[frm.doc.status] || 'gray';
    frm.page.set_indicator(__(frm.doc.status), color);
}

/**
 * Check if RFQ deadline has passed
 */
function validate_rfq_deadline(frm) {
    frappe.db.get_value('RFQ', frm.doc.rfq, ['submission_deadline', 'status'], function(r) {
        if (r) {
            if (r.submission_deadline) {
                const deadline = frappe.datetime.str_to_obj(r.submission_deadline);
                const now = new Date();

                if (deadline < now && frm.doc.status === 'Draft') {
                    frm.dashboard.add_comment(
                        __('Warning: The RFQ submission deadline has passed. You may not be able to submit this quote.'),
                        'red',
                        true
                    );
                }
            }

            if (r.status && !['Open', 'In Progress', 'Quotes Received'].includes(r.status)) {
                frm.dashboard.add_comment(
                    __('Warning: The RFQ is no longer accepting quotes (Status: {0}).', [r.status]),
                    'orange',
                    true
                );
            }
        }
    });
}
