// Copyright (c) 2026, TR TradeHub and contributors
// For license information, please see license.txt

/**
 * PIM Product Client Script
 *
 * This script provides dynamic form rendering for PIM Product based on
 * Product Family configuration. It:
 * - Dynamically renders attribute sections based on product_family selection
 * - Uses frm.call() to fetch family config and rebuild form sections
 * - Organizes attributes by PIM Attribute Group
 * - Manages attribute values in the child table
 * - Provides completeness tracking and display
 */

frappe.ui.form.on('PIM Product', {
    /**
     * Called when the form is refreshed
     */
    refresh: function(frm) {
        // Add custom buttons
        pim_product_add_custom_buttons(frm);

        // Render attribute sections if family is selected
        if (frm.doc.product_family && !frm.is_new()) {
            pim_product_load_family_config(frm);
        }

        // Update completeness display
        pim_product_update_completeness_display(frm);

        // Set up event handlers for attribute value changes
        pim_product_setup_attribute_handlers(frm);
    },

    /**
     * Called when form is loaded for the first time
     */
    onload: function(frm) {
        // Clear any existing custom sections when form loads
        frm.pim_custom_sections = {};
        frm.pim_attribute_fields = {};
        frm.pim_family_config = null;
    },

    /**
     * Called when product_family field changes
     */
    product_family: function(frm) {
        if (frm.doc.product_family) {
            pim_product_load_family_config(frm, true);
        } else {
            // Clear family config and custom sections when family is cleared
            pim_product_clear_custom_sections(frm);
            frm.pim_family_config = null;
        }
    },

    /**
     * Called before saving the document
     */
    before_save: function(frm) {
        // Sync UI field values to attribute_values child table
        pim_product_sync_attribute_values(frm);
    },

    /**
     * Called after the document is saved
     */
    after_save: function(frm) {
        // Recalculate completeness
        pim_product_recalculate_completeness(frm);
    }
});

/**
 * Load family configuration and rebuild attribute sections
 *
 * @param {Object} frm - The form object
 * @param {Boolean} apply_defaults - Whether to apply default values
 */
function pim_product_load_family_config(frm, apply_defaults) {
    frm.call({
        method: 'tr_tradehub.pim.api.get_family_config',
        args: {
            family: frm.doc.product_family
        },
        freeze: true,
        freeze_message: __('Loading family configuration...'),
        callback: function(r) {
            if (r.message) {
                frm.pim_family_config = r.message;
                pim_product_rebuild_attribute_sections(frm, r.message);

                if (apply_defaults) {
                    pim_product_apply_default_values(frm, r.message);
                }
            }
        },
        error: function(e) {
            frappe.msgprint({
                title: __('Error'),
                indicator: 'red',
                message: __('Failed to load family configuration. Please try again.')
            });
        }
    });
}

/**
 * Clear all custom attribute sections from the form
 *
 * @param {Object} frm - The form object
 */
function pim_product_clear_custom_sections(frm) {
    // Remove custom section elements from DOM
    if (frm.pim_custom_sections) {
        Object.keys(frm.pim_custom_sections).forEach(function(key) {
            var section = frm.pim_custom_sections[key];
            if (section && section.$wrapper) {
                section.$wrapper.remove();
            }
        });
    }

    // Clear tracking objects
    frm.pim_custom_sections = {};
    frm.pim_attribute_fields = {};
}

/**
 * Rebuild attribute sections based on family configuration
 *
 * @param {Object} frm - The form object
 * @param {Object} config - Family configuration from API
 */
function pim_product_rebuild_attribute_sections(frm, config) {
    // Clear existing custom sections first
    pim_product_clear_custom_sections(frm);

    if (!config || !config.attributes || config.attributes.length === 0) {
        return;
    }

    var attribute_groups = config.attribute_groups || [];
    var label_overrides = config.label_overrides || {};

    // Get the attributes tab wrapper
    var $attributes_tab = frm.fields_dict.attributes_tab;
    if (!$attributes_tab || !$attributes_tab.$wrapper) {
        return;
    }

    // Find the attribute_values section to insert sections before it
    var $attr_values_section = frm.fields_dict.attribute_values_section;
    var $insert_point = $attr_values_section && $attr_values_section.$wrapper
        ? $attr_values_section.$wrapper
        : null;

    // Sort attribute groups by sort_order
    attribute_groups.sort(function(a, b) {
        return (a.sort_order || 999) - (b.sort_order || 999);
    });

    // Build attributes by group for easy lookup
    var attributes_by_code = {};
    config.attributes.forEach(function(attr) {
        attributes_by_code[attr.attribute_code] = attr;
    });

    // Render each attribute group as a section
    attribute_groups.forEach(function(group) {
        if (!group.attributes || group.attributes.length === 0) {
            return;
        }

        var section_wrapper = pim_product_create_attribute_section(
            frm,
            group,
            attributes_by_code,
            label_overrides,
            $insert_point
        );

        if (section_wrapper) {
            frm.pim_custom_sections[group.group_code] = section_wrapper;
        }
    });

    // Populate fields with existing attribute values
    pim_product_populate_attribute_fields(frm);

    // Refresh the form layout
    frm.refresh_fields();
}

/**
 * Create an attribute section with fields
 *
 * @param {Object} frm - The form object
 * @param {Object} group - Attribute group configuration
 * @param {Object} attributes_by_code - Attributes lookup by code
 * @param {Object} label_overrides - Label override configurations
 * @param {jQuery} $insert_point - Element to insert section before
 * @returns {Object} Section wrapper
 */
function pim_product_create_attribute_section(frm, group, attributes_by_code, label_overrides, $insert_point) {
    // Create section HTML
    var section_id = 'pim_section_' + group.group_code;
    var icon_html = group.icon ? '<i class="' + group.icon + '"></i> ' : '';
    var collapsible_class = group.is_collapsible ? 'collapsible' : '';

    var $section = $('<div class="frappe-control pim-attribute-section ' + collapsible_class + '" data-section="' + section_id + '">');

    // Section header
    var $header = $('<div class="section-head">')
        .html(icon_html + '<span class="section-title">' + __(group.group_name) + '</span>');

    if (group.is_collapsible) {
        $header.addClass('collapsible')
            .append('<span class="collapse-indicator octicon octicon-chevron-down"></span>');
        $header.on('click', function() {
            var $body = $(this).siblings('.section-body');
            $body.toggle();
            $(this).find('.collapse-indicator')
                .toggleClass('octicon-chevron-down octicon-chevron-right');
        });
    }

    $section.append($header);

    // Section body with fields
    var $body = $('<div class="section-body">');

    // Create row for fields (two columns)
    var $row = $('<div class="form-group frappe-control" style="display: flex; flex-wrap: wrap;">');

    // Track columns
    var current_column = 0;

    group.attributes.forEach(function(attr_code) {
        var attr = attributes_by_code[attr_code];
        if (!attr) {
            return;
        }

        // Apply label overrides
        var override = label_overrides[attr_code] || {};
        var label = override.label || attr.attribute_name;
        var description = override.description || attr.description || '';
        var placeholder = override.placeholder || attr.placeholder || '';

        // Create field container
        var $field_container = $('<div class="col-sm-6 pim-attribute-field" data-attribute="' + attr_code + '">');

        // Create field based on attribute type
        var field_html = pim_product_create_attribute_field(
            frm,
            attr,
            label,
            description,
            placeholder
        );

        $field_container.html(field_html);
        $row.append($field_container);

        // Track field for later population
        frm.pim_attribute_fields[attr_code] = {
            attribute: attr,
            label: label,
            container: $field_container
        };

        current_column++;
    });

    $body.append($row);
    $section.append($body);

    // Insert section into form
    if ($insert_point) {
        $insert_point.before($section);
    } else {
        frm.fields_dict.attributes_tab.$wrapper.find('.form-layout').append($section);
    }

    // Initialize field controls
    pim_product_initialize_field_controls(frm, group.attributes, attributes_by_code);

    return {
        $wrapper: $section,
        group: group
    };
}

/**
 * Create HTML for an attribute field based on its type
 *
 * @param {Object} frm - The form object
 * @param {Object} attr - Attribute configuration
 * @param {String} label - Field label
 * @param {String} description - Field description
 * @param {String} placeholder - Field placeholder
 * @returns {String} HTML for the field
 */
function pim_product_create_attribute_field(frm, attr, label, description, placeholder) {
    var field_id = 'pim_attr_' + attr.attribute_code;
    var required_indicator = attr.is_required ? '<span class="text-danger">*</span>' : '';
    var variant_badge = attr.is_variant ? '<span class="badge badge-info ml-1">Variant</span>' : '';

    var html = '<div class="form-group">';
    html += '<label class="control-label">' + __(label) + required_indicator + variant_badge + '</label>';

    switch (attr.attribute_type) {
        case 'Text':
        case 'URL':
            html += '<input type="text" class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'placeholder="' + __(placeholder) + '" ' +
                (attr.max_length ? 'maxlength="' + attr.max_length + '"' : '') + '>';
            break;

        case 'Long Text':
            html += '<textarea class="form-control pim-attr-input" rows="3" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'placeholder="' + __(placeholder) + '" ' +
                (attr.max_length ? 'maxlength="' + attr.max_length + '"' : '') + '></textarea>';
            break;

        case 'HTML':
            html += '<div class="pim-attr-html-editor" data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '"></div>';
            break;

        case 'Int':
            html += '<input type="number" class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'step="1" ' +
                (attr.min_value !== null ? 'min="' + attr.min_value + '"' : '') +
                (attr.max_value !== null ? 'max="' + attr.max_value + '"' : '') + '>';
            break;

        case 'Float':
        case 'Currency':
        case 'Percent':
        case 'Measurement':
        case 'Rating':
            html += '<input type="number" class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'step="0.01" ' +
                (attr.min_value !== null ? 'min="' + attr.min_value + '"' : '') +
                (attr.max_value !== null ? 'max="' + attr.max_value + '"' : '') + '>';
            if (attr.attribute_type === 'Measurement' && attr.unit_of_measure) {
                html += '<small class="text-muted">' + attr.unit_of_measure + '</small>';
            }
            break;

        case 'Check':
            html += '<div class="checkbox">' +
                '<label><input type="checkbox" class="pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '"> ' +
                __(label) + '</label></div>';
            break;

        case 'Select':
            html += '<select class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '">';
            html += '<option value="">' + __('Select...') + '</option>';
            if (attr.options && attr.options.length > 0) {
                attr.options.forEach(function(opt) {
                    var opt_label = opt.label || opt.value;
                    html += '<option value="' + opt.value + '">' + __(opt_label) + '</option>';
                });
            }
            html += '</select>';
            break;

        case 'Multiselect':
            html += '<select class="form-control pim-attr-input" multiple ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '">';
            if (attr.options && attr.options.length > 0) {
                attr.options.forEach(function(opt) {
                    var opt_label = opt.label || opt.value;
                    html += '<option value="' + opt.value + '">' + __(opt_label) + '</option>';
                });
            }
            html += '</select>';
            break;

        case 'Color':
            html += '<div class="input-group">' +
                '<input type="text" class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'placeholder="#000000">' +
                '<span class="input-group-addon">' +
                '<input type="color" class="pim-color-picker" ' +
                'data-target="' + attr.attribute_code + '">' +
                '</span></div>';
            break;

        case 'Size':
            html += '<select class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '">';
            html += '<option value="">' + __('Select Size...') + '</option>';
            if (attr.options && attr.options.length > 0) {
                attr.options.forEach(function(opt) {
                    var opt_label = opt.label || opt.value;
                    html += '<option value="' + opt.value + '">' + __(opt_label) + '</option>';
                });
            }
            html += '</select>';
            break;

        case 'Date':
            html += '<input type="date" class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '">';
            break;

        case 'Datetime':
            html += '<input type="datetime-local" class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '">';
            break;

        case 'Link':
            html += '<div class="pim-attr-link-wrapper" data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'data-doctype="' + (attr.linked_doctype || '') + '"></div>';
            break;

        case 'Image':
        case 'File':
            html += '<div class="pim-attr-file-wrapper" data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '"></div>';
            break;

        case 'JSON':
        case 'Table':
            html += '<div class="pim-attr-json-wrapper" data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '">' +
                '<textarea class="form-control pim-attr-input" rows="4" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'placeholder="' + __('Enter JSON...') + '"></textarea></div>';
            break;

        default:
            // Default to text input
            html += '<input type="text" class="form-control pim-attr-input" ' +
                'data-attr-code="' + attr.attribute_code + '" ' +
                'data-attr-type="' + attr.attribute_type + '" ' +
                'placeholder="' + __(placeholder) + '">';
    }

    if (description) {
        html += '<small class="text-muted">' + __(description) + '</small>';
    }

    html += '</div>';

    return html;
}

/**
 * Initialize Frappe field controls for special field types
 *
 * @param {Object} frm - The form object
 * @param {Array} attribute_codes - List of attribute codes
 * @param {Object} attributes_by_code - Attributes lookup
 */
function pim_product_initialize_field_controls(frm, attribute_codes, attributes_by_code) {
    attribute_codes.forEach(function(attr_code) {
        var attr = attributes_by_code[attr_code];
        if (!attr) return;

        // Initialize Link fields with Frappe controls
        if (attr.attribute_type === 'Link' && attr.linked_doctype) {
            var $wrapper = frm.$wrapper.find('.pim-attr-link-wrapper[data-attr-code="' + attr_code + '"]');
            if ($wrapper.length) {
                var link_field = frappe.ui.form.make_control({
                    df: {
                        fieldtype: 'Link',
                        options: attr.linked_doctype,
                        fieldname: 'pim_link_' + attr_code,
                        label: attr.attribute_name,
                        change: function() {
                            // Value will be synced on save
                        }
                    },
                    parent: $wrapper,
                    render_input: true
                });
                link_field.refresh();

                // Store reference
                if (!frm.pim_link_controls) {
                    frm.pim_link_controls = {};
                }
                frm.pim_link_controls[attr_code] = link_field;
            }
        }

        // Initialize HTML editor fields
        if (attr.attribute_type === 'HTML') {
            var $html_wrapper = frm.$wrapper.find('.pim-attr-html-editor[data-attr-code="' + attr_code + '"]');
            if ($html_wrapper.length) {
                var html_field = frappe.ui.form.make_control({
                    df: {
                        fieldtype: 'Text Editor',
                        fieldname: 'pim_html_' + attr_code,
                        label: attr.attribute_name,
                        change: function() {
                            // Value will be synced on save
                        }
                    },
                    parent: $html_wrapper,
                    render_input: true
                });
                html_field.refresh();

                if (!frm.pim_html_controls) {
                    frm.pim_html_controls = {};
                }
                frm.pim_html_controls[attr_code] = html_field;
            }
        }

        // Initialize File/Image attachment fields
        if (attr.attribute_type === 'Image' || attr.attribute_type === 'File') {
            var $file_wrapper = frm.$wrapper.find('.pim-attr-file-wrapper[data-attr-code="' + attr_code + '"]');
            if ($file_wrapper.length) {
                var fieldtype = attr.attribute_type === 'Image' ? 'Attach Image' : 'Attach';
                var file_field = frappe.ui.form.make_control({
                    df: {
                        fieldtype: fieldtype,
                        fieldname: 'pim_file_' + attr_code,
                        label: attr.attribute_name,
                        change: function() {
                            // Value will be synced on save
                        }
                    },
                    parent: $file_wrapper,
                    render_input: true
                });
                file_field.refresh();

                if (!frm.pim_file_controls) {
                    frm.pim_file_controls = {};
                }
                frm.pim_file_controls[attr_code] = file_field;
            }
        }
    });

    // Set up color picker sync
    frm.$wrapper.find('.pim-color-picker').on('change', function() {
        var target = $(this).data('target');
        var color = $(this).val();
        frm.$wrapper.find('.pim-attr-input[data-attr-code="' + target + '"]').val(color);
    });
}

/**
 * Populate attribute fields with existing values from the child table
 *
 * @param {Object} frm - The form object
 */
function pim_product_populate_attribute_fields(frm) {
    if (!frm.doc.attribute_values || !frm.doc.attribute_values.length) {
        return;
    }

    frm.doc.attribute_values.forEach(function(attr_val) {
        var attr_code = attr_val.attribute_code;
        var attr_type = attr_val.attribute_type;

        // Get the value based on type
        var value = pim_product_get_attribute_value_from_row(attr_val, attr_type);

        // Set value in the UI field
        pim_product_set_field_value(frm, attr_code, attr_type, value);
    });
}

/**
 * Get the attribute value from a child table row
 *
 * @param {Object} row - Attribute value row
 * @param {String} attr_type - Attribute type
 * @returns {*} The attribute value
 */
function pim_product_get_attribute_value_from_row(row, attr_type) {
    switch (attr_type) {
        case 'Int':
            return row.value_int;
        case 'Float':
        case 'Currency':
        case 'Percent':
        case 'Measurement':
        case 'Rating':
            return row.value_float;
        case 'Check':
            return row.value_check;
        case 'Date':
            return row.value_date;
        case 'Datetime':
            return row.value_datetime;
        case 'Link':
            return row.value_link;
        case 'JSON':
        case 'Table':
        case 'Image':
        case 'File':
            return row.value_json;
        case 'Long Text':
            return row.value_long_text;
        case 'HTML':
            return row.value_html;
        case 'Select':
        case 'Multiselect':
            return row.value_select;
        default:
            return row.value_text;
    }
}

/**
 * Set value in a UI field
 *
 * @param {Object} frm - The form object
 * @param {String} attr_code - Attribute code
 * @param {String} attr_type - Attribute type
 * @param {*} value - Value to set
 */
function pim_product_set_field_value(frm, attr_code, attr_type, value) {
    if (value === null || value === undefined) {
        return;
    }

    // Handle special control types
    if (attr_type === 'Link' && frm.pim_link_controls && frm.pim_link_controls[attr_code]) {
        frm.pim_link_controls[attr_code].set_value(value);
        return;
    }

    if (attr_type === 'HTML' && frm.pim_html_controls && frm.pim_html_controls[attr_code]) {
        frm.pim_html_controls[attr_code].set_value(value);
        return;
    }

    if ((attr_type === 'Image' || attr_type === 'File') && frm.pim_file_controls && frm.pim_file_controls[attr_code]) {
        frm.pim_file_controls[attr_code].set_value(value);
        return;
    }

    // Handle standard input fields
    var $input = frm.$wrapper.find('.pim-attr-input[data-attr-code="' + attr_code + '"]');
    if (!$input.length) {
        return;
    }

    if (attr_type === 'Check') {
        $input.prop('checked', cint(value));
    } else if (attr_type === 'Multiselect') {
        // Split comma-separated values for multiselect
        var selected_values = (value || '').split(',').map(function(v) { return v.trim(); });
        $input.val(selected_values);
    } else {
        $input.val(value);
    }
}

/**
 * Sync UI field values to the attribute_values child table
 *
 * @param {Object} frm - The form object
 */
function pim_product_sync_attribute_values(frm) {
    if (!frm.pim_family_config || !frm.pim_family_config.attributes) {
        return;
    }

    frm.pim_family_config.attributes.forEach(function(attr) {
        var attr_code = attr.attribute_code;
        var attr_type = attr.attribute_type;

        // Get value from UI
        var value = pim_product_get_field_value(frm, attr_code, attr_type);

        // Skip empty values for non-required fields
        if ((value === null || value === undefined || value === '') && !attr.is_required) {
            return;
        }

        // Find or create row in attribute_values
        var existing_row = null;
        for (var i = 0; i < (frm.doc.attribute_values || []).length; i++) {
            if (frm.doc.attribute_values[i].attribute_code === attr_code) {
                existing_row = frm.doc.attribute_values[i];
                break;
            }
        }

        if (!existing_row) {
            // Create new row
            existing_row = frm.add_child('attribute_values', {
                pim_attribute: attr_code,
                attribute_code: attr_code,
                attribute_type: attr_type
            });
        }

        // Set value in the appropriate column
        pim_product_set_row_value(existing_row, attr_type, value);
    });

    frm.refresh_field('attribute_values');
}

/**
 * Get value from a UI field
 *
 * @param {Object} frm - The form object
 * @param {String} attr_code - Attribute code
 * @param {String} attr_type - Attribute type
 * @returns {*} The field value
 */
function pim_product_get_field_value(frm, attr_code, attr_type) {
    // Handle special control types
    if (attr_type === 'Link' && frm.pim_link_controls && frm.pim_link_controls[attr_code]) {
        return frm.pim_link_controls[attr_code].get_value();
    }

    if (attr_type === 'HTML' && frm.pim_html_controls && frm.pim_html_controls[attr_code]) {
        return frm.pim_html_controls[attr_code].get_value();
    }

    if ((attr_type === 'Image' || attr_type === 'File') && frm.pim_file_controls && frm.pim_file_controls[attr_code]) {
        return frm.pim_file_controls[attr_code].get_value();
    }

    // Handle standard input fields
    var $input = frm.$wrapper.find('.pim-attr-input[data-attr-code="' + attr_code + '"]');
    if (!$input.length) {
        return null;
    }

    if (attr_type === 'Check') {
        return $input.prop('checked') ? 1 : 0;
    } else if (attr_type === 'Multiselect') {
        var selected = $input.val() || [];
        return selected.join(',');
    } else {
        return $input.val();
    }
}

/**
 * Set value in the child table row
 *
 * @param {Object} row - Child table row
 * @param {String} attr_type - Attribute type
 * @param {*} value - Value to set
 */
function pim_product_set_row_value(row, attr_type, value) {
    // Clear all value fields first
    row.value_text = null;
    row.value_long_text = null;
    row.value_html = null;
    row.value_int = null;
    row.value_float = null;
    row.value_check = null;
    row.value_select = null;
    row.value_date = null;
    row.value_datetime = null;
    row.value_link = null;
    row.value_json = null;

    // Set the appropriate field based on type
    switch (attr_type) {
        case 'Int':
            row.value_int = cint(value);
            break;
        case 'Float':
        case 'Currency':
        case 'Percent':
        case 'Measurement':
        case 'Rating':
            row.value_float = flt(value);
            break;
        case 'Check':
            row.value_check = cint(value);
            break;
        case 'Date':
            row.value_date = value;
            break;
        case 'Datetime':
            row.value_datetime = value;
            break;
        case 'Link':
            row.value_link = value;
            break;
        case 'JSON':
        case 'Table':
        case 'Image':
        case 'File':
            row.value_json = value;
            break;
        case 'Long Text':
            row.value_long_text = value;
            break;
        case 'HTML':
            row.value_html = value;
            break;
        case 'Select':
        case 'Multiselect':
            row.value_select = value;
            break;
        default:
            row.value_text = value;
    }
}

/**
 * Apply default values from family configuration
 *
 * @param {Object} frm - The form object
 * @param {Object} config - Family configuration
 */
function pim_product_apply_default_values(frm, config) {
    var defaults = config.default_values || {};

    Object.keys(defaults).forEach(function(attr_code) {
        var default_config = defaults[attr_code];
        var value = default_config.value;

        // Find the attribute type
        var attr = null;
        for (var i = 0; i < config.attributes.length; i++) {
            if (config.attributes[i].attribute_code === attr_code) {
                attr = config.attributes[i];
                break;
            }
        }

        if (attr && value !== null && value !== undefined) {
            // Check if there's already a value
            var existing_value = pim_product_get_field_value(frm, attr_code, attr.attribute_type);
            if (!existing_value || existing_value === '') {
                pim_product_set_field_value(frm, attr_code, attr.attribute_type, value);
            }
        }
    });
}

/**
 * Add custom buttons to the form
 *
 * @param {Object} frm - The form object
 */
function pim_product_add_custom_buttons(frm) {
    if (frm.is_new()) {
        return;
    }

    // Recalculate Completeness button
    frm.add_custom_button(__('Recalculate Completeness'), function() {
        pim_product_recalculate_completeness(frm, true);
    }, __('Actions'));

    // Generate Variants button (if family has variant axes)
    if (frm.pim_family_config && frm.pim_family_config.variant_axes && frm.pim_family_config.variant_axes.length > 0) {
        frm.add_custom_button(__('Generate Variants'), function() {
            pim_product_show_variant_dialog(frm);
        }, __('Actions'));

        frm.add_custom_button(__('View Variant Matrix'), function() {
            pim_product_show_variant_matrix(frm);
        }, __('Actions'));
    }

    // Export Preview button
    frm.add_custom_button(__('Export Preview'), function() {
        pim_product_show_export_preview(frm);
    }, __('Actions'));
}

/**
 * Update completeness display in the form
 *
 * @param {Object} frm - The form object
 */
function pim_product_update_completeness_display(frm) {
    // Update completeness indicator in the form
    var score = frm.doc.completeness_score || 0;
    var status = frm.doc.completeness_status || 'Incomplete';

    var indicator_class = 'gray';
    if (score >= 90) {
        indicator_class = 'green';
    } else if (score >= 70) {
        indicator_class = 'blue';
    } else if (score >= 50) {
        indicator_class = 'orange';
    } else if (score > 0) {
        indicator_class = 'red';
    }

    // Update indicator if available
    if (frm.page && frm.page.set_indicator) {
        frm.page.set_indicator(__(status) + ' (' + score + '%)', indicator_class);
    }
}

/**
 * Recalculate completeness score
 *
 * @param {Object} frm - The form object
 * @param {Boolean} show_dialog - Whether to show the results in a dialog
 */
function pim_product_recalculate_completeness(frm, show_dialog) {
    frm.call({
        method: 'tr_tradehub.pim.api.recalculate_completeness',
        args: {
            product: frm.doc.name,
            update_product: 1
        },
        callback: function(r) {
            if (r.message) {
                // Update form fields
                frm.set_value('completeness_score', r.message.score);
                frm.set_value('completeness_status', r.message.status);
                frm.set_value('completeness_detail', JSON.stringify(r.message.detail, null, 2));
                frm.set_value('last_completeness_check', frappe.datetime.now_datetime());

                // Update display
                pim_product_update_completeness_display(frm);

                if (show_dialog) {
                    pim_product_show_completeness_dialog(frm, r.message);
                }
            }
        }
    });
}

/**
 * Show completeness details dialog
 *
 * @param {Object} frm - The form object
 * @param {Object} completeness - Completeness data
 */
function pim_product_show_completeness_dialog(frm, completeness) {
    var detail = completeness.detail || {};

    var html = '<div class="pim-completeness-details">';
    html += '<h4>' + __('Completeness Score') + ': <span class="text-primary">' + completeness.score + '%</span></h4>';
    html += '<p><strong>' + __('Status') + ':</strong> ' + completeness.status + '</p>';

    if (detail.missing_required && detail.missing_required.length > 0) {
        html += '<h5 class="text-danger">' + __('Missing Required Fields') + '</h5>';
        html += '<ul>';
        detail.missing_required.forEach(function(field) {
            html += '<li>' + field + '</li>';
        });
        html += '</ul>';
    }

    if (detail.categories) {
        html += '<h5>' + __('Category Breakdown') + '</h5>';
        html += '<table class="table table-bordered">';
        html += '<thead><tr><th>' + __('Category') + '</th><th>' + __('Score') + '</th></tr></thead>';
        html += '<tbody>';
        Object.keys(detail.categories).forEach(function(cat) {
            html += '<tr><td>' + cat + '</td><td>' + detail.categories[cat] + '%</td></tr>';
        });
        html += '</tbody></table>';
    }

    html += '</div>';

    frappe.msgprint({
        title: __('Completeness Details'),
        indicator: completeness.score >= 70 ? 'green' : 'orange',
        message: html
    });
}

/**
 * Show variant generation dialog
 *
 * @param {Object} frm - The form object
 */
function pim_product_show_variant_dialog(frm) {
    var dialog = new frappe.ui.Dialog({
        title: __('Generate Variants'),
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'info',
                options: '<p>' + __('Generate variants based on the variant axes defined in the Product Family.') + '</p>'
            },
            {
                fieldtype: 'Check',
                fieldname: 'skip_existing',
                label: __('Skip Existing Variants'),
                default: 1
            },
            {
                fieldtype: 'Check',
                fieldname: 'preview_only',
                label: __('Preview Only'),
                default: 0
            }
        ],
        primary_action_label: __('Generate'),
        primary_action: function(values) {
            frm.call({
                method: 'tr_tradehub.pim.api.generate_variants',
                args: {
                    product: frm.doc.name,
                    skip_existing: values.skip_existing ? 1 : 0,
                    preview_only: values.preview_only ? 1 : 0
                },
                freeze: true,
                freeze_message: __('Generating variants...'),
                callback: function(r) {
                    if (r.message) {
                        dialog.hide();
                        frappe.msgprint({
                            title: __('Variant Generation Result'),
                            indicator: r.message.success ? 'green' : 'orange',
                            message: __('Total combinations: {0}<br>Created: {1}<br>Skipped: {2}',
                                [r.message.total_combinations || 0, r.message.created || 0, r.message.skipped || 0])
                        });
                        frm.reload_doc();
                    }
                }
            });
        }
    });

    dialog.show();
}

/**
 * Show variant matrix view
 *
 * @param {Object} frm - The form object
 */
function pim_product_show_variant_matrix(frm) {
    frm.call({
        method: 'tr_tradehub.pim.api.get_variant_matrix',
        args: {
            product: frm.doc.name
        },
        freeze: true,
        freeze_message: __('Loading variant matrix...'),
        callback: function(r) {
            if (r.message) {
                pim_product_render_variant_matrix_dialog(frm, r.message);
            }
        }
    });
}

/**
 * Render variant matrix in a dialog
 *
 * @param {Object} frm - The form object
 * @param {Object} matrix_data - Variant matrix data
 */
function pim_product_render_variant_matrix_dialog(frm, matrix_data) {
    var html = '<div class="pim-variant-matrix">';
    html += '<p><strong>' + __('Product') + ':</strong> ' + matrix_data.product_name + '</p>';
    html += '<p><strong>' + __('Total Combinations') + ':</strong> ' + matrix_data.possible_combinations + '</p>';
    html += '<p><strong>' + __('Existing Variants') + ':</strong> ' + matrix_data.existing_count + '</p>';

    if (matrix_data.existing_variants && matrix_data.existing_variants.length > 0) {
        html += '<table class="table table-bordered table-striped">';
        html += '<thead><tr><th>' + __('Variant Code') + '</th><th>' + __('SKU') + '</th><th>' + __('Status') + '</th></tr></thead>';
        html += '<tbody>';
        matrix_data.existing_variants.forEach(function(variant) {
            html += '<tr>';
            html += '<td><a href="/app/pim-product-variant/' + variant.name + '">' + variant.variant_code + '</a></td>';
            html += '<td>' + (variant.sku || '-') + '</td>';
            html += '<td>' + (variant.status || '-') + '</td>';
            html += '</tr>';
        });
        html += '</tbody></table>';
    }

    html += '</div>';

    frappe.msgprint({
        title: __('Variant Matrix'),
        message: html,
        wide: true
    });
}

/**
 * Show export preview dialog
 *
 * @param {Object} frm - The form object
 */
function pim_product_show_export_preview(frm) {
    // First, get available channels
    frm.call({
        method: 'tr_tradehub.pim.api.get_product_channels',
        args: {
            product: frm.doc.name
        },
        callback: function(r) {
            var channels = r.message || [];

            if (channels.length === 0) {
                frappe.msgprint(__('No channels configured for this product family.'));
                return;
            }

            var channel_options = channels.map(function(ch) {
                return {
                    label: ch.channel_name,
                    value: ch.channel
                };
            });

            var dialog = new frappe.ui.Dialog({
                title: __('Export Preview'),
                fields: [
                    {
                        fieldtype: 'Select',
                        fieldname: 'channel',
                        label: __('Sales Channel'),
                        options: channel_options,
                        reqd: 1
                    }
                ],
                primary_action_label: __('Preview'),
                primary_action: function(values) {
                    frm.call({
                        method: 'tr_tradehub.pim.api.export_to_channel',
                        args: {
                            product: frm.doc.name,
                            channel: values.channel,
                            preview_only: 1
                        },
                        callback: function(r) {
                            if (r.message) {
                                dialog.hide();
                                pim_product_show_export_data_dialog(r.message);
                            }
                        }
                    });
                }
            });

            dialog.show();
        }
    });
}

/**
 * Show export data in a dialog
 *
 * @param {Object} export_data - Export preview data
 */
function pim_product_show_export_data_dialog(export_data) {
    var html = '<div class="pim-export-preview">';
    html += '<pre style="max-height: 400px; overflow: auto;">';
    html += JSON.stringify(export_data, null, 2);
    html += '</pre>';
    html += '</div>';

    frappe.msgprint({
        title: __('Export Preview'),
        message: html,
        wide: true
    });
}

/**
 * Set up event handlers for attribute value changes
 *
 * @param {Object} frm - The form object
 */
function pim_product_setup_attribute_handlers(frm) {
    // Debounced handler for input changes
    var debounced_change = frappe.utils.debounce(function() {
        frm.dirty();
    }, 500);

    // Attach change handlers to all attribute inputs
    frm.$wrapper.on('change input', '.pim-attr-input', debounced_change);
}

// Child table event handlers for attribute_values
frappe.ui.form.on('PIM Product Attribute Value', {
    pim_attribute: function(frm, cdt, cdn) {
        // When attribute is changed, update the attribute_code and type
        var row = locals[cdt][cdn];
        if (row.pim_attribute) {
            frappe.db.get_value('PIM Attribute', row.pim_attribute, ['attribute_code', 'attribute_type'], function(r) {
                if (r) {
                    frappe.model.set_value(cdt, cdn, 'attribute_code', r.attribute_code);
                    frappe.model.set_value(cdt, cdn, 'attribute_type', r.attribute_type);
                }
            });
        }
    }
});
