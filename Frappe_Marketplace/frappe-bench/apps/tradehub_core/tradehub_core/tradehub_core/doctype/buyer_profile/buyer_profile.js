// Copyright (c) 2026, Trade Hub and contributors
// For license information, please see license.txt

/**
 * Buyer Profile Client Script
 *
 * Handles form behavior for Buyer Profile DocType including:
 * - Status action buttons (activate, suspend, block)
 * - Verification workflow actions
 * - Segment management
 * - fetch_from field refresh on link field changes
 * - Purchase metrics refresh
 * - Dashboard indicators
 */

frappe.ui.form.on('Buyer Profile', {

    // =========================================================================
    // FORM EVENTS
    // =========================================================================

    refresh: function(frm) {
        // Set up dashboard indicator
        frm.trigger('set_status_indicator');

        // Add custom buttons based on status
        frm.trigger('add_action_buttons');

        // Set field filters for tenant-aware Link fields
        frm.trigger('set_field_filters');

        // Show purchase metrics summary
        if (!frm.is_new() && frm.doc.verification_status === 'Verified') {
            frm.trigger('show_purchase_summary');
        }
    },

    onload: function(frm) {
        // Set default tenant from user session if creating new
        if (frm.is_new() && !frm.doc.tenant) {
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'User',
                    filters: { name: frappe.session.user },
                    fieldname: 'tenant'
                },
                callback: function(r) {
                    if (r.message && r.message.tenant) {
                        frm.set_value('tenant', r.message.tenant);
                    }
                }
            });
        }
    },

    // =========================================================================
    // FIELD CHANGE HANDLERS
    // =========================================================================

    tenant: function(frm) {
        // Refresh fetch_from fields when tenant changes
        frm.trigger('refresh_fetch_from_fields');
    },

    user: function(frm) {
        // Refresh fetch_from fields when user changes
        frm.trigger('refresh_fetch_from_fields');
    },

    verified_by: function(frm) {
        // Refresh fetch_from fields when verified_by changes
        frm.trigger('refresh_fetch_from_fields');
    },

    billing_same_as_shipping: function(frm) {
        // Copy shipping address to billing if checkbox is checked
        if (frm.doc.billing_same_as_shipping) {
            frm.set_value('billing_address_line_1', frm.doc.address_line_1);
            frm.set_value('billing_address_line_2', frm.doc.address_line_2);
            frm.set_value('billing_city', frm.doc.city);
            frm.set_value('billing_state', frm.doc.state);
            frm.set_value('billing_country', frm.doc.country);
            frm.set_value('billing_postal_code', frm.doc.postal_code);
        }
    },

    // =========================================================================
    // CUSTOM TRIGGERS
    // =========================================================================

    set_status_indicator: function(frm) {
        // Set dashboard indicator based on status
        var status_colors = {
            'Active': 'green',
            'Inactive': 'gray',
            'Suspended': 'orange',
            'Blocked': 'red'
        };

        // Show verification badge
        if (frm.doc.verification_status === 'Verified') {
            frm.dashboard.add_indicator(
                __('Verified'),
                'green'
            );
        } else if (frm.doc.verification_status === 'Rejected') {
            frm.dashboard.add_indicator(
                __('Verification Rejected'),
                'red'
            );
        } else if (frm.doc.verification_status === 'Under Review') {
            frm.dashboard.add_indicator(
                __('Under Review'),
                'blue'
            );
        }

        // Show segment badge
        if (frm.doc.segment) {
            var segment_colors = {
                'Standard': 'gray',
                'Silver': 'blue',
                'Gold': 'yellow',
                'Platinum': 'purple',
                'Strategic': 'orange',
                'Enterprise': 'green'
            };
            frm.dashboard.add_indicator(
                frm.doc.segment + ' Buyer',
                segment_colors[frm.doc.segment] || 'gray'
            );
        }
    },

    add_action_buttons: function(frm) {
        if (frm.is_new()) return;

        // Verification actions (for admins)
        if (frappe.user.has_role('System Manager')) {
            if (frm.doc.verification_status === 'Documents Submitted' ||
                frm.doc.verification_status === 'Under Review') {

                frm.add_custom_button(__('Start Review'), function() {
                    frm.set_value('verification_status', 'Under Review');
                    frm.save();
                }, __('Verification'));

                frm.add_custom_button(__('Approve'), function() {
                    frm.trigger('approve_buyer');
                }, __('Verification'));

                frm.add_custom_button(__('Reject'), function() {
                    frm.trigger('reject_buyer');
                }, __('Verification'));
            }

            // Status actions
            if (frm.doc.status === 'Active') {
                frm.add_custom_button(__('Suspend'), function() {
                    frm.trigger('suspend_buyer');
                }, __('Actions'));

                frm.add_custom_button(__('Block'), function() {
                    frm.trigger('block_buyer');
                }, __('Actions'));
            } else if (frm.doc.status === 'Suspended' || frm.doc.status === 'Blocked') {
                frm.add_custom_button(__('Reactivate'), function() {
                    frm.trigger('activate_buyer');
                }, __('Actions'));
            } else if (frm.doc.status === 'Inactive') {
                frm.add_custom_button(__('Activate'), function() {
                    frm.trigger('activate_buyer');
                }, __('Actions'));
            }

            // Segment management
            if (frm.doc.verification_status === 'Verified') {
                frm.add_custom_button(__('Check Segment Eligibility'), function() {
                    frm.trigger('check_segment_eligibility');
                }, __('Segment'));

                frm.add_custom_button(__('Change Segment'), function() {
                    frm.trigger('change_segment');
                }, __('Segment'));
            }
        }

        // Buyer actions (for profile owner)
        if (frm.doc.user === frappe.session.user || frm.doc.created_by === frappe.session.user) {
            if (frm.doc.verification_status === 'Pending' || frm.doc.verification_status === 'Rejected') {
                frm.add_custom_button(__('Submit for Verification'), function() {
                    frm.trigger('submit_for_verification');
                });
            }
        }

        // Metrics refresh
        if (!frm.is_new() && frm.doc.verification_status === 'Verified') {
            frm.add_custom_button(__('Refresh Metrics'), function() {
                frm.trigger('refresh_metrics');
            });
        }
    },

    set_field_filters: function(frm) {
        // Filter user by tenant if tenant is set
        if (frm.doc.tenant) {
            frm.set_query('user', function() {
                return {
                    filters: {
                        tenant: frm.doc.tenant
                    }
                };
            });
        }

        // Filter interest_categories category field to exclude already selected categories
        // and show only active categories
        frm.set_query('category', 'interest_categories', function(doc, cdt, cdn) {
            // Get already selected categories from the child table
            var selected_categories = (doc.interest_categories || [])
                .map(function(row) { return row.category; })
                .filter(function(cat) { return cat; });

            return {
                filters: {
                    name: ['not in', selected_categories],
                    enabled: 1
                }
            };
        });
    },

    refresh_fetch_from_fields: function(frm) {
        // Manually refresh fetch_from fields
        var fetch_fields = [
            'tenant_name', 'user_full_name', 'user_email', 'verified_by_name'
        ];

        fetch_fields.forEach(function(field) {
            frm.refresh_field(field);
        });
    },

    show_purchase_summary: function(frm) {
        // Show purchase metrics in dashboard
        var html = '<div class="row">';

        html += '<div class="col-sm-3">';
        html += '<div class="stat-box">';
        html += '<h4>' + (frm.doc.segment || 'Standard') + '</h4>';
        html += '<small>' + __('Segment') + '</small>';
        html += '</div></div>';

        html += '<div class="col-sm-3">';
        html += '<div class="stat-box">';
        html += '<h4>' + (frm.doc.total_orders || 0) + '</h4>';
        html += '<small>' + __('Total Orders') + '</small>';
        html += '</div></div>';

        html += '<div class="col-sm-3">';
        html += '<div class="stat-box">';
        html += '<h4>' + format_currency(frm.doc.total_purchase_value || 0, frm.doc.currency) + '</h4>';
        html += '<small>' + __('Total Purchases') + '</small>';
        html += '</div></div>';

        html += '<div class="col-sm-3">';
        html += '<div class="stat-box">';
        html += '<h4>' + (frm.doc.payment_on_time_rate || 0).toFixed(0) + '%</h4>';
        html += '<small>' + __('Payment On-Time') + '</small>';
        html += '</div></div>';

        html += '</div>';

        frm.dashboard.add_section(html);
    },

    // =========================================================================
    // ACTION HANDLERS
    // =========================================================================

    approve_buyer: function(frm) {
        frappe.prompt([
            {
                fieldname: 'notes',
                label: __('Verification Notes'),
                fieldtype: 'Small Text',
                description: __('Optional notes about the verification')
            }
        ], function(values) {
            frappe.call({
                method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.verify_buyer',
                args: {
                    buyer_name: frm.doc.name,
                    status: 'Verified',
                    notes: values.notes
                },
                callback: function(r) {
                    if (r.message) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('Buyer has been verified'),
                            indicator: 'green'
                        });
                    }
                }
            });
        }, __('Approve Buyer'), __('Approve'));
    },

    reject_buyer: function(frm) {
        frappe.prompt([
            {
                fieldname: 'notes',
                label: __('Rejection Reason'),
                fieldtype: 'Small Text',
                reqd: 1,
                description: __('Please provide a reason for rejection')
            }
        ], function(values) {
            frappe.call({
                method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.verify_buyer',
                args: {
                    buyer_name: frm.doc.name,
                    status: 'Rejected',
                    notes: values.notes
                },
                callback: function(r) {
                    if (r.message) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('Buyer has been rejected'),
                            indicator: 'orange'
                        });
                    }
                }
            });
        }, __('Reject Buyer'), __('Reject'));
    },

    submit_for_verification: function(frm) {
        frappe.confirm(
            __('Submit this buyer profile for verification? Make sure all required documents are uploaded.'),
            function() {
                frappe.call({
                    method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.submit_for_verification',
                    args: {
                        buyer_name: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.reload_doc();
                            frappe.show_alert({
                                message: __('Profile submitted for verification'),
                                indicator: 'blue'
                            });
                        }
                    }
                });
            }
        );
    },

    activate_buyer: function(frm) {
        frappe.confirm(
            __('Activate this buyer account?'),
            function() {
                frappe.call({
                    method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.activate_buyer',
                    args: {
                        buyer_name: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.reload_doc();
                            frappe.show_alert({
                                message: __('Buyer activated'),
                                indicator: 'green'
                            });
                        }
                    }
                });
            }
        );
    },

    suspend_buyer: function(frm) {
        frappe.prompt([
            {
                fieldname: 'reason',
                label: __('Suspension Reason'),
                fieldtype: 'Small Text',
                reqd: 1,
                description: __('Please provide a reason for suspension')
            }
        ], function(values) {
            frappe.call({
                method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.suspend_buyer',
                args: {
                    buyer_name: frm.doc.name,
                    reason: values.reason
                },
                callback: function(r) {
                    if (r.message) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('Buyer suspended'),
                            indicator: 'orange'
                        });
                    }
                }
            });
        }, __('Suspend Buyer'), __('Suspend'));
    },

    block_buyer: function(frm) {
        frappe.prompt([
            {
                fieldname: 'reason',
                label: __('Blocking Reason'),
                fieldtype: 'Small Text',
                reqd: 1,
                description: __('Please provide a reason for blocking')
            }
        ], function(values) {
            frappe.call({
                method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.block_buyer',
                args: {
                    buyer_name: frm.doc.name,
                    reason: values.reason
                },
                callback: function(r) {
                    if (r.message) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('Buyer blocked'),
                            indicator: 'red'
                        });
                    }
                }
            });
        }, __('Block Buyer'), __('Block'));
    },

    refresh_metrics: function(frm) {
        frappe.call({
            method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.update_buyer_metrics',
            args: {
                buyer_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    frm.reload_doc();
                    frappe.show_alert({
                        message: __('Metrics updated'),
                        indicator: 'green'
                    });
                }
            }
        });
    },

    check_segment_eligibility: function(frm) {
        frappe.call({
            method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.check_segment_eligibility',
            args: {
                buyer_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    if (r.message.eligible) {
                        frappe.confirm(
                            __('Buyer is eligible for segment upgrade from {0} to {1}. Upgrade now?',
                                [r.message.current_segment, r.message.recommended_segment]) +
                            '<br><br><small>' + r.message.reason + '</small>',
                            function() {
                                frappe.call({
                                    method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.upgrade_buyer_segment',
                                    args: {
                                        buyer_name: frm.doc.name,
                                        new_segment: r.message.recommended_segment
                                    },
                                    callback: function(r2) {
                                        if (r2.message) {
                                            frm.reload_doc();
                                            frappe.show_alert({
                                                message: __('Segment upgraded successfully'),
                                                indicator: 'green'
                                            });
                                        }
                                    }
                                });
                            }
                        );
                    } else {
                        frappe.msgprint({
                            title: __('Segment Eligibility'),
                            message: r.message.reason,
                            indicator: 'blue'
                        });
                    }
                }
            }
        });
    },

    change_segment: function(frm) {
        frappe.prompt([
            {
                fieldname: 'new_segment',
                label: __('New Segment'),
                fieldtype: 'Select',
                options: ['Standard', 'Silver', 'Gold', 'Platinum', 'Strategic', 'Enterprise'],
                default: frm.doc.segment,
                reqd: 1
            }
        ], function(values) {
            if (values.new_segment !== frm.doc.segment) {
                frappe.call({
                    method: 'tr_tradehub.doctype.buyer_profile.buyer_profile.upgrade_buyer_segment',
                    args: {
                        buyer_name: frm.doc.name,
                        new_segment: values.new_segment
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.reload_doc();
                            frappe.show_alert({
                                message: __('Segment changed to {0}', [values.new_segment]),
                                indicator: 'green'
                            });
                        }
                    }
                });
            }
        }, __('Change Segment'), __('Update'));
    }
});
