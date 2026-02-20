/**
 * ECA Rule Form JavaScript
 * Visual condition builder and action configuration UI
 *
 * This script enhances the ECA Rule form with:
 * - Visual condition builder for easier rule configuration
 * - Dynamic field suggestions based on selected DocType
 * - Operator descriptions and guidance
 * - Action type-specific field visibility
 * - Test condition evaluation
 * - Template preview functionality
 */

frappe.ui.form.on('ECA Rule', {
    /**
     * Form setup - called once when form loads
     */
    setup: function(frm) {
        // Cache for doctype fields to avoid repeated API calls
        frm.doctype_fields_cache = {};

        // Operator descriptions for help text
        frm.operator_descriptions = {
            '==': __('Equals - Exact match'),
            '!=': __('Not Equals - Does not match'),
            '>': __('Greater Than - Numeric comparison'),
            '>=': __('Greater Than or Equal - Numeric comparison'),
            '<': __('Less Than - Numeric comparison'),
            '<=': __('Less Than or Equal - Numeric comparison'),
            'in': __('In List - Value exists in comma-separated list'),
            'not_in': __('Not In List - Value does not exist in list'),
            'contains': __('Contains - Substring match (case-insensitive)'),
            'not_contains': __('Not Contains - Substring not found'),
            'starts_with': __('Starts With - String prefix match'),
            'ends_with': __('Ends With - String suffix match'),
            'is_set': __('Is Set - Field has a value (not null/empty)'),
            'is_not_set': __('Is Not Set - Field is null or empty'),
            'regex_match': __('Regex Match - Regular expression pattern'),
            'date_before': __('Date Before - Date comparison'),
            'date_after': __('Date After - Date comparison'),
            'between': __('Between - Value within range (format: min,max)'),
            'is_empty': __('Is Empty - Null, empty string, empty list, or empty object'),
            'changed': __('Changed - Field value changed from previous state'),
            'changed_to': __('Changed To - Field changed TO this specific value'),
            'changed_from': __('Changed From - Field changed FROM this specific value')
        };

        // Action type configurations for dynamic field visibility
        frm.action_type_config = {
            'Update Field': { requires: ['target'], optional: ['field_mapping_json'] },
            'Create Document': { requires: ['target'], optional: ['field_mapping_json'] },
            'Delete Document': { requires: ['target'], optional: [] },
            'Send Notification': { requires: ['notification'], optional: [] },
            'Send Email': { requires: ['notification'], optional: [] },
            'Create Notification Log': { requires: ['notification'], optional: [] },
            'Webhook': { requires: ['webhook'], optional: [] },
            'Custom Python': { requires: ['code'], optional: [] },
            'Set Workflow State': { requires: ['target'], optional: ['field_mapping_json'] },
            'Add Comment': { requires: ['notification'], optional: [] },
            'Add Tag': { requires: ['target'], optional: [] },
            'Remove Tag': { requires: ['target'], optional: [] },
            'Create Todo': { requires: ['notification', 'target'], optional: [] },
            'Enqueue Job': { requires: ['code'], optional: [] },
            'Call API': { requires: ['webhook'], optional: [] },
            'Assign To': { requires: ['notification', 'target'], optional: [] }
        };
    },

    /**
     * Form refresh - called when form data is loaded/refreshed
     */
    refresh: function(frm) {
        // Add custom buttons
        eca_rule_add_custom_buttons(frm);

        // Initialize visual condition builder
        eca_rule_init_condition_builder(frm);

        // Update condition groups visualization
        eca_rule_visualize_conditions(frm);

        // Set up field path autocomplete if doctype is selected
        if (frm.doc.event_doctype) {
            eca_rule_setup_field_autocomplete(frm);
        }

        // Apply status-based styling
        eca_rule_apply_status_styling(frm);

        // Show statistics if rule has been executed
        if (frm.doc.total_executions > 0) {
            eca_rule_show_statistics_summary(frm);
        }
    },

    /**
     * Event DocType changed - update field suggestions
     */
    event_doctype: function(frm) {
        if (frm.doc.event_doctype) {
            eca_rule_setup_field_autocomplete(frm);

            // Clear cached fields for previous doctype
            frm.trigger('refresh');
        }
    },

    /**
     * Condition logic changed - update visualization
     */
    condition_logic: function(frm) {
        eca_rule_visualize_conditions(frm);
    },

    /**
     * Enabled checkbox changed
     */
    enabled: function(frm) {
        if (frm.doc.enabled && frm.doc.status === 'Draft') {
            frappe.show_alert({
                message: __('Remember to set status to "Active" after saving'),
                indicator: 'orange'
            });
        }
    },

    /**
     * Status changed
     */
    status: function(frm) {
        eca_rule_apply_status_styling(frm);
    },

    /**
     * Before save - validate configuration
     */
    before_save: function(frm) {
        // Validate conditions have required fields
        let validation_errors = eca_rule_validate_configuration(frm);
        if (validation_errors.length > 0) {
            frappe.throw(validation_errors.join('<br>'));
        }
    },

    /**
     * After save - show success message with next steps
     */
    after_save: function(frm) {
        if (frm.doc.status === 'Draft' && frm.doc.enabled) {
            frappe.show_alert({
                message: __('Rule saved. Set status to "Active" to enable automatic execution.'),
                indicator: 'blue'
            });
        }
    }
});

/**
 * ECA Rule Condition child table events
 */
frappe.ui.form.on('ECA Rule Condition', {
    /**
     * New condition row added
     */
    conditions_add: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Set default condition group based on existing conditions
        let max_group = 1;
        (frm.doc.conditions || []).forEach(c => {
            if (c.condition_group > max_group) {
                max_group = c.condition_group;
            }
        });
        row.condition_group = max_group;

        frm.refresh_field('conditions');
        eca_rule_visualize_conditions(frm);
    },

    /**
     * Condition row removed
     */
    conditions_remove: function(frm) {
        eca_rule_visualize_conditions(frm);
    },

    /**
     * Condition group changed
     */
    condition_group: function(frm) {
        eca_rule_visualize_conditions(frm);
    },

    /**
     * Group logic changed
     */
    group_logic: function(frm) {
        eca_rule_visualize_conditions(frm);
    },

    /**
     * Operator changed - show description
     */
    operator: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.operator && frm.operator_descriptions[row.operator]) {
            frappe.show_alert({
                message: frm.operator_descriptions[row.operator],
                indicator: 'blue'
            }, 3);
        }

        // Update value placeholder based on operator
        eca_rule_update_value_placeholder(frm, row);
    },

    /**
     * Field path changed - validate and suggest
     */
    field_path: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.field_path && frm.doc.event_doctype) {
            eca_rule_validate_field_path(frm, row.field_path);
        }
    }
});

/**
 * ECA Rule Action child table events
 */
frappe.ui.form.on('ECA Rule Action', {
    /**
     * New action row added
     */
    actions_add: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Set sequence based on existing actions
        let max_seq = 0;
        (frm.doc.actions || []).forEach(a => {
            if (a.sequence > max_seq) {
                max_seq = a.sequence;
            }
        });
        row.sequence = max_seq + 1;

        frm.refresh_field('actions');
    },

    /**
     * Action type changed - show relevant fields
     */
    action_type: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        if (row.action_type) {
            // Show guidance for selected action type
            eca_rule_show_action_guidance(frm, row.action_type);
        }

        frm.refresh_field('actions');
    },

    /**
     * Template fields changed - preview
     */
    subject_template: function(frm, cdt, cdn) {
        eca_rule_preview_template(frm, cdt, cdn, 'subject_template');
    },

    message_template: function(frm, cdt, cdn) {
        eca_rule_preview_template(frm, cdt, cdn, 'message_template');
    }
});


// =============================================================================
// CUSTOM BUTTONS
// =============================================================================

/**
 * Add custom buttons to the form
 */
function eca_rule_add_custom_buttons(frm) {
    if (!frm.is_new()) {
        // Test Conditions button
        frm.add_custom_button(__('Test Conditions'), function() {
            eca_rule_test_conditions(frm);
        }, __('Actions'));

        // Preview Template button
        frm.add_custom_button(__('Preview Templates'), function() {
            eca_rule_preview_all_templates(frm);
        }, __('Actions'));

        // View Execution Logs button
        frm.add_custom_button(__('View Logs'), function() {
            frappe.set_route('List', 'ECA Rule Log', {
                eca_rule: frm.doc.name
            });
        }, __('Actions'));

        // Duplicate Rule button
        frm.add_custom_button(__('Duplicate'), function() {
            eca_rule_duplicate_rule(frm);
        }, __('Actions'));

        // Add Condition Group button
        frm.add_custom_button(__('Add Condition Group'), function() {
            eca_rule_add_condition_group(frm);
        }, __('Builder'));

        // Import/Export buttons
        frm.add_custom_button(__('Export Rule'), function() {
            eca_rule_export_rule(frm);
        }, __('Data'));

        if (frappe.user.has_role('System Manager')) {
            // Manually Trigger (for testing)
            frm.add_custom_button(__('Trigger Manually'), function() {
                eca_rule_manual_trigger(frm);
            }, __('Actions'));
        }
    }
}


// =============================================================================
// VISUAL CONDITION BUILDER
// =============================================================================

/**
 * Initialize the visual condition builder interface
 */
function eca_rule_init_condition_builder(frm) {
    // Add visual builder container before conditions table
    let $conditions_wrapper = frm.fields_dict.conditions.$wrapper;

    // Remove existing visual builder if present
    $conditions_wrapper.find('.eca-condition-builder').remove();

    // Add visual builder HTML
    let builder_html = `
        <div class="eca-condition-builder" style="margin-bottom: 15px;">
            <div class="eca-builder-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h6 style="margin: 0;">${__('Condition Builder')}</h6>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-default btn-xs eca-toggle-builder" title="${__('Toggle Visual Builder')}">
                        <i class="fa fa-eye"></i> ${__('Visual')}
                    </button>
                    <button class="btn btn-default btn-xs eca-toggle-table" title="${__('Toggle Table View')}">
                        <i class="fa fa-table"></i> ${__('Table')}
                    </button>
                </div>
            </div>
            <div class="eca-builder-content">
                <div class="eca-condition-groups"></div>
                <div class="eca-builder-actions" style="margin-top: 10px;">
                    <button class="btn btn-default btn-sm eca-add-group">
                        <i class="fa fa-plus"></i> ${__('Add Condition Group')}
                    </button>
                </div>
            </div>
        </div>
    `;

    $conditions_wrapper.prepend(builder_html);

    // Set up event handlers
    $conditions_wrapper.find('.eca-add-group').on('click', function() {
        eca_rule_add_condition_group(frm);
    });

    $conditions_wrapper.find('.eca-toggle-builder').on('click', function() {
        $conditions_wrapper.find('.eca-builder-content').show();
        $conditions_wrapper.find('.frappe-control[data-fieldname="conditions"]').hide();
        $(this).addClass('btn-primary').removeClass('btn-default');
        $conditions_wrapper.find('.eca-toggle-table').addClass('btn-default').removeClass('btn-primary');
    });

    $conditions_wrapper.find('.eca-toggle-table').on('click', function() {
        $conditions_wrapper.find('.eca-builder-content').hide();
        $conditions_wrapper.find('.frappe-control[data-fieldname="conditions"]').show();
        $(this).addClass('btn-primary').removeClass('btn-default');
        $conditions_wrapper.find('.eca-toggle-builder').addClass('btn-default').removeClass('btn-primary');
    });
}

/**
 * Visualize conditions as grouped cards
 */
function eca_rule_visualize_conditions(frm) {
    let $groups_container = frm.fields_dict.conditions.$wrapper.find('.eca-condition-groups');
    $groups_container.empty();

    if (!frm.doc.conditions || frm.doc.conditions.length === 0) {
        $groups_container.html(`
            <div class="text-muted text-center" style="padding: 20px;">
                ${__('No conditions defined. Add conditions using the table below or click "Add Condition Group".')}
            </div>
        `);
        return;
    }

    // Group conditions by condition_group
    let groups = {};
    frm.doc.conditions.forEach((condition, idx) => {
        let group_num = condition.condition_group || 1;
        if (!groups[group_num]) {
            groups[group_num] = {
                logic: condition.group_logic || 'AND',
                conditions: []
            };
        }
        groups[group_num].conditions.push({
            idx: idx,
            ...condition
        });
    });

    // Get top-level logic
    let top_logic = frm.doc.condition_logic || 'AND';

    // Build visual representation
    let group_nums = Object.keys(groups).sort((a, b) => parseInt(a) - parseInt(b));

    group_nums.forEach((group_num, group_idx) => {
        let group = groups[group_num];

        // Add logic connector between groups
        if (group_idx > 0) {
            $groups_container.append(`
                <div class="eca-logic-connector" style="text-align: center; margin: 10px 0;">
                    <span class="badge badge-${top_logic === 'AND' ? 'primary' : 'warning'}"
                          style="font-size: 12px; padding: 5px 15px;">
                        ${top_logic}
                    </span>
                </div>
            `);
        }

        // Build group card
        let group_html = `
            <div class="eca-condition-group card" style="margin-bottom: 10px;" data-group="${group_num}">
                <div class="card-header" style="padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
                    <span><strong>${__('Group')} ${group_num}</strong>
                        <span class="badge badge-${group.logic === 'AND' ? 'info' : 'success'}" style="margin-left: 5px;">
                            ${group.logic}
                        </span>
                    </span>
                    <button class="btn btn-xs btn-danger eca-remove-group" data-group="${group_num}" title="${__('Remove Group')}">
                        <i class="fa fa-trash"></i>
                    </button>
                </div>
                <div class="card-body" style="padding: 10px;">
        `;

        // Add conditions
        group.conditions.forEach((cond, cond_idx) => {
            if (cond_idx > 0) {
                group_html += `
                    <div class="text-center text-muted" style="margin: 5px 0; font-size: 11px;">
                        ${group.logic}
                    </div>
                `;
            }

            group_html += `
                <div class="eca-condition-item" style="background: #f5f7fa; padding: 8px 12px; border-radius: 4px; margin-bottom: 5px; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <code style="background: #e9ecef; padding: 2px 6px; border-radius: 3px;">${frappe.utils.escape_html(cond.field_path || '')}</code>
                        <span class="badge badge-secondary" style="margin: 0 5px;">${frappe.utils.escape_html(cond.operator || '')}</span>
                        <code style="background: #e9ecef; padding: 2px 6px; border-radius: 3px;">${frappe.utils.escape_html(cond.value || '(empty)')}</code>
                        <small class="text-muted" style="margin-left: 5px;">(${cond.value_type || 'String'})</small>
                    </div>
                    <button class="btn btn-xs btn-default eca-edit-condition" data-idx="${cond.idx}" title="${__('Edit')}">
                        <i class="fa fa-pencil"></i>
                    </button>
                </div>
            `;
        });

        // Add "Add Condition" button
        group_html += `
                    <button class="btn btn-xs btn-default eca-add-condition" data-group="${group_num}" style="margin-top: 5px;">
                        <i class="fa fa-plus"></i> ${__('Add Condition')}
                    </button>
                </div>
            </div>
        `;

        $groups_container.append(group_html);
    });

    // Set up event handlers for group actions
    $groups_container.find('.eca-remove-group').on('click', function() {
        let group_num = parseInt($(this).data('group'));
        eca_rule_remove_condition_group(frm, group_num);
    });

    $groups_container.find('.eca-add-condition').on('click', function() {
        let group_num = parseInt($(this).data('group'));
        eca_rule_add_condition_to_group(frm, group_num);
    });

    $groups_container.find('.eca-edit-condition').on('click', function() {
        let idx = parseInt($(this).data('idx'));
        // Scroll to and highlight the condition row in the table
        let grid = frm.fields_dict.conditions.grid;
        if (grid.grid_rows[idx]) {
            grid.grid_rows[idx].toggle_view(true);
        }
    });
}

/**
 * Add a new condition group
 */
function eca_rule_add_condition_group(frm) {
    // Find the max group number
    let max_group = 0;
    (frm.doc.conditions || []).forEach(c => {
        if (c.condition_group > max_group) {
            max_group = c.condition_group;
        }
    });

    let new_group = max_group + 1;

    // Add a new condition with the new group number
    let child = frm.add_child('conditions');
    child.condition_group = new_group;
    child.group_logic = 'AND';
    child.value_type = 'String';

    frm.refresh_field('conditions');
    eca_rule_visualize_conditions(frm);

    frappe.show_alert({
        message: __('Added Group {0}. Now add conditions to this group.', [new_group]),
        indicator: 'green'
    });
}

/**
 * Add a condition to a specific group
 */
function eca_rule_add_condition_to_group(frm, group_num) {
    // Get the group logic from existing conditions in this group
    let group_logic = 'AND';
    (frm.doc.conditions || []).forEach(c => {
        if (c.condition_group === group_num) {
            group_logic = c.group_logic || 'AND';
        }
    });

    let child = frm.add_child('conditions');
    child.condition_group = group_num;
    child.group_logic = group_logic;
    child.value_type = 'String';

    frm.refresh_field('conditions');
    eca_rule_visualize_conditions(frm);

    // Open the new row for editing
    let grid = frm.fields_dict.conditions.grid;
    grid.grid_rows[grid.grid_rows.length - 1].toggle_view(true);
}

/**
 * Remove all conditions in a group
 */
function eca_rule_remove_condition_group(frm, group_num) {
    frappe.confirm(
        __('Remove all conditions in Group {0}?', [group_num]),
        function() {
            // Remove conditions in reverse order to maintain indices
            let indices_to_remove = [];
            (frm.doc.conditions || []).forEach((c, idx) => {
                if (c.condition_group === group_num) {
                    indices_to_remove.push(idx);
                }
            });

            indices_to_remove.reverse().forEach(idx => {
                frm.doc.conditions.splice(idx, 1);
            });

            frm.refresh_field('conditions');
            eca_rule_visualize_conditions(frm);

            frappe.show_alert({
                message: __('Group {0} removed', [group_num]),
                indicator: 'orange'
            });
        }
    );
}


// =============================================================================
// FIELD PATH AUTOCOMPLETE
// =============================================================================

/**
 * Set up field path autocomplete based on selected DocType
 */
function eca_rule_setup_field_autocomplete(frm) {
    if (!frm.doc.event_doctype) return;

    // Fetch doctype fields if not cached
    if (!frm.doctype_fields_cache[frm.doc.event_doctype]) {
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'DocField',
                filters: {
                    parent: frm.doc.event_doctype,
                    fieldtype: ['not in', ['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Fold']]
                },
                fields: ['fieldname', 'label', 'fieldtype', 'options'],
                limit_page_length: 0
            },
            async: false,
            callback: function(r) {
                if (r.message) {
                    frm.doctype_fields_cache[frm.doc.event_doctype] = r.message;
                    eca_rule_setup_field_autocomplete_handlers(frm);
                }
            }
        });
    } else {
        eca_rule_setup_field_autocomplete_handlers(frm);
    }
}

/**
 * Set up autocomplete handlers for field_path fields
 */
function eca_rule_setup_field_autocomplete_handlers(frm) {
    let fields = frm.doctype_fields_cache[frm.doc.event_doctype] || [];

    // Build autocomplete options
    let options = fields.map(f => ({
        value: f.fieldname,
        label: `${f.fieldname} (${f.label}) - ${f.fieldtype}`,
        fieldtype: f.fieldtype,
        options: f.options
    }));

    // Add common nested paths
    fields.forEach(f => {
        if (f.fieldtype === 'Link' && f.options) {
            options.push({
                value: `${f.fieldname}.name`,
                label: `${f.fieldname}.name (Linked ${f.options} - name)`,
                fieldtype: 'Data'
            });
        }
        if (f.fieldtype === 'Table' && f.options) {
            options.push({
                value: `${f.fieldname}[0].`,
                label: `${f.fieldname}[0]. (First ${f.options} row)`,
                fieldtype: 'Table'
            });
        }
    });

    // Store options for use in condition rows
    frm.field_path_options = options;
}

/**
 * Validate field path exists in doctype
 */
function eca_rule_validate_field_path(frm, field_path) {
    if (!frm.field_path_options) return;

    // Extract base field name
    let base_field = field_path.split('.')[0].replace(/\[\d+\]/, '');

    let valid = frm.field_path_options.some(opt => {
        return opt.value.startsWith(base_field);
    });

    if (!valid) {
        frappe.show_alert({
            message: __('Field "{0}" not found in {1}. Please verify the field path.', [base_field, frm.doc.event_doctype]),
            indicator: 'orange'
        }, 5);
    }
}


// =============================================================================
// ACTION HELPERS
// =============================================================================

/**
 * Show guidance for selected action type
 */
function eca_rule_show_action_guidance(frm, action_type) {
    let guidance = {
        'Update Field': __('Update fields on the trigger document. Use Field Mapping JSON to specify field-value pairs.'),
        'Create Document': __('Create a new document. Specify Target DocType and use Field Mapping for initial values.'),
        'Delete Document': __('Delete the trigger document or a related document. Use with caution!'),
        'Send Notification': __('Create a Notification Log entry. Configure recipient and message.'),
        'Send Email': __('Send an email to specified recipients. Configure subject and message templates.'),
        'Create Notification Log': __('Create a notification visible in Frappe\'s notification panel.'),
        'Webhook': __('Send HTTP request to external service. Configure URL, method, and payload.'),
        'Custom Python': __('Execute custom Python code using frappe.safe_exec(). Use with caution!'),
        'Set Workflow State': __('Change the workflow state of the document.'),
        'Add Comment': __('Add a comment to the document. Good for audit trail.'),
        'Add Tag': __('Add a tag to the document.'),
        'Remove Tag': __('Remove a tag from the document.'),
        'Create Todo': __('Create a ToDo item for a user.'),
        'Enqueue Job': __('Queue a background job. Specify job function in Python Code.'),
        'Call API': __('Call an internal or external API endpoint.'),
        'Assign To': __('Assign the document to a user or role.')
    };

    if (guidance[action_type]) {
        frappe.show_alert({
            message: guidance[action_type],
            indicator: 'blue'
        }, 5);
    }
}


// =============================================================================
// TESTING & PREVIEW
// =============================================================================

/**
 * Test conditions against a sample document
 */
function eca_rule_test_conditions(frm) {
    if (!frm.doc.event_doctype) {
        frappe.msgprint(__('Please select an Event DocType first.'));
        return;
    }

    // Dialog to select test document
    let d = new frappe.ui.Dialog({
        title: __('Test Conditions'),
        fields: [
            {
                fieldname: 'test_doc',
                fieldtype: 'Link',
                label: __('Test Document'),
                options: frm.doc.event_doctype,
                reqd: 1,
                description: __('Select a document to test conditions against')
            }
        ],
        primary_action_label: __('Test'),
        primary_action: function(values) {
            d.hide();
            eca_rule_execute_condition_test(frm, values.test_doc);
        }
    });
    d.show();
}

/**
 * Execute condition test against a document
 */
function eca_rule_execute_condition_test(frm, test_doc_name) {
    frappe.call({
        method: 'tr_tradehub.eca.handlers.test_rule_conditions',
        args: {
            rule_name: frm.doc.name,
            doctype: frm.doc.event_doctype,
            docname: test_doc_name
        },
        freeze: true,
        freeze_message: __('Testing conditions...'),
        callback: function(r) {
            if (r.message) {
                eca_rule_show_test_results(frm, r.message);
            }
        },
        error: function(r) {
            frappe.msgprint({
                title: __('Test Error'),
                message: r.message || __('An error occurred while testing conditions.'),
                indicator: 'red'
            });
        }
    });
}

/**
 * Display condition test results
 */
function eca_rule_show_test_results(frm, results) {
    let overall_result = results.result ?
        '<span class="text-success"><strong>' + __('PASS') + '</strong></span>' :
        '<span class="text-danger"><strong>' + __('FAIL') + '</strong></span>';

    let details_html = '<table class="table table-bordered">';
    details_html += `<tr><th>${__('Field Path')}</th><th>${__('Operator')}</th><th>${__('Expected')}</th><th>${__('Actual')}</th><th>${__('Result')}</th></tr>`;

    (results.details || []).forEach(detail => {
        let result_badge = detail.passed ?
            '<span class="badge badge-success">Pass</span>' :
            '<span class="badge badge-danger">Fail</span>';

        details_html += `
            <tr>
                <td><code>${frappe.utils.escape_html(detail.field_path)}</code></td>
                <td>${frappe.utils.escape_html(detail.operator)}</td>
                <td>${frappe.utils.escape_html(detail.expected)}</td>
                <td>${frappe.utils.escape_html(detail.actual)}</td>
                <td>${result_badge}</td>
            </tr>
        `;
    });

    details_html += '</table>';

    frappe.msgprint({
        title: __('Condition Test Results'),
        message: `
            <div style="margin-bottom: 15px;">
                ${__('Overall Result')}: ${overall_result}
            </div>
            <div>
                <h6>${__('Condition Details')}</h6>
                ${details_html}
            </div>
        `,
        indicator: results.result ? 'green' : 'red'
    });
}

/**
 * Preview a template field
 */
function eca_rule_preview_template(frm, cdt, cdn, fieldname) {
    let row = locals[cdt][cdn];
    let template = row[fieldname];

    if (!template || !template.includes('{{')) {
        return; // Not a Jinja template
    }

    // Show preview hint
    frappe.show_alert({
        message: __('Template detected. Use "Preview Templates" to see rendered output.'),
        indicator: 'blue'
    }, 3);
}

/**
 * Preview all templates in actions
 */
function eca_rule_preview_all_templates(frm) {
    if (!frm.doc.event_doctype) {
        frappe.msgprint(__('Please select an Event DocType first.'));
        return;
    }

    // Dialog to select sample document for preview
    let d = new frappe.ui.Dialog({
        title: __('Preview Templates'),
        fields: [
            {
                fieldname: 'sample_doc',
                fieldtype: 'Link',
                label: __('Sample Document'),
                options: frm.doc.event_doctype,
                reqd: 1,
                description: __('Select a document to use as context for template rendering')
            }
        ],
        primary_action_label: __('Preview'),
        primary_action: function(values) {
            d.hide();
            eca_rule_render_template_preview(frm, values.sample_doc);
        }
    });
    d.show();
}

/**
 * Render and display template preview
 */
function eca_rule_render_template_preview(frm, sample_doc_name) {
    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: frm.doc.event_doctype,
            name: sample_doc_name
        },
        callback: function(r) {
            if (r.message) {
                let doc = r.message;
                let previews = [];

                (frm.doc.actions || []).forEach((action, idx) => {
                    let action_previews = [];

                    if (action.subject_template) {
                        action_previews.push({
                            field: 'Subject',
                            template: action.subject_template,
                            rendered: eca_rule_simple_template_render(action.subject_template, doc)
                        });
                    }

                    if (action.message_template) {
                        action_previews.push({
                            field: 'Message',
                            template: action.message_template,
                            rendered: eca_rule_simple_template_render(action.message_template, doc)
                        });
                    }

                    if (action_previews.length > 0) {
                        previews.push({
                            action_num: idx + 1,
                            action_type: action.action_type,
                            templates: action_previews
                        });
                    }
                });

                if (previews.length === 0) {
                    frappe.msgprint(__('No templates found in actions.'));
                    return;
                }

                eca_rule_display_template_previews(previews);
            }
        }
    });
}

/**
 * Simple client-side template rendering (for preview only)
 */
function eca_rule_simple_template_render(template, doc) {
    try {
        // Simple replacement of {{ doc.field }} patterns
        return template.replace(/\{\{\s*doc\.(\w+)\s*\}\}/g, function(match, field) {
            return doc[field] !== undefined ? doc[field] : match;
        }).replace(/\{\{\s*user\s*\}\}/g, frappe.session.user);
    } catch (e) {
        return template + ' (preview error)';
    }
}

/**
 * Display template previews in a dialog
 */
function eca_rule_display_template_previews(previews) {
    let html = '';

    previews.forEach(preview => {
        html += `<div class="mb-3"><strong>${__('Action')} ${preview.action_num}: ${preview.action_type}</strong></div>`;

        preview.templates.forEach(t => {
            html += `
                <div class="card mb-2">
                    <div class="card-header"><small>${t.field}</small></div>
                    <div class="card-body">
                        <div><small class="text-muted">${__('Template')}:</small><br><code>${frappe.utils.escape_html(t.template)}</code></div>
                        <hr>
                        <div><small class="text-muted">${__('Rendered')}:</small><br>${frappe.utils.escape_html(t.rendered)}</div>
                    </div>
                </div>
            `;
        });
    });

    frappe.msgprint({
        title: __('Template Preview'),
        message: html,
        wide: true
    });
}


// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Apply status-based styling to the form
 */
function eca_rule_apply_status_styling(frm) {
    // Remove existing status classes
    $(frm.wrapper).removeClass('eca-status-draft eca-status-active eca-status-paused eca-status-error eca-status-deprecated');

    // Add current status class
    if (frm.doc.status) {
        $(frm.wrapper).addClass('eca-status-' + frm.doc.status.toLowerCase());
    }

    // Update page indicator based on status
    let indicator = {
        'Draft': 'orange',
        'Active': 'green',
        'Paused': 'yellow',
        'Error': 'red',
        'Deprecated': 'grey'
    }[frm.doc.status] || 'blue';

    frm.page.set_indicator(frm.doc.status, indicator);
}

/**
 * Show statistics summary
 */
function eca_rule_show_statistics_summary(frm) {
    let stats_html = `
        <div class="eca-stats-summary" style="background: #f5f7fa; padding: 10px; border-radius: 4px; margin-bottom: 15px;">
            <div class="row">
                <div class="col-sm-6">
                    <strong>${__('Total Executions')}:</strong> ${frm.doc.total_executions || 0}
                </div>
                <div class="col-sm-6">
                    <strong>${__('Last Executed')}:</strong> ${frm.doc.last_executed ? frappe.datetime.prettyDate(frm.doc.last_executed) : __('Never')}
                </div>
            </div>
        </div>
    `;

    // Add to statistics section
    let $stats_section = frm.fields_dict.statistics_section.$wrapper;
    $stats_section.find('.eca-stats-summary').remove();
    $stats_section.prepend(stats_html);
}

/**
 * Validate rule configuration
 */
function eca_rule_validate_configuration(frm) {
    let errors = [];

    // Validate conditions have required fields
    (frm.doc.conditions || []).forEach((c, idx) => {
        if (!c.field_path) {
            errors.push(__('Condition #{0}: Field Path is required', [idx + 1]));
        }
        if (!c.operator) {
            errors.push(__('Condition #{0}: Operator is required', [idx + 1]));
        }
    });

    // Validate actions have required fields
    (frm.doc.actions || []).forEach((a, idx) => {
        if (!a.action_type) {
            errors.push(__('Action #{0}: Action Type is required', [idx + 1]));
        }

        // Action-specific validation
        if (a.action_type === 'Webhook' && !a.webhook_url) {
            errors.push(__('Action #{0}: Webhook URL is required for Webhook action', [idx + 1]));
        }
        if (a.action_type === 'Custom Python' && !a.python_code) {
            errors.push(__('Action #{0}: Python Code is required for Custom Python action', [idx + 1]));
        }
        if (['Send Notification', 'Send Email'].includes(a.action_type) && !a.recipient_type) {
            errors.push(__('Action #{0}: Recipient Type is required', [idx + 1]));
        }
    });

    return errors;
}

/**
 * Update value placeholder based on operator
 */
function eca_rule_update_value_placeholder(frm, row) {
    let placeholders = {
        'between': __('min,max (e.g., 10,100)'),
        'in': __('value1,value2,value3'),
        'not_in': __('value1,value2,value3'),
        'regex_match': __('regex pattern (e.g., ^[A-Z]+$)'),
        'date_before': __('date or {{now()}}'),
        'date_after': __('date or {{now()}}'),
        'is_set': __('(no value needed)'),
        'is_not_set': __('(no value needed)'),
        'is_empty': __('(no value needed)'),
        'changed': __('(no value needed)'),
        'changed_to': __('new value'),
        'changed_from': __('old value')
    };

    // Note: In Frappe, updating placeholder for child table fields is tricky
    // This is just for documentation/guidance purposes
}

/**
 * Duplicate the current rule
 */
function eca_rule_duplicate_rule(frm) {
    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'ECA Rule',
            name: frm.doc.name
        },
        callback: function(r) {
            if (r.message) {
                let new_doc = r.message;

                // Clear unique fields
                delete new_doc.name;
                delete new_doc.naming_series;
                new_doc.rule_name = new_doc.rule_name + ' (Copy)';
                new_doc.status = 'Draft';
                new_doc.enabled = 0;
                new_doc.last_executed = null;
                new_doc.total_executions = 0;

                // Clear child table names
                (new_doc.conditions || []).forEach(c => delete c.name);
                (new_doc.actions || []).forEach(a => delete a.name);

                frappe.model.with_doctype('ECA Rule', function() {
                    let doc = frappe.model.get_new_doc('ECA Rule');
                    Object.assign(doc, new_doc);
                    frappe.set_route('Form', 'ECA Rule', doc.name);

                    frappe.show_alert({
                        message: __('Rule duplicated. Please review and save.'),
                        indicator: 'green'
                    });
                });
            }
        }
    });
}

/**
 * Export rule as JSON
 */
function eca_rule_export_rule(frm) {
    let export_data = {
        rule_name: frm.doc.rule_name,
        event_doctype: frm.doc.event_doctype,
        event_type: frm.doc.event_type,
        condition_logic: frm.doc.condition_logic,
        conditions: frm.doc.conditions,
        actions: frm.doc.actions,
        priority: frm.doc.priority,
        enable_rate_limit: frm.doc.enable_rate_limit,
        rate_limit_count: frm.doc.rate_limit_count,
        rate_limit_seconds: frm.doc.rate_limit_seconds,
        prevent_circular: frm.doc.prevent_circular,
        max_chain_depth: frm.doc.max_chain_depth
    };

    let data_str = JSON.stringify(export_data, null, 2);
    let blob = new Blob([data_str], {type: 'application/json'});
    let url = URL.createObjectURL(blob);

    let a = document.createElement('a');
    a.href = url;
    a.download = `eca_rule_${frm.doc.name}.json`;
    a.click();

    URL.revokeObjectURL(url);

    frappe.show_alert({
        message: __('Rule exported'),
        indicator: 'green'
    });
}

/**
 * Manually trigger rule for testing
 */
function eca_rule_manual_trigger(frm) {
    if (!frm.doc.event_doctype) {
        frappe.msgprint(__('Please select an Event DocType first.'));
        return;
    }

    let d = new frappe.ui.Dialog({
        title: __('Manually Trigger Rule'),
        fields: [
            {
                fieldname: 'trigger_doc',
                fieldtype: 'Link',
                label: __('Document'),
                options: frm.doc.event_doctype,
                reqd: 1,
                description: __('Select a document to trigger the rule against')
            },
            {
                fieldname: 'warning',
                fieldtype: 'HTML',
                options: `<div class="alert alert-warning">${__('Warning: This will execute actions on the selected document if conditions pass.')}</div>`
            }
        ],
        primary_action_label: __('Trigger'),
        primary_action: function(values) {
            d.hide();

            frappe.call({
                method: 'tr_tradehub.eca.handlers.manually_trigger_rules',
                args: {
                    doctype: frm.doc.event_doctype,
                    docname: values.trigger_doc,
                    rule_name: frm.doc.name
                },
                freeze: true,
                freeze_message: __('Triggering rule...'),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __('Trigger Result'),
                            message: __('Rule triggered. Check ECA Rule Logs for execution details.'),
                            indicator: 'green'
                        });

                        // Refresh to show updated statistics
                        frm.reload_doc();
                    }
                }
            });
        }
    });
    d.show();
}


// =============================================================================
// CUSTOM STYLES
// =============================================================================

// Add custom styles for the condition builder
frappe.dom.set_style(`
    .eca-condition-builder {
        border: 1px solid #d1d8dd;
        border-radius: 4px;
        padding: 15px;
        background: #fff;
    }

    .eca-condition-group {
        border: 1px solid #d1d8dd;
    }

    .eca-condition-group .card-header {
        background: #f5f7fa;
    }

    .eca-logic-connector {
        position: relative;
    }

    .eca-logic-connector::before,
    .eca-logic-connector::after {
        content: '';
        position: absolute;
        top: 50%;
        width: 30%;
        height: 1px;
        background: #d1d8dd;
    }

    .eca-logic-connector::before {
        left: 0;
    }

    .eca-logic-connector::after {
        right: 0;
    }

    .eca-status-active .page-head {
        border-bottom-color: #36b37e;
    }

    .eca-status-error .page-head {
        border-bottom-color: #ff5630;
    }

    .eca-status-paused .page-head {
        border-bottom-color: #ffab00;
    }

    .eca-condition-item:hover {
        background: #e9ecef !important;
    }
`);
