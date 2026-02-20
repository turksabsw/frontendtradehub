# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, get_datetime, time_diff_in_seconds, get_files_path
import os
import json
import csv
import io
import traceback


# Supported file formats
SUPPORTED_FORMATS = ["CSV", "Excel (XLSX)", "Excel (XLS)", "JSON"]

# Maximum file size (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

# Maximum rows per import
MAX_ROWS = 50000

# Default batch size
DEFAULT_BATCH_SIZE = 100


class ImportJob(Document):
    """
    Import Job DocType for bulk uploads.

    Provides centralized management for bulk importing data into the marketplace:
    - Listings and variants
    - SKUs and inventory
    - Categories
    - Media assets
    - Price updates
    - Inventory updates

    Features:
    - CSV, Excel, and JSON file support
    - Column mapping configuration
    - Validation before processing
    - Background processing with progress tracking
    - Error reporting and retry capability
    - Notification on completion
    """

    def before_insert(self):
        """Set default values before inserting a new import job."""
        # Generate unique job code
        if not self.job_code:
            self.job_code = self.generate_job_code()

        # Set created by
        if not self.created_by:
            self.created_by = frappe.session.user

        # Set tenant if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Set default job name
        if not self.job_name:
            self.job_name = f"{self.import_type} Import - {self.job_code}"

        # Initialize JSON fields
        if not self.column_mapping:
            self.column_mapping = "{}"
        if not self.field_defaults:
            self.field_defaults = "{}"

        # Set default email for notification
        if self.notify_on_completion and not self.notification_email:
            self.notification_email = frappe.session.user

        # Set status
        self.status = "Pending"

    def validate(self):
        """Validate import job data before saving."""
        self.validate_file()
        self.validate_import_type()
        self.validate_configuration()
        self.validate_batch_size()
        self.extract_file_info()
        self.validate_column_mapping()

    def on_update(self):
        """Actions to perform after import job is updated."""
        self.clear_cache()

    def on_trash(self):
        """Clean up related files when import job is deleted."""
        self.cleanup_files()

    # Helper Methods
    def generate_job_code(self):
        """Generate a unique job code."""
        return f"IMP-{frappe.generate_hash(length=8).upper()}"

    def set_tenant_from_context(self):
        """Set tenant from current context or seller."""
        # Try to get tenant from seller
        if self.seller:
            tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if tenant:
                self.tenant = tenant
                return

        # Try to get from session context
        try:
            from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant
        except ImportError:
            pass

    def clear_cache(self):
        """Clear cached job data."""
        cache_key = f"import_job:{self.name}"
        frappe.cache().delete_value(cache_key)

    def cleanup_files(self):
        """Clean up generated report files."""
        files_to_cleanup = [
            self.error_file_url,
            self.success_file_url,
            self.log_file_url
        ]

        for file_url in files_to_cleanup:
            if file_url:
                try:
                    file_path = self.get_file_path(file_url)
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    pass

    # Validation Methods
    def validate_file(self):
        """Validate that import file is provided and valid."""
        if not self.import_file:
            frappe.throw(_("Import file is required"))

    def validate_import_type(self):
        """Validate import type is supported."""
        valid_types = [
            "Listing", "Listing Variant", "SKU", "Category",
            "Media Asset", "Inventory Update", "Price Update"
        ]
        if self.import_type not in valid_types:
            frappe.throw(_("Invalid import type: {0}").format(self.import_type))

    def validate_configuration(self):
        """Validate import configuration."""
        if self.skip_validation and self.import_type == "Listing":
            frappe.msgprint(
                _("Skipping validation may result in invalid data. Proceed with caution."),
                indicator="orange"
            )

    def validate_batch_size(self):
        """Validate batch size is within acceptable range."""
        if self.batch_size:
            if self.batch_size < 1:
                self.batch_size = 1
            elif self.batch_size > 1000:
                self.batch_size = 1000
        else:
            self.batch_size = DEFAULT_BATCH_SIZE

    def extract_file_info(self):
        """Extract file information from import file."""
        if not self.import_file:
            return

        # Extract filename
        file_path = self.import_file
        if file_path.startswith("/"):
            file_path = file_path.lstrip("/")

        filename = os.path.basename(file_path)
        if not self.original_filename:
            self.original_filename = filename

        # Detect file format
        _, ext = os.path.splitext(filename)
        ext = ext.lower()

        if not self.file_format:
            if ext == ".csv":
                self.file_format = "CSV"
            elif ext == ".xlsx":
                self.file_format = "Excel (XLSX)"
            elif ext == ".xls":
                self.file_format = "Excel (XLS)"
            elif ext == ".json":
                self.file_format = "JSON"

        # Get file size
        if not self.file_size:
            full_path = self.get_file_path(self.import_file)
            if full_path and os.path.exists(full_path):
                self.file_size = os.path.getsize(full_path)

                # Validate file size
                if self.file_size > MAX_FILE_SIZE:
                    max_mb = MAX_FILE_SIZE / (1024 * 1024)
                    frappe.throw(
                        _("File size exceeds maximum limit of {0} MB").format(max_mb)
                    )

    def validate_column_mapping(self):
        """Validate column mapping JSON is valid."""
        if self.column_mapping:
            try:
                if isinstance(self.column_mapping, str):
                    json.loads(self.column_mapping)
            except json.JSONDecodeError:
                frappe.throw(_("Invalid column mapping JSON"))

        if self.field_defaults:
            try:
                if isinstance(self.field_defaults, str):
                    json.loads(self.field_defaults)
            except json.JSONDecodeError:
                frappe.throw(_("Invalid field defaults JSON"))

    def get_file_path(self, file_url):
        """Get the full filesystem path of a file."""
        if not file_url:
            return None

        if file_url.startswith("/files/"):
            return os.path.join(get_files_path(), file_url.replace("/files/", ""))
        elif file_url.startswith("/private/files/"):
            return os.path.join(
                get_files_path(is_private=True),
                file_url.replace("/private/files/", "")
            )
        return None

    # Status Management Methods
    def start_validation(self):
        """Start the validation phase."""
        self.db_set("status", "Validating")

    def queue_for_processing(self):
        """Queue the job for processing."""
        self.db_set("status", "Queued")

    def start_processing(self):
        """Mark job as processing."""
        self.db_set("status", "Processing")
        self.db_set("started_at", now_datetime())

    def pause(self):
        """Pause the import job."""
        if self.status == "Processing":
            self.db_set("status", "Paused")

    def resume(self):
        """Resume a paused import job."""
        if self.status == "Paused":
            self.db_set("status", "Processing")
            # Re-queue for background processing
            frappe.enqueue(
                method="tr_tradehub.doctype.import_job.import_job.process_import_job",
                queue="long",
                timeout=3600,
                job_name=self.name
            )

    def complete(self, with_errors=False):
        """Mark job as completed."""
        status = "Completed with Errors" if with_errors else "Completed"
        self.db_set("status", status)
        self.db_set("completed_at", now_datetime())

        # Calculate duration
        if self.started_at:
            duration = time_diff_in_seconds(now_datetime(), self.started_at)
            self.db_set("duration_seconds", cint(duration))

        # Send notification
        if self.notify_on_completion:
            self.send_completion_notification()

    def fail(self, error_message=None):
        """Mark job as failed."""
        self.db_set("status", "Failed")
        self.db_set("completed_at", now_datetime())

        if error_message:
            self.db_set("summary", f"Import failed: {error_message}")

        # Send notification
        if self.notify_on_completion:
            self.send_completion_notification()

    def cancel(self):
        """Cancel the import job."""
        if self.status in ["Pending", "Validating", "Queued", "Paused"]:
            self.db_set("status", "Cancelled")
            self.db_set("completed_at", now_datetime())

    # Progress Tracking Methods
    def update_progress(self, processed=0, successful=0, failed=0, skipped=0):
        """Update progress counters."""
        frappe.db.set_value(
            "Import Job", self.name,
            {
                "processed_rows": cint(self.processed_rows) + processed,
                "successful_rows": cint(self.successful_rows) + successful,
                "failed_rows": cint(self.failed_rows) + failed,
                "skipped_rows": cint(self.skipped_rows) + skipped
            },
            update_modified=False
        )

        # Reload to get updated values
        self.reload()

        # Calculate progress percentage
        if self.total_rows and self.total_rows > 0:
            progress = (self.processed_rows / self.total_rows) * 100
            self.db_set("progress_percent", min(100, progress), update_modified=False)

        # Calculate rows per second and ETA
        if self.started_at and self.processed_rows > 0:
            elapsed = time_diff_in_seconds(now_datetime(), self.started_at)
            if elapsed > 0:
                rps = self.processed_rows / elapsed
                self.db_set("rows_per_second", round(rps, 2), update_modified=False)

                remaining = self.total_rows - self.processed_rows
                if rps > 0:
                    eta = remaining / rps
                    self.db_set("estimated_time_remaining", cint(eta), update_modified=False)

    def add_error(self, row_number, error_type, error_message, field_name=None,
                  field_value=None, severity="Error", row_data=None, stack_trace=None):
        """Add an error record to the job."""
        error = {
            "row_number": row_number,
            "error_type": error_type,
            "error_message": str(error_message)[:500],
            "field_name": field_name,
            "field_value": str(field_value)[:255] if field_value else None,
            "severity": severity,
            "row_data": json.dumps(row_data) if row_data else None,
            "stack_trace": stack_trace[:2000] if stack_trace else None
        }

        # Append to errors child table
        self.append("errors", error)

        # Limit errors stored in database (keep last 1000)
        if len(self.errors) > 1000:
            self.errors = self.errors[-1000:]

        self.save(ignore_permissions=True)

    # File Processing Methods
    def read_import_file(self):
        """Read and parse the import file."""
        file_path = self.get_file_path(self.import_file)
        if not file_path or not os.path.exists(file_path):
            frappe.throw(_("Import file not found"))

        if self.file_format == "CSV":
            return self.read_csv_file(file_path)
        elif self.file_format in ["Excel (XLSX)", "Excel (XLS)"]:
            return self.read_excel_file(file_path)
        elif self.file_format == "JSON":
            return self.read_json_file(file_path)
        else:
            frappe.throw(_("Unsupported file format: {0}").format(self.file_format))

    def read_csv_file(self, file_path):
        """Read CSV file and return rows."""
        rows = []
        headers = []
        delimiter = self.delimiter or ","

        # Handle tab delimiter
        if delimiter == "\\t":
            delimiter = "\t"

        encoding = self.encoding or "utf-8"

        with open(file_path, "r", encoding=encoding) as f:
            reader = csv.reader(f, delimiter=delimiter)

            for i, row in enumerate(reader):
                if i == 0 and self.has_header_row:
                    headers = row
                else:
                    if headers:
                        rows.append(dict(zip(headers, row)))
                    else:
                        rows.append(row)

                # Check max rows
                if len(rows) > MAX_ROWS:
                    frappe.throw(
                        _("File exceeds maximum {0} rows").format(MAX_ROWS)
                    )

        return rows, headers

    def read_excel_file(self, file_path):
        """Read Excel file and return rows."""
        try:
            import openpyxl

            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            ws = wb.active

            rows = []
            headers = []

            for i, row in enumerate(ws.iter_rows(values_only=True)):
                # Skip empty rows
                if all(cell is None for cell in row):
                    continue

                if i == 0 and self.has_header_row:
                    headers = [str(cell) if cell else f"Column_{j}" for j, cell in enumerate(row)]
                else:
                    row_data = [cell for cell in row]
                    if headers:
                        rows.append(dict(zip(headers, row_data)))
                    else:
                        rows.append(row_data)

                # Check max rows
                if len(rows) > MAX_ROWS:
                    frappe.throw(
                        _("File exceeds maximum {0} rows").format(MAX_ROWS)
                    )

            wb.close()
            return rows, headers

        except ImportError:
            frappe.throw(_("openpyxl is required to read Excel files. Please install it."))

    def read_json_file(self, file_path):
        """Read JSON file and return rows."""
        encoding = self.encoding or "utf-8"

        with open(file_path, "r", encoding=encoding) as f:
            data = json.load(f)

        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and "data" in data:
            rows = data["data"]
        else:
            frappe.throw(_("Invalid JSON format. Expected array or object with 'data' key."))

        if len(rows) > MAX_ROWS:
            frappe.throw(_("File exceeds maximum {0} rows").format(MAX_ROWS))

        # Extract headers from first row
        headers = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []

        return rows, headers

    def get_column_mapping(self):
        """Get column mapping as dictionary."""
        if not self.column_mapping:
            return {}

        if isinstance(self.column_mapping, str):
            return json.loads(self.column_mapping)
        return self.column_mapping

    def get_field_defaults(self):
        """Get field defaults as dictionary."""
        if not self.field_defaults:
            return {}

        if isinstance(self.field_defaults, str):
            return json.loads(self.field_defaults)
        return self.field_defaults

    def map_row_to_fields(self, row, mapping=None, defaults=None):
        """Map a row of data to DocType fields."""
        mapping = mapping or self.get_column_mapping()
        defaults = defaults or self.get_field_defaults()

        result = dict(defaults)

        if isinstance(row, dict):
            for source_col, target_field in mapping.items():
                if source_col in row:
                    value = row[source_col]
                    if value is not None and value != "":
                        result[target_field] = value
        elif isinstance(row, list):
            for i, target_field in mapping.items():
                try:
                    idx = int(i)
                    if idx < len(row):
                        value = row[idx]
                        if value is not None and value != "":
                            result[target_field] = value
                except (ValueError, IndexError):
                    pass

        return result

    # Notification Methods
    def send_completion_notification(self):
        """Send notification email on completion."""
        if not self.notification_email:
            return

        try:
            subject = _("Import Job {0} - {1}").format(self.job_code, self.status)

            message = _("""
Your import job has completed.

**Job Details:**
- Job Code: {job_code}
- Job Name: {job_name}
- Import Type: {import_type}
- Status: {status}

**Results:**
- Total Rows: {total}
- Successful: {successful}
- Failed: {failed}
- Skipped: {skipped}

**Duration:** {duration} seconds

{error_note}

View job details: {link}
            """).format(
                job_code=self.job_code,
                job_name=self.job_name,
                import_type=self.import_type,
                status=self.status,
                total=self.total_rows,
                successful=self.successful_rows,
                failed=self.failed_rows,
                skipped=self.skipped_rows,
                duration=self.duration_seconds or 0,
                error_note=_("Please check the error report for failed rows.") if self.failed_rows else "",
                link=frappe.utils.get_url_to_form("Import Job", self.name)
            )

            frappe.sendmail(
                recipients=[self.notification_email],
                subject=subject,
                message=message,
                now=True
            )

            self.db_set("notification_sent", 1)
            self.db_set("notification_sent_at", now_datetime())

        except Exception as e:
            frappe.log_error(
                f"Failed to send import completion notification for {self.name}: {str(e)}",
                "Import Job Notification Error"
            )

    # Report Generation Methods
    def generate_error_report(self):
        """Generate a CSV file with error details."""
        if not self.errors:
            return None

        try:
            files_path = get_files_path()
            filename = f"{self.job_code}_errors.csv"
            file_path = os.path.join(files_path, filename)

            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Row Number", "Error Type", "Error Message",
                    "Field Name", "Field Value", "Severity"
                ])

                for error in self.errors:
                    writer.writerow([
                        error.row_number,
                        error.error_type,
                        error.error_message,
                        error.field_name,
                        error.field_value,
                        error.severity
                    ])

            self.db_set("error_file_url", f"/files/{filename}")
            return f"/files/{filename}"

        except Exception as e:
            frappe.log_error(
                f"Failed to generate error report for {self.name}: {str(e)}",
                "Import Job Error Report"
            )
            return None

    def generate_summary(self):
        """Generate import summary."""
        success_rate = 0
        if self.total_rows and self.total_rows > 0:
            success_rate = round((self.successful_rows / self.total_rows) * 100, 1)

        summary = _("""
Import Summary for {job_name}
============================

Import Type: {import_type}
File: {filename}
Started: {started}
Completed: {completed}
Duration: {duration} seconds

Results:
- Total Rows: {total}
- Successful: {successful} ({success_rate}%)
- Failed: {failed}
- Skipped: {skipped}

Processing Rate: {rps} rows/second
        """).format(
            job_name=self.job_name,
            import_type=self.import_type,
            filename=self.original_filename,
            started=self.started_at,
            completed=self.completed_at,
            duration=self.duration_seconds or 0,
            total=self.total_rows,
            successful=self.successful_rows,
            success_rate=success_rate,
            failed=self.failed_rows,
            skipped=self.skipped_rows,
            rps=self.rows_per_second or 0
        )

        self.db_set("summary", summary)
        return summary

    # Retry Methods
    def can_retry(self):
        """Check if job can be retried."""
        return (
            self.status in ["Failed", "Completed with Errors"] and
            self.retry_count < self.max_retries
        )

    def create_retry_job(self):
        """Create a new job to retry failed rows only."""
        if not self.can_retry():
            frappe.throw(_("Cannot retry this job"))

        # Create new job with failed rows only
        retry_job = frappe.get_doc({
            "doctype": "Import Job",
            "job_name": f"{self.job_name} (Retry {self.retry_count + 1})",
            "import_type": self.import_type,
            "import_file": self.import_file,
            "file_format": self.file_format,
            "tenant": self.tenant,
            "seller": self.seller,
            "category": self.category,
            "default_status": self.default_status,
            "update_existing": self.update_existing,
            "column_mapping": self.column_mapping,
            "field_defaults": self.field_defaults,
            "batch_size": self.batch_size,
            "notify_on_completion": self.notify_on_completion,
            "notification_email": self.notification_email,
            "is_retry": 1,
            "original_job": self.name,
            "retry_count": self.retry_count + 1
        })
        retry_job.insert()

        # Update original job
        self.db_set("last_retry_at", now_datetime())

        return retry_job.name

    # Processing Logic
    def process(self):
        """Main processing method - called by background job."""
        try:
            self.start_processing()

            # Read file
            rows, headers = self.read_import_file()
            self.db_set("total_rows", len(rows))

            # Get configuration
            mapping = self.get_column_mapping()
            defaults = self.get_field_defaults()
            batch_size = self.batch_size or DEFAULT_BATCH_SIZE

            # Process in batches
            for i in range(0, len(rows), batch_size):
                # Check if paused or cancelled
                self.reload()
                if self.status in ["Paused", "Cancelled"]:
                    return

                batch = rows[i:i + batch_size]
                self.process_batch(batch, i + 1, mapping, defaults)

                # Commit after each batch
                frappe.db.commit()

            # Generate reports
            if self.failed_rows > 0:
                self.generate_error_report()

            self.generate_summary()

            # Complete
            with_errors = self.failed_rows > 0
            self.complete(with_errors=with_errors)

        except Exception as e:
            self.fail(str(e))
            frappe.log_error(
                f"Import job {self.name} failed: {str(e)}\n{traceback.format_exc()}",
                "Import Job Error"
            )

    def process_batch(self, batch, start_row, mapping, defaults):
        """Process a batch of rows."""
        for i, row in enumerate(batch):
            row_number = start_row + i

            try:
                # Map row data
                data = self.map_row_to_fields(row, mapping, defaults)

                # Process based on import type
                success = self.process_row(row_number, data, row)

                if success:
                    self.update_progress(processed=1, successful=1)
                else:
                    self.update_progress(processed=1, skipped=1)

            except Exception as e:
                self.add_error(
                    row_number=row_number,
                    error_type="System Error",
                    error_message=str(e),
                    row_data=row if isinstance(row, dict) else None,
                    stack_trace=traceback.format_exc()
                )
                self.update_progress(processed=1, failed=1)

                # Stop on error if configured
                if self.stop_on_error:
                    self.fail(f"Stopped at row {row_number}: {str(e)}")
                    raise

    def process_row(self, row_number, data, original_row):
        """Process a single row based on import type."""
        if self.import_type == "Listing":
            return self.process_listing_row(row_number, data, original_row)
        elif self.import_type == "Listing Variant":
            return self.process_variant_row(row_number, data, original_row)
        elif self.import_type == "SKU":
            return self.process_sku_row(row_number, data, original_row)
        elif self.import_type == "Category":
            return self.process_category_row(row_number, data, original_row)
        elif self.import_type == "Media Asset":
            return self.process_media_row(row_number, data, original_row)
        elif self.import_type == "Inventory Update":
            return self.process_inventory_update(row_number, data, original_row)
        elif self.import_type == "Price Update":
            return self.process_price_update(row_number, data, original_row)
        else:
            self.add_error(
                row_number=row_number,
                error_type="System Error",
                error_message=f"Unknown import type: {self.import_type}"
            )
            return False

    def process_listing_row(self, row_number, data, original_row):
        """Process a listing row."""
        # Check required fields
        required_fields = ["title"]
        for field in required_fields:
            if not data.get(field):
                self.add_error(
                    row_number=row_number,
                    error_type="Missing Required Field",
                    error_message=f"Required field '{field}' is missing",
                    field_name=field,
                    row_data=original_row if isinstance(original_row, dict) else None
                )
                return False

        # Set defaults
        data["doctype"] = "Listing"
        data["seller"] = data.get("seller") or self.seller
        data["tenant"] = data.get("tenant") or self.tenant
        data["category"] = data.get("category") or self.category
        data["status"] = data.get("status") or self.default_status or "Draft"
        data["import_job"] = self.name

        # Check for existing (update mode)
        if self.update_existing and data.get("sku"):
            existing = frappe.db.exists("Listing", {"sku": data["sku"], "seller": data["seller"]})
            if existing:
                try:
                    listing = frappe.get_doc("Listing", existing)
                    listing.update(data)
                    listing.save()
                    return True
                except Exception as e:
                    self.add_error(
                        row_number=row_number,
                        error_type="Validation Error",
                        error_message=str(e),
                        row_data=original_row if isinstance(original_row, dict) else None
                    )
                    return False

        # Create new listing
        try:
            listing = frappe.get_doc(data)

            if not self.skip_validation:
                listing.validate()

            listing.insert()
            return True

        except Exception as e:
            self.add_error(
                row_number=row_number,
                error_type="Validation Error",
                error_message=str(e),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

    def process_variant_row(self, row_number, data, original_row):
        """Process a listing variant row."""
        # Check required fields
        if not data.get("listing"):
            self.add_error(
                row_number=row_number,
                error_type="Missing Required Field",
                error_message="Required field 'listing' is missing",
                field_name="listing",
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        # Verify listing exists
        if not frappe.db.exists("Listing", data["listing"]):
            self.add_error(
                row_number=row_number,
                error_type="Reference Not Found",
                error_message=f"Listing '{data['listing']}' does not exist",
                field_name="listing",
                field_value=data.get("listing"),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        data["doctype"] = "Listing Variant"

        try:
            variant = frappe.get_doc(data)

            if not self.skip_validation:
                variant.validate()

            variant.insert()
            return True

        except Exception as e:
            self.add_error(
                row_number=row_number,
                error_type="Validation Error",
                error_message=str(e),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

    def process_sku_row(self, row_number, data, original_row):
        """Process an SKU row."""
        if not data.get("sku_code"):
            self.add_error(
                row_number=row_number,
                error_type="Missing Required Field",
                error_message="Required field 'sku_code' is missing",
                field_name="sku_code",
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        data["doctype"] = "SKU"
        data["seller"] = data.get("seller") or self.seller
        data["tenant"] = data.get("tenant") or self.tenant

        # Check for existing
        if self.update_existing:
            existing = frappe.db.exists("SKU", {"sku_code": data["sku_code"]})
            if existing:
                try:
                    sku = frappe.get_doc("SKU", existing)
                    sku.update(data)
                    sku.save()
                    return True
                except Exception as e:
                    self.add_error(
                        row_number=row_number,
                        error_type="Validation Error",
                        error_message=str(e),
                        row_data=original_row if isinstance(original_row, dict) else None
                    )
                    return False

        try:
            sku = frappe.get_doc(data)

            if not self.skip_validation:
                sku.validate()

            sku.insert()
            return True

        except Exception as e:
            self.add_error(
                row_number=row_number,
                error_type="Validation Error",
                error_message=str(e),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

    def process_category_row(self, row_number, data, original_row):
        """Process a category row."""
        if not data.get("category_name"):
            self.add_error(
                row_number=row_number,
                error_type="Missing Required Field",
                error_message="Required field 'category_name' is missing",
                field_name="category_name",
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        data["doctype"] = "Category"

        try:
            category = frappe.get_doc(data)

            if not self.skip_validation:
                category.validate()

            category.insert()
            return True

        except Exception as e:
            self.add_error(
                row_number=row_number,
                error_type="Validation Error",
                error_message=str(e),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

    def process_media_row(self, row_number, data, original_row):
        """Process a media asset row."""
        if not data.get("file_url"):
            self.add_error(
                row_number=row_number,
                error_type="Missing Required Field",
                error_message="Required field 'file_url' is missing",
                field_name="file_url",
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        data["doctype"] = "Media Asset"
        data["tenant"] = data.get("tenant") or self.tenant

        try:
            asset = frappe.get_doc(data)

            if not self.skip_validation:
                asset.validate()

            asset.insert()
            return True

        except Exception as e:
            self.add_error(
                row_number=row_number,
                error_type="Validation Error",
                error_message=str(e),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

    def process_inventory_update(self, row_number, data, original_row):
        """Process an inventory update row."""
        sku_code = data.get("sku_code") or data.get("sku")

        if not sku_code:
            self.add_error(
                row_number=row_number,
                error_type="Missing Required Field",
                error_message="Required field 'sku_code' is missing",
                field_name="sku_code",
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        # Find SKU
        sku_name = frappe.db.get_value("SKU", {"sku_code": sku_code}, "name")
        if not sku_name:
            # Try finding by listing SKU
            listing_name = frappe.db.get_value("Listing", {"sku": sku_code}, "name")
            if not listing_name:
                self.add_error(
                    row_number=row_number,
                    error_type="Reference Not Found",
                    error_message=f"SKU or Listing with code '{sku_code}' not found",
                    field_name="sku_code",
                    field_value=sku_code,
                    row_data=original_row if isinstance(original_row, dict) else None
                )
                return False

            # Update listing stock
            try:
                stock_qty = flt(data.get("stock_qty") or data.get("quantity") or 0)
                frappe.db.set_value("Listing", listing_name, "stock_qty", stock_qty)
                return True
            except Exception as e:
                self.add_error(
                    row_number=row_number,
                    error_type="System Error",
                    error_message=str(e),
                    row_data=original_row if isinstance(original_row, dict) else None
                )
                return False

        # Update SKU stock
        try:
            sku = frappe.get_doc("SKU", sku_name)
            stock_qty = flt(data.get("stock_qty") or data.get("quantity") or 0)
            sku.update_stock(stock_qty)
            return True
        except Exception as e:
            self.add_error(
                row_number=row_number,
                error_type="System Error",
                error_message=str(e),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

    def process_price_update(self, row_number, data, original_row):
        """Process a price update row."""
        sku_code = data.get("sku_code") or data.get("sku")

        if not sku_code:
            self.add_error(
                row_number=row_number,
                error_type="Missing Required Field",
                error_message="Required field 'sku_code' is missing",
                field_name="sku_code",
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        # Find listing by SKU
        listing_name = frappe.db.get_value("Listing", {"sku": sku_code}, "name")
        if not listing_name:
            # Try by listing variant
            variant_name = frappe.db.get_value("Listing Variant", {"sku": sku_code}, "name")
            if variant_name:
                try:
                    variant = frappe.get_doc("Listing Variant", variant_name)
                    if data.get("selling_price"):
                        variant.price = flt(data["selling_price"])
                    if data.get("compare_at_price"):
                        variant.compare_at_price = flt(data["compare_at_price"])
                    variant.save()
                    return True
                except Exception as e:
                    self.add_error(
                        row_number=row_number,
                        error_type="System Error",
                        error_message=str(e),
                        row_data=original_row if isinstance(original_row, dict) else None
                    )
                    return False

            self.add_error(
                row_number=row_number,
                error_type="Reference Not Found",
                error_message=f"Listing with SKU '{sku_code}' not found",
                field_name="sku_code",
                field_value=sku_code,
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False

        # Update listing prices
        try:
            listing = frappe.get_doc("Listing", listing_name)
            if data.get("selling_price"):
                listing.selling_price = flt(data["selling_price"])
            if data.get("base_price"):
                listing.base_price = flt(data["base_price"])
            if data.get("compare_at_price"):
                listing.compare_at_price = flt(data["compare_at_price"])
            if data.get("wholesale_price"):
                listing.wholesale_price = flt(data["wholesale_price"])
            listing.save()
            return True
        except Exception as e:
            self.add_error(
                row_number=row_number,
                error_type="System Error",
                error_message=str(e),
                row_data=original_row if isinstance(original_row, dict) else None
            )
            return False


# Background processing function
def process_import_job(job_name):
    """Process import job in background."""
    try:
        job = frappe.get_doc("Import Job", job_name)
        job.process()
    except Exception as e:
        frappe.log_error(
            f"Background processing failed for {job_name}: {str(e)}",
            "Import Job Background Error"
        )
        try:
            frappe.db.set_value("Import Job", job_name, "status", "Failed")
        except Exception:
            pass


# API Endpoints
@frappe.whitelist()
def get_import_job(job_name=None, job_code=None):
    """
    Get import job details.

    Args:
        job_name: Name of the job
        job_code: Unique job code

    Returns:
        dict: Job details
    """
    if not job_name and not job_code:
        frappe.throw(_("Either job_name or job_code is required"))

    if job_code and not job_name:
        job_name = frappe.db.get_value(
            "Import Job", {"job_code": job_code}, "name"
        )

    if not job_name:
        return {"error": _("Import job not found")}

    job = frappe.get_doc("Import Job", job_name)

    return {
        "name": job.name,
        "job_code": job.job_code,
        "job_name": job.job_name,
        "import_type": job.import_type,
        "status": job.status,
        "file_format": job.file_format,
        "original_filename": job.original_filename,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "successful_rows": job.successful_rows,
        "failed_rows": job.failed_rows,
        "skipped_rows": job.skipped_rows,
        "progress_percent": job.progress_percent,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "duration_seconds": job.duration_seconds,
        "rows_per_second": job.rows_per_second,
        "estimated_time_remaining": job.estimated_time_remaining,
        "error_file_url": job.error_file_url,
        "success_file_url": job.success_file_url,
        "summary": job.summary,
        "can_retry": job.can_retry(),
        "error_count": len(job.errors) if job.errors else 0
    }


@frappe.whitelist()
def create_import_job(import_file, import_type, **kwargs):
    """
    Create a new import job.

    Args:
        import_file: URL of the uploaded file
        import_type: Type of import
        **kwargs: Additional job fields

    Returns:
        dict: Created job details
    """
    job = frappe.get_doc({
        "doctype": "Import Job",
        "import_file": import_file,
        "import_type": import_type,
        "job_name": kwargs.get("job_name"),
        "file_format": kwargs.get("file_format"),
        "has_header_row": kwargs.get("has_header_row", 1),
        "delimiter": kwargs.get("delimiter", ","),
        "encoding": kwargs.get("encoding", "utf-8"),
        "seller": kwargs.get("seller"),
        "tenant": kwargs.get("tenant"),
        "category": kwargs.get("category"),
        "default_status": kwargs.get("default_status", "Draft"),
        "update_existing": kwargs.get("update_existing", 0),
        "skip_validation": kwargs.get("skip_validation", 0),
        "stop_on_error": kwargs.get("stop_on_error", 0),
        "batch_size": kwargs.get("batch_size", DEFAULT_BATCH_SIZE),
        "column_mapping": kwargs.get("column_mapping"),
        "field_defaults": kwargs.get("field_defaults"),
        "notify_on_completion": kwargs.get("notify_on_completion", 1),
        "notification_email": kwargs.get("notification_email"),
        "priority": kwargs.get("priority", "Medium")
    })
    job.insert()

    return {
        "status": "success",
        "job_name": job.name,
        "job_code": job.job_code,
        "message": _("Import job created successfully")
    }


@frappe.whitelist()
def start_import_job(job_name):
    """
    Start processing an import job.

    Args:
        job_name: Name of the job to start

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Import Job", job_name):
        return {"error": _("Import job not found")}

    job = frappe.get_doc("Import Job", job_name)

    if job.status not in ["Pending", "Paused"]:
        return {"error": _("Job cannot be started from status: {0}").format(job.status)}

    # Queue for background processing
    job.queue_for_processing()

    frappe.enqueue(
        method="tr_tradehub.doctype.import_job.import_job.process_import_job",
        queue="long",
        timeout=3600,
        job_name=job_name
    )

    return {
        "status": "success",
        "message": _("Import job queued for processing")
    }


@frappe.whitelist()
def pause_import_job(job_name):
    """
    Pause a running import job.

    Args:
        job_name: Name of the job to pause

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Import Job", job_name):
        return {"error": _("Import job not found")}

    job = frappe.get_doc("Import Job", job_name)
    job.pause()

    return {
        "status": "success",
        "message": _("Import job paused")
    }


@frappe.whitelist()
def resume_import_job(job_name):
    """
    Resume a paused import job.

    Args:
        job_name: Name of the job to resume

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Import Job", job_name):
        return {"error": _("Import job not found")}

    job = frappe.get_doc("Import Job", job_name)
    job.resume()

    return {
        "status": "success",
        "message": _("Import job resumed")
    }


@frappe.whitelist()
def cancel_import_job(job_name):
    """
    Cancel an import job.

    Args:
        job_name: Name of the job to cancel

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Import Job", job_name):
        return {"error": _("Import job not found")}

    job = frappe.get_doc("Import Job", job_name)
    job.cancel()

    return {
        "status": "success",
        "message": _("Import job cancelled")
    }


@frappe.whitelist()
def retry_import_job(job_name):
    """
    Create a retry job for failed rows.

    Args:
        job_name: Name of the original job

    Returns:
        dict: Result with new job details
    """
    if not frappe.db.exists("Import Job", job_name):
        return {"error": _("Import job not found")}

    job = frappe.get_doc("Import Job", job_name)

    if not job.can_retry():
        return {"error": _("Job cannot be retried")}

    new_job_name = job.create_retry_job()

    return {
        "status": "success",
        "new_job_name": new_job_name,
        "message": _("Retry job created successfully")
    }


@frappe.whitelist()
def get_import_job_errors(job_name, limit=100, offset=0):
    """
    Get errors for an import job.

    Args:
        job_name: Name of the job
        limit: Max errors to return
        offset: Offset for pagination

    Returns:
        list: List of errors
    """
    if not frappe.db.exists("Import Job", job_name):
        return {"error": _("Import job not found")}

    errors = frappe.get_all(
        "Import Job Error",
        filters={"parent": job_name},
        fields=[
            "row_number", "error_type", "error_message",
            "field_name", "field_value", "severity"
        ],
        order_by="row_number ASC",
        limit=cint(limit),
        start=cint(offset)
    )

    total = frappe.db.count("Import Job Error", {"parent": job_name})

    return {
        "errors": errors,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@frappe.whitelist()
def get_seller_import_jobs(seller=None, status=None, limit=20, offset=0):
    """
    Get import jobs for a seller.

    Args:
        seller: Seller profile name (optional, defaults to current user's seller)
        status: Filter by status
        limit: Max jobs to return
        offset: Offset for pagination

    Returns:
        list: List of import jobs
    """
    filters = {}

    if seller:
        filters["seller"] = seller
    else:
        # Try to get current user's seller profile
        seller = frappe.db.get_value(
            "Seller Profile",
            {"user": frappe.session.user},
            "name"
        )
        if seller:
            filters["seller"] = seller

    if status:
        filters["status"] = status

    jobs = frappe.get_all(
        "Import Job",
        filters=filters,
        fields=[
            "name", "job_code", "job_name", "import_type", "status",
            "total_rows", "successful_rows", "failed_rows",
            "progress_percent", "created_by", "creation"
        ],
        order_by="creation DESC",
        limit=cint(limit),
        start=cint(offset)
    )

    total = frappe.db.count("Import Job", filters)

    return {
        "jobs": jobs,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@frappe.whitelist()
def get_import_statistics(seller=None, tenant=None):
    """
    Get import statistics.

    Args:
        seller: Filter by seller
        tenant: Filter by tenant

    Returns:
        dict: Statistics
    """
    filters = {}
    if seller:
        filters["seller"] = seller
    if tenant:
        filters["tenant"] = tenant

    total_jobs = frappe.db.count("Import Job", filters)

    # Use parameterized queries to prevent SQL injection
    params = {}
    if seller:
        where_clause = "seller = %(seller)s"
        params["seller"] = seller
    elif tenant:
        where_clause = "tenant = %(tenant)s"
        params["tenant"] = tenant
    else:
        where_clause = "1=1"

    # Count by status
    status_counts = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabImport Job`
        WHERE {where_clause}
        GROUP BY status
    """.format(where_clause=where_clause), params, as_dict=True)

    # Count by type
    type_counts = frappe.db.sql("""
        SELECT import_type, COUNT(*) as count
        FROM `tabImport Job`
        WHERE {where_clause}
        GROUP BY import_type
    """.format(where_clause=where_clause), params, as_dict=True)

    # Total rows processed
    totals = frappe.db.sql("""
        SELECT
            SUM(total_rows) as total_rows,
            SUM(successful_rows) as successful_rows,
            SUM(failed_rows) as failed_rows
        FROM `tabImport Job`
        WHERE {where_clause}
    """.format(where_clause=where_clause), params, as_dict=True)

    return {
        "total_jobs": total_jobs,
        "by_status": {s.status: s.count for s in status_counts},
        "by_type": {t.import_type: t.count for t in type_counts},
        "total_rows": cint(totals[0].total_rows if totals else 0),
        "successful_rows": cint(totals[0].successful_rows if totals else 0),
        "failed_rows": cint(totals[0].failed_rows if totals else 0)
    }


@frappe.whitelist()
def validate_import_file(import_file, file_format=None, has_header_row=1):
    """
    Validate an import file before creating a job.

    Args:
        import_file: URL of the file to validate
        file_format: File format (optional, auto-detected)
        has_header_row: Whether first row is header

    Returns:
        dict: Validation results with preview
    """
    # Create temporary job for validation
    job = frappe.get_doc({
        "doctype": "Import Job",
        "import_file": import_file,
        "import_type": "Listing",
        "file_format": file_format,
        "has_header_row": cint(has_header_row)
    })

    try:
        job.extract_file_info()
        rows, headers = job.read_import_file()

        # Preview first 10 rows
        preview = rows[:10] if rows else []

        return {
            "status": "success",
            "file_format": job.file_format,
            "file_size": job.file_size,
            "original_filename": job.original_filename,
            "total_rows": len(rows),
            "headers": headers,
            "preview": preview,
            "message": _("File validated successfully")
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@frappe.whitelist()
def get_import_template(import_type):
    """
    Get template CSV headers for an import type.

    Args:
        import_type: Type of import

    Returns:
        dict: Template headers and example row
    """
    templates = {
        "Listing": {
            "headers": [
                "title", "sku", "category", "description", "base_price",
                "selling_price", "stock_qty", "uom", "weight", "weight_uom",
                "brand", "manufacturer", "barcode", "status"
            ],
            "example": [
                "Product Title", "SKU-001", "Electronics",
                "Product description here", "100.00", "90.00", "50",
                "Nos", "0.5", "Kg", "Brand Name", "Manufacturer Name",
                "1234567890123", "Draft"
            ]
        },
        "Listing Variant": {
            "headers": [
                "listing", "variant_title", "sku", "price",
                "stock_qty", "attribute_1", "value_1", "attribute_2", "value_2"
            ],
            "example": [
                "LST-00001", "Red - Large", "SKU-001-R-L", "95.00",
                "20", "Color", "Red", "Size", "Large"
            ]
        },
        "SKU": {
            "headers": [
                "sku_code", "product_name", "barcode", "stock_qty",
                "reorder_level", "reorder_qty", "unit_price", "cost_price"
            ],
            "example": [
                "SKU-001", "Product Name", "1234567890123", "100",
                "10", "50", "90.00", "50.00"
            ]
        },
        "Category": {
            "headers": [
                "category_name", "parent_category", "description",
                "commission_rate", "is_active"
            ],
            "example": [
                "Smartphones", "Electronics", "Mobile phones and smartphones",
                "10", "1"
            ]
        },
        "Inventory Update": {
            "headers": ["sku_code", "stock_qty"],
            "example": ["SKU-001", "150"]
        },
        "Price Update": {
            "headers": [
                "sku_code", "selling_price", "base_price",
                "compare_at_price", "wholesale_price"
            ],
            "example": ["SKU-001", "95.00", "100.00", "110.00", "80.00"]
        },
        "Media Asset": {
            "headers": [
                "file_url", "title", "asset_type", "entity_type",
                "entity_name", "alt_text", "position"
            ],
            "example": [
                "/files/product-image.jpg", "Product Image",
                "Image", "Listing", "LST-00001", "Product front view", "0"
            ]
        }
    }

    template = templates.get(import_type)
    if not template:
        return {"error": _("Unknown import type")}

    return {
        "import_type": import_type,
        "headers": template["headers"],
        "example": template["example"],
        "csv_template": ",".join(template["headers"]) + "\n" + ",".join(template["example"])
    }
