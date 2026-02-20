// Copyright (c) 2026, Trade Hub and contributors
// For license information, please see license.txt

/**
 * Order DocType client script for Trade Hub B2B Marketplace.
 *
 * This script handles:
 * - Status action buttons for order workflow
 * - fetch_from field refresh when buyer/seller changes
 * - Total calculations
 * - Payment tracking
 * - Shipping information management
 */

frappe.ui.form.on('Order', {
    /**
     * Form refresh handler - sets up action buttons and dashboard
     */
    refresh: function(frm) {
        // Show status indicator
        frm.page.set_indicator(frm.doc.status, get_status_color(frm.doc.status));

        // Add action buttons based on current status
        add_status_action_buttons(frm);

        // Show payment summary in dashboard
        show_payment_summary(frm);

        // Show order summary
        if (!frm.is_new()) {
            show_order_summary(frm);
        }

        // Set filters for Link fields based on tenant
        set_tenant_filters(frm);
    },

    /**
     * Buyer field change handler - refreshes fetch_from fields
     */
    buyer: function(frm) {
        if (frm.doc.buyer) {
            // Trigger fetch_from for buyer-related fields
            frappe.model.set_value(frm.doctype, frm.docname, 'buyer_name', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'buyer_company', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'buyer_email', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'buyer_phone', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'buyer_segment', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'tenant', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'tenant_name', null);

            // Refresh form to trigger fetch_from
            frm.refresh_fields(['buyer_name', 'buyer_company', 'buyer_email',
                               'buyer_phone', 'buyer_segment', 'tenant', 'tenant_name']);

            // Copy buyer's shipping address if delivery address is empty
            if (!frm.doc.delivery_address) {
                frappe.call({
                    method: 'frappe.client.get_value',
                    args: {
                        doctype: 'Buyer Profile',
                        filters: { name: frm.doc.buyer },
                        fieldname: ['shipping_address', 'shipping_city', 'shipping_state',
                                   'shipping_country', 'shipping_postal_code']
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.set_value('delivery_address', r.message.shipping_address || '');
                            frm.set_value('delivery_city', r.message.shipping_city || '');
                            frm.set_value('delivery_state', r.message.shipping_state || '');
                            frm.set_value('delivery_country', r.message.shipping_country || '');
                            frm.set_value('delivery_postal_code', r.message.shipping_postal_code || '');
                        }
                    }
                });
            }
        }
    },

    /**
     * Seller field change handler - refreshes fetch_from fields
     */
    seller: function(frm) {
        if (frm.doc.seller) {
            // Trigger fetch_from for seller-related fields
            frappe.model.set_value(frm.doctype, frm.docname, 'seller_name', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'seller_company', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'seller_email', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'seller_phone', null);
            frappe.model.set_value(frm.doctype, frm.docname, 'seller_tier', null);

            // Refresh form to trigger fetch_from
            frm.refresh_fields(['seller_name', 'seller_company', 'seller_email',
                               'seller_phone', 'seller_tier']);
        }
    },

    /**
     * RFQ field change handler - refreshes fetch_from fields
     */
    rfq: function(frm) {
        if (frm.doc.rfq) {
            frm.refresh_field('rfq_title');
        }
    },

    /**
     * Quotation field change handler - refreshes fetch_from fields and copies details
     */
    quotation: function(frm) {
        if (frm.doc.quotation) {
            frm.refresh_field('quotation_amount');

            // Copy quotation details
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Quotation',
                    name: frm.doc.quotation
                },
                callback: function(r) {
                    if (r.message) {
                        var quo = r.message;
                        frm.set_value('currency', quo.currency);
                        frm.set_value('payment_terms', quo.payment_terms);
                        frm.set_value('incoterm', quo.incoterm);
                        frm.set_value('delivery_days', quo.delivery_days);
                        frm.set_value('shipping_method', quo.shipping_method);

                        // Set seller if not set
                        if (!frm.doc.seller && quo.seller) {
                            frm.set_value('seller', quo.seller);
                        }

                        // Set buyer from RFQ if not set
                        if (!frm.doc.buyer && quo.rfq_buyer) {
                            frm.set_value('buyer', quo.rfq_buyer);
                        }
                    }
                }
            });
        }
    },

    /**
     * Discount percentage change handler - recalculates totals
     */
    discount_percentage: function(frm) {
        calculate_totals(frm);
    },

    /**
     * Tax rate change handler - recalculates totals
     */
    tax_rate: function(frm) {
        calculate_totals(frm);
    },

    /**
     * Shipping cost change handler - recalculates totals
     */
    shipping_cost: function(frm) {
        calculate_totals(frm);
    },

    /**
     * Advance percentage change handler - recalculates advance amount
     */
    advance_percentage: function(frm) {
        calculate_payment_amounts(frm);
    },

    /**
     * Paid amount change handler - recalculates balance
     */
    paid_amount: function(frm) {
        calculate_payment_amounts(frm);
    },

    /**
     * Source type change handler - shows/hides related fields
     */
    source_type: function(frm) {
        frm.refresh_fields(['rfq', 'quotation', 'sample_request']);
    }
});

/**
 * Child table event handlers for Order Items
 */
frappe.ui.form.on('Order Item', {
    /**
     * Quantity change handler
     */
    quantity: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        row.amount = flt(row.quantity) * flt(row.unit_price);
        frm.refresh_field('items');
        calculate_totals(frm);
    },

    /**
     * Unit price change handler
     */
    unit_price: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        row.amount = flt(row.quantity) * flt(row.unit_price);
        frm.refresh_field('items');
        calculate_totals(frm);
    },

    /**
     * Item row added handler
     */
    items_add: function(frm, cdt, cdn) {
        calculate_totals(frm);
    },

    /**
     * Item row removed handler
     */
    items_remove: function(frm, cdt, cdn) {
        calculate_totals(frm);
    }
});

/**
 * Get status color for indicator
 * @param {string} status - Order status
 * @returns {string} Color name
 */
function get_status_color(status) {
    var colors = {
        'Draft': 'gray',
        'Pending': 'blue',
        'Confirmed': 'cyan',
        'Processing': 'orange',
        'Ready to Ship': 'purple',
        'Shipped': 'yellow',
        'Delivered': 'green',
        'Completed': 'green',
        'Cancelled': 'red',
        'Refunded': 'red',
        'On Hold': 'gray'
    };
    return colors[status] || 'gray';
}

/**
 * Add action buttons based on current status
 * @param {object} frm - Form object
 */
function add_status_action_buttons(frm) {
    if (frm.is_new()) return;

    var status = frm.doc.status;

    // Draft actions
    if (status === 'Draft') {
        frm.add_custom_button(__('Submit Order'), function() {
            submit_order_action(frm);
        }, __('Actions'));
    }

    // Pending actions
    if (status === 'Pending') {
        frm.add_custom_button(__('Confirm Order'), function() {
            confirm_order_action(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Put On Hold'), function() {
            hold_order_action(frm);
        }, __('Actions'));
    }

    // Confirmed actions
    if (status === 'Confirmed') {
        frm.add_custom_button(__('Start Processing'), function() {
            start_processing_action(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Put On Hold'), function() {
            hold_order_action(frm);
        }, __('Actions'));
    }

    // Processing actions
    if (status === 'Processing') {
        frm.add_custom_button(__('Mark Ready to Ship'), function() {
            mark_ready_to_ship_action(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Put On Hold'), function() {
            hold_order_action(frm);
        }, __('Actions'));
    }

    // Ready to Ship actions
    if (status === 'Ready to Ship') {
        frm.add_custom_button(__('Ship Order'), function() {
            ship_order_action(frm);
        }, __('Actions'));
    }

    // Shipped actions
    if (status === 'Shipped') {
        frm.add_custom_button(__('Mark Delivered'), function() {
            mark_delivered_action(frm);
        }, __('Actions'));
    }

    // Delivered actions
    if (status === 'Delivered') {
        frm.add_custom_button(__('Complete Order'), function() {
            complete_order_action(frm);
        }, __('Actions'));
    }

    // On Hold actions
    if (status === 'On Hold') {
        frm.add_custom_button(__('Release from Hold'), function() {
            release_from_hold_action(frm);
        }, __('Actions'));
    }

    // Cancel action (available for most statuses)
    if (['Pending', 'Confirmed', 'Processing', 'Ready to Ship', 'On Hold'].includes(status)) {
        frm.add_custom_button(__('Cancel Order'), function() {
            cancel_order_action(frm);
        }, __('Actions'));
    }

    // Refund action
    if (['Cancelled', 'Delivered', 'Completed'].includes(status)) {
        if (flt(frm.doc.paid_amount) > 0 && frm.doc.refund_status !== 'Completed') {
            frm.add_custom_button(__('Process Refund'), function() {
                process_refund_action(frm);
            }, __('Actions'));
        }
    }

    // Record payment action
    if (['Pending', 'Confirmed', 'Processing', 'Ready to Ship', 'Shipped', 'Delivered'].includes(status)) {
        if (flt(frm.doc.balance_amount) > 0) {
            frm.add_custom_button(__('Record Payment'), function() {
                record_payment_action(frm);
            }, __('Payment'));
        }
    }
}

/**
 * Submit order action
 * @param {object} frm - Form object
 */
function submit_order_action(frm) {
    frappe.confirm(
        __('Are you sure you want to submit this order for seller confirmation?'),
        function() {
            frappe.call({
                method: 'tr_tradehub.doctype.order.order.submit_order',
                args: { order_name: frm.doc.name },
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
        }
    );
}

/**
 * Confirm order action
 * @param {object} frm - Form object
 */
function confirm_order_action(frm) {
    frappe.confirm(
        __('Are you sure you want to confirm this order?'),
        function() {
            frappe.call({
                method: 'tr_tradehub.doctype.order.order.confirm_order',
                args: { order_name: frm.doc.name },
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
        }
    );
}

/**
 * Start processing action
 * @param {object} frm - Form object
 */
function start_processing_action(frm) {
    frappe.call({
        method: 'tr_tradehub.doctype.order.order.start_order_processing',
        args: { order_name: frm.doc.name },
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
}

/**
 * Mark ready to ship action
 * @param {object} frm - Form object
 */
function mark_ready_to_ship_action(frm) {
    frappe.call({
        method: 'tr_tradehub.doctype.order.order.mark_order_ready_to_ship',
        args: { order_name: frm.doc.name },
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
}

/**
 * Ship order action
 * @param {object} frm - Form object
 */
function ship_order_action(frm) {
    frappe.prompt([
        {
            fieldname: 'tracking_number',
            fieldtype: 'Data',
            label: __('Tracking Number'),
            description: __('Enter shipment tracking number')
        },
        {
            fieldname: 'carrier',
            fieldtype: 'Data',
            label: __('Carrier'),
            description: __('Enter shipping carrier name')
        }
    ], function(values) {
        frappe.call({
            method: 'tr_tradehub.doctype.order.order.ship_order',
            args: {
                order_name: frm.doc.name,
                tracking_number: values.tracking_number,
                carrier: values.carrier
            },
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
    }, __('Ship Order'), __('Ship'));
}

/**
 * Mark delivered action
 * @param {object} frm - Form object
 */
function mark_delivered_action(frm) {
    frappe.confirm(
        __('Confirm that this order has been delivered?'),
        function() {
            frappe.call({
                method: 'tr_tradehub.doctype.order.order.mark_order_delivered',
                args: { order_name: frm.doc.name },
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
        }
    );
}

/**
 * Complete order action
 * @param {object} frm - Form object
 */
function complete_order_action(frm) {
    frappe.confirm(
        __('Are you sure you want to mark this order as completed?'),
        function() {
            frappe.call({
                method: 'tr_tradehub.doctype.order.order.complete_order',
                args: { order_name: frm.doc.name },
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
        }
    );
}

/**
 * Cancel order action
 * @param {object} frm - Form object
 */
function cancel_order_action(frm) {
    frappe.prompt([
        {
            fieldname: 'reason',
            fieldtype: 'Small Text',
            label: __('Cancellation Reason'),
            reqd: 1,
            description: __('Please provide a reason for cancellation')
        },
        {
            fieldname: 'cancelled_by',
            fieldtype: 'Select',
            label: __('Cancelled By'),
            options: ['Buyer', 'Seller', 'System', 'Admin'],
            default: 'Admin'
        }
    ], function(values) {
        frappe.call({
            method: 'tr_tradehub.doctype.order.order.cancel_order',
            args: {
                order_name: frm.doc.name,
                reason: values.reason,
                cancelled_by: values.cancelled_by
            },
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
    }, __('Cancel Order'), __('Cancel'));
}

/**
 * Hold order action
 * @param {object} frm - Form object
 */
function hold_order_action(frm) {
    frappe.prompt([
        {
            fieldname: 'reason',
            fieldtype: 'Small Text',
            label: __('Hold Reason'),
            description: __('Why is this order being put on hold?')
        }
    ], function(values) {
        frappe.call({
            method: 'tr_tradehub.doctype.order.order.hold_order',
            args: {
                order_name: frm.doc.name,
                reason: values.reason
            },
            callback: function(r) {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'gray'
                    });
                    frm.reload_doc();
                }
            }
        });
    }, __('Put Order On Hold'), __('Hold'));
}

/**
 * Release from hold action
 * @param {object} frm - Form object
 */
function release_from_hold_action(frm) {
    frappe.prompt([
        {
            fieldname: 'target_status',
            fieldtype: 'Select',
            label: __('Return to Status'),
            options: ['Pending', 'Confirmed', 'Processing', 'Ready to Ship'],
            default: 'Pending',
            reqd: 1
        }
    ], function(values) {
        frappe.call({
            method: 'tr_tradehub.doctype.order.order.release_order_from_hold',
            args: {
                order_name: frm.doc.name,
                target_status: values.target_status
            },
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
    }, __('Release Order from Hold'), __('Release'));
}

/**
 * Process refund action
 * @param {object} frm - Form object
 */
function process_refund_action(frm) {
    frappe.prompt([
        {
            fieldname: 'refund_amount',
            fieldtype: 'Currency',
            label: __('Refund Amount'),
            default: frm.doc.paid_amount,
            reqd: 1
        },
        {
            fieldname: 'refund_status',
            fieldtype: 'Select',
            label: __('Refund Status'),
            options: ['Completed', 'Partial', 'Processing'],
            default: 'Completed'
        }
    ], function(values) {
        frappe.call({
            method: 'tr_tradehub.doctype.order.order.process_order_refund',
            args: {
                order_name: frm.doc.name,
                refund_amount: values.refund_amount,
                refund_status: values.refund_status
            },
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
    }, __('Process Refund'), __('Refund'));
}

/**
 * Record payment action
 * @param {object} frm - Form object
 */
function record_payment_action(frm) {
    frappe.prompt([
        {
            fieldname: 'amount',
            fieldtype: 'Currency',
            label: __('Payment Amount'),
            default: frm.doc.balance_amount,
            reqd: 1
        },
        {
            fieldname: 'payment_method',
            fieldtype: 'Select',
            label: __('Payment Method'),
            options: ['', 'Bank Transfer', 'Credit Card', 'Letter of Credit', 'PayPal', 'Other']
        },
        {
            fieldname: 'reference',
            fieldtype: 'Data',
            label: __('Reference Number')
        }
    ], function(values) {
        frappe.call({
            method: 'tr_tradehub.doctype.order.order.record_order_payment',
            args: {
                order_name: frm.doc.name,
                amount: values.amount,
                payment_method: values.payment_method,
                reference: values.reference
            },
            callback: function(r) {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: __('Payment recorded: {0}', [format_currency(values.amount, frm.doc.currency)]),
                        indicator: 'green'
                    });
                    frm.reload_doc();
                }
            }
        });
    }, __('Record Payment'), __('Record'));
}

/**
 * Calculate order totals
 * @param {object} frm - Form object
 */
function calculate_totals(frm) {
    var subtotal = 0;

    // Sum up item amounts
    if (frm.doc.items) {
        frm.doc.items.forEach(function(item) {
            subtotal += flt(item.amount);
        });
    }

    frm.set_value('subtotal', subtotal);

    // Calculate discount
    var discount_amount = 0;
    if (frm.doc.discount_percentage) {
        discount_amount = subtotal * flt(frm.doc.discount_percentage) / 100;
    }
    frm.set_value('discount_amount', discount_amount);

    // Calculate tax
    var taxable_amount = subtotal - discount_amount;
    var tax_amount = 0;
    if (frm.doc.tax_rate) {
        tax_amount = taxable_amount * flt(frm.doc.tax_rate) / 100;
    }
    frm.set_value('tax_amount', tax_amount);

    // Calculate total
    var total = subtotal - discount_amount + tax_amount + flt(frm.doc.shipping_cost);
    frm.set_value('total_amount', total);

    // Update payment amounts
    calculate_payment_amounts(frm);
}

/**
 * Calculate payment amounts
 * @param {object} frm - Form object
 */
function calculate_payment_amounts(frm) {
    // Calculate advance amount
    if (frm.doc.advance_percentage) {
        var advance_amount = flt(frm.doc.total_amount) * flt(frm.doc.advance_percentage) / 100;
        frm.set_value('advance_amount', advance_amount);
    }

    // Calculate balance
    var balance = flt(frm.doc.total_amount) - flt(frm.doc.paid_amount);
    frm.set_value('balance_amount', balance);
}

/**
 * Show payment summary in dashboard
 * @param {object} frm - Form object
 */
function show_payment_summary(frm) {
    if (frm.is_new()) return;

    var html = '<div class="row">';
    html += '<div class="col-sm-3"><strong>' + __('Total') + ':</strong> ' +
            format_currency(frm.doc.total_amount, frm.doc.currency) + '</div>';
    html += '<div class="col-sm-3"><strong>' + __('Paid') + ':</strong> ' +
            format_currency(frm.doc.paid_amount || 0, frm.doc.currency) + '</div>';
    html += '<div class="col-sm-3"><strong>' + __('Balance') + ':</strong> ' +
            format_currency(frm.doc.balance_amount || 0, frm.doc.currency) + '</div>';
    html += '<div class="col-sm-3"><strong>' + __('Status') + ':</strong> ' +
            frm.doc.payment_status + '</div>';
    html += '</div>';

    frm.dashboard.add_section(html);
}

/**
 * Show order summary
 * @param {object} frm - Form object
 */
function show_order_summary(frm) {
    var item_count = frm.doc.items ? frm.doc.items.length : 0;
    frm.dashboard.set_headline(
        __('Order {0} - {1} items - {2}', [
            frm.doc.order_number || frm.doc.name,
            item_count,
            frm.doc.status
        ])
    );
}

/**
 * Set tenant-based filters for Link fields
 * @param {object} frm - Form object
 */
function set_tenant_filters(frm) {
    if (frm.doc.tenant) {
        // Filter buyer by tenant
        frm.set_query('buyer', function() {
            return {
                filters: {
                    tenant: frm.doc.tenant,
                    status: ['in', ['Active', 'Verified']]
                }
            };
        });

        // Filter seller by tenant
        frm.set_query('seller', function() {
            return {
                filters: {
                    tenant: frm.doc.tenant,
                    status: ['in', ['Active', 'Verified']]
                }
            };
        });
    }
}
