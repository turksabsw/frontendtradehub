// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on("Neighborhood", {
    refresh: function(frm) {
        // Set up district filter to show only active districts
        frm.set_query("district", function() {
            return {
                filters: {
                    is_active: 1
                }
            };
        });
    },

    district: function(frm) {
        // When district changes, clear district-dependent fields if needed
        if (!frm.doc.district) {
            frm.set_value("district_name", "");
            frm.set_value("city", "");
            frm.set_value("city_name", "");
            frm.set_value("region", "");
        }
    },

    validate: function(frm) {
        // Client-side validation for neighborhood name
        if (frm.doc.neighborhood_name && frm.doc.neighborhood_name.trim().length < 2) {
            frappe.throw(__("Neighborhood name must be at least 2 characters"));
        }
    }
});

// Cascading filter helper - can be used by other DocTypes that need to filter Neighborhood by District
// Usage in other JS files:
// frm.set_query("neighborhood", function() {
//     return {
//         filters: {
//             district: frm.doc.district,
//             is_active: 1
//         }
//     };
// });

// Full cascading filter example for City -> District -> Neighborhood:
//
// frm.set_query("city", function() {
//     return {
//         filters: {
//             is_active: 1
//         }
//     };
// });
//
// frm.set_query("district", function() {
//     return {
//         filters: {
//             city: frm.doc.city,
//             is_active: 1
//         }
//     };
// });
//
// frm.set_query("neighborhood", function() {
//     return {
//         filters: {
//             district: frm.doc.district,
//             is_active: 1
//         }
//     };
// });
