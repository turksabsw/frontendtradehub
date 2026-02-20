// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Marketplace Shipment', {
    refresh: function(frm) {
        // Set up UOM field filters
        setup_uom_filters(frm);

        // Add delivery action buttons
        if (!frm.is_new()) {
            add_action_buttons(frm);
        }

        // Show delivery status indicators
        update_status_indicator(frm);
    },

    onload: function(frm) {
        // Set up UOM filters on load
        setup_uom_filters(frm);
    },

    sub_order: function(frm) {
        // When sub_order is selected, auto-populate related fields
        if (frm.doc.sub_order) {
            frappe.db.get_doc('Sub Order', frm.doc.sub_order).then(sub_order => {
                // Populate seller from sub order
                if (sub_order.seller && !frm.doc.seller) {
                    frm.set_value('seller', sub_order.seller);
                }

                // Populate shipping address if not set
                const address_fields = [
                    ['recipient_name', 'shipping_address_name'],
                    ['address_line1', 'shipping_address_line1'],
                    ['address_line2', 'shipping_address_line2'],
                    ['city', 'shipping_city'],
                    ['state', 'shipping_state'],
                    ['postal_code', 'shipping_postal_code'],
                    ['country', 'shipping_country'],
                    ['recipient_phone', 'shipping_phone']
                ];

                address_fields.forEach(([shipment_field, sub_order_field]) => {
                    if (sub_order[sub_order_field] && !frm.doc[shipment_field]) {
                        frm.set_value(shipment_field, sub_order[sub_order_field]);
                    }
                });

                frm.refresh_fields();
            });
        }
    },

    seller: function(frm) {
        // Auto-populate tenant when seller is selected
        if (frm.doc.seller) {
            frappe.db.get_value('Seller Profile', frm.doc.seller, ['tenant', 'seller_name'], (r) => {
                if (r) {
                    if (r.tenant) {
                        frm.set_value('tenant', r.tenant);
                    }
                    frm.set_df_property('tenant', 'read_only', 1);
                }
            });
        }
    },

    logistics_provider: function(frm) {
        // Auto-generate tracking URL when provider is changed
        if (frm.doc.logistics_provider && frm.doc.tracking_number) {
            generate_tracking_url(frm);
        }
    },

    tracking_number: function(frm) {
        // Clean tracking number and generate URL
        if (frm.doc.tracking_number) {
            frm.set_value('tracking_number', frm.doc.tracking_number.trim().toUpperCase());
            if (frm.doc.logistics_provider) {
                generate_tracking_url(frm);
            }
        }
    },

    receiver_signature: function(frm) {
        // Auto-set signature captured timestamp
        if (frm.doc.receiver_signature && !frm.doc.signature_captured_at) {
            frm.set_value('signature_captured_at', frappe.datetime.now_datetime());
        }
    },

    status: function(frm) {
        // Handle status changes
        update_status_indicator(frm);

        // If status is Delivered, show received_by prompt if empty
        if (frm.doc.status === 'Delivered' && frm.doc.requires_signature && !frm.doc.received_by) {
            frappe.msgprint({
                title: __('Proof of Delivery'),
                message: __('Please fill in the "Received By" field and capture signature for proof of delivery.'),
                indicator: 'orange'
            });
        }
    },

    package_length: function(frm) {
        calculate_volume(frm);
    },

    package_width: function(frm) {
        calculate_volume(frm);
    },

    package_height: function(frm) {
        calculate_volume(frm);
    }
});

function setup_uom_filters(frm) {
    // Filter weight_uom to show only weight units
    frm.set_query('weight_uom', function() {
        return {
            filters: {
                'name': ['in', [
                    'Kilogram', 'Gram', 'Pound', 'Ounce', 'Kg', 'Gm',
                    'g', 'kg', 'lb', 'oz', 'Milligram', 'Ton'
                ]]
            }
        };
    });

    // Filter dimension_uom to show only length units
    frm.set_query('dimension_uom', function() {
        return {
            filters: {
                'name': ['in', [
                    'Centimeter', 'Meter', 'Inch', 'Foot', 'Cm', 'M',
                    'cm', 'm', 'in', 'ft', 'Millimeter', 'Yard'
                ]]
            }
        };
    });

    // Filter volume_uom to show only volume units
    frm.set_query('volume_uom', function() {
        return {
            filters: {
                'name': ['in', [
                    'Cubic Meter', 'Cubic Centimeter', 'Liter', 'Cubic Foot',
                    'Cubic Inch', 'Milliliter', 'Gallon'
                ]]
            }
        };
    });

    // Filter declared_currency and cod_currency
    frm.set_query('declared_currency', function() {
        return {
            filters: {
                'enabled': 1
            }
        };
    });

    frm.set_query('cod_currency', function() {
        return {
            filters: {
                'enabled': 1
            }
        };
    });
}

function add_action_buttons(frm) {
    // Mark as Delivered button
    if (['Out for Delivery', 'In Transit', 'Picked Up'].includes(frm.doc.status)) {
        frm.add_custom_button(__('Mark as Delivered'), function() {
            show_delivery_dialog(frm);
        }, __('Actions'));
    }

    // Verify POD button
    if (frm.doc.status === 'Delivered' && !frm.doc.pod_verified) {
        if (frm.doc.receiver_signature || frm.doc.proof_of_delivery) {
            frm.add_custom_button(__('Verify POD'), function() {
                frappe.call({
                    method: 'tr_tradehub.tr_tradehub.doctype.marketplace_shipment.marketplace_shipment.verify_pod',
                    args: {
                        shipment_name: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frappe.show_alert({
                                message: __('Proof of Delivery verified'),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));
        }
    }

    // Generate Label button (if logistics provider supports it)
    if (frm.doc.status === 'Pending' && frm.doc.logistics_provider) {
        frm.add_custom_button(__('Generate Label'), function() {
            frappe.msgprint(__('Label generation feature will be implemented via logistics provider API integration.'));
        }, __('Actions'));
    }

    // Track Shipment button
    if (frm.doc.tracking_url) {
        frm.add_custom_button(__('Track Shipment'), function() {
            window.open(frm.doc.tracking_url, '_blank');
        }, __('Actions'));
    }
}

function show_delivery_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: __('Mark as Delivered'),
        fields: [
            {
                label: __('Received By'),
                fieldname: 'received_by',
                fieldtype: 'Data',
                reqd: frm.doc.requires_signature,
                description: __('Name of person who received the shipment')
            },
            {
                label: __('Receiver Relation'),
                fieldname: 'receiver_relation',
                fieldtype: 'Select',
                options: '\nSelf\nFamily Member\nColleague\nNeighbor\nBuilding Security\nReception/Front Desk\nAuthorized Representative\nOther'
            },
            {
                fieldtype: 'Column Break'
            },
            {
                label: __('ID Type'),
                fieldname: 'receiver_id_type',
                fieldtype: 'Select',
                options: '\nTurkish National ID (TC Kimlik)\nPassport\nDriver\'s License\nOther Government ID\nCompany ID'
            },
            {
                label: __('ID Number (Last 4 digits)'),
                fieldname: 'receiver_id_number',
                fieldtype: 'Data',
                description: __('For verification purposes')
            },
            {
                fieldtype: 'Section Break',
                label: __('Signature'),
                depends_on: 'eval:' + (frm.doc.requires_signature ? '1' : '0')
            },
            {
                label: __('Receiver Signature'),
                fieldname: 'signature',
                fieldtype: 'Signature'
            },
            {
                fieldtype: 'Section Break',
                label: __('Notes')
            },
            {
                label: __('Delivery Notes'),
                fieldname: 'delivery_notes',
                fieldtype: 'Small Text'
            }
        ],
        primary_action_label: __('Confirm Delivery'),
        primary_action: function(values) {
            frappe.call({
                method: 'tr_tradehub.tr_tradehub.doctype.marketplace_shipment.marketplace_shipment.mark_shipment_delivered',
                args: {
                    shipment_name: frm.doc.name,
                    received_by: values.received_by,
                    receiver_relation: values.receiver_relation,
                    signature: values.signature,
                    delivery_notes: values.delivery_notes
                },
                callback: function(r) {
                    if (r.message) {
                        d.hide();
                        frappe.show_alert({
                            message: __('Shipment marked as delivered'),
                            indicator: 'green'
                        });
                        frm.reload_doc();
                    }
                }
            });
        }
    });
    d.show();
}

function update_status_indicator(frm) {
    // Add visual status indicator
    const status_colors = {
        'Pending': 'gray',
        'Label Created': 'blue',
        'Picked Up': 'yellow',
        'In Transit': 'purple',
        'Out for Delivery': 'blue',
        'Delivery Attempted': 'orange',
        'Delivered': 'green',
        'Returned to Sender': 'red',
        'Exception': 'red',
        'Cancelled': 'red'
    };

    const color = status_colors[frm.doc.status] || 'gray';
    frm.page.set_indicator(__(frm.doc.status), color);
}

function generate_tracking_url(frm) {
    if (!frm.doc.logistics_provider || !frm.doc.tracking_number) {
        return;
    }

    frappe.db.get_value('Logistics Provider', frm.doc.logistics_provider, 'tracking_url_template', (r) => {
        if (r && r.tracking_url_template) {
            const url = r.tracking_url_template.replace('{tracking_number}', frm.doc.tracking_number);
            frm.set_value('tracking_url', url);
        }
    });
}

function calculate_volume(frm) {
    // Auto-calculate volume if all dimensions are provided
    if (frm.doc.package_length && frm.doc.package_width && frm.doc.package_height) {
        const volume = frm.doc.package_length * frm.doc.package_width * frm.doc.package_height;
        frm.set_value('total_volume', volume);
    }
}
