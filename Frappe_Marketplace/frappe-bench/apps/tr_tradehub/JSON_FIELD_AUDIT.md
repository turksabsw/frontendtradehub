# TR TradeHub JSON Field Audit

**Date**: 2026-02-12
**Author**: Coder Agent
**Purpose**: Identify all JSON fields in DocTypes and determine which should be converted to Child Tables

---

## Summary

| Category | Count | Action |
|----------|-------|--------|
| **Tabular Data → Child Table** | 31 fields | Convert to Child DocTypes |
| **Configuration/Metadata → Keep JSON** | 20 fields | No conversion needed |
| **Code Fields (Templates)** | 25+ fields | No conversion (Jinja/Python code) |

---

## PRIORITY 1: Critical Tabular Fields (Must Convert)

These fields store structured list data that should be Child Tables for proper Frappe integration:

### 1. Listing DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `attributes` | JSON | Product attributes (key-value pairs) | `Listing Attribute Value` |
| `images` | JSON | Additional product images (array of URLs) | `Listing Image` |
| `bulk_pricing_tiers` | JSON | Price tiers: `[{min_qty, max_qty, price}]` | `Listing Bulk Pricing Tier` |

**Impact**: High - core product functionality

### 2. Listing Variant DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `images` | JSON | Variant images (array of URLs) | `Listing Variant Image` |

### 3. Product Variant DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `variant_images` | JSON | Variant images (hidden) | `Product Variant Image` |

### 4. SKU Product DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `images` | JSON | Product images (hidden) | `SKU Product Image` |

### 5. Payment Intent DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `installment_plan` | JSON | Installment breakdown | `Payment Installment` |
| `partial_refunds` | JSON | Array of partial refunds | `Payment Refund` |
| `fraud_flags` | JSON | Triggered fraud flags | `Payment Fraud Flag` |

**Impact**: High - payment processing functionality

### 6. Escrow Account DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `partial_releases` | JSON | Partial release records | `Escrow Partial Release` |

### 7. Commission Rule DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `restricted_sellers` | JSON | Seller profile names (inclusion list) | `Commission Rule Seller` (with `is_excluded=0`) |
| `excluded_sellers` | JSON | Seller profile names (exclusion list) | `Commission Rule Seller` (with `is_excluded=1`) |
| `restricted_categories` | JSON | Category names (inclusion list) | `Commission Rule Category` (with `is_excluded=0`) |
| `excluded_categories` | JSON | Category names (exclusion list) | `Commission Rule Category` (with `is_excluded=1`) |
| `day_of_week_restrictions` | JSON | Days array `[1,2,3,4,5]` | `Commission Rule Day` or Multi-Select field |
| `override_by` | JSON | Roles that can override | `Commission Rule Override Role` |

**Impact**: Medium - affects commission calculations

### 8. Seller Profile DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `badges` | JSON | Earned badges array | `Seller Badge` |

### 9. Seller Score DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `special_achievements` | JSON | Special achievements in period | `Seller Achievement` |

### 10. Seller Balance DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `recent_transactions` | JSON | Recent balance transactions | `Seller Balance Transaction` |

### 11. Seller Tier DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `custom_benefits` | JSON | Custom tier benefits | `Seller Tier Benefit` |

### 12. Review DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `images` | JSON | Review photos (max 5) | `Review Image` |
| `flags` | JSON | Flagged issues array | `Review Flag` |

### 13. Message DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `attachments` | JSON | Attachment objects `{file_url, file_name, file_type, file_size}` | `Message Attachment` |

### 14. Moderation Case DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `related_cases` | JSON | Related moderation case IDs | `Moderation Case Link` |
| `moderation_history` | JSON | Action history (read-only) | `Moderation Action Log` |

### 15. Order Event DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `related_events` | JSON | Related event names | `Order Event Link` |

### 16. Escrow Event DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `related_events` | JSON | Related event names | `Escrow Event Link` |

### 17. Marketplace Order DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `seller_summary` | JSON | Seller-wise subtotals and item counts | `Order Seller Summary` |

### 18. Cart DocType

| Field Name | Current Type | Description | Recommended Child DocType |
|------------|--------------|-------------|---------------------------|
| `seller_summary` | JSON | Seller-wise item groupings | `Cart Seller Summary` |

---

## PRIORITY 2: Keep as JSON (No Conversion Needed)

These fields store configuration, metadata, or external API responses that should remain JSON:

### Configuration/Settings Fields

| DocType | Field Name | Reason to Keep as JSON |
|---------|------------|------------------------|
| `ERPNext Integration Settings` | `custom_field_mappings` | UI-configurable mapping |
| `Import Job` | `column_mapping` | Dynamic import configuration |
| `Import Job` | `field_defaults` | Key-value defaults |
| `Analytics Settings` | `custom_events` | UI-configurable events |
| `Seller Tag Rule` | `rule_json` | Complex rule definition |
| `Notification Template` | `available_variables` | Simple string list |
| `Notification Template` | `example_data` | Template preview data |

### External API Responses (Immutable)

| DocType | Field Name | Reason to Keep as JSON |
|---------|------------|------------------------|
| `Payment Intent` | `gateway_response` | Full payment gateway response |
| `Payment Intent` | `fraud_check_response` | External fraud check result |
| `Payment Intent` | `webhook_response` | Webhook payload |
| `Tracking Event` | `raw_event_data` | Carrier API raw data |
| `Moderation Case` | `ai_analysis_result` | AI/ML analysis output |

### Metadata/Audit Fields

| DocType | Field Name | Reason to Keep as JSON |
|---------|------------|------------------------|
| `Escrow Account` | `metadata` | Custom key-value metadata |
| `Payment Intent` | `metadata` | Custom key-value metadata |
| `Import Job Error` | `row_data` | Original import row snapshot |
| `Moderation Case` | `content_snapshot` | Audit snapshot (immutable) |
| `Moderation Case` | `detection_flags` | Auto-detection output |
| `Media Asset` | `exif_data` | EXIF metadata (read-only) |

### Computed/Derived Fields

| DocType | Field Name | Reason to Keep as JSON |
|---------|------------|------------------------|
| `Seller KPI` | `breakdown_data` | Computed KPI breakdown |
| `Order Event` | `data_json` | Variable event data |
| `Escrow Event` | `event_data` | Variable event data |
| `Media Asset` | `dominant_colors` | Simple array of hex codes |

---

## PRIORITY 3: Code Fields (No Conversion)

These are Code fields storing templates/scripts - not tabular data:

| DocType | Field Name | Content Type |
|---------|------------|--------------|
| `Storefront` | Various | CSS/JS/HTML templates |
| `ECA Rule` | `condition` | Python condition code |
| `ECA Rule Action` | Various | Python/Jinja templates |
| `ECA Action Template` | `template` | Jinja template |
| `Payment Method` | Various | Configuration code |
| `Commission Rule` | `formula` | Calculation formula |
| `Risk Score` | `formula` | Scoring formula |
| `Sales Channel` | Various | Integration code |
| `Category Display Schema` | Various | Display templates |
| `PIM Attribute` | `validation_regex` | Regex pattern |
| `PIM Product` | Various | SEO/description templates |
| `SEO Meta` | `schema_markup` | JSON-LD schema |
| `Seller Store` | Various | Store templates |
| `Marketplace Shipment` | `label_data` | Label template |
| `Channel Field Mapping` | `transform_code` | Transformation code |
| `ECA Rule Log` | Various | Execution logs |

---

## Recommended Child Table DocTypes to Create

### Phase 2-1: Image Child Tables (Consolidate to 1 reusable)

Create **`Image Link`** child table (reusable across DocTypes):
```json
{
  "doctype": "DocType",
  "istable": 1,
  "name": "Image Link",
  "fields": [
    {"fieldname": "image_url", "fieldtype": "Attach Image", "reqd": 1},
    {"fieldname": "alt_text", "fieldtype": "Data"},
    {"fieldname": "sort_order", "fieldtype": "Int", "default": 0},
    {"fieldname": "is_primary", "fieldtype": "Check", "default": 0}
  ]
}
```

**Usage**: Listing, Listing Variant, Product Variant, SKU Product, Review

### Phase 2-2: Listing-Specific Child Tables

1. **`Listing Attribute Value`**
   - `attribute` (Link to Attribute)
   - `attribute_name` (Data, fetch_from)
   - `value` (Data)
   - `unit` (Data)

2. **`Listing Bulk Pricing Tier`**
   - `min_qty` (Int, reqd)
   - `max_qty` (Int)
   - `price` (Currency, reqd)
   - `discount_percentage` (Percent)

### Phase 2-3: Payment Child Tables

1. **`Payment Installment`**
   - `installment_number` (Int)
   - `due_date` (Date)
   - `amount` (Currency)
   - `status` (Select: Pending/Paid/Overdue)

2. **`Payment Refund`**
   - `refund_date` (Datetime)
   - `amount` (Currency)
   - `reason` (Data)
   - `gateway_refund_id` (Data)

3. **`Payment Fraud Flag`**
   - `flag_code` (Data)
   - `flag_description` (Data)
   - `severity` (Select: Low/Medium/High)

### Phase 2-4: Commission Rule Link Tables

1. **`Commission Rule Seller`**
   - `seller` (Link to Seller Profile)
   - `is_excluded` (Check) - 0=restricted, 1=excluded

2. **`Commission Rule Category`**
   - `category` (Link to Category)
   - `is_excluded` (Check)

### Phase 2-5: Seller Profile Child Tables

1. **`Seller Badge`**
   - `badge_name` (Data)
   - `badge_icon` (Attach Image)
   - `earned_date` (Date)
   - `description` (Small Text)

2. **`Seller Achievement`**
   - `achievement_type` (Data)
   - `achievement_date` (Date)
   - `value` (Float)
   - `period` (Data)

### Phase 2-6: Moderation & Review Child Tables

1. **`Review Image`** → Use `Image Link`

2. **`Review Flag`**
   - `flag_type` (Select: Spam/Inappropriate/Fake/Other)
   - `flagged_by` (Link to User)
   - `flagged_date` (Datetime)
   - `notes` (Small Text)

3. **`Moderation Action Log`**
   - `action_type` (Select: Reviewed/Escalated/Approved/Rejected)
   - `action_by` (Link to User)
   - `action_date` (Datetime)
   - `notes` (Text)

### Phase 2-7: Message Attachment

1. **`Message Attachment`**
   - `file` (Attach)
   - `file_name` (Data, read_only)
   - `file_type` (Data, read_only)
   - `file_size` (Int, read_only)

### Phase 2-8: Escrow Child Tables

1. **`Escrow Partial Release`**
   - `release_date` (Datetime)
   - `amount` (Currency)
   - `released_by` (Link to User)
   - `reason` (Data)
   - `reference` (Data)

### Phase 2-9: Order/Cart Seller Summary

1. **`Order Seller Summary`**
   - `seller` (Link to Seller Profile)
   - `item_count` (Int)
   - `subtotal` (Currency)
   - `shipping_total` (Currency)
   - `tax_total` (Currency)
   - `grand_total` (Currency)

2. **`Cart Seller Summary`** → Same structure as above

---

## Migration Strategy

1. **Create Child DocTypes first** (new tables in DB)
2. **Add Table fields to parents** (keep JSON fields temporarily)
3. **Run migration patches** to copy data from JSON to Child Tables
4. **Update Python/JS code** to use Child Tables instead of JSON
5. **Mark JSON fields as deprecated** (hidden, read_only)
6. **Remove JSON fields** after verification period

---

## Files to Modify (Per Phase)

### Phase 2-2: Listing Child Tables
- `listing/listing.json` - Add Table fields, deprecate JSON
- `listing/listing.py` - Update Python code
- `listing/listing.js` - Update JS code
- Create: `listing_attribute_value/`, `listing_bulk_pricing_tier/`

### Phase 2-3: Payment Child Tables
- `payment_intent/payment_intent.json`
- `payment_intent/payment_intent.py`
- Create: `payment_installment/`, `payment_refund/`, `payment_fraud_flag/`

### Phase 2-4: Commission Rule
- `commission_rule/commission_rule.json`
- `commission_rule/commission_rule.py`
- Create: `commission_rule_seller/`, `commission_rule_category/`

### Phase 2-5: Seller Profile
- `seller_profile/seller_profile.json`
- `seller_profile/seller_profile.py`
- Create: `seller_badge/`

### Phase 2-6: Seller Score/Balance/Tier
- Multiple seller-related DocTypes
- Create: `seller_achievement/`, `seller_balance_transaction/`, `seller_tier_benefit/`

---

## Existing Child Tables (Already Implemented)

The following Child Tables already exist in the codebase (from PIM module):

| Child DocType | Parent DocType | Purpose |
|---------------|----------------|---------|
| `PIM Product Media` | `PIM Product` | Product images/videos |
| `PIM Product Relation` | `PIM Product` | Related products |
| `PIM Product Description` | `PIM Product` | Multi-language descriptions |
| `PIM Product Category Link` | `PIM Product` | Category assignments |
| `PIM Product Attribute Value` | `PIM Product` | Attribute values |
| `PIM Product Class Field Value` | `PIM Product` | Class-specific fields |

These can serve as **patterns** for the new Child Tables.

---

## Notes

1. **Image consolidation**: Consider using a single `Image Link` child table for all image arrays
2. **Link tables**: For seller/category restrictions, use Link fields pointing to actual DocTypes
3. **Read-only fields**: Some JSON fields (like `moderation_history`) are read-only audit logs - these still benefit from Child Tables for queryability
4. **Backwards compatibility**: Keep deprecated JSON fields hidden for a transition period

---

## Next Steps

1. ✅ Complete this audit document (subtask-2-1)
2. Create Child DocType definitions (subtask-2-2)
3. Write migration patches (subtask-2-3)
