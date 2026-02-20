#!/bin/bash
# TR-TradeHub Comprehensive Test Suite
# =====================================
# Runs all tests across the marketplace platform.

set -e

echo "=========================================="
echo "TR-TradeHub Test Suite"
echo "=========================================="

SITE_NAME="${SITE_NAME:-marketplace.local}"
BENCH_PATH="${BENCH_PATH:-$(pwd)}"
FAILED_TESTS=0
PASSED_TESTS=0

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_test() {
    echo -e "\n${BLUE}[TEST]${NC} $1"
    echo "--------------------------------------"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED_TESTS++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED_TESTS++))
}

# Ensure we're in bench directory
if [ ! -f "sites/common_site_config.json" ]; then
    echo -e "${RED}[ERROR]${NC} Not in a bench directory. Please run from frappe-bench root."
    exit 1
fi

# ============================================
# Test Section 1: TR Consent Center (KVKK)
# ============================================
log_test "Running tr_consent_center tests..."
if bench --site $SITE_NAME run-tests --app tr_consent_center 2>&1; then
    log_pass "tr_consent_center tests"
else
    log_fail "tr_consent_center tests"
fi

# ============================================
# Test Section 2: TR Contract Center
# ============================================
log_test "Running tr_contract_center tests..."
if bench --site $SITE_NAME run-tests --app tr_contract_center 2>&1; then
    log_pass "tr_contract_center tests"
else
    log_fail "tr_contract_center tests"
fi

# ============================================
# Test Section 3: TR TradeHub - Rule Engine
# ============================================
log_test "Running Rule Engine tests (Seller Tags)..."
if bench --site $SITE_NAME run-tests --app tr_tradehub --module tr_tradehub.tests.test_seller_tags 2>&1; then
    log_pass "Rule Engine tests"
else
    log_fail "Rule Engine tests"
fi

# ============================================
# Test Section 4: TR TradeHub - RFQ Framework
# ============================================
log_test "Running RFQ Framework tests..."
if bench --site $SITE_NAME run-tests --app tr_tradehub --module tr_tradehub.tests.test_rfq 2>&1; then
    log_pass "RFQ Framework tests"
else
    log_fail "RFQ Framework tests"
fi

# ============================================
# Test Section 5: TR TradeHub - Group Buy
# ============================================
log_test "Running Group Buy tests..."
if bench --site $SITE_NAME run-tests --app tr_tradehub --module tr_tradehub.tests.test_group_buy 2>&1; then
    log_pass "Group Buy tests"
else
    log_fail "Group Buy tests"
fi

# ============================================
# Test Section 6: TR TradeHub - Reviews
# ============================================
log_test "Running Reviews & Moderation tests..."
if bench --site $SITE_NAME run-tests --app tr_tradehub --module tr_tradehub.tests.test_reviews 2>&1; then
    log_pass "Reviews & Moderation tests"
else
    log_fail "Reviews & Moderation tests"
fi

# ============================================
# Test Section 7: Full TR TradeHub App
# ============================================
log_test "Running complete tr_tradehub test suite..."
if bench --site $SITE_NAME run-tests --app tr_tradehub 2>&1; then
    log_pass "tr_tradehub full test suite"
else
    log_fail "tr_tradehub full test suite"
fi

# ============================================
# Summary
# ============================================
echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "${GREEN}Passed:${NC} $PASSED_TESTS"
echo -e "${RED}Failed:${NC} $FAILED_TESTS"
echo ""

if [ $FAILED_TESTS -gt 0 ]; then
    echo -e "${RED}Some tests failed. Please review the output above.${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed successfully!${NC}"
    exit 0
fi
