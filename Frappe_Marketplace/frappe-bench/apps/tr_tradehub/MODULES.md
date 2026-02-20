# TR-TradeHub Module Documentation

This document provides an overview of all modules implemented in the TR-TradeHub B2B2B marketplace platform.

## Table of Contents

1. [KVKK Consent Center](#1-kvkk-consent-center)
2. [Contract Center](#2-contract-center)
3. [Rule Engine (Seller Tags)](#3-rule-engine-seller-tags)
4. [RFQ Framework](#4-rfq-framework)
5. [Group Buy Module](#5-group-buy-module)
6. [Reviews & Moderation](#6-reviews--moderation)

---

## 1. KVKK Consent Center

**App:** `tr_consent_center`
**Purpose:** Turkish KVKK (Personal Data Protection Law) compliance management

### DocTypes

| DocType | Description | Key Features |
|---------|-------------|--------------|
| Consent Channel | Communication channels (Email, SMS, Web, Mobile) | Status tracking, priority ordering |
| Consent Topic | Data processing topics | KVKK article reference, retention period |
| Consent Method | Collection methods (Explicit, Implicit, Cookie) | Proof requirements |
| Consent Text | Version-controlled consent texts | SHA256 versioning, markdown support |
| Consent Record | Individual consent records | Dynamic Link to subject, proof storage |
| Consent Audit Log | Immutable audit trail | Cannot be deleted, action tracking |

### Key Features

- **Version Control**: Consent texts use SHA256 hashing for integrity
- **5-Year Retention**: Enforced per KVKK requirements
- **Audit Trail**: Immutable logging of all consent operations
- **Dynamic Subject**: Can link to User, Customer, Organization

### API Endpoints

- `record_consent()` - Record new consent
- `withdraw_consent()` - Withdraw existing consent
- `get_consent_status()` - Check consent for a subject
- `get_consent_history()` - Full consent history

---

## 2. Contract Center

**App:** `tr_contract_center`
**Purpose:** Contract lifecycle management with e-signature support

### DocTypes

| DocType | Description | Key Features |
|---------|-------------|--------------|
| Contract Template | Reusable contract templates | Jinja2 variable support, multi-party |
| Contract Instance | Instantiated contracts | Workflow: Draft → Negotiation → Pending Signature → Active |
| Contract Revision | Version history | Diff tracking, comments |
| ESign Provider | E-signature provider config | Turkcell, Generic adapters |
| ESign Transaction | Signature transactions | Status tracking, webhook handling |

### Key Features

- **E-Sign Abstraction**: Pluggable adapter pattern for providers
- **Turkcell Integration**: Native Turkish e-signature support
- **Variable Substitution**: Jinja2 templating for dynamic contracts
- **Multi-Party Signing**: Support for multiple signatories

### API Endpoints

- `create_contract()` - Create from template
- `send_for_signature()` - Initiate e-sign flow
- `check_signature_status()` - Poll signature status
- `download_signed_contract()` - Get final document

---

## 3. Rule Engine (Seller Tags)

**Module:** `tr_tradehub.seller_tags`
**Purpose:** Dynamic seller classification and metrics-based tagging

### DocTypes

| DocType | Description | Key Features |
|---------|-------------|--------------|
| Seller Tag | Tags for seller classification | Style, description, priority |
| Seller Tag Rule | Rule definitions | AND/OR groups, 13+ operators |
| Seller Tag Assignment | Tag-to-seller mappings | Auto/manual assignment |
| Seller Metrics | Calculated performance metrics | GMV, rating, response time, etc. |

### Evaluation Operators

```
equal, not_equal, greater_than, less_than,
greater_than_or_equal, less_than_or_equal,
contains, not_contains, starts_with, ends_with,
in, not_in, between
```

### Key Features

- **Recursive AND/OR Groups**: Complex boolean logic
- **13+ Comparison Operators**: Flexible condition matching
- **Auto-Recalculation**: Scheduled metric updates
- **Fixtures Included**: 8 default tags, 7 example rules

### Scheduler Tasks

- `evaluate_all_rules()` - Daily rule evaluation
- `refresh_seller_metrics()` - Hourly metrics update
- `cleanup_old_metrics()` - Weekly cleanup

---

## 4. RFQ Framework

**Module:** `tr_tradehub.rfq`
**Purpose:** Request for Quote system for B2B procurement

### DocTypes

| DocType | Description | Key Features |
|---------|-------------|--------------|
| RFQ | Main request document | Multi-item, target sellers/categories |
| RFQ Item | Line items | Quantity, specs, delivery requirements |
| RFQ Quote | Seller responses | Pricing, validity, terms |
| RFQ Quote Revision | Quote versions | Negotiation history |
| RFQ Message Thread | Communication | Buyer-seller messaging |
| RFQ NDA Link | Contract integration | Links to Contract Center NDAs |

### Key Features

- **Target Filtering**: By seller or category
- **NDA Integration**: Links to Contract Center
- **Deadline Tracking**: Automated reminders
- **Quote Revisions**: Full negotiation history

### API Endpoints

- `create_rfq()` - Create new RFQ
- `submit_quote()` - Submit seller quote
- `accept_quote()` - Buyer accepts quote
- `send_message()` - Thread messaging

---

## 5. Group Buy Module

**Module:** `tr_tradehub.groupbuy`
**Purpose:** Contribution-based dynamic pricing for group purchases

### DocTypes

| DocType | Description | Key Features |
|---------|-------------|--------------|
| Group Buy | Main campaign | Target qty, price range, deadline |
| Group Buy Tier | Price tiers (Child) | Quantity breakpoints |
| Group Buy Commitment | Buyer commitments | Dynamic price calculation |
| Group Buy Payment | Payment processing | Integration with Payment Intent |
| Buyer Profile | Buyer accounts | Stats, commitment history |

### Pricing Formula (Model B)

```
P_i = max(P_best, P_T - α × f_i × (P_T - P_best))

Where:
- P_i: Price for buyer i
- P_T: Target price (max price at low volume)
- P_best: Best price at full target quantity
- f_i: Share factor (q_i / s_ref × T)
- α: Adjustment factor (default: 1.0)
- s_ref: Reference share (default: 20%)
```

### Key Features

- **Dynamic Pricing**: Prices decrease as volume increases
- **Fair Distribution**: Larger commitments get better prices
- **Status Workflow**: Draft → Active → Funded → Completed
- **Auto-Expiration**: Unfunded campaigns expire automatically

### Scheduler Tasks

- `check_deadlines()` - Hourly deadline checking
- `expire_unfunded()` - Expire campaigns past deadline
- `process_completed()` - Daily completion processing
- `send_reminders()` - Daily reminder emails

---

## 6. Reviews & Moderation

**Module:** `tr_tradehub.reviews`
**Purpose:** Product/seller reviews with moderation workflow

### DocTypes

| DocType | Description | Key Features |
|---------|-------------|--------------|
| Review | Customer reviews | Verified purchase, ratings, media |
| Moderation Case | Content moderation | SLA tracking, appeals, escalation |

### Review Features

- **Verified Purchase**: Order-based verification
- **Detailed Ratings**: Quality, value, shipping, communication
- **Media Support**: Images, videos (YouTube/Vimeo)
- **Helpfulness Voting**: Wilson score ranking
- **Seller Response**: Sellers can respond to reviews
- **Anonymous Option**: Privacy for reviewers

### Moderation Features

- **Auto-Detection**: Spam, profanity, low-effort detection
- **SLA Tracking**: Priority-based resolution targets
- **Escalation**: Multi-level escalation workflow
- **Appeals**: Content owners can appeal decisions
- **Content Snapshot**: Original content preserved

### API Endpoints

**Reviews:**
- `submit_review()` - Create new review
- `vote_review()` - Helpfulness voting
- `add_seller_response()` - Seller responds
- `get_listing_reviews()` - Reviews for product
- `get_seller_reviews()` - Reviews for seller

**Moderation:**
- `report_content()` - Report for moderation
- `assign_case()` - Assign to moderator
- `resolve_case()` - Make decision
- `escalate_case()` - Escalate to higher level
- `submit_appeal()` - Appeal decision

### Scheduler Tasks

- `process_pending_reviews()` - Auto-approve old pending reviews
- `check_sla_breaches()` - Hourly SLA monitoring
- `send_review_reminders()` - Remind buyers to review
- `calculate_seller_scores()` - Update seller ratings
- `cleanup_old_cases()` - Archive old cases
- `process_expired_appeals()` - Auto-reject old appeals

---

## Installation

```bash
# From frappe-bench directory
./apps/tr_tradehub/setup_tradehub.sh
```

## Testing

```bash
# Run all tests
./apps/tr_tradehub/run_all_tests.sh

# Run specific module tests
bench --site marketplace.local run-tests --app tr_tradehub --module tr_tradehub.tests.test_reviews
```

## Configuration

All module settings are managed in **TR TradeHub Settings** (Single DocType):
- Gemini API Key (for AI features)
- Payment gateway credentials
- Scheduler intervals
- Feature flags

---

## Architecture Notes

### Multi-Tenant Support
All DocTypes include `tenant_id` field for data isolation.

### ERPNext Integration
- Listings sync to ERPNext Items
- Orders sync to Sales Orders
- Payments sync to Payment Entries
- Escrow uses Journal Entries

### API Pattern
All APIs follow: `@frappe.whitelist()` with versioned paths (`/api/v1/*`)

### Scheduler
All background tasks registered in `hooks.py` under `scheduler_events`
