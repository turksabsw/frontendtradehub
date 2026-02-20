// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Review', {
    refresh: function(frm) {
        // Ensure seller and tenant fields are always read-only
        frm.set_df_property('seller', 'read_only', 1);
        frm.set_df_property('seller_name', 'read_only', 1);
        frm.set_df_property('tenant', 'read_only', 1);
        frm.set_df_property('tenant_name', 'read_only', 1);

        // Add moderation buttons for System Manager
        if (frappe.user.has_role('System Manager') && frm.doc.name && !frm.is_new()) {
            if (frm.doc.status === 'Pending' || frm.doc.status === 'Flagged') {
                frm.add_custom_button(__('Approve'), function() {
                    frappe.call({
                        method: 'tr_tradehub.tr_tradehub.doctype.review.review.approve_review',
                        args: {
                            review_name: frm.doc.name
                        },
                        callback: function(r) {
                            if (!r.exc) {
                                frm.reload_doc();
                                frappe.show_alert({
                                    message: __('Review approved'),
                                    indicator: 'green'
                                });
                            }
                        }
                    });
                }, __('Moderation'));

                frm.add_custom_button(__('Reject'), function() {
                    frappe.prompt({
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Rejection Reason'),
                        reqd: 1
                    }, function(values) {
                        frappe.call({
                            method: 'tr_tradehub.tr_tradehub.doctype.review.review.reject_review',
                            args: {
                                review_name: frm.doc.name,
                                reason: values.reason
                            },
                            callback: function(r) {
                                if (!r.exc) {
                                    frm.reload_doc();
                                    frappe.show_alert({
                                        message: __('Review rejected'),
                                        indicator: 'red'
                                    });
                                }
                            }
                        });
                    }, __('Reject Review'), __('Reject'));
                }, __('Moderation'));
            }
        }

        // Add seller response button
        if (frm.doc.seller && frm.doc.name && !frm.is_new() && frm.doc.status === 'Approved') {
            // Check if current user is the seller
            frappe.db.get_value('Seller Profile', frm.doc.seller, 'user', function(r) {
                if (r && (r.user === frappe.session.user || frappe.user.has_role('System Manager'))) {
                    if (!frm.doc.seller_response) {
                        frm.add_custom_button(__('Add Response'), function() {
                            frappe.prompt({
                                fieldname: 'response',
                                fieldtype: 'Text Editor',
                                label: __('Your Response'),
                                reqd: 1
                            }, function(values) {
                                frappe.call({
                                    method: 'tr_tradehub.tr_tradehub.doctype.review.review.submit_seller_response',
                                    args: {
                                        review_name: frm.doc.name,
                                        response: values.response
                                    },
                                    callback: function(r) {
                                        if (!r.exc) {
                                            frm.reload_doc();
                                            frappe.show_alert({
                                                message: __('Response submitted'),
                                                indicator: 'green'
                                            });
                                        }
                                    }
                                });
                            }, __('Respond to Review'), __('Submit'));
                        }, __('Actions'));
                    }
                }
            });
        }

        // Show verified purchase badge
        if (frm.doc.is_verified_purchase) {
            frm.set_intro(__('Verified Purchase'), 'green');
        }
    },

    listing: function(frm) {
        // When product/listing is selected, auto-populate seller details
        if (frm.doc.listing) {
            frappe.call({
                method: 'tr_tradehub.tr_tradehub.doctype.review.review.get_seller_from_listing',
                args: {
                    listing: frm.doc.listing
                },
                callback: function(r) {
                    if (r.message) {
                        let data = r.message;

                        // Auto-populate seller fields
                        if (data.seller) {
                            frm.set_value('seller', data.seller);
                        }
                        if (data.seller_name) {
                            frm.set_value('seller_name', data.seller_name);
                        }
                        if (data.tenant) {
                            frm.set_value('tenant', data.tenant);
                        }
                        if (data.tenant_name) {
                            frm.set_value('tenant_name', data.tenant_name);
                        }
                        if (data.listing_title) {
                            frm.set_value('listing_title', data.listing_title);
                        }
                        if (data.listing_image) {
                            frm.set_value('listing_image', data.listing_image);
                        }

                        // Make seller fields read-only
                        frm.set_df_property('seller', 'read_only', 1);
                        frm.set_df_property('tenant', 'read_only', 1);
                    }
                }
            });
        } else {
            // Clear seller fields when listing is cleared
            frm.set_value('seller', '');
            frm.set_value('seller_name', '');
            frm.set_value('tenant', '');
            frm.set_value('tenant_name', '');
            frm.set_value('listing_title', '');
            frm.set_value('listing_image', '');
        }
    },

    marketplace_order: function(frm) {
        // When order is selected, try to get seller from order items
        if (frm.doc.marketplace_order && !frm.doc.listing) {
            frappe.call({
                method: 'tr_tradehub.tr_tradehub.doctype.review.review.get_seller_from_order',
                args: {
                    marketplace_order: frm.doc.marketplace_order
                },
                callback: function(r) {
                    if (r.message && r.message.seller) {
                        let data = r.message;

                        // Auto-populate seller fields from order
                        if (data.seller) {
                            frm.set_value('seller', data.seller);
                        }
                        if (data.seller_name) {
                            frm.set_value('seller_name', data.seller_name);
                        }
                        if (data.tenant) {
                            frm.set_value('tenant', data.tenant);
                        }
                        if (data.tenant_name) {
                            frm.set_value('tenant_name', data.tenant_name);
                        }

                        // Make seller fields read-only
                        frm.set_df_property('seller', 'read_only', 1);
                        frm.set_df_property('tenant', 'read_only', 1);
                    }
                }
            });
        }
    },

    rating: function(frm) {
        // Show visual feedback when rating is changed
        if (frm.doc.rating) {
            let stars = Math.round(frm.doc.rating);
            let message = '';

            switch(stars) {
                case 1:
                    message = __('Poor');
                    break;
                case 2:
                    message = __('Fair');
                    break;
                case 3:
                    message = __('Good');
                    break;
                case 4:
                    message = __('Very Good');
                    break;
                case 5:
                    message = __('Excellent');
                    break;
            }

            if (message) {
                frappe.show_alert({
                    message: message + ' (' + stars + '/5)',
                    indicator: stars >= 4 ? 'green' : (stars >= 3 ? 'yellow' : 'red')
                }, 2);
            }
        }
    },

    seller_response: function(frm) {
        // Auto-set response date when seller adds a response
        if (frm.doc.seller_response && !frm.doc.response_date) {
            frm.set_value('response_date', frappe.datetime.now_datetime());
        }
    }
});
