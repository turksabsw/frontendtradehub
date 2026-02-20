// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('KYC Profile', {
    refresh: function(frm) {
        // Set up the verification workflow display
        frm.trigger('render_verification_progress');
        frm.trigger('setup_workflow_buttons');
        frm.trigger('setup_document_actions');

        // Make tenant read-only if auto-populated
        if (frm.doc.tenant) {
            frm.set_df_property('tenant', 'read_only', 1);
        }
    },

    profile_type: function(frm) {
        // Clear the opposite profile link when type changes
        if (frm.doc.profile_type === 'Seller') {
            frm.set_value('buyer_profile', null);
            frm.set_value('buyer_name', null);
        } else {
            frm.set_value('seller_profile', null);
            frm.set_value('seller_name', null);
        }
    },

    seller_profile: function(frm) {
        // Auto-populate tenant from seller profile
        if (frm.doc.seller_profile) {
            frappe.db.get_value('Seller Profile', frm.doc.seller_profile, ['tenant', 'seller_name', 'contact_email', 'contact_phone', 'tax_id', 'tax_id_type'], (r) => {
                if (r) {
                    if (r.tenant) {
                        frm.set_value('tenant', r.tenant);
                        frm.set_df_property('tenant', 'read_only', 1);
                    }
                    // Pre-fill some fields if empty
                    if (!frm.doc.full_name && r.seller_name) {
                        frm.set_value('full_name', r.seller_name);
                    }
                    if (!frm.doc.email && r.contact_email) {
                        frm.set_value('email', r.contact_email);
                    }
                    if (!frm.doc.phone && r.contact_phone) {
                        frm.set_value('phone', r.contact_phone);
                    }
                    if (!frm.doc.tax_id && r.tax_id) {
                        frm.set_value('tax_id', r.tax_id);
                        if (r.tax_id_type) {
                            frm.set_value('tax_id_type', r.tax_id_type);
                        }
                    }
                }
            });
        }
    },

    buyer_profile: function(frm) {
        // Auto-populate fields from buyer user profile
        if (frm.doc.buyer_profile) {
            frappe.db.get_value('User', frm.doc.buyer_profile, ['full_name', 'email', 'mobile_no'], (r) => {
                if (r) {
                    if (!frm.doc.full_name && r.full_name) {
                        frm.set_value('full_name', r.full_name);
                    }
                    if (!frm.doc.email && r.email) {
                        frm.set_value('email', r.email);
                    }
                    if (!frm.doc.phone && r.mobile_no) {
                        frm.set_value('phone', r.mobile_no);
                    }
                }
            });
        }
    },

    tax_id: function(frm) {
        // Validate tax ID on change
        if (frm.doc.tax_id) {
            frm.trigger('validate_tax_id');
        }
    },

    validate_tax_id: function(frm) {
        const tax_id = frm.doc.tax_id;
        if (!tax_id) return;

        // Clean up tax ID
        const cleaned = tax_id.replace(/\s/g, '');

        // Auto-detect type based on length
        if (cleaned.length === 10) {
            frm.set_value('tax_id_type', 'VKN');
        } else if (cleaned.length === 11) {
            frm.set_value('tax_id_type', 'TCKN');
        }

        // Call server-side validation
        frappe.call({
            method: 'tr_tradehub.utils.turkish_validation.validate_tax_id_api',
            args: {
                tax_id: cleaned,
                expected_type: frm.doc.tax_id_type
            },
            callback: function(r) {
                if (r.message) {
                    const result = r.message;
                    if (result.valid) {
                        frm.set_df_property('tax_id', 'description',
                            `<span style="color: green;">&#10004; ${result.message}</span>`);
                    } else {
                        frm.set_df_property('tax_id', 'description',
                            `<span style="color: red;">&#10008; ${result.message}</span>`);
                    }
                }
            }
        });
    },

    render_verification_progress: function(frm) {
        // Render the verification progress visualization
        const wrapper = frm.fields_dict.verification_steps_html.$wrapper;
        wrapper.empty();

        const steps = [
            { name: 'Identity', field: 'identity_verification_status', icon: 'fa-user' },
            { name: 'Address', field: 'address_verification_status', icon: 'fa-map-marker' },
            { name: 'Business', field: 'business_verification_status', icon: 'fa-building' },
            { name: 'Documents', field: 'document_verification_status', icon: 'fa-file' }
        ];

        let html = '<div class="verification-progress" style="display: flex; justify-content: space-between; margin: 20px 0;">';

        steps.forEach((step, index) => {
            const status = frm.doc[step.field] || 'Pending';
            let statusClass = 'pending';
            let statusIcon = 'fa-clock-o';

            if (status === 'Passed') {
                statusClass = 'passed';
                statusIcon = 'fa-check-circle';
            } else if (status === 'Failed') {
                statusClass = 'failed';
                statusIcon = 'fa-times-circle';
            } else if (status === 'In Progress') {
                statusClass = 'in-progress';
                statusIcon = 'fa-spinner fa-spin';
            } else if (status === 'Skipped' || status === 'N/A') {
                statusClass = 'skipped';
                statusIcon = 'fa-minus-circle';
            }

            html += `
                <div class="verification-step ${statusClass}" style="text-align: center; flex: 1;">
                    <div class="step-icon" style="font-size: 24px; margin-bottom: 8px;">
                        <i class="fa ${statusIcon}"></i>
                    </div>
                    <div class="step-name" style="font-weight: bold; margin-bottom: 4px;">${step.name}</div>
                    <div class="step-status" style="font-size: 12px; color: var(--text-muted);">${status}</div>
                </div>
            `;

            // Add connector line between steps (except for last step)
            if (index < steps.length - 1) {
                html += `
                    <div class="step-connector" style="flex: 0.5; display: flex; align-items: center; justify-content: center;">
                        <div style="width: 100%; height: 2px; background-color: var(--border-color);"></div>
                    </div>
                `;
            }
        });

        html += '</div>';

        // Add CSS for status colors
        html += `
            <style>
                .verification-step.passed .step-icon { color: var(--green-500); }
                .verification-step.failed .step-icon { color: var(--red-500); }
                .verification-step.in-progress .step-icon { color: var(--blue-500); }
                .verification-step.pending .step-icon { color: var(--gray-500); }
                .verification-step.skipped .step-icon { color: var(--gray-400); }
            </style>
        `;

        wrapper.html(html);
    },

    setup_workflow_buttons: function(frm) {
        // Add workflow action buttons based on status
        if (frm.doc.docstatus === 0) {
            if (frm.doc.status === 'Draft') {
                frm.add_custom_button(__('Submit for Verification'), function() {
                    frappe.call({
                        method: 'tr_tradehub.tr_tradehub.doctype.kyc_profile.kyc_profile.submit_kyc',
                        args: { kyc_name: frm.doc.name },
                        callback: function(r) {
                            if (r.message) {
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Actions'));
            }

            if (frm.doc.status === 'Submitted' && frappe.user_roles.includes('System Manager')) {
                frm.add_custom_button(__('Start Review'), function() {
                    frappe.call({
                        method: 'tr_tradehub.tr_tradehub.doctype.kyc_profile.kyc_profile.start_review',
                        args: { kyc_name: frm.doc.name },
                        callback: function(r) {
                            if (r.message) {
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Actions'));
            }

            if (['Submitted', 'Under Review', 'Documents Requested', 'Pending Verification'].includes(frm.doc.status) &&
                frappe.user_roles.includes('System Manager')) {

                frm.add_custom_button(__('Verify'), function() {
                    frappe.prompt([
                        {
                            fieldname: 'notes',
                            fieldtype: 'Small Text',
                            label: 'Review Notes'
                        }
                    ], function(values) {
                        frappe.call({
                            method: 'tr_tradehub.tr_tradehub.doctype.kyc_profile.kyc_profile.verify_kyc',
                            args: {
                                kyc_name: frm.doc.name,
                                notes: values.notes
                            },
                            callback: function(r) {
                                if (r.message) {
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Verify KYC'), __('Verify'));
                }, __('Actions'));

                frm.add_custom_button(__('Request Documents'), function() {
                    frappe.prompt([
                        {
                            fieldname: 'notes',
                            fieldtype: 'Small Text',
                            label: 'Documents Required',
                            reqd: 1
                        }
                    ], function(values) {
                        frappe.call({
                            method: 'tr_tradehub.tr_tradehub.doctype.kyc_profile.kyc_profile.request_documents',
                            args: {
                                kyc_name: frm.doc.name,
                                notes: values.notes
                            },
                            callback: function(r) {
                                if (r.message) {
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Request Documents'), __('Request'));
                }, __('Actions'));

                frm.add_custom_button(__('Reject'), function() {
                    frappe.prompt([
                        {
                            fieldname: 'reason',
                            fieldtype: 'Small Text',
                            label: 'Rejection Reason',
                            reqd: 1
                        },
                        {
                            fieldname: 'category',
                            fieldtype: 'Select',
                            label: 'Category',
                            options: '\nInvalid Documents\nUnreadable Documents\nMismatched Information\nSuspicious Activity\nFailed Verification Check\nIncomplete Information\nExpired Documents\nOther'
                        },
                        {
                            fieldname: 'allow_resubmission',
                            fieldtype: 'Check',
                            label: 'Allow Resubmission',
                            default: 1
                        }
                    ], function(values) {
                        frappe.call({
                            method: 'tr_tradehub.tr_tradehub.doctype.kyc_profile.kyc_profile.reject_kyc',
                            args: {
                                kyc_name: frm.doc.name,
                                reason: values.reason,
                                category: values.category,
                                allow_resubmission: values.allow_resubmission
                            },
                            callback: function(r) {
                                if (r.message) {
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Reject KYC'), __('Reject'));
                }, __('Actions'));
            }

            if (frm.doc.status === 'Verified' && frappe.user_roles.includes('System Manager')) {
                frm.add_custom_button(__('Suspend'), function() {
                    frappe.prompt([
                        {
                            fieldname: 'reason',
                            fieldtype: 'Small Text',
                            label: 'Suspension Reason',
                            reqd: 1
                        }
                    ], function(values) {
                        frappe.call({
                            method: 'tr_tradehub.tr_tradehub.doctype.kyc_profile.kyc_profile.suspend_kyc',
                            args: {
                                kyc_name: frm.doc.name,
                                reason: values.reason
                            },
                            callback: function(r) {
                                if (r.message) {
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Suspend KYC'), __('Suspend'));
                }, __('Actions'));
            }
        }
    },

    setup_document_actions: function(frm) {
        // Add actions to verify/reject individual documents
        if (frm.doc.documents && frm.doc.documents.length > 0 &&
            ['Under Review', 'Pending Verification'].includes(frm.doc.status) &&
            frappe.user_roles.includes('System Manager')) {

            frm.add_custom_button(__('Verify All Documents'), function() {
                frm.doc.documents.forEach((doc, idx) => {
                    if (doc.verification_status === 'Pending' || doc.verification_status === 'In Review') {
                        frappe.call({
                            method: 'tr_tradehub.tr_tradehub.doctype.kyc_profile.kyc_profile.update_document_status',
                            args: {
                                kyc_name: frm.doc.name,
                                document_idx: idx,
                                status: 'Verified'
                            },
                            async: false
                        });
                    }
                });
                frm.reload_doc();
            }, __('Documents'));
        }
    },

    ai_audit_enabled: function(frm) {
        // Initialize AI audit when enabled
        if (frm.doc.ai_audit_enabled && frm.doc.ai_audit_status === 'Not Started') {
            frm.set_value('ai_audit_status', 'Queued');
        }
    }
});

// Child table event handlers
frappe.ui.form.on('KYC Document', {
    documents_add: function(frm, cdt, cdn) {
        // Set default verification status for new documents
        frappe.model.set_value(cdt, cdn, 'verification_status', 'Pending');
    },

    document_file: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        // Auto-set document name from file if not set
        if (row.document_file && !row.document_name) {
            const filename = row.document_file.split('/').pop();
            frappe.model.set_value(cdt, cdn, 'document_name', filename);
        }
    }
});
