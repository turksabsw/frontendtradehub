# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import nowdate, add_days, now_datetime


class TestAccountAction(unittest.TestCase):
    """Test cases for Account Action DocType."""

    def setUp(self):
        """Set up test data."""
        # Clean up any existing test data
        frappe.db.delete("Account Action", {"reason": ["like", "Test%"]})

    def tearDown(self):
        """Clean up test data."""
        frappe.db.delete("Account Action", {"reason": ["like", "Test%"]})

    def create_test_action(self, **kwargs):
        """Helper to create test account action."""
        defaults = {
            "doctype": "Account Action",
            "action_type": "Warning",
            "severity": "Low",
            "status": "Active",
            "target_type": "User",
            "user": "Administrator",
            "reason": "Test warning",
            "start_date": now_datetime()
        }
        defaults.update(kwargs)
        action = frappe.get_doc(defaults)
        action.insert(ignore_permissions=True)
        return action

    def test_create_warning(self):
        """Test creating a warning action."""
        action = self.create_test_action(
            action_type="Warning",
            reason="Test warning for policy violation"
        )

        self.assertEqual(action.action_type, "Warning")
        self.assertEqual(action.severity, "Low")
        self.assertEqual(action.status, "Active")
        self.assertIsNotNone(action.name)

    def test_create_restriction(self):
        """Test creating a restriction action."""
        action = self.create_test_action(
            action_type="Restriction",
            severity="Medium",
            reason="Test restriction",
            end_date=add_days(nowdate(), 7),
            restrict_selling=1,
            restrict_listing_create=1
        )

        self.assertEqual(action.action_type, "Restriction")
        self.assertTrue(action.restrict_selling)
        self.assertTrue(action.restrict_listing_create)

    def test_create_temporary_ban(self):
        """Test creating a temporary ban."""
        action = self.create_test_action(
            action_type="Temporary Ban",
            severity="High",
            reason="Test temporary ban",
            end_date=add_days(nowdate(), 30)
        )

        self.assertEqual(action.action_type, "Temporary Ban")
        self.assertTrue(action.restrict_all_activity)

    def test_create_permanent_ban(self):
        """Test creating a permanent ban."""
        action = self.create_test_action(
            action_type="Permanent Ban",
            severity="Critical",
            reason="Test permanent ban",
            is_permanent=1
        )

        self.assertEqual(action.action_type, "Permanent Ban")
        self.assertTrue(action.is_permanent)
        self.assertIsNone(action.end_date)

    def test_validation_dates(self):
        """Test date validation."""
        # End date before start date should fail
        with self.assertRaises(frappe.ValidationError):
            self.create_test_action(
                action_type="Restriction",
                reason="Test invalid dates",
                start_date=add_days(nowdate(), 7),
                end_date=nowdate()
            )

    def test_escalation_level_calculation(self):
        """Test escalation level is calculated correctly."""
        # Create first action
        action1 = self.create_test_action(
            action_type="Warning",
            reason="Test first warning"
        )
        self.assertEqual(action1.escalation_level, 1)

        # Create escalated action
        action2 = self.create_test_action(
            action_type="Restriction",
            reason="Test escalated action",
            previous_action=action1.name,
            end_date=add_days(nowdate(), 7)
        )
        self.assertEqual(action2.escalation_level, 2)

    def test_lift_action(self):
        """Test lifting an action."""
        action = self.create_test_action(
            action_type="Restriction",
            reason="Test restriction to lift",
            end_date=add_days(nowdate(), 7)
        )

        result = action.lift_action(reason="Test lift reason")

        self.assertEqual(result["status"], "success")
        action.reload()
        self.assertEqual(action.status, "Lifted")
        self.assertIsNotNone(action.lifted_at)

    def test_appeal_workflow(self):
        """Test appeal submission and review."""
        action = self.create_test_action(
            action_type="Warning",
            reason="Test warning for appeal",
            is_appealable=1
        )

        # Submit appeal
        result = action.submit_appeal(reason="Test appeal reason")
        self.assertEqual(result["status"], "success")

        action.reload()
        self.assertEqual(action.appeal_status, "Appeal Submitted")
        self.assertEqual(action.status, "Appealed")

        # Review and approve appeal
        result = action.review_appeal(
            decision="Appeal approved",
            status="Approved",
            response="Your appeal has been accepted"
        )
        self.assertEqual(result["status"], "success")

        action.reload()
        self.assertEqual(action.appeal_status, "Approved")
        self.assertEqual(action.status, "Overturned")

    def test_appeal_rejection(self):
        """Test appeal rejection."""
        action = self.create_test_action(
            action_type="Warning",
            reason="Test warning for rejected appeal",
            is_appealable=1
        )

        action.submit_appeal(reason="Invalid appeal reason")
        action.reload()

        result = action.review_appeal(
            decision="Appeal rejected - insufficient evidence",
            status="Rejected",
            response="Your appeal has been rejected"
        )

        action.reload()
        self.assertEqual(action.appeal_status, "Rejected")
        self.assertEqual(action.status, "Active")

    def test_non_appealable_action(self):
        """Test that non-appealable actions cannot be appealed."""
        action = self.create_test_action(
            action_type="Account Termination",
            reason="Test termination",
            is_permanent=1
        )

        # Account termination should not be appealable
        self.assertFalse(action.is_appealable)

        with self.assertRaises(frappe.ValidationError):
            action.submit_appeal(reason="Cannot appeal")

    def test_restriction_flags(self):
        """Test that restriction flags work correctly."""
        action = self.create_test_action(
            action_type="Restriction",
            reason="Test restrictions",
            end_date=add_days(nowdate(), 7),
            restrict_selling=1,
            restrict_messaging=1
        )

        self.assertTrue(action.restrict_selling)
        self.assertTrue(action.restrict_messaging)
        self.assertFalse(action.restrict_buying)

    def test_all_activity_restriction(self):
        """Test that all activity restriction sets individual flags."""
        action = self.create_test_action(
            action_type="Suspension",
            reason="Test full suspension",
            end_date=add_days(nowdate(), 14),
            restrict_all_activity=1
        )

        # All individual restrictions should be set
        self.assertTrue(action.restrict_selling)
        self.assertTrue(action.restrict_buying)
        self.assertTrue(action.restrict_messaging)
        self.assertTrue(action.restrict_reviews)
        self.assertTrue(action.restrict_listing_create)
        self.assertTrue(action.restrict_withdrawal)

    def test_get_action_summary(self):
        """Test getting action summary."""
        action = self.create_test_action(
            action_type="Restriction",
            reason="Test summary",
            end_date=add_days(nowdate(), 7),
            restrict_selling=1
        )

        summary = action.get_action_summary()

        self.assertEqual(summary["action_type"], "Restriction")
        self.assertEqual(summary["reason"], "Test summary")
        self.assertTrue(summary["is_active"])
        self.assertTrue(summary["restrictions"]["selling"])

    def test_is_active(self):
        """Test is_active method."""
        # Active action
        action = self.create_test_action(
            action_type="Warning",
            reason="Test active check"
        )
        self.assertTrue(action.is_active())

        # Lifted action
        action.lift_action(reason="Test")
        self.assertFalse(action.is_active())

    def test_deletion_prevention(self):
        """Test that actions cannot be deleted."""
        action = self.create_test_action(
            action_type="Warning",
            reason="Test deletion prevention"
        )

        with self.assertRaises(frappe.ValidationError):
            action.delete()


def get_test_records():
    """Return test records for the DocType."""
    return [
        {
            "doctype": "Account Action",
            "action_type": "Warning",
            "severity": "Low",
            "status": "Active",
            "target_type": "User",
            "user": "Administrator",
            "reason": "Test warning record",
            "start_date": now_datetime()
        }
    ]
