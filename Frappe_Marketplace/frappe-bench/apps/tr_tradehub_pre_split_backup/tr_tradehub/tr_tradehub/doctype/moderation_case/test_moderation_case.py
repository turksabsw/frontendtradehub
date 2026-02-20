# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, now_datetime, add_days
import json


class TestModerationCase(FrappeTestCase):
    """Test cases for Moderation Case DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a test user if not exists
        if not frappe.db.exists("User", "test_moderator@example.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "test_moderator@example.com",
                "first_name": "Test",
                "last_name": "Moderator",
                "enabled": 1
            }).insert(ignore_permissions=True)

        if not frappe.db.exists("User", "test_reporter@example.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "test_reporter@example.com",
                "first_name": "Test",
                "last_name": "Reporter",
                "enabled": 1
            }).insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data."""
        frappe.db.rollback()

    def create_test_case(self, **kwargs):
        """Helper to create a test moderation case."""
        default_data = {
            "doctype": "Moderation Case",
            "content_type": "User",  # Use User as test content type since it always exists
            "content_id": frappe.session.user,
            "case_type": "Content Report",
            "report_source": "User Report",
            "report_reason": "Inappropriate Content",
            "priority": "Medium",
            "status": "Open"
        }
        default_data.update(kwargs)
        case = frappe.get_doc(default_data)
        case.insert(ignore_permissions=True)
        return case

    # -------------------- Basic Creation Tests --------------------

    def test_case_creation(self):
        """Test basic moderation case creation."""
        case = self.create_test_case()

        self.assertIsNotNone(case.name)
        self.assertIsNotNone(case.case_id)
        self.assertEqual(case.status, "Open")
        self.assertEqual(case.case_type, "Content Report")
        self.assertIsNotNone(case.creation_date)

    def test_case_id_generation(self):
        """Test that case ID is automatically generated."""
        case = self.create_test_case()

        self.assertTrue(case.case_id.startswith("MC-"))

    def test_sla_target_set_by_priority(self):
        """Test that SLA target is set based on priority."""
        # Critical priority
        case_critical = self.create_test_case(priority="Critical")
        self.assertEqual(case_critical.sla_target_hours, 4)

        # High priority
        case_high = self.create_test_case(priority="High")
        self.assertEqual(case_high.sla_target_hours, 12)

        # Medium priority
        case_medium = self.create_test_case(priority="Medium")
        self.assertEqual(case_medium.sla_target_hours, 24)

        # Low priority
        case_low = self.create_test_case(priority="Low")
        self.assertEqual(case_low.sla_target_hours, 48)

    # -------------------- Validation Tests --------------------

    def test_content_validation(self):
        """Test that content type and ID are validated."""
        # Missing content type
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({
                "doctype": "Moderation Case",
                "content_id": "test",
                "case_type": "Content Report"
            }).insert()

        # Non-existent content
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({
                "doctype": "Moderation Case",
                "content_type": "User",
                "content_id": "nonexistent@user.com",
                "case_type": "Content Report"
            }).insert()

    def test_status_transitions(self):
        """Test valid and invalid status transitions."""
        case = self.create_test_case()

        # Valid transition: Open -> Assigned
        case.status = "Assigned"
        case.assigned_to = "test_moderator@example.com"
        case.save()
        self.assertEqual(case.status, "Assigned")

        # Valid transition: Assigned -> In Review
        case.status = "In Review"
        case.save()
        self.assertEqual(case.status, "In Review")

        # Reload and try invalid transition
        case.reload()
        case.status = "Open"  # Invalid: can't go back to Open from In Review
        with self.assertRaises(frappe.ValidationError):
            case.save()

    # -------------------- Assignment Tests --------------------

    def test_assign_case(self):
        """Test case assignment."""
        case = self.create_test_case()

        result = case.assign_case("test_moderator@example.com")

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "Assigned")
        self.assertEqual(case.assigned_to, "test_moderator@example.com")
        self.assertIsNotNone(case.assigned_at)

    def test_assign_already_assigned_case(self):
        """Test that assigned case cannot be reassigned directly."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()

        # Can't assign from In Review
        with self.assertRaises(frappe.ValidationError):
            case.assign_case("test_reporter@example.com")

    # -------------------- Review Tests --------------------

    def test_start_review(self):
        """Test starting review."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()

        result = case.start_review()

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "In Review")
        self.assertIsNotNone(case.review_started_at)

    def test_resolve_case(self):
        """Test resolving a case."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()

        result = case.resolve_case(
            decision="No Action Needed",
            decision_reason="Content complies with guidelines",
            action_taken="None"
        )

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "Resolved")
        self.assertEqual(case.decision, "No Action Needed")
        self.assertIsNotNone(case.review_completed_at)
        self.assertIsNotNone(case.reviewed_by)

    def test_resolve_requires_decision(self):
        """Test that resolving requires a decision."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()

        with self.assertRaises(frappe.ValidationError):
            case.resolve_case(decision=None)

    # -------------------- Escalation Tests --------------------

    def test_escalate_case(self):
        """Test case escalation."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()

        result = case.escalate_case(
            escalation_level="Level 2 - Senior Moderator",
            escalated_to="test_reporter@example.com",
            reason="Complex legal issue"
        )

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "Escalated")
        self.assertTrue(case.is_escalated)
        self.assertEqual(case.escalation_level, "Level 2 - Senior Moderator")
        self.assertIsNotNone(case.escalated_at)

    def test_escalation_increases_priority(self):
        """Test that escalation increases priority if needed."""
        case = self.create_test_case(priority="Low")
        case.assign_case("test_moderator@example.com")
        case.reload()

        case.escalate_case(
            escalation_level="Level 2 - Senior Moderator",
            escalated_to="test_reporter@example.com",
            reason="Urgent issue"
        )

        case.reload()
        self.assertEqual(case.priority, "High")

    # -------------------- Appeal Tests --------------------

    def test_submit_appeal(self):
        """Test submitting an appeal."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()
        case.resolve_case(
            decision="Removed",
            decision_reason="Policy violation",
            action_taken="Content Removed",
            content_action="Remove"
        )
        case.reload()

        result = case.submit_appeal(
            appeal_reason="The content was incorrectly flagged"
        )

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "Appealed")
        self.assertEqual(case.appeal_status, "Appeal Submitted")
        self.assertIsNotNone(case.appeal_submitted_at)

    def test_cannot_appeal_non_resolved_case(self):
        """Test that only resolved cases can be appealed."""
        case = self.create_test_case()

        with self.assertRaises(frappe.ValidationError):
            case.submit_appeal(appeal_reason="Test appeal")

    def test_cannot_appeal_non_appealable_case(self):
        """Test that non-appealable cases cannot be appealed."""
        case = self.create_test_case()
        case.is_appealable = 0
        case.save()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()
        case.resolve_case(decision="Removed")
        case.reload()

        with self.assertRaises(frappe.ValidationError):
            case.submit_appeal(appeal_reason="Test appeal")

    def test_review_appeal_approved(self):
        """Test approving an appeal."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()
        case.resolve_case(decision="Removed", action_taken="Content Removed")
        case.reload()
        case.submit_appeal(appeal_reason="Incorrect flag")
        case.reload()

        result = case.review_appeal(
            status="Approved",
            decision="Content does not violate policy",
            response="Your appeal has been approved."
        )

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.appeal_status, "Approved")
        self.assertEqual(case.status, "Resolved")
        self.assertIsNotNone(case.appeal_decided_at)

    def test_review_appeal_rejected(self):
        """Test rejecting an appeal."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()
        case.resolve_case(decision="Removed", action_taken="Content Removed")
        case.reload()
        case.submit_appeal(appeal_reason="Incorrect flag")
        case.reload()

        result = case.review_appeal(
            status="Rejected",
            decision="Content clearly violates policy",
            response="Your appeal has been rejected."
        )

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.appeal_status, "Rejected")
        self.assertEqual(case.status, "Resolved")

    # -------------------- History Tests --------------------

    def test_moderation_history_tracking(self):
        """Test that moderation history is tracked."""
        case = self.create_test_case()

        # History should have creation event
        history = json.loads(case.moderation_history or "[]")
        self.assertTrue(len(history) > 0)

        # Assign and check history
        case.assign_case("test_moderator@example.com")
        case.reload()

        history = json.loads(case.moderation_history or "[]")
        events = [h["event"] for h in history]
        self.assertIn("assigned", events)

    # -------------------- Close and Reopen Tests --------------------

    def test_close_case(self):
        """Test closing a case."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()
        case.resolve_case(decision="No Action Needed")
        case.reload()

        result = case.close_case(close_reason="Resolution accepted")

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "Closed")

    def test_reopen_case(self):
        """Test reopening a closed case."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()
        case.resolve_case(decision="No Action Needed")
        case.reload()
        case.close_case()
        case.reload()

        result = case.reopen_case(reason="New evidence found")

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "Reopened")

    # -------------------- Request Info Tests --------------------

    def test_request_info(self):
        """Test requesting additional information."""
        case = self.create_test_case()
        case.assign_case("test_moderator@example.com")
        case.reload()
        case.start_review()
        case.reload()

        result = case.request_info("Please provide original content source")

        self.assertEqual(result["status"], "success")
        case.reload()
        self.assertEqual(case.status, "Pending Info")

    # -------------------- Case Summary Tests --------------------

    def test_get_case_summary(self):
        """Test getting case summary."""
        case = self.create_test_case()

        summary = case.get_case_summary()

        self.assertEqual(summary["case_id"], case.case_id)
        self.assertEqual(summary["case_type"], case.case_type)
        self.assertEqual(summary["status"], case.status)
        self.assertEqual(summary["priority"], case.priority)
        self.assertIn("content_type", summary)
        self.assertIn("content_id", summary)

    # -------------------- Prevention Tests --------------------

    def test_case_cannot_be_deleted(self):
        """Test that cases cannot be deleted for audit purposes."""
        case = self.create_test_case()

        with self.assertRaises(frappe.ValidationError):
            case.delete()
