# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Chunked Upload API v1.

This module provides a chunked file upload API with resume capability for
uploading large files to the Trade Hub platform. Key features:

- Chunked uploads for files of any size
- Resume capability for interrupted uploads
- Multi-tenant isolation
- Background processing for optimization
- Automatic Media Asset creation upon completion

Usage Flow:
1. init_upload() - Initialize an upload session, get upload_id
2. upload_chunk() - Upload file chunks (can be parallel or sequential)
3. complete_upload() - Finalize upload and create Media Asset
4. (Optional) cancel_upload() - Cancel an in-progress upload

The chunked upload system uses Redis for session state and temporary file
storage to support resume capability and multi-server environments.
"""

import os
import hashlib
import json
import uuid
import base64
from typing import Optional, Dict, Any, List

import frappe
from frappe import _
from frappe.utils import (
    cint, flt, now_datetime, get_files_path, cstr
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum chunk size (5MB)
MAX_CHUNK_SIZE = 5 * 1024 * 1024

# Default chunk size (1MB)
DEFAULT_CHUNK_SIZE = 1 * 1024 * 1024

# Maximum file size (500MB)
MAX_FILE_SIZE = 500 * 1024 * 1024

# Upload session expiry (24 hours in seconds)
UPLOAD_SESSION_EXPIRY = 24 * 60 * 60

# Temporary upload directory
TEMP_UPLOAD_DIR = "temp_uploads"

# Allowed file extensions (matching Media Asset)
ALLOWED_EXTENSIONS = [
    # Images
    "jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico", "tiff",
    # Videos
    "mp4", "webm", "mov", "avi", "mkv",
    # Documents
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv",
    # Audio
    "mp3", "wav", "ogg", "m4a",
    # 3D Models
    "gltf", "glb", "obj", "fbx", "stl"
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_upload_session_key(upload_id: str) -> str:
    """Get Redis cache key for upload session."""
    return f"chunked_upload:{upload_id}"


def get_chunk_key(upload_id: str, chunk_index: int) -> str:
    """Get Redis cache key for a specific chunk."""
    return f"chunked_upload:{upload_id}:chunk:{chunk_index}"


def get_temp_upload_path() -> str:
    """Get path for temporary upload files."""
    path = os.path.join(get_files_path(), TEMP_UPLOAD_DIR)
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def validate_file_extension(filename: str) -> bool:
    """Validate that file extension is allowed."""
    if not filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS


def get_file_extension(filename: str) -> str:
    """Extract file extension from filename."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def generate_upload_id() -> str:
    """Generate a unique upload ID."""
    return str(uuid.uuid4())


def calculate_chunk_hash(data: bytes) -> str:
    """Calculate MD5 hash of chunk data for integrity verification."""
    return hashlib.md5(data).hexdigest()


def get_current_tenant() -> Optional[str]:
    """Get current user's tenant."""
    try:
        from tr_tradehub.utils.tenant import get_current_tenant as _get_tenant
        return _get_tenant()
    except ImportError:
        # Fallback if tenant utils not available
        return frappe.db.get_value("User", frappe.session.user, "tenant")


# =============================================================================
# UPLOAD SESSION MANAGEMENT
# =============================================================================

def get_upload_session(upload_id: str) -> Optional[Dict[str, Any]]:
    """
    Get upload session data from cache.

    Args:
        upload_id: The upload session ID

    Returns:
        dict: Session data or None if not found
    """
    cache_key = get_upload_session_key(upload_id)
    session_data = frappe.cache().get_value(cache_key)

    if session_data:
        return json.loads(session_data)
    return None


def save_upload_session(upload_id: str, session_data: Dict[str, Any]):
    """
    Save upload session data to cache.

    Args:
        upload_id: The upload session ID
        session_data: Session data to save
    """
    cache_key = get_upload_session_key(upload_id)
    frappe.cache().set_value(
        cache_key,
        json.dumps(session_data),
        expires_in_sec=UPLOAD_SESSION_EXPIRY
    )


def delete_upload_session(upload_id: str):
    """
    Delete upload session and all associated chunks from cache.

    Args:
        upload_id: The upload session ID
    """
    session = get_upload_session(upload_id)
    if session:
        # Delete all chunk data
        total_chunks = session.get("total_chunks", 0)
        for i in range(total_chunks):
            chunk_key = get_chunk_key(upload_id, i)
            frappe.cache().delete_value(chunk_key)

    # Delete session
    cache_key = get_upload_session_key(upload_id)
    frappe.cache().delete_value(cache_key)

    # Clean up temp file if exists
    temp_path = os.path.join(get_temp_upload_path(), f"{upload_id}.tmp")
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================

@frappe.whitelist()
def init_upload(
    filename: str,
    file_size: int,
    chunk_size: int = None,
    asset_type: str = "Image",
    media_category: str = None,
    tags: str = None,
    alt_text: str = None,
    is_public: int = 0
) -> Dict[str, Any]:
    """
    Initialize a chunked upload session.

    This must be called first to start a chunked upload. It validates the
    file parameters and creates an upload session that tracks chunk progress.

    Args:
        filename: Original filename (used for validation and final name)
        file_size: Total file size in bytes
        chunk_size: Size of each chunk in bytes (default 1MB, max 5MB)
        asset_type: Type of media asset (Image, Video, Document, etc.)
        media_category: Category for organization
        tags: Comma-separated tags
        alt_text: Alternative text for accessibility
        is_public: Whether asset is publicly accessible (0 or 1)

    Returns:
        dict: Upload session info including upload_id and chunk parameters

    Raises:
        frappe.ValidationError: If parameters are invalid
    """
    # Validate filename
    if not filename:
        frappe.throw(_("Filename is required"))

    filename = cstr(filename).strip()

    # Validate extension
    if not validate_file_extension(filename):
        frappe.throw(
            _("File type not allowed. Allowed types: {0}").format(
                ", ".join(ALLOWED_EXTENSIONS)
            )
        )

    # Validate file size
    file_size = cint(file_size)
    if file_size <= 0:
        frappe.throw(_("File size must be greater than 0"))

    if file_size > MAX_FILE_SIZE:
        frappe.throw(
            _("File size exceeds maximum allowed ({0} MB)").format(
                MAX_FILE_SIZE / (1024 * 1024)
            )
        )

    # Determine chunk size
    chunk_size = cint(chunk_size) or DEFAULT_CHUNK_SIZE
    if chunk_size > MAX_CHUNK_SIZE:
        chunk_size = MAX_CHUNK_SIZE
    if chunk_size < 1024:  # Minimum 1KB
        chunk_size = 1024

    # Calculate total chunks
    total_chunks = (file_size + chunk_size - 1) // chunk_size

    # Get tenant
    tenant = get_current_tenant()

    # Generate upload ID
    upload_id = generate_upload_id()

    # Create session data
    session_data = {
        "upload_id": upload_id,
        "filename": filename,
        "file_size": file_size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "uploaded_chunks": [],
        "status": "in_progress",
        "created_at": now_datetime().isoformat(),
        "user": frappe.session.user,
        "tenant": tenant,
        "asset_type": asset_type,
        "media_category": media_category,
        "tags": tags,
        "alt_text": alt_text,
        "is_public": cint(is_public),
        "file_hash": None,  # Will be calculated when complete
        "bytes_uploaded": 0
    }

    # Save session
    save_upload_session(upload_id, session_data)

    return {
        "success": True,
        "upload_id": upload_id,
        "filename": filename,
        "file_size": file_size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "message": _("Upload session initialized. You can now upload chunks.")
    }


@frappe.whitelist()
def upload_chunk(
    upload_id: str,
    chunk_index: int,
    chunk_data: str,
    chunk_hash: str = None
) -> Dict[str, Any]:
    """
    Upload a single chunk of a file.

    Chunks can be uploaded in any order and can be re-uploaded to resume
    interrupted uploads. Each chunk is stored in Redis cache until the
    upload is completed.

    Args:
        upload_id: The upload session ID from init_upload
        chunk_index: Zero-based index of this chunk
        chunk_data: Base64-encoded chunk data
        chunk_hash: Optional MD5 hash of chunk for integrity verification

    Returns:
        dict: Upload progress info including chunks received

    Raises:
        frappe.ValidationError: If chunk is invalid or session not found
    """
    # Validate upload_id
    if not upload_id:
        frappe.throw(_("Upload ID is required"))

    # Get session
    session = get_upload_session(upload_id)
    if not session:
        frappe.throw(_("Upload session not found or expired"))

    # Check session status
    if session["status"] != "in_progress":
        frappe.throw(_("Upload session is not active"))

    # Validate user/tenant
    if session["user"] != frappe.session.user:
        # Check if System Manager
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Access denied: You can only upload to your own sessions"))

    # Validate chunk index
    chunk_index = cint(chunk_index)
    if chunk_index < 0 or chunk_index >= session["total_chunks"]:
        frappe.throw(
            _("Invalid chunk index. Expected 0-{0}, got {1}").format(
                session["total_chunks"] - 1, chunk_index
            )
        )

    # Decode chunk data
    if not chunk_data:
        frappe.throw(_("Chunk data is required"))

    try:
        decoded_data = base64.b64decode(chunk_data)
    except Exception as e:
        frappe.throw(_("Invalid chunk data encoding: {0}").format(str(e)))

    # Validate chunk size
    expected_size = session["chunk_size"]
    is_last_chunk = (chunk_index == session["total_chunks"] - 1)

    if is_last_chunk:
        # Last chunk can be smaller
        remaining_bytes = session["file_size"] - (chunk_index * session["chunk_size"])
        if len(decoded_data) != remaining_bytes:
            frappe.throw(
                _("Invalid last chunk size. Expected {0} bytes, got {1}").format(
                    remaining_bytes, len(decoded_data)
                )
            )
    else:
        if len(decoded_data) != expected_size:
            frappe.throw(
                _("Invalid chunk size. Expected {0} bytes, got {1}").format(
                    expected_size, len(decoded_data)
                )
            )

    # Verify chunk hash if provided
    if chunk_hash:
        calculated_hash = calculate_chunk_hash(decoded_data)
        if calculated_hash != chunk_hash:
            frappe.throw(
                _("Chunk integrity check failed. Expected hash {0}, got {1}").format(
                    chunk_hash, calculated_hash
                )
            )

    # Store chunk in cache
    chunk_key = get_chunk_key(upload_id, chunk_index)
    frappe.cache().set_value(
        chunk_key,
        base64.b64encode(decoded_data).decode("utf-8"),
        expires_in_sec=UPLOAD_SESSION_EXPIRY
    )

    # Update session
    if chunk_index not in session["uploaded_chunks"]:
        session["uploaded_chunks"].append(chunk_index)
        session["bytes_uploaded"] += len(decoded_data)

    session["uploaded_chunks"] = sorted(session["uploaded_chunks"])
    save_upload_session(upload_id, session)

    # Calculate progress
    progress = len(session["uploaded_chunks"]) / session["total_chunks"] * 100

    return {
        "success": True,
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "chunks_uploaded": len(session["uploaded_chunks"]),
        "total_chunks": session["total_chunks"],
        "bytes_uploaded": session["bytes_uploaded"],
        "file_size": session["file_size"],
        "progress": round(progress, 2),
        "is_complete": len(session["uploaded_chunks"]) == session["total_chunks"]
    }


@frappe.whitelist()
def complete_upload(upload_id: str) -> Dict[str, Any]:
    """
    Complete a chunked upload and create the Media Asset.

    This assembles all uploaded chunks into a single file, validates
    integrity, and creates a Media Asset document. The upload session
    is then cleaned up.

    Args:
        upload_id: The upload session ID

    Returns:
        dict: Created Media Asset info

    Raises:
        frappe.ValidationError: If upload is incomplete or assembly fails
    """
    # Validate upload_id
    if not upload_id:
        frappe.throw(_("Upload ID is required"))

    # Get session
    session = get_upload_session(upload_id)
    if not session:
        frappe.throw(_("Upload session not found or expired"))

    # Validate user
    if session["user"] != frappe.session.user:
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Access denied: You can only complete your own uploads"))

    # Check all chunks are uploaded
    if len(session["uploaded_chunks"]) != session["total_chunks"]:
        missing = set(range(session["total_chunks"])) - set(session["uploaded_chunks"])
        frappe.throw(
            _("Upload incomplete. Missing chunks: {0}").format(
                ", ".join(str(c) for c in sorted(missing)[:10])
            )
        )

    # Assemble file
    try:
        assembled_data = b""
        for i in range(session["total_chunks"]):
            chunk_key = get_chunk_key(upload_id, i)
            chunk_b64 = frappe.cache().get_value(chunk_key)
            if not chunk_b64:
                frappe.throw(_("Chunk {0} data not found in cache").format(i))
            assembled_data += base64.b64decode(chunk_b64)

        # Verify total size
        if len(assembled_data) != session["file_size"]:
            frappe.throw(
                _("Assembled file size mismatch. Expected {0}, got {1}").format(
                    session["file_size"], len(assembled_data)
                )
            )

        # Calculate file hash
        file_hash = hashlib.md5(assembled_data).hexdigest()

        # Generate unique filename
        ext = get_file_extension(session["filename"])
        safe_filename = f"{upload_id[:8]}_{session['filename']}"

        # Determine if private
        is_private = not cint(session.get("is_public", 0))

        # Save file using Frappe's file system
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": safe_filename,
            "is_private": is_private,
            "content": assembled_data
        })
        file_doc.insert(ignore_permissions=True)

        file_url = file_doc.file_url

        # Create Media Asset
        asset = frappe.new_doc("Media Asset")
        asset.file = file_url
        asset.asset_name = session["filename"].rsplit(".", 1)[0]  # Name without extension
        asset.asset_type = session.get("asset_type", "Image")
        asset.media_category = session.get("media_category")
        asset.tags = session.get("tags")
        asset.alt_text = session.get("alt_text")
        asset.is_public = cint(session.get("is_public", 0))
        asset.tenant = session.get("tenant")
        asset.status = "Processing"
        asset.file_size = len(assembled_data)
        asset.original_filename = session["filename"]

        asset.insert()

        # Clean up session and chunks
        delete_upload_session(upload_id)

        return {
            "success": True,
            "message": _("File uploaded successfully"),
            "media_asset": {
                "name": asset.name,
                "asset_code": asset.asset_code,
                "file_url": file_url,
                "file_size": len(assembled_data),
                "file_hash": file_hash,
                "status": asset.status
            }
        }

    except Exception as e:
        frappe.log_error(
            message=f"Chunked upload assembly failed: {str(e)}",
            title=f"Upload Assembly Error: {upload_id}"
        )

        # Mark session as failed
        session["status"] = "failed"
        session["error"] = str(e)
        save_upload_session(upload_id, session)

        frappe.throw(_("Failed to assemble uploaded file: {0}").format(str(e)))


@frappe.whitelist()
def get_upload_status(upload_id: str) -> Dict[str, Any]:
    """
    Get the current status of an upload session.

    Use this to check progress or resume an interrupted upload.

    Args:
        upload_id: The upload session ID

    Returns:
        dict: Current upload status and progress
    """
    if not upload_id:
        frappe.throw(_("Upload ID is required"))

    session = get_upload_session(upload_id)
    if not session:
        return {
            "success": False,
            "found": False,
            "message": _("Upload session not found or expired")
        }

    # Validate user access
    if session["user"] != frappe.session.user:
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Access denied"))

    # Calculate progress
    chunks_uploaded = len(session["uploaded_chunks"])
    progress = chunks_uploaded / session["total_chunks"] * 100 if session["total_chunks"] > 0 else 0

    return {
        "success": True,
        "found": True,
        "upload_id": upload_id,
        "filename": session["filename"],
        "file_size": session["file_size"],
        "chunk_size": session["chunk_size"],
        "total_chunks": session["total_chunks"],
        "chunks_uploaded": chunks_uploaded,
        "uploaded_chunks": session["uploaded_chunks"],
        "missing_chunks": sorted(
            set(range(session["total_chunks"])) - set(session["uploaded_chunks"])
        ),
        "bytes_uploaded": session.get("bytes_uploaded", 0),
        "progress": round(progress, 2),
        "status": session["status"],
        "created_at": session["created_at"],
        "is_complete": chunks_uploaded == session["total_chunks"]
    }


@frappe.whitelist()
def cancel_upload(upload_id: str) -> Dict[str, Any]:
    """
    Cancel an in-progress upload and clean up resources.

    This removes the upload session and all uploaded chunks from cache.
    Use this if you need to abort an upload.

    Args:
        upload_id: The upload session ID

    Returns:
        dict: Cancellation result
    """
    if not upload_id:
        frappe.throw(_("Upload ID is required"))

    session = get_upload_session(upload_id)
    if not session:
        return {
            "success": True,
            "message": _("Upload session not found (may have already expired)")
        }

    # Validate user access
    if session["user"] != frappe.session.user:
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Access denied: You can only cancel your own uploads"))

    # Delete session and chunks
    delete_upload_session(upload_id)

    return {
        "success": True,
        "message": _("Upload cancelled successfully"),
        "upload_id": upload_id
    }


@frappe.whitelist()
def get_upload_config() -> Dict[str, Any]:
    """
    Get chunked upload configuration.

    Use this to determine chunk size and file limits before starting
    an upload.

    Returns:
        dict: Upload configuration parameters
    """
    return {
        "max_chunk_size": MAX_CHUNK_SIZE,
        "default_chunk_size": DEFAULT_CHUNK_SIZE,
        "max_file_size": MAX_FILE_SIZE,
        "session_expiry_seconds": UPLOAD_SESSION_EXPIRY,
        "allowed_extensions": ALLOWED_EXTENSIONS
    }


@frappe.whitelist()
def list_active_uploads() -> List[Dict[str, Any]]:
    """
    List all active upload sessions for the current user.

    This helps users track and resume their uploads across sessions.

    Returns:
        list: Active upload sessions
    """
    # This is a simplified implementation - in production, you'd want
    # to track upload sessions in a DocType for better persistence

    user = frappe.session.user

    # For now, return empty list as we don't have a persistent tracking mechanism
    # The Redis-based sessions are ephemeral and not easily enumerable
    return {
        "success": True,
        "uploads": [],
        "message": _("Use get_upload_status with a specific upload_id to check session status")
    }


@frappe.whitelist()
def verify_chunk(
    upload_id: str,
    chunk_index: int,
    expected_hash: str
) -> Dict[str, Any]:
    """
    Verify a previously uploaded chunk's integrity.

    Use this to confirm a chunk was uploaded correctly before completing
    the upload.

    Args:
        upload_id: The upload session ID
        chunk_index: Zero-based index of the chunk to verify
        expected_hash: Expected MD5 hash of the chunk

    Returns:
        dict: Verification result
    """
    if not upload_id:
        frappe.throw(_("Upload ID is required"))

    session = get_upload_session(upload_id)
    if not session:
        frappe.throw(_("Upload session not found or expired"))

    # Validate access
    if session["user"] != frappe.session.user:
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Access denied"))

    chunk_index = cint(chunk_index)
    if chunk_index < 0 or chunk_index >= session["total_chunks"]:
        frappe.throw(_("Invalid chunk index"))

    # Check if chunk exists
    if chunk_index not in session["uploaded_chunks"]:
        return {
            "success": False,
            "verified": False,
            "message": _("Chunk has not been uploaded yet")
        }

    # Get chunk and verify hash
    chunk_key = get_chunk_key(upload_id, chunk_index)
    chunk_b64 = frappe.cache().get_value(chunk_key)

    if not chunk_b64:
        return {
            "success": False,
            "verified": False,
            "message": _("Chunk data not found in cache (may have expired)")
        }

    chunk_data = base64.b64decode(chunk_b64)
    actual_hash = calculate_chunk_hash(chunk_data)

    is_valid = actual_hash == expected_hash

    return {
        "success": True,
        "verified": is_valid,
        "chunk_index": chunk_index,
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "message": _("Chunk verified successfully") if is_valid else _("Chunk hash mismatch")
    }
