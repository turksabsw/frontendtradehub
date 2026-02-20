// Copyright (c) 2024, TR TradeHub and contributors
// For license information, please see license.txt

frappe.ui.form.on('Tenant', {
    refresh: function(frm) {
        // Only show dashboard for saved tenants
        if (!frm.is_new()) {
            // Add custom buttons for common actions
            frm.add_custom_button(__('View Sellers'), function() {
                frappe.set_route('List', 'Seller Profile', {'tenant': frm.doc.name});
            }, __('Actions'));

            frm.add_custom_button(__('View Organizations'), function() {
                frappe.set_route('List', 'Organization', {'tenant': frm.doc.name});
            }, __('Actions'));

            frm.add_custom_button(__('View Orders'), function() {
                frappe.set_route('List', 'Marketplace Order', {'tenant': frm.doc.name});
            }, __('Actions'));

            frm.add_custom_button(__('View Listings'), function() {
                frappe.set_route('List', 'Listing', {'tenant': frm.doc.name});
            }, __('Actions'));

            // Load and display dashboard statistics
            load_tenant_dashboard(frm);
        }

        // Set up query filter for country to show only active countries
        frm.set_query('country', function() {
            return {
                filters: {
                    'enabled': 1
                }
            };
        });

        // Set up query filter for currency
        frm.set_query('currency', function() {
            return {
                filters: {
                    'enabled': 1
                }
            };
        });
    },

    setup: function(frm) {
        // frm.set_query must be in setup or onload for proper initialization
        // This is critical for preventing popup errors

        // Country filter
        frm.set_query('country', function() {
            return {
                filters: {
                    'enabled': 1
                }
            };
        });

        // Currency filter
        frm.set_query('currency', function() {
            return {
                filters: {
                    'enabled': 1
                }
            };
        });
    },

    onload: function(frm) {
        // Additional setup on form load
        if (frm.is_new()) {
            // Set default values for new tenants
            if (!frm.doc.subscription_start_date) {
                frm.set_value('subscription_start_date', frappe.datetime.nowdate());
            }
        }
    },

    status: function(frm) {
        // Handle status change logic
        if (frm.doc.status === 'Suspended' || frm.doc.status === 'Cancelled') {
            frappe.confirm(
                __('Changing tenant status to {0} will affect all associated sellers. Continue?', [frm.doc.status]),
                function() {
                    // User confirmed
                    frm.save();
                },
                function() {
                    // User cancelled - revert the change
                    frm.reload_doc();
                }
            );
        }
    },

    subscription_tier: function(frm) {
        // Update limits based on subscription tier
        const tier_limits = {
            'Free': { max_sellers: 3, max_listings: 50 },
            'Basic': { max_sellers: 10, max_listings: 100 },
            'Professional': { max_sellers: 50, max_listings: 500 },
            'Enterprise': { max_sellers: 0, max_listings: 0 } // 0 = unlimited
        };

        let limits = tier_limits[frm.doc.subscription_tier];
        if (limits) {
            // Only update if user hasn't customized these values
            if (!frm.doc.__unsaved) {
                frm.set_value('max_sellers', limits.max_sellers);
                frm.set_value('max_listings_per_seller', limits.max_listings);
            }

            frappe.show_alert({
                message: __('Tier changed to {0}. Default limits: {1} sellers, {2} listings/seller',
                    [frm.doc.subscription_tier,
                     limits.max_sellers || 'Unlimited',
                     limits.max_listings || 'Unlimited']),
                indicator: 'blue'
            });
        }
    }
});


/**
 * Load tenant dashboard statistics
 */
function load_tenant_dashboard(frm) {
    // Clear existing dashboard
    let dashboard_section = frm.dashboard.wrapper.find('.tenant-dashboard-section');
    if (dashboard_section.length === 0) {
        dashboard_section = $('<div class="tenant-dashboard-section"></div>');
        frm.dashboard.wrapper.append(dashboard_section);
    }
    dashboard_section.empty();

    // Fetch statistics
    frappe.call({
        method: 'frappe.client.get_count',
        args: {
            doctype: 'Seller Profile',
            filters: { tenant: frm.doc.name }
        },
        async: false,
        callback: function(r) {
            let seller_count = r.message || 0;

            // Add more stat calls
            Promise.all([
                get_count('Seller Profile', { tenant: frm.doc.name }),
                get_count('Seller Profile', { tenant: frm.doc.name, status: 'Active' }),
                get_count('Organization', { tenant: frm.doc.name }),
                get_count('Listing', { tenant: frm.doc.name }),
                get_count('Marketplace Order', { tenant: frm.doc.name })
            ]).then(function(results) {
                let stats = {
                    total_sellers: results[0],
                    active_sellers: results[1],
                    organizations: results[2],
                    listings: results[3],
                    orders: results[4]
                };

                render_dashboard_stats(dashboard_section, stats, frm);
            });
        }
    });
}

/**
 * Helper function to get document count
 */
function get_count(doctype, filters) {
    return new Promise(function(resolve) {
        frappe.call({
            method: 'frappe.client.get_count',
            args: { doctype: doctype, filters: filters },
            async: true,
            callback: function(r) {
                resolve(r.message || 0);
            }
        });
    });
}

/**
 * Render dashboard statistics cards
 */
function render_dashboard_stats(container, stats, frm) {
    let max_sellers = frm.doc.max_sellers || 'Unlimited';
    let seller_usage = max_sellers === 'Unlimited' ? '' :
        ` / ${max_sellers} (${Math.round(stats.total_sellers / frm.doc.max_sellers * 100)}%)`;

    let html = `
        <div class="row" style="margin-top: 15px;">
            <div class="col-sm-4">
                <div class="stat-card" style="padding: 15px; background: #f5f7fa; border-radius: 8px; text-align: center;">
                    <div class="stat-value" style="font-size: 24px; font-weight: bold; color: #5e64ff;">
                        ${stats.total_sellers}${seller_usage}
                    </div>
                    <div class="stat-label" style="color: #8d99a6; font-size: 12px; text-transform: uppercase;">
                        ${__('Total Sellers')}
                    </div>
                    <div class="stat-detail" style="color: #36414c; font-size: 14px;">
                        ${stats.active_sellers} ${__('Active')}
                    </div>
                </div>
            </div>
            <div class="col-sm-4">
                <div class="stat-card" style="padding: 15px; background: #f5f7fa; border-radius: 8px; text-align: center;">
                    <div class="stat-value" style="font-size: 24px; font-weight: bold; color: #5e64ff;">
                        ${stats.listings}
                    </div>
                    <div class="stat-label" style="color: #8d99a6; font-size: 12px; text-transform: uppercase;">
                        ${__('Total Listings')}
                    </div>
                    <div class="stat-detail" style="color: #36414c; font-size: 14px;">
                        ${stats.organizations} ${__('Organizations')}
                    </div>
                </div>
            </div>
            <div class="col-sm-4">
                <div class="stat-card" style="padding: 15px; background: #f5f7fa; border-radius: 8px; text-align: center;">
                    <div class="stat-value" style="font-size: 24px; font-weight: bold; color: #5e64ff;">
                        ${stats.orders}
                    </div>
                    <div class="stat-label" style="color: #8d99a6; font-size: 12px; text-transform: uppercase;">
                        ${__('Total Orders')}
                    </div>
                    <div class="stat-detail" style="color: #36414c; font-size: 14px;">
                        ${frm.doc.commission_rate || 0}% ${__('Commission')}
                    </div>
                </div>
            </div>
        </div>
    `;

    container.html(html);
}
