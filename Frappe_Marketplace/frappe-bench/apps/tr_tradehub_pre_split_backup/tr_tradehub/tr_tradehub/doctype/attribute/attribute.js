// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Attribute', {
    setup: function(frm) {
        // Set up child table query filters in setup for proper initialization
        // This is critical - set_query MUST be in setup or onload
    },

    refresh: function(frm) {
        // Show/hide sections based on attribute type
        toggle_type_specific_sections(frm);

        // Add custom button to copy attribute
        if (!frm.is_new()) {
            frm.add_custom_button(__('Duplicate'), function() {
                duplicate_attribute(frm);
            }, __('Actions'));

            frm.add_custom_button(__('View Listings Using This Attribute'), function() {
                frappe.set_route('List', 'Listing', {
                    'attributes.attribute': frm.doc.name
                });
            }, __('Actions'));
        }

        // Display attribute values count
        if (frm.doc.attribute_type === 'Select' || frm.doc.attribute_type === 'Color') {
            let values_count = (frm.doc.attribute_values || []).length;
            frm.dashboard.set_headline(
                __('Attribute Type: {0} | Values: {1}', [frm.doc.attribute_type, values_count])
            );
        }
    },

    attribute_type: function(frm) {
        // Handle attribute type change
        toggle_type_specific_sections(frm);

        // Clear type-specific fields when type changes
        if (frm.doc.attribute_type === 'Select' || frm.doc.attribute_type === 'Color') {
            // Clear numeric fields
            frm.set_value('numeric_min', null);
            frm.set_value('numeric_max', null);
            frm.set_value('numeric_step', null);
            frm.set_value('numeric_unit', null);
        } else if (frm.doc.attribute_type === 'Numeric') {
            // Clear attribute values when switching to Numeric
            if (frm.doc.attribute_values && frm.doc.attribute_values.length > 0) {
                frappe.confirm(
                    __('Switching to Numeric type will clear existing attribute values. Continue?'),
                    function() {
                        frm.clear_table('attribute_values');
                        frm.refresh_field('attribute_values');
                    },
                    function() {
                        // Revert to previous type
                        frm.set_value('attribute_type', 'Select');
                    }
                );
            }
        } else {
            // For Text, Boolean, Date types - clear both
            frm.set_value('numeric_min', null);
            frm.set_value('numeric_max', null);
            frm.set_value('numeric_step', null);
            frm.set_value('numeric_unit', null);
        }

        // Show alert about type implications
        if (frm.doc.attribute_type === 'Boolean') {
            frappe.show_alert({
                message: __('Boolean attributes have only Yes/No values'),
                indicator: 'blue'
            });
        } else if (frm.doc.attribute_type === 'Numeric') {
            frappe.show_alert({
                message: __('Set min, max, step, and unit in the Numeric Settings section'),
                indicator: 'blue'
            });
        }
    },

    is_variant: function(frm) {
        // When marking as variant attribute, suggest making it required
        if (frm.doc.is_variant && !frm.doc.is_required) {
            frappe.confirm(
                __('Variant attributes are typically required. Would you like to mark this attribute as required?'),
                function() {
                    frm.set_value('is_required', 1);
                }
            );
        }
    },

    validate: function(frm) {
        // Validate based on attribute type
        if (frm.doc.attribute_type === 'Select' || frm.doc.attribute_type === 'Color') {
            if (!frm.doc.attribute_values || frm.doc.attribute_values.length === 0) {
                frappe.msgprint({
                    title: __('Validation Warning'),
                    message: __('Select and Color type attributes should have at least one value defined'),
                    indicator: 'orange'
                });
            }
        }

        if (frm.doc.attribute_type === 'Numeric') {
            if (frm.doc.numeric_min && frm.doc.numeric_max) {
                if (flt(frm.doc.numeric_min) >= flt(frm.doc.numeric_max)) {
                    frappe.throw(__('Numeric Min must be less than Numeric Max'));
                }
            }
        }
    }
});

/**
 * Toggle visibility of type-specific sections
 */
function toggle_type_specific_sections(frm) {
    let is_select_or_color = (frm.doc.attribute_type === 'Select' || frm.doc.attribute_type === 'Color');
    let is_numeric = (frm.doc.attribute_type === 'Numeric');

    // Show/hide values section
    frm.toggle_display('values_section', is_select_or_color);
    frm.toggle_display('attribute_values', is_select_or_color);

    // Show/hide numeric section
    frm.toggle_display('numeric_section', is_numeric);
    frm.toggle_display('numeric_min', is_numeric);
    frm.toggle_display('numeric_max', is_numeric);
    frm.toggle_display('numeric_step', is_numeric);
    frm.toggle_display('numeric_unit', is_numeric);
}

/**
 * Duplicate the current attribute
 */
function duplicate_attribute(frm) {
    frappe.prompt([
        {
            fieldname: 'new_name',
            fieldtype: 'Data',
            label: __('New Attribute Name'),
            reqd: 1,
            default: frm.doc.attribute_name + ' (Copy)'
        }
    ], function(values) {
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'Attribute',
                name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    let new_doc = frappe.model.copy_doc(r.message);
                    new_doc.attribute_name = values.new_name;
                    new_doc.attribute_label = values.new_name;
                    frappe.set_route('Form', 'Attribute', new_doc.name);
                }
            }
        });
    }, __('Duplicate Attribute'));
}

// =====================================================
// Attribute Value Child Table Events
// =====================================================

frappe.ui.form.on('Attribute Value', {
    attribute_value: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Auto-generate abbreviation if not set
        if (row.attribute_value && !row.abbreviation) {
            // Generate abbreviation: first 3 characters uppercase
            let abbr = row.attribute_value.substring(0, 3).toUpperCase();
            frappe.model.set_value(cdt, cdn, 'abbreviation', abbr);
        }
    },

    attribute_values_add: function(frm, cdt, cdn) {
        // Set default display_order for new row
        let row = locals[cdt][cdn];
        let max_order = 0;
        (frm.doc.attribute_values || []).forEach(function(r) {
            if (r.display_order && r.display_order > max_order) {
                max_order = r.display_order;
            }
        });
        frappe.model.set_value(cdt, cdn, 'display_order', max_order + 10);
    }
});
