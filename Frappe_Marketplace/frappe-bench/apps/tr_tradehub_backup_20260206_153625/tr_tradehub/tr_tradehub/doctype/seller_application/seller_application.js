// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Seller Application', {
    refresh: function(frm) {
        // Set up workflow action buttons based on status
        frm.trigger('setup_workflow_buttons');

        // Show status indicator
        frm.trigger('show_status_indicator');

        // Set up field visibility based on applicant type
        frm.trigger('toggle_business_fields');

        // Add custom buttons for approved applications
        if (frm.doc.status === 'Approved') {
            frm.trigger('add_approved_links');
        }
    },

    setup_workflow_buttons: function(frm) {
        // Remove existing custom buttons
        frm.clear_custom_buttons();

        const status = frm.doc.status;

        // Draft: Show Submit button
        if (status === 'Draft' && !frm.is_new()) {
            frm.add_custom_button(__('Submit Application'), function() {
                frm.trigger('submit_application');
            }, __('Actions'));
        }

        // Submitted: Show Start Review button (for admins)
        if (status === 'Submitted' && frappe.user.has_role('System Manager')) {
            frm.add_custom_button(__('Start Review'), function() {
                frm.trigger('start_review');
            }, __('Actions'));
        }

        // Under Review / Submitted: Show Approve, Reject, Request Documents buttons (for admins)
        if (['Submitted', 'Under Review', 'Documents Requested'].includes(status) && frappe.user.has_role('System Manager')) {
            frm.add_custom_button(__('Approve'), function() {
                frm.trigger('approve_application');
            }, __('Actions'));

            frm.add_custom_button(__('Reject'), function() {
                frm.trigger('reject_application');
            }, __('Actions'));

            if (status !== 'Documents Requested') {
                frm.add_custom_button(__('Request Documents'), function() {
                    frm.trigger('request_documents');
                }, __('Actions'));
            }
        }

        // Non-approved: Show Cancel button
        if (!['Approved', 'Cancelled'].includes(status)) {
            frm.add_custom_button(__('Cancel Application'), function() {
                frm.trigger('cancel_application');
            }, __('Actions'));
        }

        // Highlight the Actions button
        frm.change_custom_button_type(__('Actions'), null, 'primary');
    },

    show_status_indicator: function(frm) {
        const status_colors = {
            'Draft': 'gray',
            'Submitted': 'blue',
            'Under Review': 'orange',
            'Documents Requested': 'yellow',
            'Approved': 'green',
            'Rejected': 'red',
            'Cancelled': 'darkgray'
        };

        const color = status_colors[frm.doc.status] || 'gray';
        frm.page.set_indicator(__(frm.doc.status), color);
    },

    toggle_business_fields: function(frm) {
        // Show/hide business-specific fields based on applicant type
        const is_business = ['Business', 'Enterprise'].includes(frm.doc.applicant_type);

        frm.toggle_reqd('business_name', is_business && ['Submitted', 'Under Review', 'Approved'].includes(frm.doc.status));

        // Auto-detect tax ID type based on applicant type
        if (frm.doc.applicant_type === 'Individual' && !frm.doc.tax_id_type) {
            frm.set_value('tax_id_type', 'TCKN');
        } else if (is_business && !frm.doc.tax_id_type) {
            frm.set_value('tax_id_type', 'VKN');
        }
    },

    add_approved_links: function(frm) {
        // Add links to created records
        if (frm.doc.seller_profile) {
            frm.add_custom_button(__('View Seller Profile'), function() {
                frappe.set_route('Form', 'Seller Profile', frm.doc.seller_profile);
            }, __('Links'));
        }

        if (frm.doc.erpnext_supplier) {
            frm.add_custom_button(__('View Supplier'), function() {
                frappe.set_route('Form', 'Supplier', frm.doc.erpnext_supplier);
            }, __('Links'));
        }

        if (frm.doc.organization) {
            frm.add_custom_button(__('View Organization'), function() {
                frappe.set_route('Form', 'Organization', frm.doc.organization);
            }, __('Links'));
        }
    },

    applicant_type: function(frm) {
        frm.trigger('toggle_business_fields');
    },

    // Workflow Action Handlers
    submit_application: function(frm) {
        frappe.confirm(
            __('Are you sure you want to submit this application? You will not be able to edit it after submission.'),
            function() {
                frappe.call({
                    method: 'tr_tradehub.tr_tradehub.doctype.seller_application.seller_application.submit_application',
                    args: {
                        application_name: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frappe.show_alert({
                                message: __('Application submitted successfully'),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }
        );
    },

    start_review: function(frm) {
        frappe.call({
            method: 'tr_tradehub.tr_tradehub.doctype.seller_application.seller_application.start_review',
            args: {
                application_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    frappe.show_alert({
                        message: __('Review started'),
                        indicator: 'blue'
                    });
                    frm.reload_doc();
                }
            }
        });
    },

    approve_application: function(frm) {
        // Show dialog to select tier and commission plan
        let d = new frappe.ui.Dialog({
            title: __('Approve Application'),
            fields: [
                {
                    label: __('Approved Tier'),
                    fieldname: 'approved_tier',
                    fieldtype: 'Link',
                    options: 'Seller Level',
                    default: frm.doc.requested_tier
                },
                {
                    label: __('Commission Plan'),
                    fieldname: 'commission_plan',
                    fieldtype: 'Link',
                    options: 'Commission Plan'
                },
                {
                    label: __('Approval Notes'),
                    fieldname: 'notes',
                    fieldtype: 'Small Text'
                }
            ],
            primary_action_label: __('Approve'),
            primary_action: function(values) {
                frappe.call({
                    method: 'tr_tradehub.tr_tradehub.doctype.seller_application.seller_application.approve_application',
                    args: {
                        application_name: frm.doc.name,
                        approved_tier: values.approved_tier,
                        commission_plan: values.commission_plan,
                        notes: values.notes
                    },
                    callback: function(r) {
                        if (r.message) {
                            d.hide();
                            frappe.show_alert({
                                message: __('Application approved! Seller Profile and Supplier created.'),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }
        });
        d.show();
    },

    reject_application: function(frm) {
        let d = new frappe.ui.Dialog({
            title: __('Reject Application'),
            fields: [
                {
                    label: __('Rejection Reason'),
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    reqd: 1
                },
                {
                    label: __('Allow Reapplication'),
                    fieldname: 'allow_reapplication',
                    fieldtype: 'Check',
                    default: 1
                },
                {
                    label: __('Reapplication After'),
                    fieldname: 'reapplication_after',
                    fieldtype: 'Date',
                    depends_on: 'eval:doc.allow_reapplication',
                    default: frappe.datetime.add_days(frappe.datetime.nowdate(), 30)
                }
            ],
            primary_action_label: __('Reject'),
            primary_action: function(values) {
                frappe.call({
                    method: 'tr_tradehub.tr_tradehub.doctype.seller_application.seller_application.reject_application',
                    args: {
                        application_name: frm.doc.name,
                        reason: values.reason,
                        allow_reapplication: values.allow_reapplication,
                        reapplication_after: values.reapplication_after
                    },
                    callback: function(r) {
                        if (r.message) {
                            d.hide();
                            frappe.show_alert({
                                message: __('Application rejected'),
                                indicator: 'red'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }
        });
        d.show();
    },

    request_documents: function(frm) {
        let d = new frappe.ui.Dialog({
            title: __('Request Additional Documents'),
            fields: [
                {
                    label: __('Documents Required'),
                    fieldname: 'notes',
                    fieldtype: 'Small Text',
                    reqd: 1,
                    description: __('Describe what documents are needed from the applicant')
                }
            ],
            primary_action_label: __('Request Documents'),
            primary_action: function(values) {
                frappe.call({
                    method: 'tr_tradehub.tr_tradehub.doctype.seller_application.seller_application.request_documents',
                    args: {
                        application_name: frm.doc.name,
                        notes: values.notes
                    },
                    callback: function(r) {
                        if (r.message) {
                            d.hide();
                            frappe.show_alert({
                                message: __('Document request sent'),
                                indicator: 'yellow'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }
        });
        d.show();
    },

    cancel_application: function(frm) {
        frappe.confirm(
            __('Are you sure you want to cancel this application?'),
            function() {
                let d = new frappe.ui.Dialog({
                    title: __('Cancel Application'),
                    fields: [
                        {
                            label: __('Reason for Cancellation'),
                            fieldname: 'reason',
                            fieldtype: 'Small Text'
                        }
                    ],
                    primary_action_label: __('Cancel Application'),
                    primary_action: function(values) {
                        frappe.call({
                            method: 'tr_tradehub.tr_tradehub.doctype.seller_application.seller_application.cancel_application',
                            args: {
                                application_name: frm.doc.name,
                                reason: values.reason
                            },
                            callback: function(r) {
                                if (r.message) {
                                    d.hide();
                                    frappe.show_alert({
                                        message: __('Application cancelled'),
                                        indicator: 'gray'
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                });
                d.show();
            }
        );
    },

    // Tax ID validation
    tax_id: function(frm) {
        if (!frm.doc.tax_id) {
            frm.set_df_property('tax_id', 'description', __('VKN (10 digits) or TCKN (11 digits)'));
            return;
        }

        // Clean the tax ID
        const cleanId = frm.doc.tax_id.replace(/\s/g, '');
        frm.set_value('tax_id', cleanId);

        // Auto-detect type based on length
        if (cleanId.length === 10) {
            frm.set_value('tax_id_type', 'VKN');
        } else if (cleanId.length === 11) {
            frm.set_value('tax_id_type', 'TCKN');
        }

        // Validate via API if available
        if (cleanId.length === 10 || cleanId.length === 11) {
            frappe.call({
                method: 'tr_tradehub.utils.turkish_validation.validate_tax_id_api',
                args: {
                    tax_id: cleanId,
                    tax_id_type: frm.doc.tax_id_type
                },
                callback: function(r) {
                    if (r.message) {
                        const result = r.message;
                        let indicator = result.valid ? 'green' : 'red';
                        let icon = result.valid ? '&check;' : '&times;';

                        frm.set_df_property('tax_id', 'description',
                            `<span style="color: ${indicator};">${icon}</span> ${result.message}`
                        );
                    }
                }
            });
        }
    },

    // IBAN formatting
    iban: function(frm) {
        if (frm.doc.iban) {
            // Clean and format IBAN
            let iban = frm.doc.iban.replace(/\s/g, '').toUpperCase();
            frm.set_value('iban', iban);

            // Basic validation for Turkish IBAN
            if (frm.doc.country === 'Turkey' || iban.startsWith('TR')) {
                if (iban.length !== 26) {
                    frm.set_df_property('iban', 'description',
                        '<span style="color: orange;">Turkish IBAN should be 26 characters</span>'
                    );
                } else if (!iban.startsWith('TR')) {
                    frm.set_df_property('iban', 'description',
                        '<span style="color: orange;">Turkish IBAN should start with TR</span>'
                    );
                } else {
                    frm.set_df_property('iban', 'description',
                        '<span style="color: green;">&check; Valid format</span>'
                    );
                }
            }
        }
    }
});
