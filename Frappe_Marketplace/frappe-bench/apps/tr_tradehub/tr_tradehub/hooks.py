"""TR TradeHub Meta-App

This app has been decomposed into modular microservice apps:
- tradehub_core: Base platform infrastructure (tenant, ECA, org, buyer, city...)
- tradehub_catalog: Product Information Management (product, brand, category, PIM...)
- tradehub_seller: Seller lifecycle management (seller profile, KPI, listing, SKU...)
- tradehub_compliance: Legal, trust, moderation (certificate, consent, contract, esign...)
- tradehub_commerce: Orders, payments, transactions (order, RFQ, payment, escrow...)
- tradehub_logistics: Shipping and delivery (shipment, carrier, tracking...)
- tradehub_marketing: Campaigns, coupons, subscriptions (campaign, coupon, group buy...)

This meta-app provides a single installation point that brings in all
required TradeHub functionality through its dependencies.
"""

app_name = "tr_tradehub"
app_title = "TR TradeHub"
app_publisher = "TradeHub Team"
app_description = "TradeHub Meta-App - Installs all TradeHub modules"
app_email = "support@tradehub.example.com"
app_license = "MIT"

# All TradeHub functionality is provided through these required apps
required_apps = [
    "tradehub_core",
    "tradehub_catalog",
    "tradehub_seller",
    "tradehub_compliance",
    "tradehub_commerce",
    "tradehub_logistics",
    "tradehub_marketing",
]
