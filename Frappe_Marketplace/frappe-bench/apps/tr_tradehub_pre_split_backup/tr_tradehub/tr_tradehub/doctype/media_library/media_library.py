# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, cint
import os
import mimetypes


class MediaLibrary(Document):
    """
    Media Library DocType for centralized file management with user-specific isolation.

    Users can only see and manage their own uploaded files unless they have
    System Manager role.
    """

    def before_insert(self):
        """Set default values before inserting a new record."""
        self.set_uploaded_by()
        self.set_tenant_from_user()
        self.uploaded_at = now_datetime()

    def before_save(self):
        """Validate and process data before saving."""
        self.validate_file()
        self.extract_file_metadata()
        self.modified_at = now_datetime()

    def validate(self):
        """Validate the document data."""
        self.validate_title()
        self.validate_file_size()

    def set_uploaded_by(self):
        """Set the uploaded_by field to current user if not already set."""
        if not self.uploaded_by:
            self.uploaded_by = frappe.session.user

    def set_tenant_from_user(self):
        """Set tenant from the user's associated tenant."""
        if not self.tenant and self.uploaded_by:
            # Try to get tenant from user's associated seller profile
            seller_tenant = frappe.db.get_value(
                "Seller Profile",
                {"user": self.uploaded_by},
                "tenant"
            )
            if seller_tenant:
                self.tenant = seller_tenant
            else:
                # Try to get tenant from user's associated organization
                org_tenant = frappe.db.get_value(
                    "Organization",
                    {"owner": self.uploaded_by},
                    "tenant"
                )
                if org_tenant:
                    self.tenant = org_tenant

    def validate_title(self):
        """Ensure title is provided and not empty."""
        if not self.title or not self.title.strip():
            frappe.throw(_("Title is required and cannot be empty"))

    def validate_file(self):
        """Ensure file is provided."""
        if not self.file:
            frappe.throw(_("File is required"))

    def validate_file_size(self):
        """Validate file size doesn't exceed maximum allowed (25MB)."""
        max_size = 25 * 1024 * 1024  # 25MB in bytes
        if self.file_size and cint(self.file_size) > max_size:
            frappe.throw(
                _("File size exceeds maximum allowed size of 25MB")
            )

    def extract_file_metadata(self):
        """Extract and store file metadata from the uploaded file."""
        if not self.file:
            return

        # Set file URL
        self.file_url = self.file

        # Extract filename and detect MIME type
        filename = self.file.split("/")[-1] if "/" in self.file else self.file
        mime_type, _ = mimetypes.guess_type(filename)
        self.mime_type = mime_type or "application/octet-stream"

        # Determine file type from MIME type
        self.file_type = self.get_file_type_from_mime(self.mime_type)

        # Try to get file size from file doc if available
        if self.file.startswith("/files/") or self.file.startswith("/private/files/"):
            file_doc = frappe.db.get_value(
                "File",
                {"file_url": self.file},
                ["file_size"],
                as_dict=True
            )
            if file_doc and file_doc.file_size:
                self.file_size = cint(file_doc.file_size)

        # For images, try to get dimensions
        if self.file_type == "Image":
            self.extract_image_dimensions()

    def get_file_type_from_mime(self, mime_type):
        """Determine file type category from MIME type."""
        if not mime_type:
            return "Other"

        mime_lower = mime_type.lower()

        if mime_lower.startswith("image/"):
            return "Image"
        elif mime_lower.startswith("video/"):
            return "Video"
        elif mime_lower.startswith("audio/"):
            return "Audio"
        elif mime_lower in [
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/plain",
            "text/csv"
        ]:
            return "Document"
        elif mime_lower in [
            "application/zip",
            "application/x-rar-compressed",
            "application/x-7z-compressed",
            "application/x-tar",
            "application/gzip"
        ]:
            return "Archive"
        else:
            return "Other"

    def extract_image_dimensions(self):
        """Try to extract image dimensions using PIL if available."""
        try:
            from PIL import Image
            import io

            # Get the file path
            file_path = self.get_file_path()
            if file_path and os.path.exists(file_path):
                with Image.open(file_path) as img:
                    self.image_width = img.width
                    self.image_height = img.height
        except ImportError:
            # PIL not available, skip dimension extraction
            pass
        except Exception:
            # Any other error, skip silently
            pass

    def get_file_path(self):
        """Get the full file system path for the uploaded file."""
        if not self.file:
            return None

        site_path = frappe.get_site_path()

        if self.file.startswith("/private/files/"):
            return os.path.join(site_path, self.file[1:])
        elif self.file.startswith("/files/"):
            return os.path.join(site_path, "public", self.file[1:])
        elif self.file.startswith("http"):
            return None  # External URL, cannot get local path

        return None

    def increment_usage(self):
        """Increment the usage count and update last_used_at timestamp."""
        frappe.db.set_value(
            "Media Library",
            self.name,
            {
                "usage_count": cint(self.usage_count) + 1,
                "last_used_at": now_datetime()
            },
            update_modified=False
        )


def get_permission_query_conditions(user):
    """
    Return permission query conditions for user-specific file isolation.

    Users can only see their own media files unless they are System Manager.
    This function is called by Frappe's permission system.
    """
    if not user:
        user = frappe.session.user

    # System Manager can see all media
    if "System Manager" in frappe.get_roles(user):
        return ""

    # Users can only see their own uploaded media
    return f"`tabMedia Library`.uploaded_by = {frappe.db.escape(user)}"


def has_permission(doc, ptype, user):
    """
    Check if user has permission to access a specific Media Library document.

    This provides document-level permission checking beyond list permissions.
    """
    if not user:
        user = frappe.session.user

    # System Manager has all permissions
    if "System Manager" in frappe.get_roles(user):
        return True

    # Owner has all permissions
    if doc.uploaded_by == user or doc.owner == user:
        return True

    # Public media can be read by anyone
    if ptype == "read" and doc.is_public:
        return True

    return False


@frappe.whitelist()
def get_media_by_folder(folder=None, category=None, limit=50, offset=0):
    """
    Get media files for the current user, optionally filtered by folder/category.

    Args:
        folder: Optional folder filter
        category: Optional category filter
        limit: Maximum number of records to return
        offset: Number of records to skip

    Returns:
        List of Media Library documents
    """
    user = frappe.session.user
    filters = {"uploaded_by": user, "status": "Active"}

    if folder:
        filters["folder"] = folder
    if category:
        filters["category"] = category

    # System Manager can see all media
    if "System Manager" in frappe.get_roles(user):
        filters.pop("uploaded_by", None)

    return frappe.get_all(
        "Media Library",
        filters=filters,
        fields=[
            "name", "title", "file", "file_type", "category",
            "folder", "file_size", "image_width", "image_height",
            "uploaded_at", "is_featured"
        ],
        order_by="uploaded_at desc",
        limit_page_length=cint(limit),
        limit_start=cint(offset)
    )


@frappe.whitelist()
def get_user_folders():
    """
    Get list of unique folders for the current user's media.

    Returns:
        List of folder names
    """
    user = frappe.session.user
    filters = {"uploaded_by": user}

    # System Manager can see all folders
    if "System Manager" in frappe.get_roles(user):
        filters = {}

    folders = frappe.db.sql("""
        SELECT DISTINCT folder
        FROM `tabMedia Library`
        WHERE folder IS NOT NULL AND folder != ''
        {conditions}
        ORDER BY folder
    """.format(
        conditions=f"AND uploaded_by = {frappe.db.escape(user)}" if filters else ""
    ), as_dict=True)

    return [f.folder for f in folders if f.folder]


@frappe.whitelist()
def increment_media_usage(media_name):
    """
    Increment the usage count for a media item.

    Args:
        media_name: The name (ID) of the Media Library document
    """
    if not frappe.db.exists("Media Library", media_name):
        frappe.throw(_("Media not found"))

    doc = frappe.get_doc("Media Library", media_name)
    doc.increment_usage()

    return {"success": True}
