// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.treeview_settings["Buyer Category"] = {
    breadcrumb: "TR TradeHub",
    title: __("Buyer Categories"),
    get_tree_root: false,
    root_label: "All Buyer Categories",
    get_tree_nodes: "tr_tradehub.tr_tradehub.doctype.buyer_category.buyer_category.get_children",
    add_tree_node: "tr_tradehub.tr_tradehub.doctype.buyer_category.buyer_category.add_node",

    filters: [
        {
            fieldname: "status",
            fieldtype: "Select",
            options: ["", "Active", "Inactive", "Deprecated"],
            label: __("Status"),
            default: "Active"
        }
    ],

    fields: [
        {
            fieldtype: "Data",
            fieldname: "category_name",
            label: __("Category Name"),
            reqd: true
        }
    ],

    // Menu items for tree nodes
    menu_items: [
        {
            label: __("View Buyers"),
            action: function(node) {
                frappe.set_route("List", "Buyer Profile", {buyer_category: node.data.value});
            },
            condition: function(node) {
                return !node.is_root;
            }
        },
        {
            label: __("Add Child Category"),
            action: function(node) {
                frappe.new_doc("Buyer Category", {
                    parent_buyer_category: node.data.value
                });
            },
            condition: function(node) {
                return frappe.boot.user.can_create.includes("Buyer Category");
            }
        },
        {
            label: __("View Category Path"),
            action: function(node) {
                if (node.data.value) {
                    frappe.call({
                        method: "frappe.client.get",
                        args: {
                            doctype: "Buyer Category",
                            name: node.data.value
                        },
                        callback: function(r) {
                            if (r.message) {
                                // Build path from ancestors
                                let path = r.message.category_name;
                                frappe.msgprint({
                                    title: __("Category: {0}", [r.message.category_name]),
                                    message: `
                                        <p><strong>${__("Code")}:</strong> ${r.message.category_code || "-"}</p>
                                        <p><strong>${__("Status")}:</strong> ${r.message.status}</p>
                                        <p><strong>${__("Buyers")}:</strong> ${r.message.buyer_count || 0}</p>
                                        <p><strong>${__("Default")}:</strong> ${r.message.is_default ? __("Yes") : __("No")}</p>
                                    `,
                                    indicator: r.message.status === "Active" ? "green" : "gray"
                                });
                            }
                        }
                    });
                }
            },
            condition: function(node) {
                return !node.is_root;
            }
        }
    ],

    // Customize how nodes are rendered
    onrender: function(node) {
        if (node.data && !node.is_root) {
            // Add icon if available
            if (node.data.icon) {
                let icon_html = `<i class="${node.data.icon}" style="color: ${node.data.icon_color || '#333'}; margin-right: 5px;"></i>`;
                $(node.element).find(".tree-label").prepend(icon_html);
            }

            // Show buyer count badge
            if (node.data.buyer_count > 0) {
                let badge = `<span class="badge badge-secondary ml-2" style="font-size: 10px;">${node.data.buyer_count}</span>`;
                $(node.element).find(".tree-label").append(badge);
            }

            // Show default indicator
            if (node.data.is_default) {
                let default_badge = `<span class="badge badge-primary ml-2" style="font-size: 10px;">${__("Default")}</span>`;
                $(node.element).find(".tree-label").append(default_badge);
            }

            // Style inactive categories
            if (node.data.status && node.data.status !== "Active") {
                $(node.element).find(".tree-label").addClass("text-muted");
                let status_badge = `<span class="badge badge-warning ml-2" style="font-size: 10px;">${node.data.status}</span>`;
                $(node.element).find(".tree-label").append(status_badge);
            }
        }
    },

    // Called when a node is expanded
    onload: function(tree) {
        // Expand root by default
        if (tree.root_node) {
            tree.root_node.toggle(true);
        }
    },

    // Custom CSS for tree nodes
    extend_toolbar: true,
    toolbar: [
        {
            label: __("Refresh Counts"),
            click: function() {
                frappe.call({
                    method: "tr_tradehub.tr_tradehub.doctype.buyer_category.buyer_category.update_all_buyer_counts",
                    callback: function(r) {
                        // Refresh tree after updating counts
                        cur_tree.reload();
                    }
                });
            }
        }
    ]
};
