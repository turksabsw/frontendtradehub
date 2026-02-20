# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Media Processor Background Tasks.

This module provides background job functions for processing media assets including:
- Image resizing for multiple dimensions (thumbnail, medium, large)
- WebP conversion for modern browsers
- Image optimization for file size reduction
- Metadata extraction (dimensions, color mode, format)
- Batch processing of pending media assets

The processor is designed to be:
- Multi-tenant aware (respects tenant isolation)
- Fault-tolerant (logs errors, marks failed assets)
- Efficient (uses PIL/Pillow for image operations)
- CDN-ready (generates optimized URLs)

Usage in hooks.py:
    scheduler_events = {
        "cron": {
            "*/5 * * * *": [
                "tr_tradehub.tasks.media_processor.process_pending_media"
            ]
        }
    }

Usage for single asset:
    frappe.enqueue(
        "tr_tradehub.tasks.media_processor.process_media_asset",
        media_asset="ASSET-00001",
        queue="long"
    )
"""

import os
import io
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import (
    cint, flt, now_datetime, get_files_path, get_url, cstr
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Image resize dimensions (width, height)
RESIZE_DIMENSIONS = {
    "thumbnail": (200, 200),
    "small": (400, 400),
    "medium": (800, 800),
    "large": (1200, 1200),
    "xlarge": (1920, 1920),
}

# Default thumbnail size
DEFAULT_THUMBNAIL_SIZE = 200

# Maximum optimization size (larger images will be resized first)
MAX_OPTIMIZE_SIZE = (2000, 2000)

# JPEG quality for optimization
JPEG_QUALITY = 85

# WebP quality for conversion
WEBP_QUALITY = 85

# PNG compression level (0-9, higher = more compression but slower)
PNG_COMPRESSION = 6

# Maximum file size before optimization (5MB)
MAX_FILE_SIZE_BEFORE_OPTIMIZE = 5 * 1024 * 1024

# Image formats that can be converted to WebP
WEBP_CONVERTIBLE_FORMATS = ["jpg", "jpeg", "png", "gif", "bmp", "tiff"]

# Image formats that can be optimized
OPTIMIZABLE_FORMATS = ["jpg", "jpeg", "png", "gif", "webp"]

# Batch size for processing pending media
BATCH_SIZE = 20


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_file_path(file_url: str) -> Optional[str]:
    """
    Convert file URL to filesystem path.

    Args:
        file_url: File URL (e.g., /files/image.jpg or /private/files/image.jpg)

    Returns:
        str: Filesystem path or None if invalid
    """
    if not file_url:
        return None

    if file_url.startswith("/files/"):
        return get_files_path() + file_url.replace("/files", "", 1)
    elif file_url.startswith("/private/files/"):
        return get_files_path(is_private=True) + file_url.replace("/private/files", "", 1)

    return None


def get_file_extension(filename: str) -> str:
    """
    Extract file extension from filename.

    Args:
        filename: Filename or path

    Returns:
        str: Lowercase file extension without dot
    """
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def get_output_path(original_path: str, suffix: str, new_ext: str = None) -> str:
    """
    Generate output path for processed file.

    Args:
        original_path: Original file path
        suffix: Suffix to add (e.g., "_thumb", "_webp")
        new_ext: New extension (optional)

    Returns:
        str: Output file path
    """
    directory = os.path.dirname(original_path)
    filename = os.path.basename(original_path)
    name, ext = os.path.splitext(filename)

    if new_ext:
        ext = f".{new_ext.lstrip('.')}"

    return os.path.join(directory, f"{name}{suffix}{ext}")


def get_output_url(original_url: str, suffix: str, new_ext: str = None) -> str:
    """
    Generate output URL for processed file.

    Args:
        original_url: Original file URL
        suffix: Suffix to add (e.g., "_thumb", "_webp")
        new_ext: New extension (optional)

    Returns:
        str: Output file URL
    """
    if "." in original_url:
        base, ext = original_url.rsplit(".", 1)
        if new_ext:
            ext = new_ext.lstrip(".")
        return f"{base}{suffix}.{ext}"
    return f"{original_url}{suffix}"


def is_image_file(file_path: str) -> bool:
    """
    Check if file is an image that can be processed.

    Args:
        file_path: File path to check

    Returns:
        bool: True if file is a processable image
    """
    ext = get_file_extension(file_path)
    return ext in OPTIMIZABLE_FORMATS + WEBP_CONVERTIBLE_FORMATS


def load_image(file_path: str):
    """
    Load image from file path using PIL.

    Args:
        file_path: Path to image file

    Returns:
        PIL.Image: Loaded image object

    Raises:
        ImportError: If PIL is not installed
        IOError: If image cannot be loaded
    """
    from PIL import Image
    return Image.open(file_path)


def ensure_rgb(image):
    """
    Ensure image is in RGB mode for JPEG/WebP conversion.

    Args:
        image: PIL Image object

    Returns:
        PIL.Image: Image in RGB or RGBA mode
    """
    if image.mode in ("RGBA", "LA", "PA"):
        # Image has alpha channel, convert to RGBA
        return image.convert("RGBA")
    elif image.mode not in ("RGB", "L"):
        # Convert to RGB
        return image.convert("RGB")
    return image


# =============================================================================
# IMAGE PROCESSING FUNCTIONS
# =============================================================================


def resize_image(
    file_path: str,
    max_width: int,
    max_height: int,
    output_path: str = None,
    maintain_aspect: bool = True
) -> Optional[str]:
    """
    Resize an image to fit within specified dimensions.

    Args:
        file_path: Path to input image
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels
        output_path: Path for output file (optional, overwrites original if not specified)
        maintain_aspect: Whether to maintain aspect ratio (default True)

    Returns:
        str: Path to resized image or None on failure
    """
    try:
        from PIL import Image

        if not os.path.exists(file_path):
            frappe.log_error(
                message=f"File not found: {file_path}",
                title="Media Processor - Resize Failed"
            )
            return None

        with Image.open(file_path) as img:
            original_width, original_height = img.size

            # Check if resize is needed
            if original_width <= max_width and original_height <= max_height:
                # Image is already small enough
                if output_path and output_path != file_path:
                    img.save(output_path)
                    return output_path
                return file_path

            if maintain_aspect:
                # Calculate new size maintaining aspect ratio
                ratio = min(max_width / original_width, max_height / original_height)
                new_width = int(original_width * ratio)
                new_height = int(original_height * ratio)
            else:
                new_width = max_width
                new_height = max_height

            # Resize using high-quality resampling
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Determine output path
            if not output_path:
                output_path = file_path

            # Save with appropriate quality
            ext = get_file_extension(output_path)
            if ext in ["jpg", "jpeg"]:
                resized = ensure_rgb(resized)
                if resized.mode == "RGBA":
                    # Convert RGBA to RGB for JPEG
                    background = Image.new("RGB", resized.size, (255, 255, 255))
                    background.paste(resized, mask=resized.split()[3])
                    resized = background
                resized.save(output_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
            elif ext == "png":
                resized.save(output_path, "PNG", compress_level=PNG_COMPRESSION)
            elif ext == "webp":
                resized.save(output_path, "WEBP", quality=WEBP_QUALITY)
            else:
                resized.save(output_path)

            return output_path

    except ImportError:
        frappe.log_error(
            message="PIL/Pillow is not installed. Install with: pip install Pillow",
            title="Media Processor - PIL Missing"
        )
        return None
    except Exception as e:
        frappe.log_error(
            message=f"Failed to resize image {file_path}: {str(e)}",
            title="Media Processor - Resize Error"
        )
        return None


def convert_to_webp(
    file_path: str,
    output_path: str = None,
    quality: int = WEBP_QUALITY
) -> Optional[str]:
    """
    Convert image to WebP format for better compression.

    Args:
        file_path: Path to input image
        output_path: Path for WebP output (optional, auto-generated if not specified)
        quality: WebP quality (0-100, default 85)

    Returns:
        str: Path to WebP image or None on failure
    """
    try:
        from PIL import Image

        if not os.path.exists(file_path):
            frappe.log_error(
                message=f"File not found: {file_path}",
                title="Media Processor - WebP Conversion Failed"
            )
            return None

        # Check if file format can be converted
        ext = get_file_extension(file_path)
        if ext not in WEBP_CONVERTIBLE_FORMATS:
            return None

        if not output_path:
            output_path = get_output_path(file_path, "", "webp")

        with Image.open(file_path) as img:
            # Ensure proper color mode
            img = ensure_rgb(img)

            # Save as WebP
            img.save(output_path, "WEBP", quality=quality, method=6)

            return output_path

    except ImportError:
        frappe.log_error(
            message="PIL/Pillow is not installed. Install with: pip install Pillow",
            title="Media Processor - PIL Missing"
        )
        return None
    except Exception as e:
        frappe.log_error(
            message=f"Failed to convert to WebP {file_path}: {str(e)}",
            title="Media Processor - WebP Error"
        )
        return None


def generate_thumbnail(
    file_path: str,
    size: int = DEFAULT_THUMBNAIL_SIZE,
    output_path: str = None
) -> Optional[str]:
    """
    Generate square thumbnail for an image.

    Args:
        file_path: Path to input image
        size: Thumbnail size (width and height)
        output_path: Path for thumbnail output (optional, auto-generated if not specified)

    Returns:
        str: Path to thumbnail or None on failure
    """
    try:
        from PIL import Image

        if not os.path.exists(file_path):
            frappe.log_error(
                message=f"File not found: {file_path}",
                title="Media Processor - Thumbnail Failed"
            )
            return None

        if not output_path:
            output_path = get_output_path(file_path, f"_thumb_{size}")

        with Image.open(file_path) as img:
            # Create thumbnail (maintains aspect ratio, fits within box)
            img.thumbnail((size, size), Image.Resampling.LANCZOS)

            # Save thumbnail
            ext = get_file_extension(output_path)
            if ext in ["jpg", "jpeg"]:
                img = ensure_rgb(img)
                if img.mode == "RGBA":
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                img.save(output_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
            elif ext == "png":
                img.save(output_path, "PNG", compress_level=PNG_COMPRESSION)
            elif ext == "webp":
                img.save(output_path, "WEBP", quality=WEBP_QUALITY)
            else:
                img.save(output_path)

            return output_path

    except ImportError:
        frappe.log_error(
            message="PIL/Pillow is not installed. Install with: pip install Pillow",
            title="Media Processor - PIL Missing"
        )
        return None
    except Exception as e:
        frappe.log_error(
            message=f"Failed to generate thumbnail {file_path}: {str(e)}",
            title="Media Processor - Thumbnail Error"
        )
        return None


def optimize_image(
    file_path: str,
    output_path: str = None,
    max_size: Tuple[int, int] = MAX_OPTIMIZE_SIZE
) -> Optional[str]:
    """
    Optimize image for web delivery (resize if needed, compress).

    Args:
        file_path: Path to input image
        output_path: Path for optimized output (optional, auto-generated if not specified)
        max_size: Maximum dimensions (width, height)

    Returns:
        str: Path to optimized image or None on failure
    """
    try:
        from PIL import Image

        if not os.path.exists(file_path):
            frappe.log_error(
                message=f"File not found: {file_path}",
                title="Media Processor - Optimization Failed"
            )
            return None

        ext = get_file_extension(file_path)
        if ext not in OPTIMIZABLE_FORMATS:
            return None

        if not output_path:
            output_path = get_output_path(file_path, "_opt")

        with Image.open(file_path) as img:
            # Resize if larger than max_size
            if img.width > max_size[0] or img.height > max_size[1]:
                ratio = min(max_size[0] / img.width, max_size[1] / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            # Ensure proper color mode
            img = ensure_rgb(img)

            # Save optimized version
            if ext in ["jpg", "jpeg"]:
                if img.mode == "RGBA":
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                img.save(output_path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
            elif ext == "png":
                img.save(output_path, "PNG", compress_level=PNG_COMPRESSION, optimize=True)
            elif ext == "webp":
                img.save(output_path, "WEBP", quality=WEBP_QUALITY, method=6)
            elif ext == "gif":
                img.save(output_path, "GIF", optimize=True)
            else:
                img.save(output_path)

            return output_path

    except ImportError:
        frappe.log_error(
            message="PIL/Pillow is not installed. Install with: pip install Pillow",
            title="Media Processor - PIL Missing"
        )
        return None
    except Exception as e:
        frappe.log_error(
            message=f"Failed to optimize image {file_path}: {str(e)}",
            title="Media Processor - Optimization Error"
        )
        return None


def extract_image_metadata(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Extract metadata from an image file.

    Args:
        file_path: Path to image file

    Returns:
        dict: Image metadata (width, height, format, color_mode) or None
    """
    try:
        from PIL import Image

        if not os.path.exists(file_path):
            return None

        with Image.open(file_path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "color_mode": img.mode
            }

    except ImportError:
        frappe.log_error(
            message="PIL/Pillow is not installed. Install with: pip install Pillow",
            title="Media Processor - PIL Missing"
        )
        return None
    except Exception as e:
        frappe.log_error(
            message=f"Failed to extract metadata {file_path}: {str(e)}",
            title="Media Processor - Metadata Error"
        )
        return None


# =============================================================================
# MAIN PROCESSING FUNCTIONS
# =============================================================================


def process_media_asset(media_asset: str) -> Dict[str, Any]:
    """
    Process a single media asset (resize, optimize, convert to WebP).

    This function is designed to be called via frappe.enqueue for background processing.

    Args:
        media_asset: Name of the Media Asset document to process

    Returns:
        dict: Processing result with status and details
    """
    result = {
        "success": False,
        "media_asset": media_asset,
        "message": "",
        "thumbnail_url": None,
        "optimized_url": None,
        "webp_url": None
    }

    try:
        # Load media asset document
        if not frappe.db.exists("Media Asset", media_asset):
            result["message"] = f"Media Asset {media_asset} not found"
            return result

        asset = frappe.get_doc("Media Asset", media_asset)

        # Only process images
        if asset.asset_type != "Image":
            result["message"] = f"Asset type {asset.asset_type} does not require image processing"
            asset.db_set("status", "Active")
            result["success"] = True
            return result

        # Get file path
        file_path = get_file_path(asset.file)
        if not file_path or not os.path.exists(file_path):
            result["message"] = f"File not found: {asset.file}"
            asset.db_set("status", "Failed")
            frappe.log_error(
                message=result["message"],
                title=f"Media Processor - File Not Found: {media_asset}"
            )
            return result

        # Extract metadata
        metadata = extract_image_metadata(file_path)
        if metadata:
            asset.db_set({
                "width": metadata["width"],
                "height": metadata["height"],
                "format": metadata["format"],
                "color_mode": metadata["color_mode"]
            })

        # Generate thumbnail
        thumb_path = generate_thumbnail(file_path, DEFAULT_THUMBNAIL_SIZE)
        if thumb_path:
            thumb_url = get_output_url(asset.file, f"_thumb_{DEFAULT_THUMBNAIL_SIZE}")
            asset.db_set("thumbnail_url", thumb_url)
            result["thumbnail_url"] = thumb_url

        # Optimize image
        opt_path = optimize_image(file_path)
        if opt_path:
            opt_url = get_output_url(asset.file, "_opt")
            asset.db_set("optimized_url", opt_url)
            result["optimized_url"] = opt_url

        # Convert to WebP
        ext = get_file_extension(file_path)
        if ext in WEBP_CONVERTIBLE_FORMATS:
            webp_path = convert_to_webp(file_path)
            if webp_path:
                webp_url = get_output_url(asset.file, "", "webp")
                asset.db_set("webp_url", webp_url)
                result["webp_url"] = webp_url

        # Mark as optimized and active
        asset.db_set({
            "is_optimized": 1,
            "processed_date": now_datetime(),
            "status": "Active"
        })

        result["success"] = True
        result["message"] = "Media asset processed successfully"

        frappe.db.commit()

    except Exception as e:
        result["message"] = str(e)
        frappe.log_error(
            message=f"Error processing media asset {media_asset}: {str(e)}",
            title=f"Media Processor Error: {media_asset}"
        )

        # Mark asset as failed
        try:
            frappe.db.set_value("Media Asset", media_asset, "status", "Failed")
            frappe.db.commit()
        except Exception:
            pass

    return result


def process_pending_media() -> Dict[str, Any]:
    """
    Scheduler job to process all pending media assets.

    This function is designed to be called by Frappe scheduler.
    It processes media assets with status "Processing" in batches.

    Returns:
        dict: Processing summary with counts and details
    """
    result = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "started_at": now_datetime()
    }

    try:
        # Get pending media assets
        pending_assets = frappe.get_all(
            "Media Asset",
            filters={
                "status": "Processing",
                "asset_type": "Image"
            },
            fields=["name", "asset_name", "tenant"],
            order_by="creation asc",
            limit_page_length=BATCH_SIZE
        )

        if not pending_assets:
            result["message"] = "No pending media assets to process"
            return result

        for asset_info in pending_assets:
            result["processed"] += 1

            try:
                # Process the asset
                process_result = process_media_asset(asset_info["name"])

                if process_result.get("success"):
                    result["succeeded"] += 1
                else:
                    result["failed"] += 1
                    result["errors"].append({
                        "asset": asset_info["name"],
                        "error": process_result.get("message", "Unknown error")
                    })

            except Exception as e:
                result["failed"] += 1
                result["errors"].append({
                    "asset": asset_info["name"],
                    "error": str(e)
                })
                frappe.log_error(
                    message=f"Error in batch processing {asset_info['name']}: {str(e)}",
                    title="Media Processor Batch Error"
                )

        result["completed_at"] = now_datetime()
        result["message"] = (
            f"Processed {result['processed']} assets: "
            f"{result['succeeded']} succeeded, {result['failed']} failed"
        )

    except Exception as e:
        result["error"] = str(e)
        frappe.log_error(
            message=f"Error in process_pending_media: {str(e)}",
            title="Media Processor Scheduler Error"
        )

    return result


# =============================================================================
# UTILITY FUNCTIONS FOR MANUAL PROCESSING
# =============================================================================


def reprocess_media_asset(media_asset: str, force: bool = False) -> Dict[str, Any]:
    """
    Re-process a media asset (useful for reprocessing failed assets).

    Args:
        media_asset: Name of the Media Asset document
        force: If True, process even if already optimized

    Returns:
        dict: Processing result
    """
    if not frappe.db.exists("Media Asset", media_asset):
        return {
            "success": False,
            "message": f"Media Asset {media_asset} not found"
        }

    asset = frappe.get_doc("Media Asset", media_asset)

    # Check if already processed
    if asset.is_optimized and not force:
        return {
            "success": False,
            "message": "Asset already optimized. Use force=True to reprocess."
        }

    # Reset status for processing
    asset.db_set("status", "Processing")
    frappe.db.commit()

    # Process the asset
    return process_media_asset(media_asset)


def process_assets_by_tenant(tenant: str, limit: int = 50) -> Dict[str, Any]:
    """
    Process all pending media assets for a specific tenant.

    Args:
        tenant: Tenant name
        limit: Maximum assets to process

    Returns:
        dict: Processing summary
    """
    result = {
        "tenant": tenant,
        "processed": 0,
        "succeeded": 0,
        "failed": 0
    }

    pending_assets = frappe.get_all(
        "Media Asset",
        filters={
            "tenant": tenant,
            "status": "Processing",
            "asset_type": "Image"
        },
        pluck="name",
        limit_page_length=limit
    )

    for asset_name in pending_assets:
        result["processed"] += 1
        process_result = process_media_asset(asset_name)
        if process_result.get("success"):
            result["succeeded"] += 1
        else:
            result["failed"] += 1

    return result


def get_processing_stats() -> Dict[str, Any]:
    """
    Get statistics about media processing status.

    Returns:
        dict: Processing statistics
    """
    stats = {
        "total": frappe.db.count("Media Asset"),
        "processing": frappe.db.count("Media Asset", {"status": "Processing"}),
        "active": frappe.db.count("Media Asset", {"status": "Active"}),
        "failed": frappe.db.count("Media Asset", {"status": "Failed"}),
        "optimized": frappe.db.count("Media Asset", {"is_optimized": 1}),
        "unoptimized_images": frappe.db.count(
            "Media Asset",
            {"asset_type": "Image", "is_optimized": 0, "status": ["!=", "Processing"]}
        )
    }

    # Get by type
    stats["by_type"] = {}
    for asset_type in ["Image", "Video", "Document", "Audio", "3D Model", "Other"]:
        stats["by_type"][asset_type.lower().replace(" ", "_")] = frappe.db.count(
            "Media Asset", {"asset_type": asset_type}
        )

    return stats


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def enqueue_media_processing(media_asset: str) -> Dict[str, Any]:
    """
    Enqueue a media asset for background processing.

    Args:
        media_asset: Name of the Media Asset document

    Returns:
        dict: Enqueue result
    """
    if not frappe.db.exists("Media Asset", media_asset):
        return {
            "success": False,
            "message": f"Media Asset {media_asset} not found"
        }

    # Update status to processing
    frappe.db.set_value("Media Asset", media_asset, "status", "Processing")

    # Enqueue background job
    frappe.enqueue(
        "tr_tradehub.tasks.media_processor.process_media_asset",
        media_asset=media_asset,
        queue="long",
        timeout=600
    )

    return {
        "success": True,
        "message": f"Media asset {media_asset} queued for processing"
    }


@frappe.whitelist()
def get_media_processing_status(media_asset: str) -> Dict[str, Any]:
    """
    Get processing status for a media asset.

    Args:
        media_asset: Name of the Media Asset document

    Returns:
        dict: Processing status and URLs
    """
    if not frappe.db.exists("Media Asset", media_asset):
        return {
            "found": False,
            "message": f"Media Asset {media_asset} not found"
        }

    asset = frappe.get_doc("Media Asset", media_asset)

    return {
        "found": True,
        "name": asset.name,
        "status": asset.status,
        "is_optimized": bool(asset.is_optimized),
        "processed_date": asset.processed_date,
        "thumbnail_url": asset.thumbnail_url,
        "optimized_url": asset.optimized_url,
        "webp_url": asset.webp_url,
        "width": asset.width,
        "height": asset.height,
        "format": asset.format
    }


@frappe.whitelist()
def bulk_enqueue_processing(tenant: str = None, limit: int = 50) -> Dict[str, Any]:
    """
    Bulk enqueue unprocessed media assets for processing.

    Args:
        tenant: Optional tenant filter
        limit: Maximum number of assets to enqueue

    Returns:
        dict: Enqueue summary
    """
    filters = {
        "status": ["in", ["Processing", "Active"]],
        "is_optimized": 0,
        "asset_type": "Image"
    }

    if tenant:
        filters["tenant"] = tenant

    # Get unprocessed images
    assets = frappe.get_all(
        "Media Asset",
        filters=filters,
        pluck="name",
        limit_page_length=cint(limit)
    )

    enqueued = 0
    for asset_name in assets:
        frappe.enqueue(
            "tr_tradehub.tasks.media_processor.process_media_asset",
            media_asset=asset_name,
            queue="long",
            timeout=600
        )
        enqueued += 1

    return {
        "success": True,
        "enqueued": enqueued,
        "message": f"Enqueued {enqueued} media assets for processing"
    }
