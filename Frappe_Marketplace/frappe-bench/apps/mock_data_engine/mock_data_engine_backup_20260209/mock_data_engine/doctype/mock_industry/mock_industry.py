# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MockIndustry(Document):
    """
    Mock Industry DocType for NACE-based industry classification.

    NACE (Statistical Classification of Economic Activities in the European Community)
    is a European industry standard classification system. The hierarchical structure is:
    - Section (A-U): Single letter representing broad economic sector
    - Division (01-99): Two digits for more specific industry
    - Group (001-999): Three digits for detailed classification
    - Class (0000-9999): Four digits for most specific classification

    This DocType provides industry context for AI-generated mock data,
    allowing generation of contextually appropriate business data.
    """

    def validate(self):
        """Validate the industry record before saving."""
        self.validate_industry_code()
        self.validate_nace_codes()
        self.validate_parent_hierarchy()

    def validate_industry_code(self):
        """Ensure industry code is properly formatted."""
        if self.industry_code:
            # Normalize to uppercase for consistency
            self.industry_code = self.industry_code.strip().upper()

            if not self.industry_code:
                frappe.throw(_("Industry Code cannot be empty"))

    def validate_nace_codes(self):
        """Validate NACE code format and consistency."""
        # Validate NACE Section (single letter A-U)
        if self.nace_section:
            self.nace_section = self.nace_section.strip().upper()
            if len(self.nace_section) != 1 or not self.nace_section.isalpha():
                frappe.throw(_("NACE Section must be a single letter (A-U)"))
            if self.nace_section not in "ABCDEFGHIJKLMNOPQRSTU":
                frappe.throw(_("NACE Section must be between A and U"))

        # Validate NACE Division (2 digits)
        if self.nace_division:
            self.nace_division = self.nace_division.strip().zfill(2)
            if not self.nace_division.isdigit() or len(self.nace_division) != 2:
                frappe.throw(_("NACE Division must be a 2-digit number"))

        # Validate NACE Group (3 digits)
        if self.nace_group:
            self.nace_group = self.nace_group.strip()
            # Allow format like "01.1" or "011"
            normalized = self.nace_group.replace(".", "")
            if not normalized.isdigit():
                frappe.throw(_("NACE Group must contain only digits"))
            # Store in consistent format (3 digits)
            self.nace_group = normalized.zfill(3)[:3]

        # Validate NACE Class (4 digits)
        if self.nace_class:
            self.nace_class = self.nace_class.strip()
            # Allow format like "01.11" or "0111"
            normalized = self.nace_class.replace(".", "")
            if not normalized.isdigit():
                frappe.throw(_("NACE Class must contain only digits"))
            # Store in consistent format (4 digits)
            self.nace_class = normalized.zfill(4)[:4]

        # Validate consistency: if class is set, group should match
        if self.nace_class and self.nace_group:
            if not self.nace_class.startswith(self.nace_group[:2]):
                frappe.msgprint(
                    _("NACE Class '{0}' may not match NACE Group '{1}'").format(
                        self.nace_class, self.nace_group
                    ),
                    indicator="orange",
                    alert=True
                )

    def validate_parent_hierarchy(self):
        """Validate parent industry to prevent circular references."""
        if self.parent_industry:
            # Check for self-reference
            if self.parent_industry == self.name:
                frappe.throw(_("An industry cannot be its own parent"))

            # Check for circular reference (up to 10 levels)
            visited = {self.name}
            current = self.parent_industry
            depth = 0
            max_depth = 10

            while current and depth < max_depth:
                if current in visited:
                    frappe.throw(
                        _("Circular reference detected in industry hierarchy: {0}").format(
                            " -> ".join(visited) + " -> " + current
                        )
                    )
                visited.add(current)
                parent_doc = frappe.db.get_value(
                    "Mock Industry", current, "parent_industry"
                )
                current = parent_doc
                depth += 1

    def get_ai_context(self) -> dict:
        """
        Get AI context hints for this industry.

        Returns a dictionary with contextual information that can be used
        to guide AI/LLM generation for more realistic industry-specific data.

        Returns:
            dict: AI context with company types, products, job titles, etc.
        """
        context = {
            "industry_code": self.industry_code,
            "industry_name": self.industry_name,
            "description": self.description or "",
            "nace_section": self.nace_section or "",
            "nace_division": self.nace_division or "",
            "typical_company_types": self._parse_multiline(self.typical_company_types),
            "typical_products_services": self._parse_multiline(self.typical_products_services),
            "typical_job_titles": self._parse_multiline(self.typical_job_titles),
            "typical_departments": self._parse_multiline(self.typical_departments),
        }

        # Include parent context if available
        if self.parent_industry:
            parent = frappe.get_doc("Mock Industry", self.parent_industry)
            context["parent_context"] = parent.get_ai_context()

        return context

    def _parse_multiline(self, text: str) -> list:
        """Parse multiline text into a list of non-empty lines."""
        if not text:
            return []
        return [line.strip() for line in text.split("\n") if line.strip()]

    def get_faker_hints(self) -> dict:
        """
        Get Faker generation hints for this industry.

        Returns:
            dict: Faker hints including locale and providers
        """
        return {
            "locale": self.faker_locale_hint or None,
            "providers": [
                p.strip()
                for p in (self.faker_providers or "").split(",")
                if p.strip()
            ]
        }

    def get_full_hierarchy(self) -> list:
        """
        Get the full hierarchy path from root to this industry.

        Returns:
            list: List of industry codes from root to this industry
        """
        hierarchy = [self.industry_code]
        current = self.parent_industry
        depth = 0
        max_depth = 10

        while current and depth < max_depth:
            hierarchy.insert(0, current)
            current = frappe.db.get_value("Mock Industry", current, "parent_industry")
            depth += 1

        return hierarchy

    @staticmethod
    def get_enabled_industries() -> list:
        """
        Get all enabled industries.

        Returns:
            list: List of enabled industry codes
        """
        return frappe.get_all(
            "Mock Industry",
            filters={"enabled": 1},
            pluck="name",
            order_by="industry_code"
        )

    @staticmethod
    def get_industries_by_section(section: str) -> list:
        """
        Get all industries in a NACE section.

        Args:
            section: NACE section letter (A-U)

        Returns:
            list: List of industry records in the section
        """
        return frappe.get_all(
            "Mock Industry",
            filters={"nace_section": section.upper(), "enabled": 1},
            fields=["name", "industry_code", "industry_name", "nace_division"],
            order_by="industry_code"
        )

    @staticmethod
    def get_root_industries() -> list:
        """
        Get all top-level industries (no parent).

        Returns:
            list: List of root industry records
        """
        return frappe.get_all(
            "Mock Industry",
            filters={"parent_industry": ["is", "not set"], "enabled": 1},
            fields=["name", "industry_code", "industry_name", "nace_section"],
            order_by="industry_code"
        )
