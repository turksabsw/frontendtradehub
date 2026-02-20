# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
ECA (Event-Condition-Action) Module for TradeHub

This module provides automation capabilities for the TradeHub B2B marketplace,
enabling business rule definition, condition evaluation, and automatic action
triggering across DocTypes.

Components:
- engine: Condition evaluation engine with 22 operators
- actions: Action executors for 16 different action types
- rate_limiter: Redis-based rate limiting
- chain_tracker: Circular trigger prevention
- handlers: Document event handlers
- tasks: Scheduled tasks for rule evaluation and cleanup
"""

from tr_tradehub.eca.engine import ECAEngine
from tr_tradehub.eca.actions import (
    ActionExecutor,
    ActionContext,
    ActionResult,
    ActionRegistry,
    ActionRunner,
    action_registry,
    register_action,
    execute_actions,
    get_registered_action_types,
)
from tr_tradehub.eca.rate_limiter import (
    ECARateLimiter,
    RateLimitResult,
    get_rate_limiter,
    check_rate_limit,
    reset_rule_limit,
    is_rate_limited,
)
from tr_tradehub.eca.chain_tracker import (
    ECAChainTracker,
    ChainTrackingResult,
    ChainContext,
    get_chain_tracker,
    chain_context,
    can_execute_rule,
    is_circular_trigger,
    is_max_depth_exceeded,
    get_current_chain_id,
    get_current_chain_depth,
    get_triggered_rules,
    reset_chain_tracking,
    with_chain_tracking,
)
from tr_tradehub.eca.handlers import (
    handle_doc_event,
    before_insert,
    after_insert,
    validate,
    before_validate,
    before_save,
    after_save,
    on_update,
    before_submit,
    on_submit,
    before_cancel,
    on_cancel,
    on_trash,
    after_delete,
    on_change,
    disable_eca_processing,
    enable_eca_processing,
    is_eca_processing_enabled,
    invalidate_rule_cache,
    manually_trigger_rules,
    get_rules_for_doctype,
    test_rule_conditions,
)

__all__ = [
    # Engine
    "ECAEngine",
    # Actions
    "ActionExecutor",
    "ActionContext",
    "ActionResult",
    "ActionRegistry",
    "ActionRunner",
    "action_registry",
    "register_action",
    "execute_actions",
    "get_registered_action_types",
    # Rate Limiter
    "ECARateLimiter",
    "RateLimitResult",
    "get_rate_limiter",
    "check_rate_limit",
    "reset_rule_limit",
    "is_rate_limited",
    # Chain Tracker
    "ECAChainTracker",
    "ChainTrackingResult",
    "ChainContext",
    "get_chain_tracker",
    "chain_context",
    "can_execute_rule",
    "is_circular_trigger",
    "is_max_depth_exceeded",
    "get_current_chain_id",
    "get_current_chain_depth",
    "get_triggered_rules",
    "reset_chain_tracking",
    "with_chain_tracking",
    # Handlers
    "handle_doc_event",
    "before_insert",
    "after_insert",
    "validate",
    "before_validate",
    "before_save",
    "after_save",
    "on_update",
    "before_submit",
    "on_submit",
    "before_cancel",
    "on_cancel",
    "on_trash",
    "after_delete",
    "on_change",
    "disable_eca_processing",
    "enable_eca_processing",
    "is_eca_processing_enabled",
    "invalidate_rule_cache",
    "manually_trigger_rules",
    "get_rules_for_doctype",
    "test_rule_conditions",
]
