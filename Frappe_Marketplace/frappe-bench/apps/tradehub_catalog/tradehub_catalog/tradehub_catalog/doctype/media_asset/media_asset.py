# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, get_files_path
import os
import hashlib
import json
import mimetypes


# Supported MIME types by asset type
SUPPORTED_IMAGE_TYPES = [
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/svg+xml", "image/bmp", "image/tiff"
]
SUPPORTED_VIDEO_TYPES = [
    "video/mp4", "video/webm", "video/ogg", "video/quicktime",
    "video/x-msvideo", "video/x-ms-wmv"
]
SUPPORTED_DOCUMENT_TYPES = [
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
]

# File size limits (in bytes)
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_DOCUMENT_SIZE = 20 * 1024 * 1024  # 20 MB


class MediaAsset(Document):
    """
    Media Asset DocType for managing images, videos, and other media files.

    Media assets provide centralized storage and management for:
    - Product images for listings and variants
    - Storefront logos and banners
    - Seller profile images
    - Review photos
    - Category images
    - Promotional banners

    Features:
    - Automatic thumbnail generation
    - Image optimization
    - CDN integration
    - Content moderation
    - Deduplication via checksum
    - EXIF metadata extraction
    """

    def before_insert(self):
        """Set default values before inserting a new media asset."""
        # Generate unique asset code
        if not self.asset_code:
            self.asset_code = self.generate_asset_code()

        # Set uploaded by
        if not self.uploaded_by:
            self.uploaded_by = frappe.session.user

        # Set tenant if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Initialize JSON fields
        if not self.dominant_colors:
            self.dominant_colors = "[]"
        if not self.exif_data:
            self.exif_data = "{}"

        # Set status to pending for processing
        self.status = "Pending"

    def validate(self):
        """Validate media asset data before saving."""
        self.validate_file_url()
        self.validate_asset_type()
        self.validate_file_size()
        self.validate_mime_type()
        self.validate_entity_link()
        self.extract_file_info()
        self.validate_primary_uniqueness()
        self.validate_moderation_notes()

    def before_save(self):
        """Actions before saving the media asset."""
        # Set title from filename if not provided
        if not self.title and self.original_filename:
            self.title = os.path.splitext(self.original_filename)[0][:255]

    def after_insert(self):
        """Actions after inserting a new media asset."""
        # Queue processing job for thumbnails and optimization
        if self.status == "Pending":
            self.queue_processing()

    def on_update(self):
        """Actions to perform after media asset is updated."""
        self.clear_asset_cache()

    def on_trash(self):
        """Clean up files when media asset is deleted."""
        self.check_usage_before_delete()

    # Helper Methods
    def generate_asset_code(self):
        """Generate a unique asset code."""
        return f"MDA-{frappe.generate_hash(length=8).upper()}"

    def set_tenant_from_context(self):
        """Set tenant from current context or entity."""
        # Try to get tenant from entity
        if self.entity_type and self.entity_name:
            tenant = self.get_tenant_from_entity()
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

    def get_tenant_from_entity(self):
        """Get tenant from linked entity if it has a tenant field."""
        if not self.entity_type or not self.entity_name:
            return None

        tenant_doctypes = [
            "Listing", "Listing Variant", "Storefront",
            "Seller Profile", "Review"
        ]

        if self.entity_type in tenant_doctypes:
            if frappe.db.exists(self.entity_type, self.entity_name):
                return frappe.db.get_value(
                    self.entity_type, self.entity_name, "tenant"
                )
        return None

    # Validation Methods
    def validate_file_url(self):
        """Validate that file URL is provided and accessible."""
        if not self.file_url:
            frappe.throw(_("File URL is required"))

    def validate_asset_type(self):
        """Validate asset type is set."""
        if not self.asset_type:
            frappe.throw(_("Asset Type is required"))

        valid_types = ["Image", "Video", "Document", "360 View", "AR Model"]
        if self.asset_type not in valid_types:
            frappe.throw(_("Invalid Asset Type: {0}").format(self.asset_type))

    def validate_file_size(self):
        """Validate file size is within limits."""
        if not self.file_size:
            return

        size = cint(self.file_size)
        max_size = MAX_IMAGE_SIZE

        if self.asset_type == "Video":
            max_size = MAX_VIDEO_SIZE
        elif self.asset_type == "Document":
            max_size = MAX_DOCUMENT_SIZE

        if size > max_size:
            max_mb = max_size / (1024 * 1024)
            frappe.throw(
                _("File size exceeds maximum limit of {0} MB for {1}").format(
                    max_mb, self.asset_type
                )
            )

    def validate_mime_type(self):
        """Validate MIME type matches asset type."""
        if not self.mime_type:
            return

        valid_mimes = []
        if self.asset_type == "Image" or self.asset_type == "360 View":
            valid_mimes = SUPPORTED_IMAGE_TYPES
        elif self.asset_type == "Video":
            valid_mimes = SUPPORTED_VIDEO_TYPES
        elif self.asset_type == "Document":
            valid_mimes = SUPPORTED_DOCUMENT_TYPES
        elif self.asset_type == "AR Model":
            valid_mimes = ["model/gltf+json", "model/gltf-binary", "application/octet-stream"]

        if valid_mimes and self.mime_type not in valid_mimes:
            frappe.throw(
                _("Invalid file type {0} for asset type {1}. Supported types: {2}").format(
                    self.mime_type, self.asset_type, ", ".join(valid_mimes)
                )
            )

    def validate_entity_link(self):
        """Validate linked entity exists."""
        if self.entity_type and self.entity_name:
            if not frappe.db.exists(self.entity_type, self.entity_name):
                frappe.throw(
                    _("{0} {1} does not exist").format(
                        self.entity_type, self.entity_name
                    )
                )

    def validate_primary_uniqueness(self):
        """Ensure only one primary asset per entity."""
        if self.is_primary and self.entity_type and self.entity_name:
            existing = frappe.db.exists(
                "Media Asset",
                {
                    "entity_type": self.entity_type,
                    "entity_name": self.entity_name,
                    "is_primary": 1,
                    "name": ["!=", self.name or ""]
                }
            )
            if existing:
                # Unset other primary assets
                frappe.db.set_value(
                    "Media Asset",
                    {"entity_type": self.entity_type, "entity_name": self.entity_name, "is_primary": 1},
                    "is_primary",
                    0
                )

    def validate_moderation_notes(self):
        """Validate moderation notes for rejected assets."""
        if self.moderation_status == "Rejected" and not self.moderation_notes:
            frappe.throw(_("Moderation notes are required when rejecting an asset"))

    def extract_file_info(self):
        """Extract file information from URL."""
        if not self.file_url:
            return

        # Extract filename and extension
        file_path = self.file_url
        if file_path.startswith("/"):
            file_path = file_path.lstrip("/")

        filename = os.path.basename(file_path)

        if not self.original_filename:
            self.original_filename = filename

        # Extract extension
        _, ext = os.path.splitext(filename)
        if ext and not self.file_extension:
            self.file_extension = ext.lower().lstrip(".")

        # Detect MIME type
        if not self.mime_type:
            mime_type, _ = mimetypes.guess_type(filename)
            if mime_type:
                self.mime_type = mime_type

        # Calculate checksum for local files
        if not self.checksum:
            self.calculate_checksum()

        # Get file size
        if not self.file_size:
            self.get_file_size()

    def calculate_checksum(self):
        """Calculate MD5 checksum of the file."""
        try:
            file_path = self.get_full_file_path()
            if file_path and os.path.exists(file_path):
                hash_md5 = hashlib.md5()
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_md5.update(chunk)
                self.checksum = hash_md5.hexdigest()
        except Exception:
            pass

    def get_file_size(self):
        """Get file size in bytes."""
        try:
            file_path = self.get_full_file_path()
            if file_path and os.path.exists(file_path):
                self.file_size = os.path.getsize(file_path)
        except Exception:
            pass

    def get_full_file_path(self):
        """Get the full filesystem path of the file."""
        if not self.file_url:
            return None

        if self.file_url.startswith("/files/"):
            return os.path.join(get_files_path(), self.file_url.replace("/files/", ""))
        elif self.file_url.startswith("/private/files/"):
            return os.path.join(
                get_files_path(is_private=True),
                self.file_url.replace("/private/files/", "")
            )
        return None

    def check_usage_before_delete(self):
        """Check if asset is in use before allowing deletion."""
        if self.usage_count and cint(self.usage_count) > 0:
            frappe.throw(
                _("Cannot delete media asset that is in use ({0} references)").format(
                    self.usage_count
                )
            )

    def clear_asset_cache(self):
        """Clear cached asset data."""
        cache_key = f"media_asset:{self.name}"
        frappe.cache().delete_value(cache_key)

        if self.asset_code:
            code_cache_key = f"media_asset_by_code:{self.asset_code}"
            frappe.cache().delete_value(code_cache_key)

    # Processing Methods
    def queue_processing(self):
        """Queue background processing for thumbnails and optimization."""
        frappe.enqueue(
            method="tr_tradehub.doctype.media_asset.media_asset.process_media_asset",
            queue="default",
            timeout=600,
            asset_name=self.name
        )

    def process(self):
        """Process the media asset (extract metadata, generate thumbnails)."""
        try:
            self.db_set("status", "Processing")

            # Extract image metadata
            if self.asset_type in ["Image", "360 View"]:
                self.extract_image_metadata()

            # Extract video metadata
            elif self.asset_type == "Video":
                self.extract_video_metadata()

            # Generate thumbnails
            self.generate_thumbnails()

            # Run optimization if enabled
            if frappe.db.get_single_value("TR TradeHub Settings", "auto_optimize_images"):
                self.optimize()

            # Update status
            self.db_set("status", "Active")

        except Exception as e:
            self.db_set("status", "Failed")
            frappe.log_error(
                f"Failed to process media asset {self.name}: {str(e)}",
                "Media Asset Processing Error"
            )

    def extract_image_metadata(self):
        """Extract metadata from image files."""
        try:
            file_path = self.get_full_file_path()
            if not file_path or not os.path.exists(file_path):
                return

            # Try to use PIL/Pillow for image analysis
            try:
                from PIL import Image

                with Image.open(file_path) as img:
                    # Basic dimensions
                    width, height = img.size
                    self.db_set("width", width)
                    self.db_set("height", height)

                    # Aspect ratio
                    if height > 0:
                        aspect = round(width / height, 4)
                        self.db_set("aspect_ratio", aspect)

                    # Orientation
                    if width > height:
                        orientation = "Landscape"
                    elif width < height:
                        orientation = "Portrait"
                    else:
                        orientation = "Square"
                    self.db_set("orientation", orientation)

                    # Color mode
                    if img.mode == "RGB":
                        self.db_set("color_space", "RGB")
                    elif img.mode == "RGBA":
                        self.db_set("color_space", "RGB")
                        self.db_set("has_transparency", 1)
                    elif img.mode == "L":
                        self.db_set("color_space", "Grayscale")
                    elif img.mode == "CMYK":
                        self.db_set("color_space", "CMYK")

                    # EXIF data
                    if hasattr(img, "_getexif") and img._getexif():
                        exif = img._getexif()
                        if exif:
                            # Convert to serializable format
                            exif_dict = {}
                            for tag_id, value in exif.items():
                                try:
                                    # Only include string/number values
                                    if isinstance(value, (str, int, float)):
                                        exif_dict[str(tag_id)] = value
                                except Exception:
                                    pass
                            if exif_dict:
                                self.db_set("exif_data", json.dumps(exif_dict))

            except ImportError:
                frappe.log_error(
                    "PIL/Pillow not installed - image metadata extraction skipped",
                    "Media Asset Warning"
                )

        except Exception as e:
            frappe.log_error(
                f"Error extracting image metadata for {self.name}: {str(e)}",
                "Media Asset Metadata Error"
            )

    def extract_video_metadata(self):
        """Extract metadata from video files."""
        try:
            file_path = self.get_full_file_path()
            if not file_path or not os.path.exists(file_path):
                return

            # Try to use ffprobe for video analysis
            try:
                import subprocess

                result = subprocess.run(
                    [
                        "ffprobe",
                        "-v", "quiet",
                        "-print_format", "json",
                        "-show_format",
                        "-show_streams",
                        file_path
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    data = json.loads(result.stdout)

                    # Duration
                    if "format" in data and "duration" in data["format"]:
                        self.db_set("duration", flt(data["format"]["duration"]))

                    # Stream info
                    for stream in data.get("streams", []):
                        if stream.get("codec_type") == "video":
                            self.db_set("video_codec", stream.get("codec_name"))
                            self.db_set("width", cint(stream.get("width")))
                            self.db_set("height", cint(stream.get("height")))

                            # Frame rate
                            fps = stream.get("r_frame_rate", "0/1")
                            if "/" in fps:
                                num, den = fps.split("/")
                                if cint(den) > 0:
                                    self.db_set("frame_rate", round(cint(num) / cint(den), 2))

                            # Resolution label
                            height = cint(stream.get("height", 0))
                            if height >= 2160:
                                self.db_set("resolution", "4K")
                            elif height >= 1080:
                                self.db_set("resolution", "1080p")
                            elif height >= 720:
                                self.db_set("resolution", "720p")
                            elif height >= 480:
                                self.db_set("resolution", "480p")
                            else:
                                self.db_set("resolution", f"{height}p")

                        elif stream.get("codec_type") == "audio":
                            self.db_set("audio_codec", stream.get("codec_name"))

                    # Bitrate
                    if "format" in data and "bit_rate" in data["format"]:
                        self.db_set("bitrate", cint(data["format"]["bit_rate"]) // 1000)

            except FileNotFoundError:
                frappe.log_error(
                    "ffprobe not installed - video metadata extraction skipped",
                    "Media Asset Warning"
                )
            except subprocess.TimeoutExpired:
                frappe.log_error(
                    f"Video metadata extraction timed out for {self.name}",
                    "Media Asset Warning"
                )

        except Exception as e:
            frappe.log_error(
                f"Error extracting video metadata for {self.name}: {str(e)}",
                "Media Asset Metadata Error"
            )

    def generate_thumbnails(self):
        """Generate thumbnail versions of the asset."""
        try:
            self.db_set("thumbnail_status", "Processing")

            file_path = self.get_full_file_path()
            if not file_path or not os.path.exists(file_path):
                self.db_set("thumbnail_status", "Failed")
                return

            if self.asset_type not in ["Image", "360 View"]:
                # For videos, generate thumbnail from first frame
                if self.asset_type == "Video":
                    self.generate_video_thumbnail()
                else:
                    self.db_set("thumbnail_status", "Skipped")
                return

            try:
                from PIL import Image

                # Thumbnail sizes
                sizes = {
                    "small": (100, 100),
                    "medium": (300, 300),
                    "large": (600, 600)
                }

                files_path = get_files_path()
                base_name = os.path.splitext(os.path.basename(self.file_url))[0]

                with Image.open(file_path) as img:
                    # Convert to RGB if needed
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")

                    for size_name, dimensions in sizes.items():
                        thumb = img.copy()
                        thumb.thumbnail(dimensions, Image.Resampling.LANCZOS)

                        thumb_filename = f"{base_name}_thumb_{size_name}.jpg"
                        thumb_path = os.path.join(files_path, thumb_filename)
                        thumb.save(thumb_path, "JPEG", quality=85)

                        thumb_url = f"/files/{thumb_filename}"

                        if size_name == "small":
                            self.db_set("thumbnail_small_url", thumb_url)
                        elif size_name == "medium":
                            self.db_set("thumbnail_medium_url", thumb_url)
                            # Use medium as default thumbnail
                            if not self.thumbnail_url:
                                self.db_set("thumbnail_url", thumb_url)
                        elif size_name == "large":
                            self.db_set("thumbnail_large_url", thumb_url)

                self.db_set("thumbnail_status", "Generated")
                self.db_set("thumbnails_generated_at", now_datetime())

            except ImportError:
                self.db_set("thumbnail_status", "Failed")
                frappe.log_error(
                    "PIL/Pillow not installed - thumbnail generation skipped",
                    "Media Asset Warning"
                )

        except Exception as e:
            self.db_set("thumbnail_status", "Failed")
            frappe.log_error(
                f"Error generating thumbnails for {self.name}: {str(e)}",
                "Media Asset Thumbnail Error"
            )

    def generate_video_thumbnail(self):
        """Generate thumbnail from video file."""
        try:
            import subprocess

            file_path = self.get_full_file_path()
            if not file_path:
                return

            files_path = get_files_path()
            base_name = os.path.splitext(os.path.basename(self.file_url))[0]
            thumb_filename = f"{base_name}_thumb.jpg"
            thumb_path = os.path.join(files_path, thumb_filename)

            # Extract frame at 1 second
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i", file_path,
                    "-ss", "00:00:01",
                    "-vframes", "1",
                    "-q:v", "2",
                    "-y",
                    thumb_path
                ],
                capture_output=True,
                timeout=30
            )

            if result.returncode == 0 and os.path.exists(thumb_path):
                self.db_set("thumbnail_url", f"/files/{thumb_filename}")
                self.db_set("thumbnail_status", "Generated")
                self.db_set("thumbnails_generated_at", now_datetime())
            else:
                self.db_set("thumbnail_status", "Failed")

        except FileNotFoundError:
            self.db_set("thumbnail_status", "Failed")
            frappe.log_error(
                "ffmpeg not installed - video thumbnail generation skipped",
                "Media Asset Warning"
            )
        except Exception as e:
            self.db_set("thumbnail_status", "Failed")
            frappe.log_error(
                f"Error generating video thumbnail for {self.name}: {str(e)}",
                "Media Asset Thumbnail Error"
            )

    def optimize(self):
        """Optimize the media asset for web delivery."""
        try:
            self.db_set("optimization_status", "Processing")

            file_path = self.get_full_file_path()
            if not file_path or not os.path.exists(file_path):
                self.db_set("optimization_status", "Failed")
                self.db_set("optimization_error", "File not found")
                return

            if self.asset_type not in ["Image", "360 View"]:
                self.db_set("optimization_status", "Skipped")
                return

            try:
                from PIL import Image

                files_path = get_files_path()
                base_name = os.path.splitext(os.path.basename(self.file_url))[0]
                opt_filename = f"{base_name}_optimized.webp"
                opt_path = os.path.join(files_path, opt_filename)

                with Image.open(file_path) as img:
                    # Convert to RGB if needed
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")

                    # Save as WebP with quality optimization
                    img.save(opt_path, "WEBP", quality=85, method=6)

                if os.path.exists(opt_path):
                    self.db_set("optimized_url", f"/files/{opt_filename}")
                    self.db_set("optimized_file_size", os.path.getsize(opt_path))
                    self.db_set("is_optimized", 1)
                    self.db_set("optimization_status", "Completed")
                    self.db_set("optimized_at", now_datetime())
                else:
                    self.db_set("optimization_status", "Failed")
                    self.db_set("optimization_error", "Output file not created")

            except ImportError:
                self.db_set("optimization_status", "Failed")
                self.db_set("optimization_error", "PIL/Pillow not installed")

        except Exception as e:
            self.db_set("optimization_status", "Failed")
            self.db_set("optimization_error", str(e)[:500])
            frappe.log_error(
                f"Error optimizing media asset {self.name}: {str(e)}",
                "Media Asset Optimization Error"
            )

    # CDN Methods
    def upload_to_cdn(self):
        """Upload asset to CDN provider."""
        if not self.cdn_enabled:
            return

        try:
            self.db_set("cdn_status", "Uploading")

            # This would integrate with actual CDN providers
            # For now, just mark as active
            cdn_url = self.generate_cdn_url()
            if cdn_url:
                self.db_set("cdn_url", cdn_url)
                self.db_set("cdn_status", "Active")
                self.db_set("cdn_uploaded_at", now_datetime())
                self.db_set("cdn_cache_key", frappe.generate_hash(length=16))
            else:
                self.db_set("cdn_status", "Failed")

        except Exception as e:
            self.db_set("cdn_status", "Failed")
            frappe.log_error(
                f"CDN upload failed for {self.name}: {str(e)}",
                "Media Asset CDN Error"
            )

    def generate_cdn_url(self):
        """Generate CDN URL based on provider settings."""
        if not self.cdn_provider:
            return None

        # Placeholder for CDN URL generation
        # Would integrate with actual CDN APIs
        return f"https://cdn.example.com/{self.asset_code}/{self.original_filename}"

    def purge_cdn_cache(self):
        """Purge CDN cache for this asset."""
        if not self.cdn_enabled or self.cdn_status != "Active":
            return

        try:
            # Placeholder for CDN cache purge
            self.db_set("cdn_status", "Purged")
            self.db_set("cdn_cache_key", frappe.generate_hash(length=16))
        except Exception as e:
            frappe.log_error(
                f"CDN cache purge failed for {self.name}: {str(e)}",
                "Media Asset CDN Error"
            )

    # Moderation Methods
    def approve(self, moderator=None):
        """Approve the media asset after moderation."""
        self.db_set("moderation_status", "Approved")
        self.db_set("moderated_by", moderator or frappe.session.user)
        self.db_set("moderated_at", now_datetime())

    def reject(self, reason, moderator=None):
        """Reject the media asset with reason."""
        if not reason:
            frappe.throw(_("Reason is required for rejection"))

        self.db_set("moderation_status", "Rejected")
        self.db_set("moderation_notes", reason)
        self.db_set("moderated_by", moderator or frappe.session.user)
        self.db_set("moderated_at", now_datetime())
        self.db_set("status", "Archived")

    def flag(self, reason=None):
        """Flag the media asset for review."""
        self.db_set("moderation_status", "Flagged")
        if reason:
            notes = f"Flagged: {reason}\n\n{self.moderation_notes or ''}"
            self.db_set("moderation_notes", notes)

    # Statistics Methods
    def increment_usage(self):
        """Increment usage count."""
        frappe.db.set_value(
            "Media Asset", self.name, "usage_count",
            cint(self.usage_count) + 1,
            update_modified=False
        )

    def decrement_usage(self):
        """Decrement usage count."""
        frappe.db.set_value(
            "Media Asset", self.name, "usage_count",
            max(0, cint(self.usage_count) - 1),
            update_modified=False
        )

    def record_access(self):
        """Record last access time."""
        frappe.db.set_value(
            "Media Asset", self.name, "last_accessed_at",
            now_datetime(),
            update_modified=False
        )

    # URL Methods
    def get_url(self, size="original"):
        """Get URL for the asset at specified size."""
        if size == "original":
            if self.cdn_enabled and self.cdn_url:
                return self.cdn_url
            if self.is_optimized and self.optimized_url:
                return self.optimized_url
            return self.file_url

        if size == "thumbnail":
            return self.thumbnail_url or self.file_url
        elif size == "small":
            return self.thumbnail_small_url or self.thumbnail_url or self.file_url
        elif size == "medium":
            return self.thumbnail_medium_url or self.thumbnail_url or self.file_url
        elif size == "large":
            return self.thumbnail_large_url or self.thumbnail_url or self.file_url
        elif size == "optimized":
            return self.optimized_url or self.file_url

        return self.file_url

    def get_formatted_file_size(self):
        """Get human-readable file size."""
        size = cint(self.file_size)
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    def get_dimensions(self):
        """Get formatted dimensions string."""
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return None


# Background processing function
def process_media_asset(asset_name):
    """Process media asset in background."""
    try:
        asset = frappe.get_doc("Media Asset", asset_name)
        asset.process()
    except Exception as e:
        frappe.log_error(
            f"Background processing failed for {asset_name}: {str(e)}",
            "Media Asset Background Error"
        )


# API Endpoints
@frappe.whitelist()
def get_media_asset(asset_name=None, asset_code=None):
    """
    Get media asset details.

    Args:
        asset_name: Name of the asset
        asset_code: Unique asset code

    Returns:
        dict: Asset details
    """
    if not asset_name and not asset_code:
        frappe.throw(_("Either asset_name or asset_code is required"))

    if asset_code and not asset_name:
        asset_name = frappe.db.get_value(
            "Media Asset", {"asset_code": asset_code}, "name"
        )

    if not asset_name:
        return {"error": _("Media asset not found")}

    asset = frappe.get_doc("Media Asset", asset_name)

    # Record access
    asset.record_access()

    return {
        "name": asset.name,
        "asset_code": asset.asset_code,
        "title": asset.title,
        "asset_type": asset.asset_type,
        "status": asset.status,
        "file_url": asset.file_url,
        "original_filename": asset.original_filename,
        "file_size": asset.file_size,
        "formatted_size": asset.get_formatted_file_size(),
        "mime_type": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
        "dimensions": asset.get_dimensions(),
        "duration": asset.duration,
        "thumbnail_url": asset.thumbnail_url,
        "thumbnail_small_url": asset.thumbnail_small_url,
        "thumbnail_medium_url": asset.thumbnail_medium_url,
        "thumbnail_large_url": asset.thumbnail_large_url,
        "optimized_url": asset.optimized_url,
        "cdn_url": asset.cdn_url,
        "entity_type": asset.entity_type,
        "entity_name": asset.entity_name,
        "is_primary": asset.is_primary,
        "position": asset.position,
        "alt_text": asset.alt_text,
        "caption": asset.caption,
        "tags": asset.tags,
        "moderation_status": asset.moderation_status
    }


@frappe.whitelist()
def get_entity_assets(entity_type, entity_name, asset_type=None, status="Active"):
    """
    Get all media assets for a specific entity.

    Args:
        entity_type: Type of entity (Listing, Storefront, etc.)
        entity_name: Name of the entity
        asset_type: Filter by asset type (optional)
        status: Filter by status (default: Active)

    Returns:
        list: List of media assets
    """
    filters = {
        "entity_type": entity_type,
        "entity_name": entity_name,
        "status": status
    }

    if asset_type:
        filters["asset_type"] = asset_type

    assets = frappe.get_all(
        "Media Asset",
        filters=filters,
        fields=[
            "name", "asset_code", "title", "asset_type", "file_url",
            "thumbnail_url", "width", "height", "position", "is_primary",
            "alt_text", "caption"
        ],
        order_by="is_primary DESC, position ASC, modified DESC"
    )

    return assets


@frappe.whitelist()
def upload_media_asset(file_url, entity_type=None, entity_name=None, **kwargs):
    """
    Upload a new media asset.

    Args:
        file_url: URL of the uploaded file
        entity_type: Type of entity to link to (optional)
        entity_name: Name of entity to link to (optional)
        **kwargs: Additional asset fields

    Returns:
        dict: Created asset details
    """
    # Determine asset type from file
    mime_type, _ = mimetypes.guess_type(file_url)
    asset_type = "Image"

    if mime_type:
        if mime_type.startswith("video/"):
            asset_type = "Video"
        elif mime_type.startswith("application/"):
            asset_type = "Document"

    asset = frappe.get_doc({
        "doctype": "Media Asset",
        "file_url": file_url,
        "asset_type": kwargs.get("asset_type", asset_type),
        "entity_type": entity_type,
        "entity_name": entity_name,
        "title": kwargs.get("title"),
        "alt_text": kwargs.get("alt_text"),
        "caption": kwargs.get("caption"),
        "position": kwargs.get("position", 0),
        "is_primary": kwargs.get("is_primary", 0),
        "tags": kwargs.get("tags"),
        "folder": kwargs.get("folder")
    })
    asset.insert()

    return {
        "status": "success",
        "asset_name": asset.name,
        "asset_code": asset.asset_code,
        "message": _("Media asset uploaded successfully")
    }


@frappe.whitelist()
def delete_media_asset(asset_name):
    """
    Delete a media asset.

    Args:
        asset_name: Name of the asset to delete

    Returns:
        dict: Deletion result
    """
    if not frappe.db.exists("Media Asset", asset_name):
        return {"error": _("Media asset not found")}

    asset = frappe.get_doc("Media Asset", asset_name)

    # Check usage
    if cint(asset.usage_count) > 0:
        return {"error": _("Cannot delete asset that is in use")}

    try:
        asset.delete()
        return {
            "status": "success",
            "message": _("Media asset deleted successfully")
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def reorder_assets(entity_type, entity_name, asset_order):
    """
    Reorder assets for an entity.

    Args:
        entity_type: Type of entity
        entity_name: Name of entity
        asset_order: List of asset names in new order

    Returns:
        dict: Result
    """
    try:
        order_list = json.loads(asset_order) if isinstance(asset_order, str) else asset_order

        for position, asset_name in enumerate(order_list):
            frappe.db.set_value(
                "Media Asset",
                asset_name,
                "position",
                position,
                update_modified=False
            )

        return {
            "status": "success",
            "message": _("Assets reordered successfully")
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def set_primary_asset(asset_name):
    """
    Set an asset as the primary asset for its entity.

    Args:
        asset_name: Name of the asset

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Media Asset", asset_name):
        return {"error": _("Media asset not found")}

    asset = frappe.get_doc("Media Asset", asset_name)

    if not asset.entity_type or not asset.entity_name:
        return {"error": _("Asset is not linked to an entity")}

    # Unset other primary assets
    frappe.db.sql("""
        UPDATE `tabMedia Asset`
        SET is_primary = 0
        WHERE entity_type = %s AND entity_name = %s AND name != %s
    """, (asset.entity_type, asset.entity_name, asset_name))

    # Set this as primary
    asset.db_set("is_primary", 1)

    return {
        "status": "success",
        "message": _("Primary asset set successfully")
    }


@frappe.whitelist()
def moderate_asset(asset_name, action, reason=None):
    """
    Moderate a media asset.

    Args:
        asset_name: Name of the asset
        action: Action (approve, reject, flag)
        reason: Reason for rejection/flagging

    Returns:
        dict: Result
    """
    if not frappe.has_permission("Media Asset", "write"):
        frappe.throw(_("Not permitted to moderate assets"))

    if not frappe.db.exists("Media Asset", asset_name):
        return {"error": _("Media asset not found")}

    asset = frappe.get_doc("Media Asset", asset_name)

    if action == "approve":
        asset.approve()
    elif action == "reject":
        if not reason:
            return {"error": _("Reason is required for rejection")}
        asset.reject(reason)
    elif action == "flag":
        asset.flag(reason)
    else:
        return {"error": _("Invalid action")}

    return {
        "status": "success",
        "moderation_status": asset.moderation_status,
        "message": _("Asset moderation action completed")
    }


@frappe.whitelist()
def get_media_statistics(tenant=None, entity_type=None):
    """
    Get media asset statistics.

    Args:
        tenant: Filter by tenant (optional)
        entity_type: Filter by entity type (optional)

    Returns:
        dict: Statistics
    """
    filters = {}
    if tenant:
        filters["tenant"] = tenant
    if entity_type:
        filters["entity_type"] = entity_type

    total = frappe.db.count("Media Asset", filters)

    # Use parameterized queries to prevent SQL injection
    params = {}
    if tenant:
        where_clause = "tenant = %(tenant)s"
        params["tenant"] = tenant
    else:
        where_clause = "1=1"

    # Count by asset type
    type_counts = frappe.db.sql("""
        SELECT asset_type, COUNT(*) as count
        FROM `tabMedia Asset`
        WHERE {where_clause}
        GROUP BY asset_type
    """.format(where_clause=where_clause), params, as_dict=True)

    # Count by status
    status_counts = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabMedia Asset`
        WHERE {where_clause}
        GROUP BY status
    """.format(where_clause=where_clause), params, as_dict=True)

    # Total file size
    total_size = frappe.db.sql("""
        SELECT SUM(file_size) as total
        FROM `tabMedia Asset`
        WHERE {where_clause}
    """.format(where_clause=where_clause), params, as_dict=True)

    return {
        "total": total,
        "by_type": {t.asset_type: t.count for t in type_counts},
        "by_status": {s.status: s.count for s in status_counts},
        "total_size_bytes": cint(total_size[0].total if total_size else 0),
        "total_size_formatted": _format_bytes(cint(total_size[0].total if total_size else 0))
    }


def _format_bytes(size):
    """Format bytes to human readable string."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


@frappe.whitelist()
def find_duplicate(checksum):
    """
    Find existing asset with same checksum.

    Args:
        checksum: MD5 checksum to search for

    Returns:
        dict: Duplicate asset details or None
    """
    if not checksum:
        return None

    existing = frappe.db.get_value(
        "Media Asset",
        {"checksum": checksum, "status": "Active"},
        ["name", "asset_code", "file_url", "title"],
        as_dict=True
    )

    return existing


@frappe.whitelist()
def regenerate_thumbnails(asset_name):
    """
    Regenerate thumbnails for an asset.

    Args:
        asset_name: Name of the asset

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Media Asset", asset_name):
        return {"error": _("Media asset not found")}

    asset = frappe.get_doc("Media Asset", asset_name)
    asset.generate_thumbnails()

    return {
        "status": "success",
        "thumbnail_status": asset.thumbnail_status,
        "message": _("Thumbnails regeneration initiated")
    }
