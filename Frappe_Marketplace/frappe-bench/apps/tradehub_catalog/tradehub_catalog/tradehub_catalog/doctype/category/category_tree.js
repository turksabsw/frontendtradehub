// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

/**
 * Category Tree View Settings
 * Configures the hierarchical tree view for product categories.
 */
frappe.treeview_settings["Category"] = {
	// Display breadcrumb in navigation
	breadcrumb: "TR TradeHub",

	// Title shown in tree view header
	title: __("Category"),

	// Path to server method for getting tree nodes
	get_tree_nodes: "tr_tradehub.tr_tradehub.doctype.category.category.get_children",

	// Path to server method for adding new nodes
	add_tree_node: "tr_tradehub.tr_tradehub.doctype.category.category.add_node",

	// Show tree root label
	get_tree_root: false,
	root_label: __("All Categories"),

	// Show item count badge
	show_expand_all: true,

	// Fields for the quick add dialog
	fields: [
		{
			fieldtype: "Data",
			fieldname: "category_name",
			label: __("Category Name"),
			reqd: 1
		}
	],

	// Filters for the tree view
	filters: [
		{
			fieldname: "is_active",
			fieldtype: "Check",
			label: __("Show Active Only"),
			default: 0,
			on_change: function(me) {
				// Refresh tree when filter changes
				me.page.tree.make_tree();
			}
		}
	],

	// Custom toolbar buttons
	toolbar: [
		{
			label: __("View All"),
			condition: function(node) {
				return !node.is_root;
			},
			click: function(node) {
				frappe.set_route("List", "Category", {
					"parent_category": node.data.value
				});
			},
			btnClass: "btn-default btn-xs"
		}
	],

	// Custom menu items for each node
	menu_items: [
		{
			label: __("View Listings"),
			action: function(node) {
				frappe.set_route("List", "Listing", {
					"category": node.data.value
				});
			},
			condition: function(node) {
				return !node.is_root;
			}
		},
		{
			label: __("Add Child Category"),
			action: function(node, tree) {
				tree.new_node();
			},
			condition: function(node) {
				return frappe.boot.user.can_create.indexOf("Category") !== -1;
			}
		},
		{
			label: __("View Full Path"),
			action: function(node) {
				frappe.call({
					method: "frappe.client.get_value",
					args: {
						doctype: "Category",
						filters: { name: node.data.value },
						fieldname: ["route"]
					},
					callback: function(r) {
						if (r.message && r.message.route) {
							frappe.msgprint({
								title: __("Category Path"),
								message: "<strong>" + __("Route") + ":</strong> /" + r.message.route,
								indicator: "blue"
							});
						}
					}
				});
			},
			condition: function(node) {
				return !node.is_root;
			}
		}
	],

	// Extend the default toolbar
	extend_toolbar: true,

	// Callback when tree is loaded
	onload: function(treeview) {
		// Add custom CSS for tree view styling
		if (!$("style#category-tree-style").length) {
			$("<style id='category-tree-style'></style>")
				.html(`
					.category-tree-node {
						padding: 8px;
					}
					.category-tree-node.inactive {
						opacity: 0.6;
					}
					.category-tree-node .node-image {
						width: 24px;
						height: 24px;
						border-radius: 4px;
						margin-right: 8px;
						object-fit: cover;
					}
					.tree-node-toolbar {
						margin-left: auto;
					}
				`)
				.appendTo("head");
		}
	},

	// Callback after tree is rendered
	post_render: function(treeview) {
		// Enable drag-drop reordering if user has write permission
		if (frappe.boot.user.can_write.indexOf("Category") !== -1) {
			treeview.$tree_wrapper.find(".tree-node").each(function() {
				$(this).attr("draggable", true);
			});
		}
	},

	// Callback for individual node rendering
	onrender: function(node) {
		// Add visual indicator for inactive categories
		if (node.data && node.data.is_active === 0) {
			$(node.element).find(".tree-label").addClass("text-muted");
			$(node.element).find(".tree-label").append(
				' <span class="badge badge-secondary">' + __("Inactive") + "</span>"
			);
		}

		// Show image thumbnail if available
		if (node.data && node.data.image) {
			var $label = $(node.element).find(".tree-label");
			var $img = $('<img class="node-image" src="' + node.data.image + '" alt="">');
			$label.prepend($img);
		}
	},

	// Process nodes after fetching from server
	on_get_node: function(nodes) {
		// Add any client-side transformations to nodes
		nodes.forEach(function(node) {
			// Mark root nodes
			if (!node.parent || node.parent === "All Categories") {
				node.is_root_level = true;
			}
		});
		return nodes;
	}
};
