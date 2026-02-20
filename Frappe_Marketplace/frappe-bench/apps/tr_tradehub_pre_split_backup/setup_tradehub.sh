#!/bin/bash
# TR-TradeHub Installation & Migration Script
# ============================================
# This script installs and configures the TR-TradeHub marketplace platform
# including all dependent apps and runs migrations.

set -e

echo "=========================================="
echo "TR-TradeHub Installation Script"
echo "=========================================="

# Configuration
SITE_NAME="${SITE_NAME:-marketplace.local}"
BENCH_PATH="${BENCH_PATH:-$(pwd)}"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running in bench directory
if [ ! -f "sites/common_site_config.json" ]; then
    log_error "Not in a bench directory. Please run from frappe-bench root."
    exit 1
fi

echo ""
log_info "Step 1: Installing required apps..."
echo "--------------------------------------"

# Install tr_consent_center (KVKK Consent Management)
if [ -d "apps/tr_consent_center" ]; then
    log_info "Installing tr_consent_center app..."
    bench --site $SITE_NAME install-app tr_consent_center || log_warn "tr_consent_center may already be installed"
fi

# Install tr_contract_center (Contract Management)
if [ -d "apps/tr_contract_center" ]; then
    log_info "Installing tr_contract_center app..."
    bench --site $SITE_NAME install-app tr_contract_center || log_warn "tr_contract_center may already be installed"
fi

# Install tr_tradehub (Main Marketplace App)
if [ -d "apps/tr_tradehub" ]; then
    log_info "Installing tr_tradehub app..."
    bench --site $SITE_NAME install-app tr_tradehub || log_warn "tr_tradehub may already be installed"
fi

echo ""
log_info "Step 2: Running migrations..."
echo "--------------------------------------"
bench --site $SITE_NAME migrate

echo ""
log_info "Step 3: Building assets..."
echo "--------------------------------------"
bench build --app tr_tradehub

echo ""
log_info "Step 4: Clearing cache..."
echo "--------------------------------------"
bench --site $SITE_NAME clear-cache

echo ""
log_info "Step 5: Loading fixtures..."
echo "--------------------------------------"

# Load fixtures for each app
log_info "Loading tr_consent_center fixtures..."
bench --site $SITE_NAME execute tr_consent_center.fixtures.load_fixtures || log_warn "No fixtures loader for tr_consent_center"

log_info "Loading tr_contract_center fixtures..."
bench --site $SITE_NAME execute tr_contract_center.fixtures.load_fixtures || log_warn "No fixtures loader for tr_contract_center"

log_info "Loading tr_tradehub fixtures..."
# Seller Tiers
bench --site $SITE_NAME import-doc apps/tr_tradehub/tr_tradehub/fixtures/seller_tier || log_warn "Seller Tier fixtures not found"
# Seller Tags
bench --site $SITE_NAME import-doc apps/tr_tradehub/tr_tradehub/fixtures/seller_tag || log_warn "Seller Tag fixtures not found"
# Seller Tag Rules
bench --site $SITE_NAME import-doc apps/tr_tradehub/tr_tradehub/fixtures/seller_tag_rule || log_warn "Seller Tag Rule fixtures not found"

echo ""
log_info "Step 6: Setting up scheduler..."
echo "--------------------------------------"
bench --site $SITE_NAME scheduler enable
bench --site $SITE_NAME scheduler resume

echo ""
log_info "Step 7: Creating admin user (if needed)..."
echo "--------------------------------------"
bench --site $SITE_NAME add-system-manager admin@tr-tradehub.com --first-name "Admin" --last-name "User" || log_warn "Admin user may already exist"

echo ""
echo "=========================================="
log_info "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Run tests:           bench --site $SITE_NAME run-tests --app tr_tradehub"
echo "2. Start development:   bench start"
echo "3. Access site:         http://$SITE_NAME:8000"
echo ""
echo "Installed Components:"
echo "- tr_consent_center:    KVKK Consent Management"
echo "- tr_contract_center:   Contract & E-Sign Management"
echo "- tr_tradehub:          Main Marketplace Platform"
echo "  - Rule Engine:        Seller Tag Rules & Metrics"
echo "  - RFQ Framework:      Request for Quote System"
echo "  - Group Buy:          Contribution-based Pricing"
echo "  - Reviews:            Review & Moderation System"
echo ""
