# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
import json
import os


class TestImportJob(FrappeTestCase):
    """Test cases for Import Job DocType."""

    def setUp(self):
        """Set up test data."""
        self.test_file_url = "/files/test_import.csv"

    def tearDown(self):
        """Clean up test data."""
        # Delete test import jobs
        frappe.db.delete("Import Job Error", {"parent": ["like", "IMP-%"]})
        frappe.db.delete("Import Job", {"job_code": ["like", "IMP-%"]})
        frappe.db.commit()

    def test_create_import_job(self):
        """Test creating a basic import job."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing",
            "job_name": "Test Import Job"
        })
        job.insert()

        self.assertIsNotNone(job.name)
        self.assertIsNotNone(job.job_code)
        self.assertEqual(job.status, "Pending")
        self.assertEqual(job.import_type, "Listing")
        self.assertTrue(job.job_code.startswith("IMP-"))

    def test_import_job_defaults(self):
        """Test that default values are set correctly."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()

        self.assertEqual(job.has_header_row, 1)
        self.assertEqual(job.delimiter, ",")
        self.assertEqual(job.encoding, "utf-8")
        self.assertEqual(job.batch_size, 100)
        self.assertEqual(job.max_retries, 3)
        self.assertEqual(job.priority, "Medium")
        self.assertEqual(job.notify_on_completion, 1)
        self.assertEqual(job.created_by, frappe.session.user)

    def test_import_type_validation(self):
        """Test that import type validation works."""
        # Valid import types should work
        valid_types = [
            "Listing", "Listing Variant", "SKU", "Category",
            "Media Asset", "Inventory Update", "Price Update"
        ]

        for import_type in valid_types:
            job = frappe.get_doc({
                "doctype": "Import Job",
                "import_file": self.test_file_url,
                "import_type": import_type
            })
            job.insert()
            self.assertEqual(job.import_type, import_type)
            job.delete()

    def test_batch_size_validation(self):
        """Test batch size bounds."""
        # Test minimum batch size
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing",
            "batch_size": 0
        })
        job.insert()
        self.assertEqual(job.batch_size, 1)

        # Test maximum batch size
        job2 = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing",
            "batch_size": 2000
        })
        job2.insert()
        self.assertEqual(job2.batch_size, 1000)

    def test_column_mapping_validation(self):
        """Test that column mapping JSON validation works."""
        # Valid JSON
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing",
            "column_mapping": json.dumps({"title": "title", "price": "selling_price"})
        })
        job.insert()
        self.assertIsNotNone(job.name)

    def test_status_transitions(self):
        """Test status transition methods."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()

        # Test start_validation
        job.start_validation()
        job.reload()
        self.assertEqual(job.status, "Validating")

        # Test queue_for_processing
        job.queue_for_processing()
        job.reload()
        self.assertEqual(job.status, "Queued")

        # Test start_processing
        job.start_processing()
        job.reload()
        self.assertEqual(job.status, "Processing")
        self.assertIsNotNone(job.started_at)

        # Test pause
        job.pause()
        job.reload()
        self.assertEqual(job.status, "Paused")

        # Test complete
        job.complete(with_errors=False)
        job.reload()
        self.assertEqual(job.status, "Completed")
        self.assertIsNotNone(job.completed_at)

    def test_complete_with_errors(self):
        """Test completing a job with errors."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()
        job.start_processing()

        job.complete(with_errors=True)
        job.reload()
        self.assertEqual(job.status, "Completed with Errors")

    def test_fail_job(self):
        """Test failing a job."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()

        job.fail("Test error message")
        job.reload()
        self.assertEqual(job.status, "Failed")
        self.assertIn("Test error message", job.summary)

    def test_cancel_job(self):
        """Test cancelling a job."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()

        job.cancel()
        job.reload()
        self.assertEqual(job.status, "Cancelled")

    def test_add_error(self):
        """Test adding errors to a job."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()

        job.add_error(
            row_number=1,
            error_type="Validation Error",
            error_message="Test error",
            field_name="title",
            field_value="",
            severity="Error",
            row_data={"title": ""}
        )

        job.reload()
        self.assertEqual(len(job.errors), 1)
        self.assertEqual(job.errors[0].row_number, 1)
        self.assertEqual(job.errors[0].error_type, "Validation Error")

    def test_progress_update(self):
        """Test updating progress counters."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()
        job.db_set("total_rows", 100)
        job.start_processing()

        job.update_progress(processed=10, successful=8, failed=2, skipped=0)
        job.reload()

        self.assertEqual(job.processed_rows, 10)
        self.assertEqual(job.successful_rows, 8)
        self.assertEqual(job.failed_rows, 2)
        self.assertEqual(job.progress_percent, 10)

    def test_can_retry(self):
        """Test retry eligibility check."""
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()

        # Pending job cannot retry
        self.assertFalse(job.can_retry())

        # Failed job can retry
        job.fail("Test error")
        job.reload()
        self.assertTrue(job.can_retry())

        # Completed with errors can retry
        job2 = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job2.insert()
        job2.complete(with_errors=True)
        job2.reload()
        self.assertTrue(job2.can_retry())

    def test_column_mapping_parsing(self):
        """Test column mapping parsing."""
        mapping = {"Product Name": "title", "Price": "selling_price"}

        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing",
            "column_mapping": json.dumps(mapping)
        })
        job.insert()

        parsed = job.get_column_mapping()
        self.assertEqual(parsed["Product Name"], "title")
        self.assertEqual(parsed["Price"], "selling_price")

    def test_field_defaults_parsing(self):
        """Test field defaults parsing."""
        defaults = {"status": "Draft", "uom": "Nos"}

        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing",
            "field_defaults": json.dumps(defaults)
        })
        job.insert()

        parsed = job.get_field_defaults()
        self.assertEqual(parsed["status"], "Draft")
        self.assertEqual(parsed["uom"], "Nos")

    def test_map_row_to_fields(self):
        """Test row mapping functionality."""
        mapping = {"Product Name": "title", "Price": "selling_price"}
        defaults = {"status": "Draft"}

        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing",
            "column_mapping": json.dumps(mapping),
            "field_defaults": json.dumps(defaults)
        })
        job.insert()

        row = {"Product Name": "Test Product", "Price": "99.99"}
        result = job.map_row_to_fields(row, mapping, defaults)

        self.assertEqual(result["title"], "Test Product")
        self.assertEqual(result["selling_price"], "99.99")
        self.assertEqual(result["status"], "Draft")


class TestImportJobAPI(FrappeTestCase):
    """Test cases for Import Job API endpoints."""

    def setUp(self):
        """Set up test data."""
        self.test_file_url = "/files/test_import.csv"

    def tearDown(self):
        """Clean up test data."""
        frappe.db.delete("Import Job Error", {"parent": ["like", "IMP-%"]})
        frappe.db.delete("Import Job", {"job_code": ["like", "IMP-%"]})
        frappe.db.commit()

    def test_create_import_job_api(self):
        """Test create_import_job API endpoint."""
        from tradehub_core.tradehub_core.doctype.import_job.import_job import create_import_job

        result = create_import_job(
            import_file=self.test_file_url,
            import_type="Listing",
            job_name="API Test Job"
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("job_name", result)
        self.assertIn("job_code", result)

    def test_get_import_job_api(self):
        """Test get_import_job API endpoint."""
        from tradehub_core.tradehub_core.doctype.import_job.import_job import get_import_job

        # Create a job first
        job = frappe.get_doc({
            "doctype": "Import Job",
            "import_file": self.test_file_url,
            "import_type": "Listing"
        })
        job.insert()

        result = get_import_job(job_name=job.name)

        self.assertEqual(result["name"], job.name)
        self.assertEqual(result["job_code"], job.job_code)
        self.assertEqual(result["status"], "Pending")

    def test_get_import_template_api(self):
        """Test get_import_template API endpoint."""
        from tradehub_core.tradehub_core.doctype.import_job.import_job import get_import_template

        result = get_import_template("Listing")

        self.assertEqual(result["import_type"], "Listing")
        self.assertIn("title", result["headers"])
        self.assertIn("sku", result["headers"])
        self.assertIn("csv_template", result)

    def test_get_import_statistics_api(self):
        """Test get_import_statistics API endpoint."""
        from tradehub_core.tradehub_core.doctype.import_job.import_job import get_import_statistics

        # Create some jobs
        for i in range(3):
            job = frappe.get_doc({
                "doctype": "Import Job",
                "import_file": self.test_file_url,
                "import_type": "Listing"
            })
            job.insert()

        result = get_import_statistics()

        self.assertIn("total_jobs", result)
        self.assertIn("by_status", result)
        self.assertIn("by_type", result)
        self.assertGreaterEqual(result["total_jobs"], 3)
