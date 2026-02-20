# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Date/Time Field Handlers Module.

This module provides handlers for date and time field types including Date,
Datetime, Time, and Duration fields.

The handlers support pattern-based generation for detected semantic patterns
like birth_date, start_date, end_date, created, modified, etc.

Handlers in this module:
- DateHandler: Date value generation (YYYY-MM-DD format)
- DatetimeHandler: Datetime value generation (YYYY-MM-DD HH:MM:SS format)
- TimeHandler: Time value generation (HH:MM:SS format)
- DurationHandler: Duration/time interval generation (seconds or HH:MM:SS format)

Usage:
    from mock_data_engine.handlers.date_handlers import (
        DateHandler,
        DatetimeHandler,
        TimeHandler,
        DurationHandler,
    )

    # Using DateHandler directly
    handler = DateHandler(locale='tr_TR', seed=42)
    value = handler.generate(context)

    # Using DatetimeHandler for timestamp values
    datetime_handler = DatetimeHandler(locale='tr_TR', seed=42)
    timestamp = datetime_handler.generate(context)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Optional, Set, Union, TYPE_CHECKING

from mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    GenerationError,
)

if TYPE_CHECKING:
    from mock_data_engine.core.config_resolver import ResolvedConfig


class DateHandler(BaseFieldHandler):
    """
    Handler for date field generation.

    Generates date values in YYYY-MM-DD format with support for
    pattern-based date ranges (birth dates, start dates, end dates, etc.).

    Supported patterns:
        - FieldPattern.DATE
        - FieldPattern.BIRTH_DATE
        - FieldPattern.START_DATE
        - FieldPattern.END_DATE
        - FieldPattern.CREATED
        - FieldPattern.MODIFIED

    Example:
        >>> handler = DateHandler(locale='en_US')
        >>> handler.generate(context)
        '2024-05-15'
    """

    # Default date range (years from today)
    DEFAULT_YEARS_BACK = 5
    DEFAULT_YEARS_FORWARD = 1

    # Pattern-specific date ranges
    PATTERN_RANGES = {
        FieldPattern.BIRTH_DATE: (-80, -18),  # 18-80 years ago
        FieldPattern.START_DATE: (-2, 1),  # 2 years ago to 1 year ahead
        FieldPattern.END_DATE: (0, 2),  # Now to 2 years ahead
        FieldPattern.CREATED: (-5, 0),  # Past 5 years
        FieldPattern.MODIFIED: (-1, 0),  # Past year
        FieldPattern.DATE: (-5, 1),  # Default date range
    }

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a date value in YYYY-MM-DD format.

        Args:
            context: The generation context

        Returns:
            A date string in YYYY-MM-DD format
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return self._parse_date_string(fixed_value)

            # Check for date range override
            start_date = context.get_override_value("start_date")
            end_date = context.get_override_value("end_date")
            if start_date and end_date:
                return self._generate_date_in_range(
                    self._parse_date(start_date),
                    self._parse_date(end_date)
                )

        # Determine date range based on pattern
        pattern = context.detected_pattern
        years_back, years_forward = self.PATTERN_RANGES.get(
            pattern,
            (-self.DEFAULT_YEARS_BACK, self.DEFAULT_YEARS_FORWARD)
        )

        # Generate date
        generated_date = self._generate_date_by_years(years_back, years_forward)
        return generated_date.strftime("%Y-%m-%d")

    def _generate_date_by_years(self, years_back: int, years_forward: int) -> date:
        """
        Generate a date within a range of years from today.

        Args:
            years_back: Years before today (negative)
            years_forward: Years after today (positive)

        Returns:
            A date object
        """
        today = date.today()

        # Calculate date range
        if years_back < 0:
            start_date = today.replace(year=today.year + years_back)
        else:
            start_date = today.replace(year=today.year + years_back)

        if years_forward > 0:
            end_date = today.replace(year=today.year + years_forward)
        else:
            end_date = today.replace(year=today.year + years_forward)

        return self._generate_date_in_range(start_date, end_date)

    def _generate_date_in_range(self, start_date: date, end_date: date) -> date:
        """
        Generate a random date within a range.

        Args:
            start_date: Start of the date range
            end_date: End of the date range

        Returns:
            A date object within the range
        """
        # Ensure start_date <= end_date
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        return self.faker.date_between(start_date=start_date, end_date=end_date)

    def _parse_date(self, date_input: Union[str, date]) -> date:
        """
        Parse a date input to a date object.

        Args:
            date_input: String or date object

        Returns:
            A date object
        """
        if isinstance(date_input, date):
            return date_input

        if isinstance(date_input, str):
            # Try common date formats
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
                try:
                    return datetime.strptime(date_input, fmt).date()
                except ValueError:
                    continue

        # Default to today
        return date.today()

    def _parse_date_string(self, value: Any) -> str:
        """
        Parse and format a date value to YYYY-MM-DD string.

        Args:
            value: Date value to parse

        Returns:
            Date string in YYYY-MM-DD format
        """
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")

        if isinstance(value, str):
            # If already in correct format, return as-is
            try:
                datetime.strptime(value, "%Y-%m-%d")
                return value
            except ValueError:
                pass

            # Try to parse and reformat
            parsed = self._parse_date(value)
            return parsed.strftime("%Y-%m-%d")

        return date.today().strftime("%Y-%m-%d")

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate date value."""
        if isinstance(value, date):
            return True

        if not isinstance(value, str):
            return False

        # Try to parse the date string
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.DATE,
            FieldPattern.BIRTH_DATE,
            FieldPattern.START_DATE,
            FieldPattern.END_DATE,
            FieldPattern.CREATED,
            FieldPattern.MODIFIED,
        }


class DatetimeHandler(BaseFieldHandler):
    """
    Handler for datetime field generation.

    Generates datetime values in YYYY-MM-DD HH:MM:SS format with support for
    pattern-based datetime ranges.

    Supported patterns:
        - FieldPattern.DATE
        - FieldPattern.CREATED
        - FieldPattern.MODIFIED

    Example:
        >>> handler = DatetimeHandler(locale='en_US')
        >>> handler.generate(context)
        '2024-05-15 14:30:45'
    """

    # Default datetime range (years from now)
    DEFAULT_YEARS_BACK = 5
    DEFAULT_YEARS_FORWARD = 1

    # Pattern-specific ranges
    PATTERN_RANGES = {
        FieldPattern.CREATED: (-5, 0),  # Past 5 years
        FieldPattern.MODIFIED: (-1, 0),  # Past year
        FieldPattern.DATE: (-5, 1),  # Default range
    }

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a datetime value in YYYY-MM-DD HH:MM:SS format.

        Args:
            context: The generation context

        Returns:
            A datetime string in YYYY-MM-DD HH:MM:SS format
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return self._parse_datetime_string(fixed_value)

            # Check for datetime range override
            start_datetime = context.get_override_value("start_datetime")
            end_datetime = context.get_override_value("end_datetime")
            if start_datetime and end_datetime:
                return self._generate_datetime_in_range(
                    self._parse_datetime(start_datetime),
                    self._parse_datetime(end_datetime)
                )

        # Determine datetime range based on pattern
        pattern = context.detected_pattern
        years_back, years_forward = self.PATTERN_RANGES.get(
            pattern,
            (-self.DEFAULT_YEARS_BACK, self.DEFAULT_YEARS_FORWARD)
        )

        # Generate datetime
        generated_datetime = self._generate_datetime_by_years(years_back, years_forward)
        return generated_datetime.strftime("%Y-%m-%d %H:%M:%S")

    def _generate_datetime_by_years(self, years_back: int, years_forward: int) -> datetime:
        """
        Generate a datetime within a range of years from now.

        Args:
            years_back: Years before now (negative)
            years_forward: Years after now (positive)

        Returns:
            A datetime object
        """
        now = datetime.now()

        # Calculate datetime range
        start_datetime = now.replace(year=now.year + years_back)
        end_datetime = now.replace(year=now.year + years_forward)

        return self._generate_datetime_in_range(start_datetime, end_datetime)

    def _generate_datetime_in_range(
        self,
        start_datetime: datetime,
        end_datetime: datetime
    ) -> datetime:
        """
        Generate a random datetime within a range.

        Args:
            start_datetime: Start of the datetime range
            end_datetime: End of the datetime range

        Returns:
            A datetime object within the range
        """
        # Ensure start <= end
        if start_datetime > end_datetime:
            start_datetime, end_datetime = end_datetime, start_datetime

        return self.faker.date_time_between(
            start_date=start_datetime,
            end_date=end_datetime
        )

    def _parse_datetime(self, datetime_input: Union[str, datetime]) -> datetime:
        """
        Parse a datetime input to a datetime object.

        Args:
            datetime_input: String or datetime object

        Returns:
            A datetime object
        """
        if isinstance(datetime_input, datetime):
            return datetime_input

        if isinstance(datetime_input, str):
            # Try common datetime formats
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d",
            ):
                try:
                    return datetime.strptime(datetime_input, fmt)
                except ValueError:
                    continue

        # Default to now
        return datetime.now()

    def _parse_datetime_string(self, value: Any) -> str:
        """
        Parse and format a datetime value to YYYY-MM-DD HH:MM:SS string.

        Args:
            value: Datetime value to parse

        Returns:
            Datetime string in YYYY-MM-DD HH:MM:SS format
        """
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")

        if isinstance(value, str):
            # If already in correct format, return as-is
            try:
                datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                return value
            except ValueError:
                pass

            # Try to parse and reformat
            parsed = self._parse_datetime(value)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate datetime value."""
        if isinstance(value, datetime):
            return True

        if not isinstance(value, str):
            return False

        # Try to parse the datetime string
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return True
        except ValueError:
            # Also accept date-only format
            try:
                datetime.strptime(value, "%Y-%m-%d")
                return True
            except ValueError:
                return False

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.DATE,
            FieldPattern.CREATED,
            FieldPattern.MODIFIED,
        }


class TimeHandler(BaseFieldHandler):
    """
    Handler for time field generation.

    Generates time values in HH:MM:SS format with support for
    configurable time ranges.

    Example:
        >>> handler = TimeHandler(locale='en_US')
        >>> handler.generate(context)
        '14:30:45'
    """

    # Default time range
    DEFAULT_START_HOUR = 0
    DEFAULT_END_HOUR = 23

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a time value in HH:MM:SS format.

        Args:
            context: The generation context

        Returns:
            A time string in HH:MM:SS format
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return self._parse_time_string(fixed_value)

            # Check for time range override
            start_time = context.get_override_value("start_time")
            end_time = context.get_override_value("end_time")
            if start_time and end_time:
                return self._generate_time_in_range(
                    self._parse_time(start_time),
                    self._parse_time(end_time)
                )

            # Check for business hours override
            business_hours_only = context.get_override_value("business_hours_only", False)
            if business_hours_only:
                return self._generate_business_hours_time()

        # Check fieldname for context
        fieldname = context.fieldname.lower()

        # Business hour patterns
        if any(x in fieldname for x in ["work", "office", "business", "mesai"]):
            return self._generate_business_hours_time()

        # Opening/closing time patterns
        if "open" in fieldname or "start" in fieldname or "acilis" in fieldname:
            return self._generate_time_in_hour_range(6, 12)
        if "close" in fieldname or "end" in fieldname or "kapanis" in fieldname:
            return self._generate_time_in_hour_range(17, 23)

        # Default: generate any time
        return self._generate_random_time()

    def _generate_random_time(self) -> str:
        """Generate a random time."""
        generated_time = self.faker.time_object()
        return generated_time.strftime("%H:%M:%S")

    def _generate_business_hours_time(self) -> str:
        """Generate a time within business hours (9:00 - 18:00)."""
        return self._generate_time_in_hour_range(9, 17)

    def _generate_time_in_hour_range(self, start_hour: int, end_hour: int) -> str:
        """
        Generate a time within a specific hour range.

        Args:
            start_hour: Start hour (0-23)
            end_hour: End hour (0-23)

        Returns:
            A time string in HH:MM:SS format
        """
        hour = self.faker.random_int(min=start_hour, max=end_hour)
        minute = self.faker.random_int(min=0, max=59)
        second = self.faker.random_int(min=0, max=59)

        generated_time = time(hour, minute, second)
        return generated_time.strftime("%H:%M:%S")

    def _generate_time_in_range(self, start_time: time, end_time: time) -> str:
        """
        Generate a time within a specific time range.

        Args:
            start_time: Start time
            end_time: End time

        Returns:
            A time string in HH:MM:SS format
        """
        # Convert times to total seconds for easy random selection
        start_seconds = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
        end_seconds = end_time.hour * 3600 + end_time.minute * 60 + end_time.second

        # Handle range that crosses midnight
        if end_seconds < start_seconds:
            end_seconds += 24 * 3600

        # Generate random seconds in range
        random_seconds = self.faker.random_int(min=start_seconds, max=end_seconds)
        random_seconds = random_seconds % (24 * 3600)  # Wrap around midnight

        # Convert back to time
        hour = random_seconds // 3600
        minute = (random_seconds % 3600) // 60
        second = random_seconds % 60

        generated_time = time(hour, minute, second)
        return generated_time.strftime("%H:%M:%S")

    def _parse_time(self, time_input: Union[str, time]) -> time:
        """
        Parse a time input to a time object.

        Args:
            time_input: String or time object

        Returns:
            A time object
        """
        if isinstance(time_input, time):
            return time_input

        if isinstance(time_input, str):
            # Try common time formats
            for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
                try:
                    return datetime.strptime(time_input, fmt).time()
                except ValueError:
                    continue

        # Default to noon
        return time(12, 0, 0)

    def _parse_time_string(self, value: Any) -> str:
        """
        Parse and format a time value to HH:MM:SS string.

        Args:
            value: Time value to parse

        Returns:
            Time string in HH:MM:SS format
        """
        if isinstance(value, time):
            return value.strftime("%H:%M:%S")

        if isinstance(value, str):
            # If already in correct format, return as-is
            try:
                datetime.strptime(value, "%H:%M:%S")
                return value
            except ValueError:
                pass

            # Try to parse and reformat
            parsed = self._parse_time(value)
            return parsed.strftime("%H:%M:%S")

        return time(12, 0, 0).strftime("%H:%M:%S")

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate time value."""
        if isinstance(value, time):
            return True

        if not isinstance(value, str):
            return False

        # Try to parse the time string
        try:
            datetime.strptime(value, "%H:%M:%S")
            return True
        except ValueError:
            # Also accept HH:MM format
            try:
                datetime.strptime(value, "%H:%M")
                return True
            except ValueError:
                return False

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.GENERIC}


class DurationHandler(BaseFieldHandler):
    """
    Handler for duration field generation.

    Generates duration values as floating-point seconds (Frappe's duration format)
    with support for configurable duration ranges.

    Frappe's Duration field stores values as seconds (float), but displays
    them in human-readable format (e.g., "2h 30m").

    Example:
        >>> handler = DurationHandler(locale='en_US')
        >>> handler.generate(context)
        9000.0  # Represents 2.5 hours
    """

    # Default duration range in seconds
    DEFAULT_MIN_SECONDS = 60  # 1 minute
    DEFAULT_MAX_SECONDS = 28800  # 8 hours

    # Pattern-based duration ranges (in seconds)
    DURATION_PRESETS = {
        "short": (60, 900),  # 1-15 minutes
        "medium": (900, 7200),  # 15 minutes to 2 hours
        "long": (7200, 28800),  # 2-8 hours
        "workday": (14400, 36000),  # 4-10 hours
        "meeting": (900, 5400),  # 15 minutes to 1.5 hours
    }

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a duration value in seconds.

        Args:
            context: The generation context

        Returns:
            Duration as floating-point seconds
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return self._parse_duration(fixed_value)

            # Check for duration range override
            min_seconds = context.get_override_value("min_seconds", self.DEFAULT_MIN_SECONDS)
            max_seconds = context.get_override_value("max_seconds", self.DEFAULT_MAX_SECONDS)
            return self._generate_duration_in_range(float(min_seconds), float(max_seconds))

            # Check for preset override
            preset = context.get_override_value("duration_preset")
            if preset and preset in self.DURATION_PRESETS:
                min_sec, max_sec = self.DURATION_PRESETS[preset]
                return self._generate_duration_in_range(float(min_sec), float(max_sec))

        # Check fieldname for context
        fieldname = context.fieldname.lower()

        # Detect duration type from fieldname
        if any(x in fieldname for x in ["break", "pause", "mola", "ara"]):
            # Short breaks: 5-30 minutes
            return self._generate_duration_in_range(300, 1800)
        elif any(x in fieldname for x in ["meeting", "toplanti", "session", "oturum"]):
            # Meetings: 15 minutes to 2 hours
            return self._generate_duration_in_range(900, 7200)
        elif any(x in fieldname for x in ["work", "task", "is", "gorev"]):
            # Work tasks: 30 minutes to 8 hours
            return self._generate_duration_in_range(1800, 28800)
        elif any(x in fieldname for x in ["total", "toplam", "sum"]):
            # Total durations: 1-12 hours
            return self._generate_duration_in_range(3600, 43200)

        # Default range
        return self._generate_duration_in_range(
            self.DEFAULT_MIN_SECONDS,
            self.DEFAULT_MAX_SECONDS
        )

    def _generate_duration_in_range(self, min_seconds: float, max_seconds: float) -> float:
        """
        Generate a duration within a range of seconds.

        Args:
            min_seconds: Minimum duration in seconds
            max_seconds: Maximum duration in seconds

        Returns:
            Duration as floating-point seconds
        """
        # Ensure min <= max
        if min_seconds > max_seconds:
            min_seconds, max_seconds = max_seconds, min_seconds

        # Generate random duration
        duration = self.faker.pyfloat(
            min_value=min_seconds,
            max_value=max_seconds,
            right_digits=0  # Round to whole seconds
        )

        return round(duration, 0)

    def _parse_duration(self, value: Any) -> float:
        """
        Parse a duration value to seconds.

        Supports formats:
        - Numeric (seconds): 3600, 3600.0
        - Time string: "1:30:00", "01:30"
        - Human readable: "1h 30m", "90 minutes"

        Args:
            value: Duration value to parse

        Returns:
            Duration in seconds as float
        """
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, timedelta):
            return value.total_seconds()

        if isinstance(value, str):
            value = value.strip()

            # Try numeric string
            try:
                return float(value)
            except ValueError:
                pass

            # Try time format (HH:MM:SS or HH:MM)
            try:
                parts = value.split(":")
                if len(parts) == 3:
                    hours, minutes, seconds = map(float, parts)
                    return hours * 3600 + minutes * 60 + seconds
                elif len(parts) == 2:
                    hours, minutes = map(float, parts)
                    return hours * 3600 + minutes * 60
            except (ValueError, TypeError):
                pass

            # Try human readable format
            total_seconds = 0.0
            value_lower = value.lower()

            # Hours
            import re
            hours_match = re.search(r"(\d+)\s*(?:h|hour|saat)", value_lower)
            if hours_match:
                total_seconds += int(hours_match.group(1)) * 3600

            # Minutes
            minutes_match = re.search(r"(\d+)\s*(?:m|min|minute|dakika)", value_lower)
            if minutes_match:
                total_seconds += int(minutes_match.group(1)) * 60

            # Seconds
            seconds_match = re.search(r"(\d+)\s*(?:s|sec|second|saniye)", value_lower)
            if seconds_match:
                total_seconds += int(seconds_match.group(1))

            if total_seconds > 0:
                return total_seconds

        # Default: 1 hour
        return 3600.0

    def format_duration(self, seconds: float) -> str:
        """
        Format a duration in seconds to human-readable string.

        Args:
            seconds: Duration in seconds

        Returns:
            Human-readable duration string (e.g., "2h 30m")
        """
        if seconds < 60:
            return f"{int(seconds)}s"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 and hours == 0:  # Only show seconds for short durations
            parts.append(f"{secs}s")

        return " ".join(parts) if parts else "0s"

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate duration value."""
        if isinstance(value, (int, float)):
            return float(value) >= 0

        if isinstance(value, timedelta):
            return value.total_seconds() >= 0

        if isinstance(value, str):
            # Try to parse the duration
            try:
                parsed = self._parse_duration(value)
                return parsed >= 0
            except (ValueError, TypeError):
                return False

        return False

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.GENERIC}


# Export all handler classes
__all__ = [
    # Primary handlers (required by subtask)
    "DateHandler",
    "DatetimeHandler",
    "TimeHandler",
    "DurationHandler",
]
