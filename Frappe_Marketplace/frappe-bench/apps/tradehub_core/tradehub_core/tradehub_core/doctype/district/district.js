// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on("District", {
    refresh: function(frm) {
        // Set up city filter to show only active cities
        frm.set_query("city", function() {
            return {
                filters: {
                    is_active: 1
                }
            };
        });

        // Show neighborhood count in dashboard if document is saved
        if (!frm.is_new()) {
            frm.add_custom_button(__("View Neighborhoods"), function() {
                frappe.set_route("List", "Neighborhood", {
                    district: frm.doc.name
                });
            });
        }
    },

    city: function(frm) {
        // When city changes, clear city-dependent fields if needed
        if (!frm.doc.city) {
            frm.set_value("city_name", "");
            frm.set_value("region", "");
        }
    },

    validate: function(frm) {
        // Client-side validation for district name
        if (frm.doc.district_name && frm.doc.district_name.trim().length < 2) {
            frappe.throw(__("District name must be at least 2 characters"));
        }
    }
});

// Cascading filter helper - can be used by other DocTypes that need to filter District by City
// Usage in other JS files:
// frm.set_query("district", function() {
//     return {
//         filters: {
//             city: frm.doc.city,
//             is_active: 1
//         }
//     };
// });
