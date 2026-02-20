# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
ECA Chain Tracker

This module provides circular trigger prevention for ECA rules using
frappe.flags for request-scoped state management.

Features:
- Chain ID tracking for correlating related rule executions
- Chain depth enforcement to prevent infinite loops
- Circular reference detection (same rule triggered twice in a chain)
- Context manager for automatic cleanup

Usage:
    from tr_tradehub.eca.chain_tracker import ECAChainTracker, chain_context

    # Using context manager (recommended)
    tracker = get_chain_tracker()
    with chain_context(rule, max_depth=5) as ctx:
        if ctx.allowed:
            # Execute the rule
            pass

    # Using class directly
    tracker = ECAChainTracker()
    if tracker.can_execute(rule, max_depth=5):
        try:
            tracker.enter_chain(rule)
            # Execute the rule
        finally:
            tracker.exit_chain()
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, Set, List

import frappe
from frappe import _


# =============================================================================
# CHAIN TRACKING RESULT
# =============================================================================

@dataclass
class ChainTrackingResult:
    """
    Result of a chain tracking check.

    Attributes:
        allowed: Whether execution is allowed
        chain_id: The current chain ID
        chain_depth: Current depth in the execution chain
        max_depth: Maximum allowed depth
        reason: Human-readable reason if not allowed
        triggered_rules: List of rules already triggered in this chain
    """
    allowed: bool
    chain_id: str
    chain_depth: int
    max_depth: int
    reason: Optional[str] = None
    triggered_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "allowed": self.allowed,
            "chain_id": self.chain_id,
            "chain_depth": self.chain_depth,
            "max_depth": self.max_depth,
            "reason": self.reason,
            "triggered_rules": self.triggered_rules,
        }


# =============================================================================
# CHAIN TRACKER CLASS
# =============================================================================

class ECAChainTracker:
    """
    Tracks ECA rule execution chains using frappe.flags.

    Uses request-scoped flags to:
    - Detect when ECA is already processing (prevent re-entry)
    - Track chain depth to enforce max_chain_depth
    - Detect circular references (same rule triggered twice)
    - Correlate related executions with chain_id

    Flag names:
    - eca_processing: Boolean indicating ECA is currently processing
    - eca_chain_id: Unique ID for the current execution chain
    - eca_chain_depth: Current depth in the chain (starts at 0)
    - eca_triggered_rules: Set of rule names already triggered in this chain
    """

    # Flag names for consistency
    FLAG_PROCESSING = "eca_processing"
    FLAG_CHAIN_ID = "eca_chain_id"
    FLAG_CHAIN_DEPTH = "eca_chain_depth"
    FLAG_TRIGGERED_RULES = "eca_triggered_rules"

    def __init__(self):
        """Initialize the chain tracker."""
        pass

    # -------------------------------------------------------------------------
    # FLAG ACCESSORS
    # -------------------------------------------------------------------------

    @property
    def is_processing(self) -> bool:
        """Check if ECA is currently processing."""
        return getattr(frappe.flags, self.FLAG_PROCESSING, False)

    @property
    def chain_id(self) -> Optional[str]:
        """Get the current chain ID."""
        return getattr(frappe.flags, self.FLAG_CHAIN_ID, None)

    @property
    def chain_depth(self) -> int:
        """Get the current chain depth."""
        return getattr(frappe.flags, self.FLAG_CHAIN_DEPTH, 0)

    @property
    def triggered_rules(self) -> Set[str]:
        """Get the set of rules already triggered in this chain."""
        rules = getattr(frappe.flags, self.FLAG_TRIGGERED_RULES, None)
        if rules is None:
            rules = set()
            setattr(frappe.flags, self.FLAG_TRIGGERED_RULES, rules)
        return rules

    # -------------------------------------------------------------------------
    # CHAIN CONTROL
    # -------------------------------------------------------------------------

    def can_execute(
        self,
        rule: "frappe.model.document.Document",
        max_depth: Optional[int] = None
    ) -> ChainTrackingResult:
        """
        Check if a rule execution is allowed.

        This checks:
        1. If max_chain_depth would be exceeded
        2. If this rule has already been triggered in the current chain (circular)

        Args:
            rule: The ECA Rule document
            max_depth: Maximum chain depth (uses rule.max_chain_depth if not provided)

        Returns:
            ChainTrackingResult indicating if execution is allowed
        """
        # Get max depth from rule or parameter
        if max_depth is None:
            max_depth = rule.get("max_chain_depth") or 5

        # Check if rule wants circular prevention
        prevent_circular = rule.get("prevent_circular", True)

        # Current chain info
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
                reason=_(
                    "Maximum chain depth exceeded: {current}/{max}"
                ).format(current=current_depth, max=max_depth),
                triggered_rules=current_rules
            )

        # Check 2: Circular reference (same rule already in chain)
        if prevent_circular and rule.name in self.triggered_rules:
            return ChainTrackingResult(
                allowed=False,
                chain_id=current_chain_id,
                chain_depth=current_depth,
                max_depth=max_depth,
                reason=_(
                    "Circular trigger detected: Rule '{rule}' already executed in this chain"
                ).format(rule=rule.name),
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

    def enter_chain(
        self,
        rule: "frappe.model.document.Document",
        chain_id: Optional[str] = None
    ) -> str:
        """
        Enter a new chain level for rule execution.

        This should be called before executing a rule's actions.
        Must be paired with exit_chain() in a finally block.

        Args:
            rule: The ECA Rule being executed
            chain_id: Optional chain ID (generates new one if not in a chain)

        Returns:
            The chain ID being used
        """
        # Set processing flag
        setattr(frappe.flags, self.FLAG_PROCESSING, True)

        # Generate or reuse chain ID
        if chain_id:
            current_chain_id = chain_id
        elif self.chain_id:
            current_chain_id = self.chain_id
        else:
            current_chain_id = frappe.generate_hash(length=12)

        setattr(frappe.flags, self.FLAG_CHAIN_ID, current_chain_id)

        # Increment depth
        new_depth = self.chain_depth + 1
        setattr(frappe.flags, self.FLAG_CHAIN_DEPTH, new_depth)

        # Add rule to triggered set
        self.triggered_rules.add(rule.name)

        return current_chain_id

    def exit_chain(self) -> None:
        """
        Exit the current chain level.

        This should be called after rule execution completes.
        Should be called in a finally block to ensure cleanup.
        """
        # Decrement depth
        new_depth = max(0, self.chain_depth - 1)
        setattr(frappe.flags, self.FLAG_CHAIN_DEPTH, new_depth)

        # If back to root level, reset all flags
        if new_depth == 0:
            self._reset_flags()

    def _reset_flags(self) -> None:
        """Reset all ECA chain tracking flags."""
        setattr(frappe.flags, self.FLAG_PROCESSING, False)
        setattr(frappe.flags, self.FLAG_CHAIN_ID, None)
        setattr(frappe.flags, self.FLAG_CHAIN_DEPTH, 0)
        setattr(frappe.flags, self.FLAG_TRIGGERED_RULES, set())

    def force_reset(self) -> None:
        """
        Force reset all chain tracking flags.

        Use this for error recovery or testing.
        """
        self._reset_flags()

    def get_chain_info(self) -> dict:
        """
        Get current chain tracking information.

        Returns:
            Dictionary with current chain state
        """
        return {
            "is_processing": self.is_processing,
            "chain_id": self.chain_id,
            "chain_depth": self.chain_depth,
            "triggered_rules": list(self.triggered_rules),
        }


# =============================================================================
# CHAIN CONTEXT DATACLASS
# =============================================================================

@dataclass
class ChainContext:
    """
    Context information for a chain execution scope.

    Returned by chain_context() context manager.
    """
    allowed: bool
    chain_id: str
    chain_depth: int
    max_depth: int
    reason: Optional[str] = None
    triggered_rules: List[str] = field(default_factory=list)


# =============================================================================
# CONTEXT MANAGER
# =============================================================================

@contextmanager
def chain_context(
    rule: "frappe.model.document.Document",
    max_depth: Optional[int] = None,
    chain_id: Optional[str] = None,
    tracker: Optional[ECAChainTracker] = None
):
    """
    Context manager for ECA chain tracking.

    Automatically handles entering and exiting the chain, with proper
    cleanup in case of exceptions.

    Usage:
        with chain_context(rule) as ctx:
            if ctx.allowed:
                # Execute rule actions
                pass

    Args:
        rule: The ECA Rule document
        max_depth: Maximum chain depth (uses rule setting if not provided)
        chain_id: Optional chain ID to use
        tracker: Optional tracker instance (uses global if not provided)

    Yields:
        ChainContext with chain information
    """
    if tracker is None:
        tracker = get_chain_tracker()

    # Check if execution is allowed
    result = tracker.can_execute(rule, max_depth)

    if not result.allowed:
        # Not allowed - yield context without entering chain
        yield ChainContext(
            allowed=False,
            chain_id=result.chain_id,
            chain_depth=result.chain_depth,
            max_depth=result.max_depth,
            reason=result.reason,
            triggered_rules=result.triggered_rules
        )
        return

    # Enter the chain
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
        # Always exit the chain
        tracker.exit_chain()


# =============================================================================
# GLOBAL TRACKER INSTANCE
# =============================================================================

# Singleton instance for convenience
_chain_tracker: Optional[ECAChainTracker] = None


def get_chain_tracker() -> ECAChainTracker:
    """
    Get the global chain tracker instance.

    Returns:
        The singleton ECAChainTracker instance
    """
    global _chain_tracker
    if _chain_tracker is None:
        _chain_tracker = ECAChainTracker()
    return _chain_tracker


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def can_execute_rule(
    rule: "frappe.model.document.Document",
    max_depth: Optional[int] = None
) -> ChainTrackingResult:
    """
    Check if a rule can be executed under chain tracking constraints.

    Convenience function that uses the global chain tracker.

    Args:
        rule: The ECA Rule document
        max_depth: Maximum chain depth

    Returns:
        ChainTrackingResult indicating if execution is allowed
    """
    return get_chain_tracker().can_execute(rule, max_depth)


def is_circular_trigger(rule: "frappe.model.document.Document") -> bool:
    """
    Quick check if executing this rule would create a circular trigger.

    Args:
        rule: The ECA Rule document

    Returns:
        True if circular (blocked), False if allowed
    """
    tracker = get_chain_tracker()
    return rule.name in tracker.triggered_rules


def is_max_depth_exceeded(max_depth: int = 5) -> bool:
    """
    Quick check if maximum chain depth has been exceeded.

    Args:
        max_depth: Maximum allowed depth

    Returns:
        True if exceeded (blocked), False if allowed
    """
    tracker = get_chain_tracker()
    return tracker.chain_depth >= max_depth


def get_current_chain_id() -> Optional[str]:
    """
    Get the current chain ID.

    Returns:
        The chain ID or None if not in a chain
    """
    return get_chain_tracker().chain_id


def get_current_chain_depth() -> int:
    """
    Get the current chain depth.

    Returns:
        The current depth (0 if not in a chain)
    """
    return get_chain_tracker().chain_depth


def get_triggered_rules() -> List[str]:
    """
    Get the list of rules already triggered in the current chain.

    Returns:
        List of rule names
    """
    return list(get_chain_tracker().triggered_rules)


def reset_chain_tracking() -> None:
    """
    Force reset all chain tracking.

    Use for error recovery or testing.
    """
    get_chain_tracker().force_reset()


# =============================================================================
# DECORATOR
# =============================================================================

def with_chain_tracking(max_depth: Optional[int] = None):
    """
    Decorator for functions that should respect chain tracking.

    Usage:
        @with_chain_tracking(max_depth=5)
        def execute_rule(rule, doc):
            # This will only run if chain tracking allows
            pass

    Args:
        max_depth: Maximum chain depth

    Returns:
        Decorated function
    """
    def decorator(func):
        def wrapper(rule, *args, **kwargs):
            with chain_context(rule, max_depth=max_depth) as ctx:
                if not ctx.allowed:
                    # Log the skip and return None
                    frappe.log_error(
                        f"Rule {rule.name} skipped: {ctx.reason}",
                        "ECA Chain Tracking"
                    )
                    return None
                return func(rule, *args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# API ENDPOINTS
# =============================================================================

@frappe.whitelist()
def get_chain_status() -> dict:
    """
    Get the current chain tracking status.

    API endpoint for debugging/monitoring.

    Returns:
        Dictionary with chain tracking state
    """
    tracker = get_chain_tracker()
    return tracker.get_chain_info()


@frappe.whitelist()
def force_reset_chain() -> dict:
    """
    Force reset all chain tracking.

    API endpoint for emergency recovery (admin only).

    Returns:
        Dictionary with success status
    """
    # Check permissions
    if not frappe.has_permission("ECA Rule", "write"):
        frappe.throw(_("Insufficient permissions to reset chain tracking"))

    reset_chain_tracking()

    return {
        "success": True,
        "message": _("Chain tracking reset successfully")
    }
