# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
PIM Completeness Calculator

Calculates product data completeness based on Product Family rules.
Supports multiple rule types including required attributes, media counts,
description length requirements, and custom validations.

Score Formula:
  Base: (filled_required/total_required)*0.6 + media_ok*0.25 + desc_ok*0.15
  With weights: Each rule contributes proportionally to its weight
"""

import json
from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime


class CompletenessCalculator:
    """
    Calculates product completeness score based on Product Family rules.

    Supports rule types:
    - Required Attribute: Check if specific attributes are filled
    - Required Description: Check if description exists
    - Min Description Length: Check description meets minimum length
    - Required Media: Check if media files exist
    - Min Media Count: Check minimum number of media files
    - Required Image Angle: Check specific image angles are provided
    - Attribute Validation: Validate attribute values meet criteria
    - Custom: Custom validation logic
    """

    # Default weights for base formula when no specific rules defined
    DEFAULT_ATTRIBUTE_WEIGHT = 0.6
    DEFAULT_MEDIA_WEIGHT = 0.25
    DEFAULT_DESCRIPTION_WEIGHT = 0.15

    # Status thresholds
    STATUS_THRESHOLDS = {
        'Incomplete': (0, 25),
        'Partial': (25, 75),
        'Complete': (75, 95),
        'Enriched': (95, 100.01)  # Slightly over 100 to include 100
    }

    def __init__(self, product: Any, channel: Optional[str] = None, locale: Optional[str] = None):
        """
        Initialize completeness calculator for a product.

        Args:
            product: PIM Product document or product name/code
            channel: Optional sales channel to filter rules by
            locale: Optional locale to filter rules by
        """
        if isinstance(product, str):
            self.product = frappe.get_doc("PIM Product", product)
        else:
            self.product = product

        self.channel = channel
        self.locale = locale
        self.family = None
        self.rules = []
        self.results = {}

        # Load product family if available
        if self.product.product_family:
            try:
                self.family = frappe.get_doc("Product Family", self.product.product_family)
                self.rules = self.family.get_completeness_rules(
                    channel=self.channel,
                    locale=self.locale
                )
            except frappe.DoesNotExistError:
                pass

    def calculate(self) -> dict:
        """
        Calculate completeness score and return detailed results.

        Returns:
            dict: {
                'score': float (0-100),
                'status': str (Incomplete/Partial/Complete/Enriched),
                'detail': {
                    'rules_evaluated': int,
                    'rules_passed': int,
                    'categories': {
                        'attributes': {...},
                        'media': {...},
                        'descriptions': {...}
                    },
                    'failed_rules': [...],
                    'passed_rules': [...]
                }
            }
        """
        if not self.family or not self.rules:
            # No family or rules defined - use default calculation
            return self._calculate_default()

        return self._calculate_with_rules()

    def _calculate_default(self) -> dict:
        """
        Calculate completeness using default formula when no rules are defined.

        Formula: (filled_required/total_required)*0.6 + media_ok*0.25 + desc_ok*0.15

        Returns:
            dict: Completeness result
        """
        result = {
            'rules_evaluated': 3,
            'rules_passed': 0,
            'categories': {},
            'failed_rules': [],
            'passed_rules': []
        }

        total_score = 0.0

        # 1. Required Attributes (60% weight)
        attr_result = self._check_required_attributes_default()
        result['categories']['attributes'] = attr_result
        attr_score = attr_result['score'] * self.DEFAULT_ATTRIBUTE_WEIGHT
        total_score += attr_score

        if attr_result['passed']:
            result['rules_passed'] += 1
            result['passed_rules'].append({
                'type': 'Required Attribute',
                'description': 'All required attributes are filled',
                'score': attr_result['score'],
                'weight': self.DEFAULT_ATTRIBUTE_WEIGHT
            })
        else:
            result['failed_rules'].append({
                'type': 'Required Attribute',
                'description': f"Missing {attr_result['missing_count']} required attributes",
                'missing': attr_result.get('missing_attributes', []),
                'score': attr_result['score'],
                'weight': self.DEFAULT_ATTRIBUTE_WEIGHT
            })

        # 2. Media (25% weight)
        media_result = self._check_media_default()
        result['categories']['media'] = media_result
        media_score = media_result['score'] * self.DEFAULT_MEDIA_WEIGHT
        total_score += media_score

        if media_result['passed']:
            result['rules_passed'] += 1
            result['passed_rules'].append({
                'type': 'Required Media',
                'description': 'Media requirements met',
                'score': media_result['score'],
                'weight': self.DEFAULT_MEDIA_WEIGHT
            })
        else:
            result['failed_rules'].append({
                'type': 'Required Media',
                'description': media_result.get('reason', 'Media requirements not met'),
                'score': media_result['score'],
                'weight': self.DEFAULT_MEDIA_WEIGHT
            })

        # 3. Description (15% weight)
        desc_result = self._check_description_default()
        result['categories']['descriptions'] = desc_result
        desc_score = desc_result['score'] * self.DEFAULT_DESCRIPTION_WEIGHT
        total_score += desc_score

        if desc_result['passed']:
            result['rules_passed'] += 1
            result['passed_rules'].append({
                'type': 'Required Description',
                'description': 'Description is provided',
                'score': desc_result['score'],
                'weight': self.DEFAULT_DESCRIPTION_WEIGHT
            })
        else:
            result['failed_rules'].append({
                'type': 'Required Description',
                'description': desc_result.get('reason', 'Description is missing'),
                'score': desc_result['score'],
                'weight': self.DEFAULT_DESCRIPTION_WEIGHT
            })

        # Calculate final score (percentage 0-100)
        final_score = total_score * 100
        status = self._get_status(final_score)

        return {
            'score': round(final_score, 2),
            'status': status,
            'detail': result,
            'calculated_at': str(now_datetime())
        }

    def _calculate_with_rules(self) -> dict:
        """
        Calculate completeness using Product Family rules.

        Each rule has a weight (0-1). The final score is:
        sum(rule_score * rule_weight) / sum(rule_weights) * 100

        Returns:
            dict: Completeness result
        """
        result = {
            'rules_evaluated': len(self.rules),
            'rules_passed': 0,
            'categories': {
                'attributes': {'total': 0, 'filled': 0, 'rules': []},
                'media': {'total': 0, 'fulfilled': 0, 'rules': []},
                'descriptions': {'total': 0, 'fulfilled': 0, 'rules': []}
            },
            'failed_rules': [],
            'passed_rules': []
        }

        total_weight = 0.0
        weighted_score = 0.0

        for rule in self.rules:
            rule_result = self._evaluate_rule(rule)
            weight = flt(rule.get('weight', 1.0))
            total_weight += weight

            if rule_result['passed']:
                weighted_score += weight
                result['rules_passed'] += 1
                result['passed_rules'].append({
                    'type': rule['rule_type'],
                    'target': rule.get('target_attribute'),
                    'weight': weight,
                    'score': 1.0
                })
            else:
                # Partial score for partial completion
                partial_score = rule_result.get('partial_score', 0)
                weighted_score += weight * partial_score
                result['failed_rules'].append({
                    'type': rule['rule_type'],
                    'target': rule.get('target_attribute'),
                    'reason': rule_result.get('reason', 'Rule not satisfied'),
                    'weight': weight,
                    'score': partial_score
                })

            # Categorize results
            self._categorize_rule_result(result['categories'], rule, rule_result)

        # Calculate final score
        if total_weight > 0:
            final_score = (weighted_score / total_weight) * 100
        else:
            final_score = 0.0

        status = self._get_status(final_score)

        return {
            'score': round(final_score, 2),
            'status': status,
            'detail': result,
            'calculated_at': str(now_datetime())
        }

    def _evaluate_rule(self, rule: dict) -> dict:
        """
        Evaluate a single completeness rule.

        Args:
            rule: Rule configuration dict

        Returns:
            dict: {passed: bool, reason: str, partial_score: float}
        """
        rule_type = rule.get('rule_type')

        evaluators = {
            'Required Attribute': self._evaluate_required_attribute,
            'Required Description': self._evaluate_required_description,
            'Min Description Length': self._evaluate_min_description_length,
            'Required Media': self._evaluate_required_media,
            'Min Media Count': self._evaluate_min_media_count,
            'Required Image Angle': self._evaluate_required_image_angle,
            'Attribute Validation': self._evaluate_attribute_validation,
            'Custom': self._evaluate_custom_rule
        }

        evaluator = evaluators.get(rule_type, self._evaluate_unknown_rule)
        return evaluator(rule)

    def _evaluate_required_attribute(self, rule: dict) -> dict:
        """Check if a required attribute has a value."""
        attribute_code = rule.get('target_attribute')
        if not attribute_code:
            return {'passed': True, 'reason': 'No target attribute specified'}

        value = self.product.get_attribute_value(
            attribute_code,
            locale=self.locale,
            channel=self.channel
        )

        if value is None or value == '' or value == []:
            return {
                'passed': False,
                'reason': f"Attribute '{attribute_code}' is not filled",
                'partial_score': 0
            }

        return {'passed': True}

    def _evaluate_required_description(self, rule: dict) -> dict:
        """Check if product has a description."""
        # Check the descriptions child table
        has_description = False

        if self.product.descriptions:
            for desc in self.product.descriptions:
                # Filter by locale/channel if specified
                if self.locale and desc.locale and desc.locale != self.locale:
                    continue
                if self.channel and desc.channel and desc.channel != self.channel:
                    continue

                if desc.description and len(desc.description.strip()) > 0:
                    has_description = True
                    break

        # Also check short_description field
        if not has_description and self.product.short_description:
            has_description = len(self.product.short_description.strip()) > 0

        if not has_description:
            return {
                'passed': False,
                'reason': 'Product has no description',
                'partial_score': 0
            }

        return {'passed': True}

    def _evaluate_min_description_length(self, rule: dict) -> dict:
        """Check if description meets minimum length requirement."""
        min_length = cint(rule.get('min_length', 0))

        if min_length <= 0:
            return {'passed': True}

        # Get description text
        description_text = ''
        if self.product.descriptions:
            for desc in self.product.descriptions:
                if self.locale and desc.locale and desc.locale != self.locale:
                    continue
                if self.channel and desc.channel and desc.channel != self.channel:
                    continue
                if desc.description:
                    # Use character count if available, otherwise calculate
                    if desc.character_count:
                        char_count = desc.character_count
                    else:
                        # Strip HTML tags for accurate count
                        import re
                        plain_text = re.sub(r'<[^>]+>', '', desc.description)
                        char_count = len(plain_text)

                    if char_count >= min_length:
                        return {'passed': True}
                    else:
                        partial = char_count / min_length if min_length > 0 else 0
                        return {
                            'passed': False,
                            'reason': f"Description length ({char_count}) is less than required ({min_length})",
                            'partial_score': min(partial, 1.0)
                        }

        return {
            'passed': False,
            'reason': 'No description found',
            'partial_score': 0
        }

    def _evaluate_required_media(self, rule: dict) -> dict:
        """Check if product has any media files."""
        media_count = len(self.product.media or [])

        if media_count == 0:
            return {
                'passed': False,
                'reason': 'Product has no media files',
                'partial_score': 0
            }

        return {'passed': True}

    def _evaluate_min_media_count(self, rule: dict) -> dict:
        """Check if product has minimum number of media files."""
        min_count = cint(rule.get('min_media_count', 1))
        media_count = len(self.product.media or [])

        if media_count >= min_count:
            return {'passed': True}

        partial = media_count / min_count if min_count > 0 else 0
        return {
            'passed': False,
            'reason': f"Media count ({media_count}) is less than required ({min_count})",
            'partial_score': min(partial, 1.0)
        }

    def _evaluate_required_image_angle(self, rule: dict) -> dict:
        """Check if specific image angles are provided."""
        if not self.family:
            return {'passed': True, 'reason': 'No family defined'}

        required_angles = self.family.get_required_image_angles(channel=self.channel)
        if not required_angles:
            return {'passed': True}

        # Get image angles from product media
        product_angles = set()
        if self.product.media:
            for media in self.product.media:
                if media.media_type == 'Image' and media.image_angle:
                    product_angles.add(media.image_angle)

        # Check required angles
        required_angle_codes = {a['angle_code'] for a in required_angles if a.get('is_required')}
        missing_angles = required_angle_codes - product_angles

        if missing_angles:
            filled = len(required_angle_codes) - len(missing_angles)
            total = len(required_angle_codes)
            partial = filled / total if total > 0 else 0
            return {
                'passed': False,
                'reason': f"Missing required image angles: {', '.join(missing_angles)}",
                'partial_score': partial
            }

        return {'passed': True}

    def _evaluate_attribute_validation(self, rule: dict) -> dict:
        """Validate attribute value against min/max constraints."""
        attribute_code = rule.get('target_attribute')
        if not attribute_code:
            return {'passed': True}

        value = self.product.get_attribute_value(
            attribute_code,
            locale=self.locale,
            channel=self.channel
        )

        if value is None:
            return {'passed': True}  # Validation only applies if value exists

        # Check min/max value for numeric types
        min_val = rule.get('min_value')
        max_val = rule.get('max_value')

        try:
            numeric_value = flt(value)

            if min_val is not None and numeric_value < flt(min_val):
                return {
                    'passed': False,
                    'reason': f"Value {numeric_value} is less than minimum {min_val}",
                    'partial_score': 0
                }

            if max_val is not None and numeric_value > flt(max_val):
                return {
                    'passed': False,
                    'reason': f"Value {numeric_value} exceeds maximum {max_val}",
                    'partial_score': 0
                }
        except (ValueError, TypeError):
            pass

        # Check min/max length for string types
        min_len = rule.get('min_length')
        max_len = rule.get('max_length')

        if isinstance(value, str):
            str_len = len(value)

            if min_len is not None and str_len < cint(min_len):
                partial = str_len / cint(min_len) if cint(min_len) > 0 else 0
                return {
                    'passed': False,
                    'reason': f"Value length ({str_len}) is less than minimum ({min_len})",
                    'partial_score': partial
                }

            if max_len is not None and str_len > cint(max_len):
                return {
                    'passed': False,
                    'reason': f"Value length ({str_len}) exceeds maximum ({max_len})",
                    'partial_score': 0
                }

        return {'passed': True}

    def _evaluate_custom_rule(self, rule: dict) -> dict:
        """Evaluate custom rule (placeholder for extension)."""
        # Custom rules can be extended by subclassing
        return {'passed': True}

    def _evaluate_unknown_rule(self, rule: dict) -> dict:
        """Handle unknown rule types."""
        return {
            'passed': True,
            'reason': f"Unknown rule type: {rule.get('rule_type')}"
        }

    def _check_required_attributes_default(self) -> dict:
        """
        Default check for required attributes based on Family Attribute settings.

        Returns:
            dict with score, passed, missing_count, missing_attributes
        """
        if not self.family:
            return {'score': 1.0, 'passed': True, 'total': 0, 'filled': 0}

        required_attrs = self.family.get_required_attributes()
        if not required_attrs:
            return {'score': 1.0, 'passed': True, 'total': 0, 'filled': 0}

        total = len(required_attrs)
        filled = 0
        missing = []

        for attr_code in required_attrs:
            value = self.product.get_attribute_value(
                attr_code,
                locale=self.locale,
                channel=self.channel
            )
            if value is not None and value != '' and value != []:
                filled += 1
            else:
                missing.append(attr_code)

        score = filled / total if total > 0 else 1.0

        return {
            'score': score,
            'passed': filled == total,
            'total': total,
            'filled': filled,
            'missing_count': len(missing),
            'missing_attributes': missing
        }

    def _check_media_default(self) -> dict:
        """
        Default check for media based on Family media requirements.

        Returns:
            dict with score, passed, count, requirements
        """
        media_count = len(self.product.media or [])

        if not self.family:
            # No family - just check if at least one media exists
            passed = media_count > 0
            return {
                'score': 1.0 if passed else 0.0,
                'passed': passed,
                'count': media_count,
                'reason': None if passed else 'No media files'
            }

        min_images = cint(self.family.min_images) or 1
        require_main = self.family.require_main_image

        # Count images
        image_count = sum(
            1 for m in (self.product.media or [])
            if m.media_type == 'Image'
        )

        # Check main image
        has_main = any(
            m.is_main for m in (self.product.media or [])
            if m.media_type == 'Image'
        ) or bool(self.product.main_image)

        passed = True
        reasons = []

        if image_count < min_images:
            passed = False
            reasons.append(f"Need {min_images} images, have {image_count}")

        if require_main and not has_main:
            passed = False
            reasons.append("Main image required")

        score = min(image_count / min_images, 1.0) if min_images > 0 else 1.0

        return {
            'score': score,
            'passed': passed,
            'count': image_count,
            'min_required': min_images,
            'has_main': has_main,
            'reason': '; '.join(reasons) if reasons else None
        }

    def _check_description_default(self) -> dict:
        """
        Default check for product description.

        Returns:
            dict with score, passed, has_description
        """
        has_description = False
        description_length = 0

        # Check descriptions table
        if self.product.descriptions:
            for desc in self.product.descriptions:
                if self.locale and desc.locale and desc.locale != self.locale:
                    continue
                if self.channel and desc.channel and desc.channel != self.channel:
                    continue
                if desc.description and len(desc.description.strip()) > 0:
                    has_description = True
                    description_length = desc.character_count or len(desc.description)
                    break

        # Check short_description
        if not has_description and self.product.short_description:
            if len(self.product.short_description.strip()) > 0:
                has_description = True
                description_length = len(self.product.short_description)

        return {
            'score': 1.0 if has_description else 0.0,
            'passed': has_description,
            'has_description': has_description,
            'length': description_length,
            'reason': None if has_description else 'No description provided'
        }

    def _categorize_rule_result(self, categories: dict, rule: dict, result: dict):
        """Add rule result to appropriate category."""
        rule_type = rule.get('rule_type', '')

        if 'Attribute' in rule_type:
            cat = categories['attributes']
            cat['total'] += 1
            if result['passed']:
                cat['filled'] += 1
            cat['rules'].append({
                'rule': rule_type,
                'target': rule.get('target_attribute'),
                'passed': result['passed']
            })
        elif 'Media' in rule_type or 'Image' in rule_type:
            cat = categories['media']
            cat['total'] += 1
            if result['passed']:
                cat['fulfilled'] += 1
            cat['rules'].append({
                'rule': rule_type,
                'passed': result['passed']
            })
        elif 'Description' in rule_type:
            cat = categories['descriptions']
            cat['total'] += 1
            if result['passed']:
                cat['fulfilled'] += 1
            cat['rules'].append({
                'rule': rule_type,
                'passed': result['passed']
            })

    def _get_status(self, score: float) -> str:
        """
        Determine completeness status based on score.

        Args:
            score: Completeness score (0-100)

        Returns:
            str: Status (Incomplete/Partial/Complete/Enriched)
        """
        for status, (min_val, max_val) in self.STATUS_THRESHOLDS.items():
            if min_val <= score < max_val:
                return status
        return 'Incomplete'


def calculate_completeness(
    product: Any,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    update_product: bool = False
) -> dict:
    """
    Calculate completeness score for a PIM Product.

    This is the main entry point for completeness calculation.

    Args:
        product: PIM Product document, name, or product_code
        channel: Optional sales channel to evaluate for
        locale: Optional locale to evaluate for
        update_product: If True, update the product's completeness fields

    Returns:
        dict: {
            'score': float (0-100),
            'status': str,
            'detail': {...}
        }

    Example:
        >>> result = calculate_completeness("PROD-001")
        >>> print(f"Score: {result['score']}%, Status: {result['status']}")
    """
    calculator = CompletenessCalculator(product, channel=channel, locale=locale)
    result = calculator.calculate()

    if update_product:
        # Update product completeness fields
        try:
            doc = calculator.product
            frappe.db.set_value(
                "PIM Product",
                doc.name,
                {
                    'completeness_score': result['score'],
                    'completeness_status': result['status'],
                    'completeness_detail': json.dumps(result['detail']),
                    'last_completeness_check': result['calculated_at']
                },
                update_modified=False
            )
        except Exception as e:
            frappe.log_error(f"Failed to update completeness: {str(e)}")

    return result


def calculate_channel_completeness(
    product: Any,
    channels: Optional[list] = None
) -> dict:
    """
    Calculate completeness for multiple sales channels.

    Args:
        product: PIM Product document or name
        channels: List of channel names/codes. If None, uses all active channels.

    Returns:
        dict: Mapping of channel -> completeness result
    """
    if isinstance(product, str):
        product_doc = frappe.get_doc("PIM Product", product)
    else:
        product_doc = product

    if channels is None:
        # Get all active sales channels
        channels = frappe.get_all(
            "Sales Channel",
            filters={"is_active": 1},
            pluck="name"
        )

    results = {}
    for channel in channels:
        calculator = CompletenessCalculator(product_doc, channel=channel)
        results[channel] = calculator.calculate()

    return results


def bulk_calculate_completeness(
    products: list,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    update_products: bool = True
) -> list:
    """
    Calculate completeness for multiple products.

    Args:
        products: List of product names or documents
        channel: Optional channel filter
        locale: Optional locale filter
        update_products: If True, update each product's fields

    Returns:
        list: List of (product_name, result) tuples
    """
    results = []

    for product in products:
        try:
            result = calculate_completeness(
                product,
                channel=channel,
                locale=locale,
                update_product=update_products
            )
            product_name = product if isinstance(product, str) else product.name
            results.append((product_name, result))
        except Exception as e:
            product_name = product if isinstance(product, str) else getattr(product, 'name', str(product))
            results.append((product_name, {'error': str(e)}))

    return results


def recalculate_all_completeness(
    family: Optional[str] = None,
    batch_size: int = 100
) -> dict:
    """
    Recalculate completeness for all products, optionally filtered by family.

    Args:
        family: Optional Product Family to filter by
        batch_size: Number of products to process per batch

    Returns:
        dict: Summary of recalculation results
    """
    filters = {}
    if family:
        filters['product_family'] = family

    products = frappe.get_all(
        "PIM Product",
        filters=filters,
        pluck="name"
    )

    total = len(products)
    processed = 0
    errors = 0

    for i in range(0, total, batch_size):
        batch = products[i:i + batch_size]

        for product_name in batch:
            try:
                calculate_completeness(product_name, update_product=True)
                processed += 1
            except Exception as e:
                frappe.log_error(f"Completeness calc error for {product_name}: {str(e)}")
                errors += 1

        # Commit after each batch
        frappe.db.commit()

    return {
        'total': total,
        'processed': processed,
        'errors': errors,
        'success_rate': (processed / total * 100) if total > 0 else 0
    }
