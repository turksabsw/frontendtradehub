# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Analytics Settings DocType for tenant-specific Google Analytics 4 configuration.

This module implements tenant-specific GA4 configuration including:
- GA4 Measurement ID and Data Stream settings
- Google Tag Manager (GTM) integration
- Consent Mode v2 for GDPR compliance
- E-commerce and B2B event tracking configuration
- Server-side tracking via Measurement Protocol
- Custom dimensions for B2B analytics

Each tenant can have its own GA4 property and tracking configuration,
enabling multi-tenant analytics isolation while maintaining platform-wide
visibility for administrators.
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, cint


class AnalyticsSettings(Document):
    """
    Analytics Settings DocType for tenant-specific GA4 configuration.

    Provides configuration for:
    - Google Analytics 4 tracking
    - Google Tag Manager integration
    - Consent management (GDPR compliance)
    - E-commerce event tracking
    - B2B-specific event tracking
    - Server-side tracking
    - Custom dimensions
    """

    def before_insert(self):
        """Set default values before inserting a new analytics configuration."""
        # Ensure only one analytics settings per tenant
        self.validate_unique_tenant()

    def validate(self):
        """Validate analytics settings before saving."""
        self.validate_ga4_measurement_id()
        self.validate_gtm_container_id()
        self.validate_api_secret()
        self.validate_session_timeout()
        self.validate_consent_settings()
        self.validate_cross_domain_domains()

    def on_update(self):
        """Actions to perform after analytics settings are updated."""
        self.clear_analytics_cache()

    def on_trash(self):
        """Actions to perform before deletion."""
        self.clear_analytics_cache()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_unique_tenant(self):
        """Ensure only one analytics settings exists per tenant."""
        if self.tenant:
            existing = frappe.db.get_value(
                "Analytics Settings",
                {"tenant": self.tenant, "name": ("!=", self.name or "")},
                "name"
            )
            if existing:
                frappe.throw(
                    _("Analytics Settings already exists for tenant {0}").format(
                        self.tenant
                    )
                )

    def validate_ga4_measurement_id(self):
        """
        Validate GA4 Measurement ID format.

        GA4 Measurement IDs follow the format: G-XXXXXXXXXX
        where X can be alphanumeric characters.
        """
        if self.ga4_measurement_id:
            measurement_id = self.ga4_measurement_id.strip().upper()

            # GA4 format: G-XXXXXXX (7-10 alphanumeric characters after G-)
            pattern = r'^G-[A-Z0-9]{7,10}$'
            if not re.match(pattern, measurement_id):
                frappe.throw(
                    _("Invalid GA4 Measurement ID format. "
                      "Expected format: G-XXXXXXX (e.g., G-ABC123XYZ)")
                )

            self.ga4_measurement_id = measurement_id

    def validate_gtm_container_id(self):
        """
        Validate Google Tag Manager Container ID format.

        GTM Container IDs follow the format: GTM-XXXXXXX
        where X can be alphanumeric characters.
        """
        if self.gtm_enabled and self.gtm_container_id:
            container_id = self.gtm_container_id.strip().upper()

            # GTM format: GTM-XXXXXXX
            pattern = r'^GTM-[A-Z0-9]{6,8}$'
            if not re.match(pattern, container_id):
                frappe.throw(
                    _("Invalid GTM Container ID format. "
                      "Expected format: GTM-XXXXXXX (e.g., GTM-ABC123)")
                )

            self.gtm_container_id = container_id

        elif self.gtm_enabled and not self.gtm_container_id:
            frappe.throw(
                _("GTM Container ID is required when GTM is enabled")
            )

    def validate_api_secret(self):
        """Validate API secret is provided for server-side tracking."""
        if self.server_side_tracking_enabled:
            if not self.ga4_api_secret:
                frappe.throw(
                    _("Measurement Protocol API Secret is required "
                      "for server-side tracking")
                )
            if not self.ga4_measurement_id:
                frappe.throw(
                    _("GA4 Measurement ID is required for server-side tracking")
                )

    def validate_session_timeout(self):
        """Validate session timeout is within reasonable bounds."""
        if self.session_timeout_minutes:
            timeout = cint(self.session_timeout_minutes)
            if timeout < 1:
                frappe.throw(_("Session timeout must be at least 1 minute"))
            if timeout > 240:
                frappe.throw(_("Session timeout cannot exceed 240 minutes"))

        if self.engagement_time_threshold:
            threshold = cint(self.engagement_time_threshold)
            if threshold < 1:
                frappe.throw(_("Engagement time threshold must be at least 1 second"))
            if threshold > 60:
                frappe.throw(_("Engagement time threshold cannot exceed 60 seconds"))

    def validate_consent_settings(self):
        """Validate consent mode settings are consistent."""
        if self.consent_mode_enabled:
            # If requiring explicit consent, default storage should be denied
            if self.require_explicit_consent:
                if self.default_analytics_storage == "granted":
                    frappe.msgprint(
                        _("Warning: Setting default analytics storage to 'granted' "
                          "while requiring explicit consent may not be GDPR compliant"),
                        indicator="orange"
                    )
                if self.default_ad_storage == "granted":
                    frappe.msgprint(
                        _("Warning: Setting default ad storage to 'granted' "
                          "while requiring explicit consent may not be GDPR compliant"),
                        indicator="orange"
                    )

    def validate_cross_domain_domains(self):
        """Validate cross-domain tracking domain list."""
        if self.cross_domain_tracking and self.cross_domain_domains:
            domains = [d.strip() for d in self.cross_domain_domains.split(",")]
            for domain in domains:
                if domain and not self._is_valid_domain(domain):
                    frappe.throw(
                        _("Invalid domain in cross-domain list: {0}").format(domain)
                    )

    def _is_valid_domain(self, domain):
        """
        Check if a domain is valid.

        Args:
            domain: Domain string to validate

        Returns:
            bool: True if valid, False otherwise
        """
        # Simple domain validation
        pattern = r'^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$'
        return bool(re.match(pattern, domain.lower()))

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_analytics_cache(self):
        """Clear cached analytics configuration."""
        cache_keys = [
            f"analytics_settings:{self.tenant}",
            f"analytics_config:{self.tenant}",
            f"gtm_config:{self.tenant}",
            f"consent_config:{self.tenant}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # CONFIGURATION GETTERS
    # =========================================================================

    def get_tracking_config(self):
        """
        Get the complete tracking configuration for frontend use.

        Returns:
            dict: Tracking configuration including GA4, GTM, consent settings
        """
        config = {
            "enabled": self.enabled,
            "debug_mode": self.debug_mode,
            "ga4": {
                "measurement_id": self.ga4_measurement_id,
                "stream_id": self.ga4_stream_id,
                "property_id": self.ga4_property_id,
            },
            "gtm": {
                "enabled": self.gtm_enabled,
                "container_id": self.gtm_container_id if self.gtm_enabled else None,
                "environment": self.gtm_environment if self.gtm_enabled else None,
                "auth_token": self.gtm_auth_token if self.gtm_enabled else None,
            },
            "consent": {
                "enabled": self.consent_mode_enabled,
                "default_analytics_storage": self.default_analytics_storage,
                "default_ad_storage": self.default_ad_storage,
                "require_explicit_consent": self.require_explicit_consent,
                "banner_text": self.consent_banner_text,
                "apply_to_eu_only": self.apply_consent_to_eu_only,
                "apply_to_all": self.apply_consent_to_all,
                "eu_countries": self.eu_countries.split(",") if self.eu_countries else [],
            },
            "ecommerce": {
                "enabled": self.track_ecommerce_events,
                "track_product_views": self.track_product_views,
                "track_add_to_cart": self.track_add_to_cart,
                "track_purchases": self.track_purchases,
                "track_rfq_events": self.track_rfq_events,
                "track_search_events": self.track_search_events,
            },
            "b2b_events": {
                "track_quote_requests": self.track_quote_requests,
                "track_sample_requests": self.track_sample_requests,
                "track_seller_interactions": self.track_seller_interactions,
                "track_buyer_interactions": self.track_buyer_interactions,
                "track_user_registration": self.track_user_registration,
                "track_login_events": self.track_login_events,
            },
            "custom_dimensions": {
                "tenant": self.custom_dimension_tenant,
                "user_type": self.custom_dimension_user_type,
                "seller_tier": self.custom_dimension_seller_tier,
                "buyer_segment": self.custom_dimension_buyer_segment,
                "category": self.custom_dimension_category,
            },
            "advanced": {
                "session_timeout_minutes": self.session_timeout_minutes,
                "engagement_time_threshold": self.engagement_time_threshold,
                "cross_domain_tracking": self.cross_domain_tracking,
                "cross_domain_domains": (
                    self.cross_domain_domains.split(",")
                    if self.cross_domain_domains else []
                ),
            },
        }

        return config

    def get_gtag_snippet(self):
        """
        Generate the gtag.js snippet for this tenant.

        Returns:
            str: HTML/JavaScript snippet for GA4 tracking
        """
        if not self.enabled or not self.ga4_measurement_id:
            return ""

        snippet = f"""
<!-- Google Analytics 4 - Trade Hub -->
<script async src="https://www.googletagmanager.com/gtag/js?id={self.ga4_measurement_id}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
"""

        # Add consent mode if enabled
        if self.consent_mode_enabled:
            snippet += f"""
  gtag('consent', 'default', {{
    'analytics_storage': '{self.default_analytics_storage}',
    'ad_storage': '{self.default_ad_storage}'
  }});
"""

        # Configure GA4
        config_options = [f"'send_page_view': true"]
        if self.debug_mode:
            config_options.append("'debug_mode': true")

        snippet += f"""
  gtag('config', '{self.ga4_measurement_id}', {{
    {', '.join(config_options)}
  }});
</script>
"""
        return snippet

    def get_gtm_snippet(self):
        """
        Generate the GTM snippet for this tenant.

        Returns:
            tuple: (head_snippet, body_snippet) for GTM installation
        """
        if not self.enabled or not self.gtm_enabled or not self.gtm_container_id:
            return ("", "")

        # Build environment parameters if not production
        env_params = ""
        if self.gtm_environment != "Production" and self.gtm_auth_token:
            env_params = f"&gtm_auth={self.gtm_auth_token}&gtm_preview={self.gtm_environment.lower()}&gtm_cookies_win=x"

        head_snippet = f"""
<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl{'+"{}"'.format(env_params) if env_params else ''};f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{self.gtm_container_id}');</script>
<!-- End Google Tag Manager -->
"""

        body_snippet = f"""
<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={self.gtm_container_id}{env_params}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->
"""

        return (head_snippet, body_snippet)

    # =========================================================================
    # SERVER-SIDE TRACKING
    # =========================================================================

    def send_event(self, event_name, event_params=None, client_id=None, user_id=None):
        """
        Send an event to GA4 via Measurement Protocol.

        Args:
            event_name: Name of the event to send
            event_params: Dictionary of event parameters
            client_id: GA4 client ID
            user_id: Optional user ID for user-scoped reporting

        Returns:
            dict: Response with success status
        """
        if not self.enabled or not self.server_side_tracking_enabled:
            return {"success": False, "message": "Server-side tracking not enabled"}

        if not self.ga4_measurement_id or not self.ga4_api_secret:
            return {"success": False, "message": "Missing GA4 credentials"}

        import requests

        # Build the Measurement Protocol payload
        payload = {
            "client_id": client_id or self._generate_client_id(),
            "events": [{
                "name": event_name,
                "params": event_params or {}
            }]
        }

        if user_id:
            payload["user_id"] = user_id

        # Add custom dimensions
        if event_params:
            event_params["tenant_id"] = self.tenant

        # Send to GA4 Measurement Protocol
        url = (
            f"https://www.google-analytics.com/mp/collect"
            f"?measurement_id={self.ga4_measurement_id}"
            f"&api_secret={self.get_password('ga4_api_secret')}"
        )

        try:
            response = requests.post(url, json=payload, timeout=10)

            # Update statistics
            self.db_set("total_events_sent", cint(self.total_events_sent) + 1)
            self.db_set("last_event_date", now_datetime())

            if response.status_code == 204:
                return {"success": True, "message": "Event sent successfully"}
            else:
                return {
                    "success": False,
                    "message": f"GA4 returned status {response.status_code}"
                }

        except Exception as e:
            frappe.log_error(
                message=str(e),
                title=f"GA4 Server-Side Event Error for {self.tenant}"
            )
            return {"success": False, "message": str(e)}

    def _generate_client_id(self):
        """
        Generate a random client ID for server-side events.

        Returns:
            str: Generated client ID
        """
        import random
        import time
        return f"{random.randint(100000000, 999999999)}.{int(time.time())}"

    # =========================================================================
    # VERIFICATION
    # =========================================================================

    def verify_configuration(self):
        """
        Verify the GA4 configuration is working.

        Returns:
            dict: Verification result with status and message
        """
        if not self.ga4_measurement_id:
            self.db_set("verification_status", "Failed")
            return {
                "success": False,
                "message": "GA4 Measurement ID is not configured"
            }

        # Send a verification event via Measurement Protocol if enabled
        if self.server_side_tracking_enabled and self.ga4_api_secret:
            result = self.send_event(
                "_verification",
                {"verification_type": "config_check"}
            )

            if result.get("success"):
                self.db_set("verification_status", "Verified")
                self.db_set("last_verified", now_datetime())
                return {
                    "success": True,
                    "message": "GA4 configuration verified successfully"
                }
            else:
                self.db_set("verification_status", "Failed")
                return result
        else:
            # Basic format verification only
            self.db_set("verification_status", "Verified")
            self.db_set("last_verified", now_datetime())
            return {
                "success": True,
                "message": "GA4 Measurement ID format verified"
            }


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_analytics_settings(tenant):
    """
    Get analytics settings for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Analytics settings document or None if not found
    """
    if not frappe.has_permission("Analytics Settings", "read"):
        frappe.throw(_("Not permitted to view analytics settings"))

    settings = frappe.db.get_value(
        "Analytics Settings",
        {"tenant": tenant},
        "*",
        as_dict=True
    )

    return settings


@frappe.whitelist()
def get_tracking_config(tenant):
    """
    Get the complete tracking configuration for frontend integration.

    Args:
        tenant: Tenant name

    Returns:
        dict: Tracking configuration for the tenant
    """
    # Check cache first
    cache_key = f"analytics_config:{tenant}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    # Get from database
    settings_name = frappe.db.get_value(
        "Analytics Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        return {"enabled": False}

    settings = frappe.get_doc("Analytics Settings", settings_name)
    config = settings.get_tracking_config()

    # Cache for 5 minutes
    frappe.cache().set_value(cache_key, config, expires_in_sec=300)

    return config


@frappe.whitelist()
def get_analytics_snippet(tenant):
    """
    Get the analytics tracking snippet for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Contains gtag_snippet and/or gtm_snippets
    """
    settings_name = frappe.db.get_value(
        "Analytics Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        return {"gtag": "", "gtm_head": "", "gtm_body": ""}

    settings = frappe.get_doc("Analytics Settings", settings_name)

    gtm_head, gtm_body = settings.get_gtm_snippet()

    return {
        "gtag": settings.get_gtag_snippet() if not settings.gtm_enabled else "",
        "gtm_head": gtm_head,
        "gtm_body": gtm_body,
    }


@frappe.whitelist()
def send_server_event(tenant, event_name, event_params=None, client_id=None, user_id=None):
    """
    Send a server-side event to GA4 via Measurement Protocol.

    Args:
        tenant: Tenant name
        event_name: Name of the event
        event_params: Event parameters as JSON string
        client_id: GA4 client ID
        user_id: Optional user ID

    Returns:
        dict: Result with success status
    """
    import json

    if not frappe.has_permission("Analytics Settings", "read"):
        frappe.throw(_("Not permitted to send analytics events"))

    settings_name = frappe.db.get_value(
        "Analytics Settings",
        {"tenant": tenant, "enabled": 1, "server_side_tracking_enabled": 1},
        "name"
    )

    if not settings_name:
        return {"success": False, "message": "Server-side tracking not configured"}

    settings = frappe.get_doc("Analytics Settings", settings_name)

    # Parse event_params if it's a string
    if isinstance(event_params, str):
        event_params = json.loads(event_params) if event_params else {}

    return settings.send_event(event_name, event_params, client_id, user_id)


@frappe.whitelist()
def verify_analytics_config(tenant):
    """
    Verify the analytics configuration for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Verification result
    """
    if not frappe.has_permission("Analytics Settings", "write"):
        frappe.throw(_("Not permitted to verify analytics configuration"))

    settings_name = frappe.db.get_value(
        "Analytics Settings",
        {"tenant": tenant},
        "name"
    )

    if not settings_name:
        return {"success": False, "message": "Analytics settings not found"}

    settings = frappe.get_doc("Analytics Settings", settings_name)
    return settings.verify_configuration()


@frappe.whitelist()
def create_analytics_settings(tenant, ga4_measurement_id=None, gtm_container_id=None):
    """
    Create analytics settings for a tenant.

    Args:
        tenant: Tenant name
        ga4_measurement_id: Optional GA4 Measurement ID
        gtm_container_id: Optional GTM Container ID

    Returns:
        dict: Created analytics settings
    """
    if not frappe.has_permission("Analytics Settings", "create"):
        frappe.throw(_("Not permitted to create analytics settings"))

    # Check if settings already exist
    existing = frappe.db.get_value("Analytics Settings", {"tenant": tenant}, "name")
    if existing:
        frappe.throw(_("Analytics settings already exist for tenant {0}").format(tenant))

    doc = frappe.get_doc({
        "doctype": "Analytics Settings",
        "tenant": tenant,
        "enabled": 1 if ga4_measurement_id else 0,
        "ga4_measurement_id": ga4_measurement_id,
        "gtm_enabled": 1 if gtm_container_id else 0,
        "gtm_container_id": gtm_container_id,
        "consent_mode_enabled": 1,
        "default_analytics_storage": "denied",
        "default_ad_storage": "denied",
        "require_explicit_consent": 1,
        "track_ecommerce_events": 1,
        "track_quote_requests": 1,
        "track_sample_requests": 1,
    })

    doc.insert()
    return doc.as_dict()


@frappe.whitelist()
def update_consent_state(tenant, analytics_storage, ad_storage=None):
    """
    Update user consent state for a tenant (called from frontend).

    This is typically called when a user interacts with a consent banner.

    Args:
        tenant: Tenant name
        analytics_storage: 'granted' or 'denied'
        ad_storage: 'granted' or 'denied' (optional)

    Returns:
        dict: Updated consent state
    """
    # This endpoint is used by frontend to log consent updates
    # The actual consent state is managed client-side via gtag('consent', 'update', ...)
    # This is for audit/logging purposes

    valid_states = ['granted', 'denied']
    if analytics_storage not in valid_states:
        frappe.throw(_("Invalid analytics_storage value"))
    if ad_storage and ad_storage not in valid_states:
        frappe.throw(_("Invalid ad_storage value"))

    # Log the consent update for audit purposes
    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Info",
        "reference_doctype": "Analytics Settings",
        "reference_name": frappe.db.get_value("Analytics Settings", {"tenant": tenant}, "name"),
        "content": f"Consent updated - analytics_storage: {analytics_storage}, ad_storage: {ad_storage or 'not specified'}",
    }).insert(ignore_permissions=True)

    return {
        "success": True,
        "analytics_storage": analytics_storage,
        "ad_storage": ad_storage,
    }


@frappe.whitelist()
def get_b2b_event_config(tenant):
    """
    Get B2B-specific event tracking configuration.

    Args:
        tenant: Tenant name

    Returns:
        dict: B2B event tracking configuration
    """
    settings = frappe.db.get_value(
        "Analytics Settings",
        {"tenant": tenant, "enabled": 1},
        [
            "track_quote_requests",
            "track_sample_requests",
            "track_seller_interactions",
            "track_buyer_interactions",
            "track_user_registration",
            "track_login_events",
            "track_rfq_events",
            "custom_dimension_tenant",
            "custom_dimension_user_type",
            "custom_dimension_seller_tier",
            "custom_dimension_buyer_segment",
        ],
        as_dict=True
    )

    if not settings:
        return {"enabled": False}

    return {
        "enabled": True,
        "events": {
            "quote_requests": settings.track_quote_requests,
            "sample_requests": settings.track_sample_requests,
            "seller_interactions": settings.track_seller_interactions,
            "buyer_interactions": settings.track_buyer_interactions,
            "user_registration": settings.track_user_registration,
            "login_events": settings.track_login_events,
            "rfq_events": settings.track_rfq_events,
        },
        "dimensions": {
            "tenant": settings.custom_dimension_tenant,
            "user_type": settings.custom_dimension_user_type,
            "seller_tier": settings.custom_dimension_seller_tier,
            "buyer_segment": settings.custom_dimension_buyer_segment,
        }
    }
