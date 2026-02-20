# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Special Field Handlers Module.

This module provides handlers for special Frappe field types including
Check (boolean), Select, Color, Attach, Geolocation, Signature, JSON, and Barcode.

These handlers handle fields that require specific formats or validation rules
different from standard text or numeric fields.

Handlers in this module:
- CheckHandler: Boolean/checkbox field generation
- SelectHandler: Select/dropdown field generation
- ColorHandler: Color hex value generation
- AttachHandler: File attachment URL generation
- AttachImageHandler: Image attachment URL generation
- GeolocationHandler: Geographic coordinates generation
- SignatureHandler: Signature data generation
- JSONHandler: JSON object generation
- BarcodeHandler: Barcode/QR code value generation

Usage:
    from mock_data_engine.handlers.special_handlers import (
        CheckHandler,
        SelectHandler,
        ColorHandler,
        AttachHandler,
        GeolocationHandler,
        SignatureHandler,
        JSONHandler,
        BarcodeHandler,
    )

    # Using CheckHandler
    handler = CheckHandler(locale='tr_TR', seed=42)
    value = handler.generate(context)  # Returns 0 or 1

    # Using SelectHandler
    select_handler = SelectHandler(locale='tr_TR', seed=42)
    value = select_handler.generate(context)  # Returns one of the options
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Union, TYPE_CHECKING

from mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    GenerationError,
)

if TYPE_CHECKING:
    from mock_data_engine.core.config_resolver import ResolvedConfig


class CheckHandler(BaseFieldHandler):
    """
    Handler for Check (boolean/checkbox) field generation.

    Generates boolean values represented as integers (0 or 1) as per
    Frappe's Check field convention.

    Check fields in Frappe:
    - Store values as 0 (unchecked) or 1 (checked)
    - Are rendered as checkboxes in the UI

    Supported patterns:
        - FieldPattern.STATUS (may influence probability)

    Example:
        >>> handler = CheckHandler(locale='en_US')
        >>> handler.generate(context)
        1  # or 0
    """

    # Default probability of being checked (True/1)
    DEFAULT_TRUE_PROBABILITY = 0.5

    def generate(self, context: GenerationContext) -> int:
        """
        Generate a Check field value.

        Args:
            context: The generation context

        Returns:
            0 (unchecked) or 1 (checked)
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                # Handle various boolean representations
                if isinstance(fixed_value, bool):
                    return 1 if fixed_value else 0
                if isinstance(fixed_value, (int, float)):
                    return 1 if fixed_value else 0
                if isinstance(fixed_value, str):
                    return 1 if fixed_value.lower() in ("true", "1", "yes", "on") else 0
                return 1 if fixed_value else 0

            # Check for probability override
            true_probability = context.get_override_value(
                "true_probability", self.DEFAULT_TRUE_PROBABILITY
            )
        else:
            # Analyze fieldname for context-specific probabilities
            fieldname = context.fieldname.lower()

            # Fields that are typically true/enabled by default
            if any(x in fieldname for x in ["enabled", "active", "allow", "is_default"]):
                true_probability = 0.8
            # Fields that are typically false/disabled by default
            elif any(x in fieldname for x in ["disabled", "hidden", "archived", "deleted"]):
                true_probability = 0.2
            # Required/mandatory fields tend to be true
            elif "required" in fieldname or "mandatory" in fieldname:
                true_probability = 0.7
            else:
                true_probability = self.DEFAULT_TRUE_PROBABILITY

        # Generate boolean based on probability
        return 1 if self.faker.pyfloat(min_value=0, max_value=1) < true_probability else 0

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Check field value."""
        if isinstance(value, bool):
            return True
        if isinstance(value, int):
            return value in (0, 1)
        return False

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.STATUS, FieldPattern.GENERIC}


class SelectHandler(BaseFieldHandler):
    """
    Handler for Select (dropdown) field generation.

    Generates values from the predefined options list of a Select field.
    Frappe Select fields have options defined as a newline-separated string.

    Select fields in Frappe:
    - Options are stored as newline-separated values
    - First option is often empty or a placeholder
    - Values must match exactly one of the options

    Supported patterns:
        - FieldPattern.STATUS

    Example:
        >>> handler = SelectHandler(locale='en_US')
        >>> handler.generate(context)  # options: "Draft\nPending\nCompleted"
        'Pending'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a Select field value.

        Args:
            context: The generation context

        Returns:
            One of the valid options for the Select field

        Raises:
            GenerationError: If no valid options are available
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)

            # Check for custom options override
            custom_options = context.get_override_value("options")
            if custom_options:
                if isinstance(custom_options, str):
                    options = [opt.strip() for opt in custom_options.split("\n") if opt.strip()]
                elif isinstance(custom_options, list):
                    options = [str(opt) for opt in custom_options if opt]
                else:
                    options = []

                if options:
                    # Check for weighted selection
                    weights = context.get_override_value("weights")
                    if weights and len(weights) == len(options):
                        return self._weighted_choice(options, weights)
                    return self.faker.random_element(options)

        # Get options from field info
        options = context.select_options

        if not options:
            # Fallback: check raw options string
            raw_options = context.options
            if raw_options:
                options = [opt.strip() for opt in raw_options.split("\n") if opt.strip()]

        if not options:
            # No options available, return empty string
            return ""

        # Filter out empty options if there are non-empty options
        non_empty_options = [opt for opt in options if opt]
        if non_empty_options:
            options = non_empty_options

        # Check for preference based on fieldname
        fieldname = context.fieldname.lower()

        # For status fields, prefer non-Draft values for variety
        if "status" in fieldname:
            # Weight against first option (usually Draft or placeholder)
            if len(options) > 1:
                # 70% chance to pick non-first option
                if self.faker.pyfloat(min_value=0, max_value=1) > 0.3:
                    return self.faker.random_element(options[1:])

        return self.faker.random_element(options)

    def _weighted_choice(self, options: List[str], weights: List[float]) -> str:
        """
        Make a weighted random choice from options.

        Args:
            options: List of option values
            weights: List of weights (probabilities)

        Returns:
            Randomly selected option based on weights
        """
        total = sum(weights)
        r = self.faker.pyfloat(min_value=0, max_value=total)
        cumulative = 0
        for option, weight in zip(options, weights):
            cumulative += weight
            if r <= cumulative:
                return option
        return options[-1]  # Fallback to last option

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Select field value."""
        if not isinstance(value, str):
            return False

        options = context.select_options
        if not options:
            # If no options defined, any string is valid
            return True

        # Value must be in options list
        return value in options or value == ""

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.STATUS, FieldPattern.GENERIC}


class ColorHandler(BaseFieldHandler):
    """
    Handler for Color field generation.

    Generates hexadecimal color values for Frappe's Color field type.
    Colors are returned in the format '#RRGGBB'.

    Color fields in Frappe:
    - Store values as hex color codes (e.g., '#FF5733')
    - Are rendered with a color picker in the UI

    Supported patterns:
        - FieldPattern.COLOR

    Example:
        >>> handler = ColorHandler(locale='en_US')
        >>> handler.generate(context)
        '#3498DB'
    """

    # Common/popular colors for better visuals
    COMMON_COLORS = [
        "#3498DB",  # Blue
        "#2ECC71",  # Green
        "#E74C3C",  # Red
        "#9B59B6",  # Purple
        "#F39C12",  # Orange
        "#1ABC9C",  # Teal
        "#34495E",  # Dark Gray
        "#E91E63",  # Pink
        "#00BCD4",  # Cyan
        "#8BC34A",  # Light Green
        "#FF5722",  # Deep Orange
        "#673AB7",  # Deep Purple
        "#009688",  # Teal
        "#795548",  # Brown
        "#607D8B",  # Blue Gray
    ]

    # Status-related colors
    STATUS_COLORS = {
        "success": ["#2ECC71", "#27AE60", "#00C853"],
        "warning": ["#F39C12", "#F1C40F", "#FFB300"],
        "danger": ["#E74C3C", "#C0392B", "#D32F2F"],
        "info": ["#3498DB", "#2980B9", "#1976D2"],
        "primary": ["#3498DB", "#2196F3", "#1565C0"],
        "secondary": ["#95A5A6", "#7F8C8D", "#607D8B"],
    }

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a Color field value.

        Args:
            context: The generation context

        Returns:
            A hex color code string (e.g., '#FF5733')
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return self._normalize_color(str(fixed_value))

            # Check for color palette override
            palette = context.get_override_value("palette")
            if palette and isinstance(palette, list):
                return self.faker.random_element(palette)

            # Check for color category override
            category = context.get_override_value("category")
            if category and category in self.STATUS_COLORS:
                return self.faker.random_element(self.STATUS_COLORS[category])

        # Analyze fieldname for context-specific colors
        fieldname = context.fieldname.lower()

        # Status-related color fields
        if any(x in fieldname for x in ["status", "state"]):
            all_status_colors = []
            for colors in self.STATUS_COLORS.values():
                all_status_colors.extend(colors)
            return self.faker.random_element(all_status_colors)

        # Priority/severity colors
        if any(x in fieldname for x in ["priority", "severity", "level"]):
            return self.faker.random_element(
                self.STATUS_COLORS["danger"] +
                self.STATUS_COLORS["warning"] +
                self.STATUS_COLORS["success"]
            )

        # Check for use_common_colors preference
        use_common = context.get_override_value("use_common_colors", True)
        if use_common:
            return self.faker.random_element(self.COMMON_COLORS)

        # Generate random hex color
        return self.faker.hex_color().upper()

    def _normalize_color(self, color: str) -> str:
        """
        Normalize a color value to proper hex format.

        Args:
            color: Color string (may or may not have #)

        Returns:
            Normalized hex color string with #
        """
        color = color.strip()
        if not color.startswith("#"):
            color = f"#{color}"

        # Ensure uppercase
        color = color.upper()

        # Validate and fix format
        if re.match(r"^#[0-9A-F]{6}$", color):
            return color
        elif re.match(r"^#[0-9A-F]{3}$", color):
            # Convert short format to full
            return f"#{color[1]*2}{color[2]*2}{color[3]*2}"

        # Invalid format, return a default color
        return "#3498DB"

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Color field value."""
        if not isinstance(value, str):
            return False
        # Valid hex color format
        return bool(re.match(r"^#[0-9A-Fa-f]{6}$", value))

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.COLOR}


class AttachHandler(BaseFieldHandler):
    """
    Handler for Attach field generation.

    Generates file attachment URLs/paths for Frappe's Attach field type.
    Returns placeholder URLs that follow Frappe's file storage conventions.

    Attach fields in Frappe:
    - Store file paths relative to the files directory
    - Format: /files/filename.ext or /private/files/filename.ext

    Supported patterns:
        - FieldPattern.GENERIC

    Example:
        >>> handler = AttachHandler(locale='en_US')
        >>> handler.generate(context)
        '/files/document-2024-01-15-a1b2c3.pdf'
    """

    # Common file extensions by category
    FILE_EXTENSIONS = {
        "document": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt"],
        "spreadsheet": [".xlsx", ".xls", ".csv", ".ods"],
        "presentation": [".pptx", ".ppt", ".odp"],
        "archive": [".zip", ".rar", ".7z", ".tar.gz"],
        "generic": [".pdf", ".docx", ".xlsx", ".txt", ".csv"],
    }

    def generate(self, context: GenerationContext) -> str:
        """
        Generate an Attach field value.

        Args:
            context: The generation context

        Returns:
            A file path/URL string
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)

            # Check for custom URL override
            custom_url = context.get_override_value("url")
            if custom_url:
                return str(custom_url)

            # Check for file type preference
            file_type = context.get_override_value("file_type", "generic")
        else:
            # Determine file type from fieldname
            fieldname = context.fieldname.lower()

            if any(x in fieldname for x in ["document", "doc", "contract", "agreement"]):
                file_type = "document"
            elif any(x in fieldname for x in ["spreadsheet", "excel", "report", "data"]):
                file_type = "spreadsheet"
            elif any(x in fieldname for x in ["presentation", "slide", "ppt"]):
                file_type = "presentation"
            elif any(x in fieldname for x in ["archive", "zip", "backup"]):
                file_type = "archive"
            else:
                file_type = "generic"

        # Check if private file
        is_private = context.get_override_value("is_private", False)

        # Generate filename
        filename = self._generate_filename(file_type, context)

        # Build path
        if is_private:
            return f"/private/files/{filename}"
        return f"/files/{filename}"

    def _generate_filename(self, file_type: str, context: GenerationContext) -> str:
        """
        Generate a realistic filename.

        Args:
            file_type: Type of file to generate
            context: The generation context

        Returns:
            A generated filename string
        """
        # Get extension
        extensions = self.FILE_EXTENSIONS.get(file_type, self.FILE_EXTENSIONS["generic"])
        extension = self.faker.random_element(extensions)

        # Generate base name
        base_names = [
            f"document-{self.faker.date_this_year().strftime('%Y-%m-%d')}",
            f"file-{uuid.uuid4().hex[:8]}",
            f"attachment-{context.batch_index:04d}",
            f"{self.faker.word()}-{self.faker.word()}",
        ]
        base_name = self.faker.random_element(base_names)

        # Sanitize filename
        base_name = re.sub(r"[^a-zA-Z0-9_-]", "-", base_name)

        return f"{base_name}{extension}"

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Attach field value."""
        if not isinstance(value, str):
            return False
        # Should be a valid path or URL
        return (
            value.startswith("/files/") or
            value.startswith("/private/files/") or
            value.startswith("http://") or
            value.startswith("https://")
        )

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.GENERIC}


class AttachImageHandler(BaseFieldHandler):
    """
    Handler for Attach Image field generation.

    Generates image attachment URLs/paths for Frappe's Attach Image field type.
    Can integrate with Unsplash for contextual images or generate placeholder URLs.

    Attach Image fields in Frappe:
    - Store image file paths
    - Often used for avatars, logos, product images
    - Support common image formats (jpg, png, gif, webp)

    Supported patterns:
        - FieldPattern.IMAGE
        - FieldPattern.PHOTO
        - FieldPattern.LOGO
        - FieldPattern.AVATAR

    Example:
        >>> handler = AttachImageHandler(locale='en_US')
        >>> handler.generate(context)
        '/files/image-a1b2c3d4.jpg'
    """

    # Image extensions
    IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".webp"]

    # Placeholder image services
    PLACEHOLDER_SERVICES = [
        "https://picsum.photos/{width}/{height}",
        "https://placehold.co/{width}x{height}",
    ]

    def generate(self, context: GenerationContext) -> str:
        """
        Generate an Attach Image field value.

        Args:
            context: The generation context

        Returns:
            An image file path/URL string
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)

            # Check for custom URL override
            custom_url = context.get_override_value("url")
            if custom_url:
                return str(custom_url)

            # Check for placeholder preference
            use_placeholder = context.get_override_value("use_placeholder", False)
            if use_placeholder:
                width = context.get_override_value("width", 300)
                height = context.get_override_value("height", 300)
                service = self.faker.random_element(self.PLACEHOLDER_SERVICES)
                return service.format(width=width, height=height)

        # Analyze fieldname for image type
        fieldname = context.fieldname.lower()
        pattern = context.detected_pattern

        # Determine image dimensions based on type
        if pattern == FieldPattern.AVATAR or "avatar" in fieldname or "profile" in fieldname:
            width, height = 150, 150
            image_type = "avatar"
        elif pattern == FieldPattern.LOGO or "logo" in fieldname:
            width, height = 200, 100
            image_type = "logo"
        elif pattern == FieldPattern.PHOTO or "photo" in fieldname:
            width, height = 800, 600
            image_type = "photo"
        else:
            width, height = 400, 300
            image_type = "image"

        # Check if Unsplash integration is enabled
        use_unsplash = context.get_override_value("use_unsplash", False)
        if use_unsplash:
            query = context.get_override_value("unsplash_query", image_type)
            return f"https://source.unsplash.com/featured/{width}x{height}/?{query}"

        # Generate local file path
        extension = self.faker.random_element(self.IMAGE_EXTENSIONS)
        filename = f"{image_type}-{uuid.uuid4().hex[:8]}{extension}"

        # Check if private
        is_private = context.get_override_value("is_private", False)
        if is_private:
            return f"/private/files/{filename}"

        return f"/files/{filename}"

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Attach Image field value."""
        if not isinstance(value, str):
            return False
        # Should be a valid image path or URL
        valid_start = (
            value.startswith("/files/") or
            value.startswith("/private/files/") or
            value.startswith("http://") or
            value.startswith("https://")
        )
        # Check for image extension (if local path)
        if value.startswith("/"):
            has_image_ext = any(value.lower().endswith(ext) for ext in self.IMAGE_EXTENSIONS)
            return valid_start and has_image_ext
        return valid_start

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.IMAGE, FieldPattern.PHOTO, FieldPattern.LOGO, FieldPattern.AVATAR}


class GeolocationHandler(BaseFieldHandler):
    """
    Handler for Geolocation field generation.

    Generates geographic coordinates (latitude/longitude) as JSON for
    Frappe's Geolocation field type.

    Geolocation fields in Frappe:
    - Store coordinates as JSON with lat/lng properties
    - Format: {"type": "FeatureCollection", "features": [...]}
    - Can also be simple lat/lng pairs

    Supported patterns:
        - FieldPattern.GENERIC

    Example:
        >>> handler = GeolocationHandler(locale='tr_TR')
        >>> handler.generate(context)
        '{"type": "FeatureCollection", "features": [...]}'
    """

    # Regional bounding boxes for locale-aware generation
    LOCALE_BOUNDS = {
        "tr": {  # Turkey
            "lat_min": 35.8,
            "lat_max": 42.1,
            "lng_min": 25.9,
            "lng_max": 44.8,
            "name": "Turkey",
        },
        "en_US": {  # United States
            "lat_min": 24.5,
            "lat_max": 49.4,
            "lng_min": -124.8,
            "lng_max": -66.9,
            "name": "United States",
        },
        "de": {  # Germany
            "lat_min": 47.3,
            "lat_max": 55.1,
            "lng_min": 5.9,
            "lng_max": 15.0,
            "name": "Germany",
        },
        "fr": {  # France
            "lat_min": 41.3,
            "lat_max": 51.1,
            "lng_min": -5.1,
            "lng_max": 9.6,
            "name": "France",
        },
        "default": {  # World
            "lat_min": -90.0,
            "lat_max": 90.0,
            "lng_min": -180.0,
            "lng_max": 180.0,
            "name": "World",
        },
    }

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a Geolocation field value.

        Args:
            context: The generation context

        Returns:
            A GeoJSON string with coordinates
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                if isinstance(fixed_value, str):
                    return fixed_value
                return json.dumps(fixed_value)

            # Check for custom coordinates
            lat = context.get_override_value("latitude")
            lng = context.get_override_value("longitude")
            if lat is not None and lng is not None:
                return self._create_geojson(float(lat), float(lng))

        # Get bounds based on locale
        bounds = self._get_locale_bounds()

        # Generate random coordinates within bounds
        lat = self.faker.pyfloat(
            min_value=bounds["lat_min"],
            max_value=bounds["lat_max"],
            right_digits=6
        )
        lng = self.faker.pyfloat(
            min_value=bounds["lng_min"],
            max_value=bounds["lng_max"],
            right_digits=6
        )

        return self._create_geojson(lat, lng)

    def _get_locale_bounds(self) -> Dict[str, Any]:
        """
        Get geographic bounds based on the current locale.

        Returns:
            Dict with lat/lng min/max bounds
        """
        locale = self._locale.lower()

        # Try exact match first
        if locale in self.LOCALE_BOUNDS:
            return self.LOCALE_BOUNDS[locale]

        # Try language prefix
        lang_prefix = locale.split("_")[0]
        if lang_prefix in self.LOCALE_BOUNDS:
            return self.LOCALE_BOUNDS[lang_prefix]

        return self.LOCALE_BOUNDS["default"]

    def _create_geojson(self, lat: float, lng: float) -> str:
        """
        Create a GeoJSON FeatureCollection with a point.

        Args:
            lat: Latitude
            lng: Longitude

        Returns:
            GeoJSON string
        """
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lng, lat]  # GeoJSON uses [lng, lat] order
                    }
                }
            ]
        }
        return json.dumps(geojson)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Geolocation field value."""
        if not isinstance(value, str):
            return False
        try:
            data = json.loads(value)
            # Should be a valid GeoJSON or have lat/lng
            if "type" in data and data["type"] == "FeatureCollection":
                return True
            if "lat" in data or "latitude" in data:
                return True
            return False
        except (json.JSONDecodeError, TypeError):
            return False

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.GENERIC}


class SignatureHandler(BaseFieldHandler):
    """
    Handler for Signature field generation.

    Generates signature data for Frappe's Signature field type.
    Signatures are stored as base64-encoded images or SVG paths.

    Signature fields in Frappe:
    - Store signature as base64 data URL
    - Format: data:image/png;base64,...
    - Can also be SVG path data

    Supported patterns:
        - FieldPattern.GENERIC

    Example:
        >>> handler = SignatureHandler(locale='en_US')
        >>> handler.generate(context)
        'data:image/svg+xml;base64,...'
    """

    # Minimal placeholder SVG signature (looks like a simple scribble)
    PLACEHOLDER_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="50">
        <path d="M10,25 Q30,10 50,25 T90,25 T130,25 T170,25"
              stroke="black" fill="none" stroke-width="2"/>
    </svg>'''

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a Signature field value.

        Args:
            context: The generation context

        Returns:
            A signature data URL string
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)

            # Check for custom signature
            custom_signature = context.get_override_value("signature_data")
            if custom_signature:
                return str(custom_signature)

        # Check for empty signature option
        allow_empty = context.get_override_value("allow_empty", False)
        if allow_empty and self.faker.boolean(chance_of_getting_true=30):
            return ""

        # Generate a unique signature SVG
        signature_svg = self._generate_signature_svg()

        # Encode as base64 data URL
        import base64
        svg_bytes = signature_svg.encode("utf-8")
        b64_data = base64.b64encode(svg_bytes).decode("utf-8")

        return f"data:image/svg+xml;base64,{b64_data}"

    def _generate_signature_svg(self) -> str:
        """
        Generate a unique signature-like SVG.

        Returns:
            SVG string representing a signature
        """
        # Generate random path points for a signature-like curve
        width = 200
        height = 50
        y_center = height // 2

        # Generate control points for the signature curve
        num_points = self.faker.random_int(min=4, max=7)
        points = []

        x = 10
        for i in range(num_points):
            y = y_center + self.faker.random_int(min=-15, max=15)
            points.append((x, y))
            x += width // (num_points + 1) + self.faker.random_int(min=-5, max=5)

        # Build SVG path
        path_d = f"M{points[0][0]},{points[0][1]}"
        for i in range(1, len(points)):
            # Use quadratic bezier for smooth curves
            cx = (points[i-1][0] + points[i][0]) // 2
            cy = y_center + self.faker.random_int(min=-20, max=20)
            path_d += f" Q{cx},{cy} {points[i][0]},{points[i][1]}"

        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
            <path d="{path_d}" stroke="#000000" fill="none" stroke-width="2" stroke-linecap="round"/>
        </svg>'''

        return svg

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Signature field value."""
        if not isinstance(value, str):
            return False
        # Empty is valid
        if value == "":
            return True
        # Should be a data URL or SVG
        return (
            value.startswith("data:image/") or
            value.startswith("<svg") or
            value.startswith("<?xml")
        )

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.GENERIC}


class JSONHandler(BaseFieldHandler):
    """
    Handler for JSON field generation.

    Generates JSON data for Frappe's JSON field type.
    Can generate various JSON structures based on context.

    JSON fields in Frappe:
    - Store arbitrary JSON data
    - Used for configurations, metadata, custom data
    - Rendered with JSON editor in UI

    Supported patterns:
        - FieldPattern.GENERIC

    Example:
        >>> handler = JSONHandler(locale='en_US')
        >>> handler.generate(context)
        '{"key": "value", "count": 42}'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a JSON field value.

        Args:
            context: The generation context

        Returns:
            A JSON string
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                if isinstance(fixed_value, str):
                    return fixed_value
                return json.dumps(fixed_value)

            # Check for schema override
            schema = context.get_override_value("schema")
            if schema:
                return json.dumps(self._generate_from_schema(schema))

            # Check for template override
            template = context.get_override_value("template")
            if template and isinstance(template, dict):
                return json.dumps(template)

        # Analyze fieldname to determine appropriate JSON structure
        fieldname = context.fieldname.lower()

        if any(x in fieldname for x in ["config", "settings", "options"]):
            data = self._generate_config_json()
        elif any(x in fieldname for x in ["meta", "metadata", "info"]):
            data = self._generate_metadata_json()
        elif any(x in fieldname for x in ["filter", "query", "criteria"]):
            data = self._generate_filter_json()
        elif any(x in fieldname for x in ["data", "payload", "content"]):
            data = self._generate_data_json()
        else:
            data = self._generate_generic_json()

        return json.dumps(data, indent=None)

    def _generate_config_json(self) -> Dict[str, Any]:
        """Generate configuration-like JSON."""
        return {
            "enabled": self.faker.boolean(),
            "mode": self.faker.random_element(["auto", "manual", "custom"]),
            "options": {
                "timeout": self.faker.random_int(min=1000, max=30000),
                "retry_count": self.faker.random_int(min=1, max=5),
            },
        }

    def _generate_metadata_json(self) -> Dict[str, Any]:
        """Generate metadata-like JSON."""
        return {
            "created_by": self.faker.user_name(),
            "version": f"{self.faker.random_int(1, 5)}.{self.faker.random_int(0, 9)}.{self.faker.random_int(0, 9)}",
            "tags": [self.faker.word() for _ in range(self.faker.random_int(1, 4))],
            "source": self.faker.random_element(["api", "import", "manual", "system"]),
        }

    def _generate_filter_json(self) -> Dict[str, Any]:
        """Generate filter/query-like JSON."""
        return {
            "field": self.faker.word(),
            "operator": self.faker.random_element(["=", "!=", ">", "<", "like", "in"]),
            "value": self.faker.word(),
        }

    def _generate_data_json(self) -> Dict[str, Any]:
        """Generate general data JSON."""
        return {
            "id": str(uuid.uuid4()),
            "name": self.faker.word().capitalize(),
            "value": self.faker.random_int(min=1, max=100),
            "active": self.faker.boolean(),
        }

    def _generate_generic_json(self) -> Dict[str, Any]:
        """Generate generic JSON with various types."""
        return {
            "string_field": self.faker.word(),
            "number_field": self.faker.random_int(min=1, max=1000),
            "boolean_field": self.faker.boolean(),
            "array_field": [self.faker.word() for _ in range(2)],
        }

    def _generate_from_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate JSON data following a provided schema.

        Args:
            schema: Schema definition dict

        Returns:
            Generated data dict
        """
        result = {}
        for key, spec in schema.items():
            if isinstance(spec, str):
                # Simple type specification
                if spec == "string":
                    result[key] = self.faker.word()
                elif spec == "int":
                    result[key] = self.faker.random_int(min=1, max=100)
                elif spec == "float":
                    result[key] = round(self.faker.pyfloat(min_value=0, max_value=100), 2)
                elif spec == "bool":
                    result[key] = self.faker.boolean()
                elif spec == "email":
                    result[key] = self.faker.email()
                else:
                    result[key] = self.faker.word()
            elif isinstance(spec, dict):
                # Nested object
                result[key] = self._generate_from_schema(spec)
            elif isinstance(spec, list) and spec:
                # Array with element specification
                result[key] = [self._generate_from_schema({f"item": spec[0]})["item"]
                               for _ in range(self.faker.random_int(1, 3))]
            else:
                result[key] = None

        return result

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate JSON field value."""
        if not isinstance(value, str):
            return False
        try:
            json.loads(value)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.GENERIC}


class BarcodeHandler(BaseFieldHandler):
    """
    Handler for Barcode field generation.

    Generates barcode values for Frappe's Barcode field type.
    Supports various barcode formats including EAN-13, UPC-A, Code-128, etc.

    Barcode fields in Frappe:
    - Store the barcode value/number
    - Rendering is handled by the frontend
    - Common formats: EAN-13, UPC-A, Code-128, QR

    Supported patterns:
        - FieldPattern.CODE
        - FieldPattern.SKU

    Example:
        >>> handler = BarcodeHandler(locale='en_US')
        >>> handler.generate(context)
        '5901234123457'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a Barcode field value.

        Args:
            context: The generation context

        Returns:
            A barcode string
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)

            # Check for barcode type override
            barcode_type = context.get_override_value("barcode_type", "EAN13")
        else:
            # Default to EAN-13
            barcode_type = "EAN13"

        # Analyze fieldname for hints
        fieldname = context.fieldname.lower()

        if "qr" in fieldname:
            return self._generate_qr_content()
        elif "upc" in fieldname:
            return self._generate_upc_a()
        elif "isbn" in fieldname:
            return self._generate_isbn()
        elif "code128" in fieldname or "code_128" in fieldname:
            return self._generate_code128()

        # Generate based on barcode_type
        barcode_type = barcode_type.upper()

        if barcode_type == "EAN13":
            return self._generate_ean13()
        elif barcode_type == "EAN8":
            return self._generate_ean8()
        elif barcode_type == "UPCA":
            return self._generate_upc_a()
        elif barcode_type == "CODE128":
            return self._generate_code128()
        elif barcode_type == "QR":
            return self._generate_qr_content()
        elif barcode_type == "ISBN":
            return self._generate_isbn()
        else:
            return self._generate_ean13()

    def _generate_ean13(self) -> str:
        """
        Generate a valid EAN-13 barcode.

        Returns:
            13-digit EAN-13 barcode string
        """
        # Generate 12 digits
        digits = [self.faker.random_digit() for _ in range(12)]

        # Calculate check digit
        odd_sum = sum(digits[i] for i in range(0, 12, 2))
        even_sum = sum(digits[i] for i in range(1, 12, 2))
        check = (10 - ((odd_sum + even_sum * 3) % 10)) % 10

        digits.append(check)
        return "".join(str(d) for d in digits)

    def _generate_ean8(self) -> str:
        """
        Generate a valid EAN-8 barcode.

        Returns:
            8-digit EAN-8 barcode string
        """
        # Generate 7 digits
        digits = [self.faker.random_digit() for _ in range(7)]

        # Calculate check digit
        odd_sum = sum(digits[i] for i in range(0, 7, 2))
        even_sum = sum(digits[i] for i in range(1, 7, 2))
        check = (10 - ((odd_sum * 3 + even_sum) % 10)) % 10

        digits.append(check)
        return "".join(str(d) for d in digits)

    def _generate_upc_a(self) -> str:
        """
        Generate a valid UPC-A barcode.

        Returns:
            12-digit UPC-A barcode string
        """
        # Generate 11 digits
        digits = [self.faker.random_digit() for _ in range(11)]

        # Calculate check digit
        odd_sum = sum(digits[i] for i in range(0, 11, 2))
        even_sum = sum(digits[i] for i in range(1, 11, 2))
        check = (10 - ((odd_sum * 3 + even_sum) % 10)) % 10

        digits.append(check)
        return "".join(str(d) for d in digits)

    def _generate_code128(self) -> str:
        """
        Generate a Code-128 compatible string.

        Returns:
            Alphanumeric code string
        """
        # Generate alphanumeric code (Code 128 supports full ASCII)
        prefix = "".join(self.faker.random_letters(3)).upper()
        numbers = "".join([str(self.faker.random_digit()) for _ in range(8)])
        return f"{prefix}{numbers}"

    def _generate_qr_content(self) -> str:
        """
        Generate content suitable for QR codes.

        Returns:
            String content for QR code
        """
        # QR codes can contain various data types
        content_type = self.faker.random_element(["url", "text", "id"])

        if content_type == "url":
            return f"https://{self.faker.domain_name()}/{self.faker.uri_path()}"
        elif content_type == "id":
            return f"{uuid.uuid4()}"
        else:
            return f"{self.faker.company()}-{self.faker.random_int(1000, 9999)}"

    def _generate_isbn(self) -> str:
        """
        Generate a valid ISBN-13.

        Returns:
            13-digit ISBN string
        """
        # ISBN-13 starts with 978 or 979
        prefix = self.faker.random_element(["978", "979"])
        # Registration group (1-5 digits, use 0 for simplicity)
        group = "0"
        # Registrant (up to 7 digits)
        registrant = "".join([str(self.faker.random_digit()) for _ in range(4)])
        # Publication (remaining to make 12 digits before check)
        publication = "".join([str(self.faker.random_digit()) for _ in range(4)])

        base = f"{prefix}{group}{registrant}{publication}"
        digits = [int(d) for d in base]

        # Calculate ISBN-13 check digit
        total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
        check = (10 - (total % 10)) % 10

        return f"{base}{check}"

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate Barcode field value."""
        if not isinstance(value, str):
            return False
        # Basic validation: non-empty string
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.CODE, FieldPattern.SKU, FieldPattern.GENERIC}


# Export all handler classes
__all__ = [
    # Primary handlers
    "CheckHandler",
    "SelectHandler",
    "ColorHandler",
    "AttachHandler",
    "AttachImageHandler",
    "GeolocationHandler",
    "SignatureHandler",
    "JSONHandler",
    "BarcodeHandler",
]
