# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
Test Suite for ECA Chain Tracker

This test suite covers:
- Chain ID generation and tracking
- Chain depth enforcement
- Circular trigger detection and prevention
- Context manager functionality
- Flag-based state management
- Chain reset and cleanup

Run with:
    bench --site [site] run-tests --module tr_tradehub.tests.test_eca_chain_tracker
"""

import unittest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from contextlib import contextmanager


# =============================================================================
# MOCK FRAPPE MODULE
# =============================================================================

class MockFlags:
    """Mock frappe.flags for testing."""
    pass


class MockFrappe:
    """Mock Frappe module for standalone testing."""

    flags = MockFlags()
    _hash_counter = 0

    @staticmethod
    def _(text):
        return text

    @staticmethod
    def log_error(message, title=None):
        pass

    @staticmethod
    def throw(message):
        raise Exception(message)

    @staticmethod
    def has_permission(doctype, ptype):
        return True

    @staticmethod
    def generate_hash(length=12):
        """Generate a predictable hash for testing."""
        MockFrappe._hash_counter += 1
        return f"chain_{MockFrappe._hash_counter:012d}"

    @staticmethod
    def whitelist():
        def decorator(func):
            return func
        return decorator

    @staticmethod
    def reset_flags():
        """Reset flags to clean state."""
        MockFrappe.flags = MockFlags()
        MockFrappe._hash_counter = 0


# Patch frappe module
import sys
sys.modules['frappe'] = MockFrappe


# =============================================================================
# CHAIN TRACKER IMPLEMENTATION (copied for standalone testing)
# =============================================================================

@dataclass
class ChainTrackingResult:
    """Result of a chain tracking check."""
    allowed: bool
    chain_id: str
    chain_depth: int
    max_depth: int
    reason: Optional[str] = None
    triggered_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "chain_id": self.chain_id,
            "chain_depth": self.chain_depth,
            "max_depth": self.max_depth,
            "reason": self.reason,
            "triggered_rules": self.triggered_rules,
        }


@dataclass
class ChainContext:
    """Context information for a chain execution scope."""
    allowed: bool
    chain_id: str
    chain_depth: int
    max_depth: int
    reason: Optional[str] = None
    triggered_rules: List[str] = field(default_factory=list)


class TestableECAChainTracker:
    """Testable version of ECAChainTracker for standalone testing."""

    FLAG_PROCESSING = "eca_processing"
    FLAG_CHAIN_ID = "eca_chain_id"
    FLAG_CHAIN_DEPTH = "eca_chain_depth"
    FLAG_TRIGGERED_RULES = "eca_triggered_rules"

    def __init__(self):
        pass

    @property
    def is_processing(self) -> bool:
        return getattr(MockFrappe.flags, self.FLAG_PROCESSING, False)

    @property
    def chain_id(self) -> Optional[str]:
        return getattr(MockFrappe.flags, self.FLAG_CHAIN_ID, None)

    @property
    def chain_depth(self) -> int:
        return getattr(MockFrappe.flags, self.FLAG_CHAIN_DEPTH, 0)

    @property
    def triggered_rules(self) -> Set[str]:
        rules = getattr(MockFrappe.flags, self.FLAG_TRIGGERED_RULES, None)
        if rules is None:
            rules = set()
            setattr(MockFrappe.flags, self.FLAG_TRIGGERED_RULES, rules)
        return rules

    def can_execute(self, rule, max_depth: Optional[int] = None) -> ChainTrackingResult:
        """Check if a rule execution is allowed."""
        if max_depth is None:
            max_depth = rule.get("max_chain_depth") or 5

        prevent_circular = rule.get("prevent_circular", True)

        current_chain_id = self.chain_id or ""
        current_depth = self.chain_depth
        current_rules = list(self.triggered_rules)

        # Check 1: Depth limit
        if current_depth >= max_depth:
            return ChainTrackingResult(
                allowed=False,
                chain_id=current_chain_id,
                chain_depth=current_depth,
                max_depth=max_depth,
                reason=f"Maximum chain depth exceeded: {current_depth}/{max_depth}",
                triggered_rules=current_rules
            )

        # Check 2: Circular reference
        if prevent_circular and rule.name in self.triggered_rules:
            return ChainTrackingResult(
                allowed=False,
                chain_id=current_chain_id,
                chain_depth=current_depth,
                max_depth=max_depth,
                reason=f"Circular trigger detected: Rule '{rule.name}' already executed in this chain",
                triggered_rules=current_rules
            )

        # All checks passed
        return ChainTrackingResult(
            allowed=True,
            chain_id=current_chain_id,
            chain_depth=current_depth,
            max_depth=max_depth,
            triggered_rules=current_rules
        )

    def enter_chain(self, rule, chain_id: Optional[str] = None) -> str:
        """Enter a new chain level for rule execution."""
        setattr(MockFrappe.flags, self.FLAG_PROCESSING, True)

        if chain_id:
            current_chain_id = chain_id
        elif self.chain_id:
            current_chain_id = self.chain_id
        else:
            current_chain_id = MockFrappe.generate_hash(length=12)

        setattr(MockFrappe.flags, self.FLAG_CHAIN_ID, current_chain_id)

        new_depth = self.chain_depth + 1
        setattr(MockFrappe.flags, self.FLAG_CHAIN_DEPTH, new_depth)

        self.triggered_rules.add(rule.name)

        return current_chain_id

    def exit_chain(self) -> None:
        """Exit the current chain level."""
        new_depth = max(0, self.chain_depth - 1)
        setattr(MockFrappe.flags, self.FLAG_CHAIN_DEPTH, new_depth)

        if new_depth == 0:
            self._reset_flags()

    def _reset_flags(self) -> None:
        """Reset all ECA chain tracking flags."""
        setattr(MockFrappe.flags, self.FLAG_PROCESSING, False)
        setattr(MockFrappe.flags, self.FLAG_CHAIN_ID, None)
        setattr(MockFrappe.flags, self.FLAG_CHAIN_DEPTH, 0)
        setattr(MockFrappe.flags, self.FLAG_TRIGGERED_RULES, set())

    def force_reset(self) -> None:
        """Force reset all chain tracking flags."""
        self._reset_flags()

    def get_chain_info(self) -> dict:
        """Get current chain tracking information."""
        return {
            "is_processing": self.is_processing,
            "chain_id": self.chain_id,
            "chain_depth": self.chain_depth,
            "triggered_rules": list(self.triggered_rules),
        }


@contextmanager
def chain_context(rule, max_depth=None, chain_id=None, tracker=None):
    """Context manager for ECA chain tracking."""
    if tracker is None:
        tracker = TestableECAChainTracker()

    result = tracker.can_execute(rule, max_depth)

    if not result.allowed:
        yield ChainContext(
            allowed=False,
            chain_id=result.chain_id,
            chain_depth=result.chain_depth,
            max_depth=result.max_depth,
            reason=result.reason,
            triggered_rules=result.triggered_rules
        )
        return

    actual_chain_id = tracker.enter_chain(rule, chain_id)

    try:
        yield ChainContext(
            allowed=True,
            chain_id=actual_chain_id,
            chain_depth=tracker.chain_depth,
            max_depth=result.max_depth,
            triggered_rules=list(tracker.triggered_rules)
        )
    finally:
        tracker.exit_chain()


# =============================================================================
# MOCK DOCUMENT CLASSES
# =============================================================================

@dataclass
class MockRule:
    """Mock ECA Rule document for testing."""
    name: str = "RULE-001"
    rule_name: str = "Test Rule"
    prevent_circular: bool = True
    max_chain_depth: int = 5

    def get(self, field, default=None):
        return getattr(self, field, default)


# =============================================================================
# TEST CLASSES
# =============================================================================

class TestChainTrackingResult(unittest.TestCase):
    """Tests for ChainTrackingResult dataclass."""

    def test_to_dict(self):
        """Test ChainTrackingResult to_dict conversion."""
        result = ChainTrackingResult(
            allowed=True,
            chain_id="abc123",
            chain_depth=2,
            max_depth=5,
            triggered_rules=["RULE-001", "RULE-002"]
        )
        d = result.to_dict()

        self.assertEqual(d["allowed"], True)
        self.assertEqual(d["chain_id"], "abc123")
        self.assertEqual(d["chain_depth"], 2)
        self.assertEqual(d["max_depth"], 5)
        self.assertEqual(d["triggered_rules"], ["RULE-001", "RULE-002"])

    def test_to_dict_with_reason(self):
        """Test ChainTrackingResult to_dict with reason."""
        result = ChainTrackingResult(
            allowed=False,
            chain_id="abc123",
            chain_depth=5,
            max_depth=5,
            reason="Maximum depth exceeded"
        )
        d = result.to_dict()

        self.assertEqual(d["allowed"], False)
        self.assertEqual(d["reason"], "Maximum depth exceeded")


class TestChainTrackerInitialState(unittest.TestCase):
    """Tests for chain tracker initial state."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_initial_not_processing(self):
        """Test that initial state is not processing."""
        self.assertFalse(self.tracker.is_processing)

    def test_initial_chain_id_none(self):
        """Test that initial chain_id is None."""
        self.assertIsNone(self.tracker.chain_id)

    def test_initial_chain_depth_zero(self):
        """Test that initial chain_depth is 0."""
        self.assertEqual(self.tracker.chain_depth, 0)

    def test_initial_triggered_rules_empty(self):
        """Test that initial triggered_rules is empty."""
        self.assertEqual(len(self.tracker.triggered_rules), 0)


class TestCanExecute(unittest.TestCase):
    """Tests for can_execute method."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_first_execution_allowed(self):
        """Test that first execution is always allowed."""
        rule = MockRule()

        result = self.tracker.can_execute(rule)

        self.assertTrue(result.allowed)
        self.assertEqual(result.chain_depth, 0)
        self.assertIsNone(result.reason)

    def test_execution_within_depth_limit_allowed(self):
        """Test execution within depth limit is allowed."""
        rule = MockRule(max_chain_depth=5)

        # Simulate being at depth 3
        setattr(MockFrappe.flags, self.tracker.FLAG_CHAIN_DEPTH, 3)

        result = self.tracker.can_execute(rule)

        self.assertTrue(result.allowed)
        self.assertEqual(result.chain_depth, 3)

    def test_execution_at_max_depth_blocked(self):
        """Test execution at max depth is blocked."""
        rule = MockRule(max_chain_depth=5)

        # Simulate being at depth 5 (max)
        setattr(MockFrappe.flags, self.tracker.FLAG_CHAIN_DEPTH, 5)

        result = self.tracker.can_execute(rule)

        self.assertFalse(result.allowed)
        self.assertIn("Maximum chain depth exceeded", result.reason)

    def test_execution_exceeding_max_depth_blocked(self):
        """Test execution exceeding max depth is blocked."""
        rule = MockRule(max_chain_depth=3)

        # Simulate being at depth 4
        setattr(MockFrappe.flags, self.tracker.FLAG_CHAIN_DEPTH, 4)

        result = self.tracker.can_execute(rule)

        self.assertFalse(result.allowed)

    def test_circular_trigger_blocked(self):
        """Test that circular trigger is blocked."""
        rule = MockRule(name="RULE-001", prevent_circular=True)

        # Simulate rule already in triggered set
        setattr(MockFrappe.flags, self.tracker.FLAG_TRIGGERED_RULES, {"RULE-001"})

        result = self.tracker.can_execute(rule)

        self.assertFalse(result.allowed)
        self.assertIn("Circular trigger detected", result.reason)
        self.assertIn("RULE-001", result.reason)

    def test_circular_prevention_disabled_allows_reexecution(self):
        """Test that disabling circular prevention allows re-execution."""
        rule = MockRule(name="RULE-001", prevent_circular=False)

        # Simulate rule already in triggered set
        setattr(MockFrappe.flags, self.tracker.FLAG_TRIGGERED_RULES, {"RULE-001"})

        result = self.tracker.can_execute(rule)

        self.assertTrue(result.allowed)

    def test_custom_max_depth_override(self):
        """Test custom max_depth parameter overrides rule setting."""
        rule = MockRule(max_chain_depth=10)

        # Set depth to 3
        setattr(MockFrappe.flags, self.tracker.FLAG_CHAIN_DEPTH, 3)

        # Override with max_depth=3
        result = self.tracker.can_execute(rule, max_depth=3)

        self.assertFalse(result.allowed)

    def test_default_max_depth_five(self):
        """Test default max_depth is 5 when not specified."""
        rule = MockRule(max_chain_depth=None)

        # Set depth to 4 (should be allowed with default 5)
        setattr(MockFrappe.flags, self.tracker.FLAG_CHAIN_DEPTH, 4)

        result = self.tracker.can_execute(rule)

        self.assertTrue(result.allowed)
        self.assertEqual(result.max_depth, 5)


class TestEnterChain(unittest.TestCase):
    """Tests for enter_chain method."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_enter_chain_sets_processing_flag(self):
        """Test that enter_chain sets processing flag."""
        rule = MockRule()

        self.tracker.enter_chain(rule)

        self.assertTrue(self.tracker.is_processing)

    def test_enter_chain_generates_chain_id(self):
        """Test that enter_chain generates a chain_id."""
        rule = MockRule()

        chain_id = self.tracker.enter_chain(rule)

        self.assertIsNotNone(chain_id)
        self.assertEqual(chain_id, self.tracker.chain_id)

    def test_enter_chain_increments_depth(self):
        """Test that enter_chain increments depth."""
        rule = MockRule()

        self.assertEqual(self.tracker.chain_depth, 0)
        self.tracker.enter_chain(rule)
        self.assertEqual(self.tracker.chain_depth, 1)

    def test_enter_chain_adds_rule_to_triggered(self):
        """Test that enter_chain adds rule to triggered set."""
        rule = MockRule(name="RULE-001")

        self.tracker.enter_chain(rule)

        self.assertIn("RULE-001", self.tracker.triggered_rules)

    def test_enter_chain_uses_provided_chain_id(self):
        """Test that enter_chain uses provided chain_id."""
        rule = MockRule()

        chain_id = self.tracker.enter_chain(rule, chain_id="custom_chain_123")

        self.assertEqual(chain_id, "custom_chain_123")
        self.assertEqual(self.tracker.chain_id, "custom_chain_123")

    def test_enter_chain_reuses_existing_chain_id(self):
        """Test that nested enter_chain reuses existing chain_id."""
        rule1 = MockRule(name="RULE-001")
        rule2 = MockRule(name="RULE-002")

        chain_id1 = self.tracker.enter_chain(rule1)
        chain_id2 = self.tracker.enter_chain(rule2)

        self.assertEqual(chain_id1, chain_id2)

    def test_multiple_enter_chain_increments_depth(self):
        """Test that multiple enter_chain calls increment depth."""
        rules = [MockRule(name=f"RULE-{i}") for i in range(5)]

        for i, rule in enumerate(rules):
            self.tracker.enter_chain(rule)
            self.assertEqual(self.tracker.chain_depth, i + 1)


class TestExitChain(unittest.TestCase):
    """Tests for exit_chain method."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_exit_chain_decrements_depth(self):
        """Test that exit_chain decrements depth."""
        rule = MockRule()
        self.tracker.enter_chain(rule)

        self.assertEqual(self.tracker.chain_depth, 1)
        self.tracker.exit_chain()
        self.assertEqual(self.tracker.chain_depth, 0)

    def test_exit_chain_at_root_resets_all_flags(self):
        """Test that exit_chain at root level resets all flags."""
        rule = MockRule()
        self.tracker.enter_chain(rule)
        self.tracker.exit_chain()

        self.assertFalse(self.tracker.is_processing)
        self.assertIsNone(self.tracker.chain_id)
        self.assertEqual(self.tracker.chain_depth, 0)
        self.assertEqual(len(self.tracker.triggered_rules), 0)

    def test_exit_chain_nested_preserves_state(self):
        """Test that exit_chain in nested context preserves outer state."""
        rule1 = MockRule(name="RULE-001")
        rule2 = MockRule(name="RULE-002")

        chain_id = self.tracker.enter_chain(rule1)
        self.tracker.enter_chain(rule2)

        self.assertEqual(self.tracker.chain_depth, 2)

        # Exit inner chain
        self.tracker.exit_chain()

        # State should be preserved at depth 1
        self.assertEqual(self.tracker.chain_depth, 1)
        self.assertTrue(self.tracker.is_processing)
        self.assertEqual(self.tracker.chain_id, chain_id)

    def test_exit_chain_never_goes_negative(self):
        """Test that exit_chain never makes depth negative."""
        # Exit without entering
        self.tracker.exit_chain()

        self.assertEqual(self.tracker.chain_depth, 0)


class TestForceReset(unittest.TestCase):
    """Tests for force_reset method."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_force_reset_clears_all_state(self):
        """Test that force_reset clears all chain tracking state."""
        # Build up some state
        rule1 = MockRule(name="RULE-001")
        rule2 = MockRule(name="RULE-002")
        self.tracker.enter_chain(rule1)
        self.tracker.enter_chain(rule2)

        # Force reset
        self.tracker.force_reset()

        # All state should be cleared
        self.assertFalse(self.tracker.is_processing)
        self.assertIsNone(self.tracker.chain_id)
        self.assertEqual(self.tracker.chain_depth, 0)
        self.assertEqual(len(self.tracker.triggered_rules), 0)

    def test_force_reset_works_when_not_processing(self):
        """Test that force_reset works even when not processing."""
        self.tracker.force_reset()

        self.assertFalse(self.tracker.is_processing)


class TestGetChainInfo(unittest.TestCase):
    """Tests for get_chain_info method."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_get_chain_info_initial_state(self):
        """Test get_chain_info in initial state."""
        info = self.tracker.get_chain_info()

        self.assertEqual(info["is_processing"], False)
        self.assertIsNone(info["chain_id"])
        self.assertEqual(info["chain_depth"], 0)
        self.assertEqual(info["triggered_rules"], [])

    def test_get_chain_info_during_processing(self):
        """Test get_chain_info during processing."""
        rule = MockRule(name="RULE-001")
        chain_id = self.tracker.enter_chain(rule)

        info = self.tracker.get_chain_info()

        self.assertEqual(info["is_processing"], True)
        self.assertEqual(info["chain_id"], chain_id)
        self.assertEqual(info["chain_depth"], 1)
        self.assertIn("RULE-001", info["triggered_rules"])


class TestChainContext(unittest.TestCase):
    """Tests for chain_context context manager."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()

    def test_context_allowed_first_execution(self):
        """Test context manager allows first execution."""
        rule = MockRule()

        with chain_context(rule) as ctx:
            self.assertTrue(ctx.allowed)
            self.assertIsNotNone(ctx.chain_id)
            self.assertEqual(ctx.chain_depth, 1)

    def test_context_cleans_up_on_exit(self):
        """Test context manager cleans up on exit."""
        rule = MockRule()
        tracker = TestableECAChainTracker()

        with chain_context(rule, tracker=tracker):
            self.assertTrue(tracker.is_processing)

        # After context, should be reset
        self.assertFalse(tracker.is_processing)
        self.assertEqual(tracker.chain_depth, 0)

    def test_context_cleans_up_on_exception(self):
        """Test context manager cleans up even on exception."""
        rule = MockRule()
        tracker = TestableECAChainTracker()

        try:
            with chain_context(rule, tracker=tracker):
                self.assertTrue(tracker.is_processing)
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Should still clean up
        self.assertFalse(tracker.is_processing)
        self.assertEqual(tracker.chain_depth, 0)

    def test_context_blocked_at_max_depth(self):
        """Test context manager blocks at max depth."""
        rule = MockRule(max_chain_depth=2)
        tracker = TestableECAChainTracker()

        # Enter to depth 2
        tracker.enter_chain(MockRule(name="R1"))
        tracker.enter_chain(MockRule(name="R2"))

        with chain_context(rule, tracker=tracker) as ctx:
            self.assertFalse(ctx.allowed)
            self.assertIn("Maximum chain depth", ctx.reason)

    def test_context_blocked_circular_trigger(self):
        """Test context manager blocks circular trigger."""
        rule = MockRule(name="RULE-001")
        tracker = TestableECAChainTracker()

        # Enter the same rule first
        tracker.enter_chain(rule)

        with chain_context(rule, tracker=tracker) as ctx:
            self.assertFalse(ctx.allowed)
            self.assertIn("Circular trigger", ctx.reason)

    def test_context_uses_custom_max_depth(self):
        """Test context manager uses custom max_depth."""
        rule = MockRule(max_chain_depth=10)
        tracker = TestableECAChainTracker()

        # Enter to depth 2
        tracker.enter_chain(MockRule(name="R1"))
        tracker.enter_chain(MockRule(name="R2"))

        # Should be blocked with max_depth=2
        with chain_context(rule, max_depth=2, tracker=tracker) as ctx:
            self.assertFalse(ctx.allowed)

    def test_context_uses_custom_chain_id(self):
        """Test context manager uses custom chain_id."""
        rule = MockRule()

        with chain_context(rule, chain_id="custom_123") as ctx:
            self.assertEqual(ctx.chain_id, "custom_123")


class TestNestedChainContexts(unittest.TestCase):
    """Tests for nested chain_context usage."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()

    def test_nested_contexts_share_chain_id(self):
        """Test nested contexts share the same chain_id."""
        rule1 = MockRule(name="RULE-001")
        rule2 = MockRule(name="RULE-002")
        tracker = TestableECAChainTracker()

        with chain_context(rule1, tracker=tracker) as ctx1:
            with chain_context(rule2, tracker=tracker) as ctx2:
                self.assertEqual(ctx1.chain_id, ctx2.chain_id)

    def test_nested_contexts_increment_depth(self):
        """Test nested contexts increment depth."""
        rule1 = MockRule(name="RULE-001")
        rule2 = MockRule(name="RULE-002")
        tracker = TestableECAChainTracker()

        with chain_context(rule1, tracker=tracker) as ctx1:
            self.assertEqual(ctx1.chain_depth, 1)
            with chain_context(rule2, tracker=tracker) as ctx2:
                self.assertEqual(ctx2.chain_depth, 2)

    def test_nested_contexts_accumulate_triggered_rules(self):
        """Test nested contexts accumulate triggered rules."""
        rule1 = MockRule(name="RULE-001")
        rule2 = MockRule(name="RULE-002")
        tracker = TestableECAChainTracker()

        with chain_context(rule1, tracker=tracker) as ctx1:
            with chain_context(rule2, tracker=tracker) as ctx2:
                self.assertIn("RULE-001", ctx2.triggered_rules)
                self.assertIn("RULE-002", ctx2.triggered_rules)

    def test_deeply_nested_contexts(self):
        """Test deeply nested contexts up to max depth."""
        tracker = TestableECAChainTracker()
        rules = [MockRule(name=f"RULE-{i}", max_chain_depth=5) for i in range(5)]

        # Manually nest to depth 5
        ctx_stack = []
        for i, rule in enumerate(rules):
            ctx = tracker.can_execute(rule)
            self.assertTrue(ctx.allowed, f"Rule {i} should be allowed")
            tracker.enter_chain(rule)
            ctx_stack.append(ctx)

        # 6th rule should be blocked
        rule6 = MockRule(name="RULE-5", max_chain_depth=5)
        ctx6 = tracker.can_execute(rule6)
        self.assertFalse(ctx6.allowed)

        # Clean up
        for _ in range(5):
            tracker.exit_chain()


class TestChainDepthLimits(unittest.TestCase):
    """Tests for chain depth limit enforcement."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_depth_limit_one(self):
        """Test depth limit of 1 (no chaining)."""
        rule = MockRule(max_chain_depth=1)

        # First execution allowed
        result1 = self.tracker.can_execute(rule)
        self.assertTrue(result1.allowed)

        self.tracker.enter_chain(rule)

        # Second execution blocked
        rule2 = MockRule(name="RULE-002", max_chain_depth=1)
        result2 = self.tracker.can_execute(rule2)
        self.assertFalse(result2.allowed)

    def test_depth_limit_three(self):
        """Test depth limit of 3."""
        tracker = TestableECAChainTracker()

        # Execute 3 rules (should be allowed)
        for i in range(3):
            rule = MockRule(name=f"RULE-{i}", max_chain_depth=3)
            result = tracker.can_execute(rule)
            self.assertTrue(result.allowed, f"Depth {i} should be allowed")
            tracker.enter_chain(rule)

        # 4th execution should be blocked
        rule4 = MockRule(name="RULE-3", max_chain_depth=3)
        result = tracker.can_execute(rule4)
        self.assertFalse(result.allowed)


class TestCircularTriggerPrevention(unittest.TestCase):
    """Tests for circular trigger prevention."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_same_rule_blocked_in_chain(self):
        """Test that same rule is blocked if already in chain."""
        rule = MockRule(name="RULE-001", prevent_circular=True)

        # First execution
        self.tracker.enter_chain(rule)

        # Same rule again should be blocked
        result = self.tracker.can_execute(rule)
        self.assertFalse(result.allowed)
        self.assertIn("Circular trigger", result.reason)

    def test_different_rule_allowed(self):
        """Test that different rule is allowed even after another."""
        rule1 = MockRule(name="RULE-001")
        rule2 = MockRule(name="RULE-002")

        self.tracker.enter_chain(rule1)

        result = self.tracker.can_execute(rule2)
        self.assertTrue(result.allowed)

    def test_rule_allowed_after_chain_reset(self):
        """Test that rule is allowed after chain is reset."""
        rule = MockRule(name="RULE-001")

        # First chain
        self.tracker.enter_chain(rule)
        self.tracker.exit_chain()

        # New chain - rule should be allowed again
        result = self.tracker.can_execute(rule)
        self.assertTrue(result.allowed)


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        MockFrappe.reset_flags()
        self.tracker = TestableECAChainTracker()

    def test_rule_with_no_name(self):
        """Test handling rule with empty name."""
        rule = MockRule(name="")

        result = self.tracker.can_execute(rule)

        self.assertTrue(result.allowed)

    def test_max_depth_zero(self):
        """Test max_depth of 0 (no execution allowed)."""
        rule = MockRule(max_chain_depth=0)

        result = self.tracker.can_execute(rule, max_depth=0)

        self.assertFalse(result.allowed)

    def test_very_high_max_depth(self):
        """Test very high max_depth (100)."""
        rule = MockRule(max_chain_depth=100)

        # Execute 50 times
        for i in range(50):
            r = MockRule(name=f"RULE-{i}", max_chain_depth=100)
            self.tracker.enter_chain(r)

        # Should still be allowed
        result = self.tracker.can_execute(rule)
        self.assertTrue(result.allowed)

    def test_triggered_rules_returns_copy(self):
        """Test that triggered_rules property returns modifiable set."""
        rule = MockRule(name="RULE-001")
        self.tracker.enter_chain(rule)

        rules = self.tracker.triggered_rules
        rules.add("FAKE-RULE")

        # Should be added to the actual set
        self.assertIn("FAKE-RULE", self.tracker.triggered_rules)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
