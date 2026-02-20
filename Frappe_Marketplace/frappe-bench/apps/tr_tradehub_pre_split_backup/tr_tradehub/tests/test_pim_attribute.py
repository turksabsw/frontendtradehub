# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Unit tests for PIM Attribute CRUD operations

Tests the PIM Attribute DocType including:
- Create: Basic creation, validation, type-specific configs
- Read: Retrieval, filtering, helper methods
- Update: Field updates, type changes, options management
- Delete: Standard deletion, system attribute protection
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestPIMAttribute(FrappeTestCase):
    """Test cases for PIM Attribute DocType"""

    def setUp(self):
        """Set up test fixtures"""
        # Clean up any test attributes from previous runs
        self._cleanup_test_attributes()

    def tearDown(self):
        """Clean up after each test"""
        self._cleanup_test_attributes()

    def _cleanup_test_attributes(self):
        """Remove test attributes created during tests"""
        test_codes = [
            "test_text_attr",
            "test_select_attr",
            "test_link_attr",
            "test_numeric_attr",
            "test_measurement_attr",
            "test_system_attr",
            "test_update_attr",
            "test_invalid_code",
            "test_rating_attr",
            "test_percent_attr",
            "test_currency_attr",
            "test_file_attr",
        ]
        for code in test_codes:
            if frappe.db.exists("PIM Attribute", code):
                # Temporarily unset is_system flag to allow deletion
                frappe.db.set_value("PIM Attribute", code, "is_system", 0)
                frappe.delete_doc("PIM Attribute", code, force=True)
        frappe.db.commit()

    # =========================================================================
    # CREATE TESTS
    # =========================================================================

    def test_create_basic_text_attribute(self):
        """Test creating a basic Text type attribute"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Text Attribute",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
        })
        doc.insert()

        self.assertEqual(doc.name, "test_text_attr")
        self.assertEqual(doc.attribute_type, "Text")
        self.assertEqual(doc.is_active, 1)

    def test_create_select_attribute_with_options(self):
        """Test creating a Select type attribute with options"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Select Attribute",
            "attribute_code": "test_select_attr",
            "attribute_type": "Select",
            "options": [
                {"option_value": "option1", "option_label": "Option 1", "sort_order": 1},
                {"option_value": "option2", "option_label": "Option 2", "sort_order": 2},
                {"option_value": "option3", "option_label": "Option 3", "sort_order": 3},
            ]
        })
        doc.insert()

        self.assertEqual(len(doc.options), 3)
        self.assertEqual(doc.options[0].option_value, "option1")

    def test_create_link_attribute(self):
        """Test creating a Link type attribute with DocType configuration"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Link Attribute",
            "attribute_code": "test_link_attr",
            "attribute_type": "Link",
            "link_doctype": "User",
            "link_display_field": "full_name",
        })
        doc.insert()

        self.assertEqual(doc.link_doctype, "User")
        self.assertEqual(doc.link_display_field, "full_name")

    def test_create_numeric_attribute_with_constraints(self):
        """Test creating a numeric attribute with min/max constraints"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Numeric Attribute",
            "attribute_code": "test_numeric_attr",
            "attribute_type": "Int",
            "min_value": 0,
            "max_value": 100,
        })
        doc.insert()

        self.assertEqual(doc.min_value, 0)
        self.assertEqual(doc.max_value, 100)

    def test_create_measurement_attribute(self):
        """Test creating a Measurement type attribute"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Measurement Attribute",
            "attribute_code": "test_measurement_attr",
            "attribute_type": "Measurement",
            "measurement_unit": "kg",
            "measurement_precision": 3,
        })
        doc.insert()

        self.assertEqual(doc.measurement_unit, "kg")
        self.assertEqual(doc.measurement_precision, 3)

    def test_create_rating_attribute_defaults(self):
        """Test that Rating attribute gets default min/max values"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Rating Attribute",
            "attribute_code": "test_rating_attr",
            "attribute_type": "Rating",
        })
        doc.insert()

        self.assertEqual(doc.min_value, 0)
        self.assertEqual(doc.max_value, 5)

    def test_create_percent_attribute_defaults(self):
        """Test that Percent attribute gets default min/max values"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Percent Attribute",
            "attribute_code": "test_percent_attr",
            "attribute_type": "Percent",
        })
        doc.insert()

        self.assertEqual(doc.min_value, 0)
        self.assertEqual(doc.max_value, 100)

    def test_create_currency_attribute_defaults(self):
        """Test that Currency attribute gets default precision"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Currency Attribute",
            "attribute_code": "test_currency_attr",
            "attribute_type": "Currency",
        })
        doc.insert()

        self.assertEqual(doc.currency_precision, 2)

    def test_create_file_attribute_with_extensions(self):
        """Test creating a File type attribute with allowed extensions"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test File Attribute",
            "attribute_code": "test_file_attr",
            "attribute_type": "File",
            "allowed_extensions": ".PDF, .DOC, docx",
            "max_file_size": 5000,
        })
        doc.insert()

        # Extensions should be normalized (lowercase, no dots)
        self.assertEqual(doc.allowed_extensions, "pdf,doc,docx")

    # =========================================================================
    # VALIDATION TESTS
    # =========================================================================

    def test_validate_attribute_code_format(self):
        """Test that attribute_code is normalized to lowercase with underscores"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Code Format",
            "attribute_code": "Test-Code Format",
            "attribute_type": "Text",
        })
        doc.insert()

        self.assertEqual(doc.attribute_code, "test_code_format")

    def test_validate_attribute_code_invalid_start(self):
        """Test that attribute_code must start with a letter"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Invalid Code",
            "attribute_code": "123_invalid",
            "attribute_type": "Text",
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert()

    def test_validate_attribute_code_too_short(self):
        """Test that attribute_code must be at least 2 characters"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Short Code",
            "attribute_code": "a",
            "attribute_type": "Text",
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert()

    def test_validate_link_attribute_requires_doctype(self):
        """Test that Link type attribute requires link_doctype"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Invalid Link",
            "attribute_code": "test_link_attr",
            "attribute_type": "Link",
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert()

    def test_validate_link_attribute_invalid_doctype(self):
        """Test that Link type validates DocType exists"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Invalid Link DocType",
            "attribute_code": "test_link_attr",
            "attribute_type": "Link",
            "link_doctype": "NonExistentDocType",
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert()

    def test_validate_numeric_range(self):
        """Test that min_value cannot be greater than max_value"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Invalid Range",
            "attribute_code": "test_numeric_attr",
            "attribute_type": "Int",
            "min_value": 100,
            "max_value": 50,
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert()

    def test_validate_link_filters_json(self):
        """Test that link_filters must be valid JSON"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Invalid JSON",
            "attribute_code": "test_link_attr",
            "attribute_type": "Link",
            "link_doctype": "User",
            "link_filters": "{ invalid json }",
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert()

    def test_validate_duplicate_options(self):
        """Test that Select options must have unique values"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Duplicate Options",
            "attribute_code": "test_select_attr",
            "attribute_type": "Select",
            "options": [
                {"option_value": "same", "option_label": "Option 1", "sort_order": 1},
                {"option_value": "same", "option_label": "Option 2", "sort_order": 2},
            ]
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert()

    # =========================================================================
    # READ TESTS
    # =========================================================================

    def test_read_attribute_by_name(self):
        """Test retrieving an attribute by its name"""
        # Create attribute
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Test Read Attribute",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
        })
        doc.insert()

        # Read it back
        retrieved = frappe.get_doc("PIM Attribute", "test_text_attr")
        self.assertEqual(retrieved.attribute_name, "Test Read Attribute")

    def test_read_attribute_filters(self):
        """Test filtering attributes by type"""
        # Create test attributes
        frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Filter Test Text",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
            "is_filterable": 1,
        }).insert()

        frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Filter Test Select",
            "attribute_code": "test_select_attr",
            "attribute_type": "Select",
            "is_filterable": 0,
        }).insert()

        # Query filterable attributes
        filterable = frappe.get_all(
            "PIM Attribute",
            filters={"is_filterable": 1, "attribute_code": ["like", "test_%"]},
            fields=["attribute_code"]
        )
        codes = [a.attribute_code for a in filterable]

        self.assertIn("test_text_attr", codes)
        self.assertNotIn("test_select_attr", codes)

    def test_get_frappe_fieldtype_method(self):
        """Test the get_frappe_fieldtype helper method"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Fieldtype Test",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
        })
        doc.insert()

        self.assertEqual(doc.get_frappe_fieldtype(), "Data")

        # Test other mappings
        test_mappings = {
            "Long Text": "Text",
            "HTML": "Text Editor",
            "Int": "Int",
            "Float": "Float",
            "Select": "Select",
            "Date": "Date",
            "Link": "Link",
            "Image": "Attach Image",
            "File": "Attach",
            "Rating": "Rating",
        }

        for pim_type, frappe_type in test_mappings.items():
            doc.attribute_type = pim_type
            self.assertEqual(
                doc.get_frappe_fieldtype(),
                frappe_type,
                f"Failed for {pim_type}"
            )

    def test_get_field_options_method(self):
        """Test the get_field_options helper method"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Options Test",
            "attribute_code": "test_select_attr",
            "attribute_type": "Select",
            "options": [
                {"option_value": "red", "option_label": "Red", "sort_order": 1},
                {"option_value": "green", "option_label": "Green", "sort_order": 2},
                {"option_value": "blue", "option_label": "Blue", "sort_order": 3},
            ]
        })
        doc.insert()

        options = doc.get_field_options()
        self.assertEqual(options, "red\ngreen\nblue")

    def test_get_validation_dict_method(self):
        """Test the get_validation_dict helper method"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Validation Test",
            "attribute_code": "test_numeric_attr",
            "attribute_type": "Int",
            "is_required": 1,
            "is_unique": 1,
            "min_value": 0,
            "max_value": 100,
            "validation_regex": r"^\d+$",
            "validation_message": "Must be a number",
        })
        doc.insert()

        validation = doc.get_validation_dict()

        self.assertEqual(validation.get("reqd"), 1)
        self.assertEqual(validation.get("unique"), 1)
        self.assertEqual(validation.get("min_value"), 0)
        self.assertEqual(validation.get("max_value"), 100)
        self.assertEqual(validation.get("regex"), r"^\d+$")
        self.assertEqual(validation.get("regex_message"), "Must be a number")

    # =========================================================================
    # UPDATE TESTS
    # =========================================================================

    def test_update_attribute_fields(self):
        """Test updating attribute fields"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Update Test",
            "attribute_code": "test_update_attr",
            "attribute_type": "Text",
            "is_filterable": 0,
        })
        doc.insert()

        # Update fields
        doc.attribute_name = "Updated Name"
        doc.is_filterable = 1
        doc.is_searchable = 1
        doc.save()

        # Verify updates
        updated = frappe.get_doc("PIM Attribute", "test_update_attr")
        self.assertEqual(updated.attribute_name, "Updated Name")
        self.assertEqual(updated.is_filterable, 1)
        self.assertEqual(updated.is_searchable, 1)

    def test_update_attribute_options(self):
        """Test adding/removing options from Select attribute"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Options Update Test",
            "attribute_code": "test_select_attr",
            "attribute_type": "Select",
            "options": [
                {"option_value": "opt1", "option_label": "Option 1", "sort_order": 1},
            ]
        })
        doc.insert()

        # Add more options
        doc.append("options", {
            "option_value": "opt2",
            "option_label": "Option 2",
            "sort_order": 2,
        })
        doc.save()

        updated = frappe.get_doc("PIM Attribute", "test_select_attr")
        self.assertEqual(len(updated.options), 2)

    def test_update_attribute_type_with_revalidation(self):
        """Test changing attribute type triggers revalidation"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Type Change Test",
            "attribute_code": "test_update_attr",
            "attribute_type": "Text",
        })
        doc.insert()

        # Change to Int type with constraints
        doc.attribute_type = "Int"
        doc.min_value = 0
        doc.max_value = 100
        doc.save()

        updated = frappe.get_doc("PIM Attribute", "test_update_attr")
        self.assertEqual(updated.attribute_type, "Int")
        self.assertEqual(updated.min_value, 0)

    # =========================================================================
    # DELETE TESTS
    # =========================================================================

    def test_delete_attribute(self):
        """Test deleting a regular attribute"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Delete Test",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
        })
        doc.insert()

        # Delete the attribute
        frappe.delete_doc("PIM Attribute", "test_text_attr")

        self.assertFalse(frappe.db.exists("PIM Attribute", "test_text_attr"))

    def test_delete_system_attribute_prevented(self):
        """Test that system attributes cannot be deleted"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "System Attribute Test",
            "attribute_code": "test_system_attr",
            "attribute_type": "Text",
            "is_system": 1,
        })
        doc.insert()

        with self.assertRaises(frappe.exceptions.ValidationError):
            frappe.delete_doc("PIM Attribute", "test_system_attr")

    def test_rename_system_attribute_prevented(self):
        """Test that system attributes cannot be renamed"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "System Rename Test",
            "attribute_code": "test_system_attr",
            "attribute_type": "Text",
            "is_system": 1,
        })
        doc.insert()

        with self.assertRaises(frappe.exceptions.ValidationError):
            frappe.rename_doc("PIM Attribute", "test_system_attr", "renamed_attr")

    def test_merge_not_allowed(self):
        """Test that merging PIM Attributes is not allowed"""
        doc1 = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Merge Test 1",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
        })
        doc1.insert()

        doc2 = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Merge Test 2",
            "attribute_code": "test_update_attr",
            "attribute_type": "Text",
        })
        doc2.insert()

        with self.assertRaises(frappe.exceptions.ValidationError):
            frappe.rename_doc(
                "PIM Attribute",
                "test_update_attr",
                "test_text_attr",
                merge=True
            )

    # =========================================================================
    # MARKETPLACE FLAGS TESTS
    # =========================================================================

    def test_marketplace_flags(self):
        """Test setting marketplace integration flags"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Marketplace Test",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
            "used_by_amazon": 1,
            "amazon_attribute_name": "item_name",
            "used_by_trendyol": 1,
            "trendyol_attribute_name": "urun_adi",
        })
        doc.insert()

        retrieved = frappe.get_doc("PIM Attribute", "test_text_attr")
        self.assertEqual(retrieved.used_by_amazon, 1)
        self.assertEqual(retrieved.amazon_attribute_name, "item_name")
        self.assertEqual(retrieved.used_by_trendyol, 1)
        self.assertEqual(retrieved.trendyol_attribute_name, "urun_adi")

    # =========================================================================
    # LOCALIZATION TESTS
    # =========================================================================

    def test_localizable_attribute(self):
        """Test creating a localizable attribute"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Localizable Test",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
            "is_localizable": 1,
            "default_locale": "en_US",
        })
        doc.insert()

        retrieved = frappe.get_doc("PIM Attribute", "test_text_attr")
        self.assertEqual(retrieved.is_localizable, 1)
        self.assertEqual(retrieved.default_locale, "en_US")

    def test_scopable_attribute(self):
        """Test creating a scopable attribute"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Scopable Test",
            "attribute_code": "test_text_attr",
            "attribute_type": "Text",
            "is_scopable": 1,
            "default_scope": "ecommerce",
        })
        doc.insert()

        retrieved = frappe.get_doc("PIM Attribute", "test_text_attr")
        self.assertEqual(retrieved.is_scopable, 1)
        self.assertEqual(retrieved.default_scope, "ecommerce")

    # =========================================================================
    # VARIANT AXIS TESTS
    # =========================================================================

    def test_variant_axis_attribute(self):
        """Test creating an attribute that can be used as variant axis"""
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": "Color",
            "attribute_code": "test_select_attr",
            "attribute_type": "Color",
            "use_for_variant": 1,
            "options": [
                {"option_value": "red", "option_label": "Red", "color_hex": "#FF0000"},
                {"option_value": "blue", "option_label": "Blue", "color_hex": "#0000FF"},
            ]
        })
        doc.insert()

        retrieved = frappe.get_doc("PIM Attribute", "test_select_attr")
        self.assertEqual(retrieved.use_for_variant, 1)
        self.assertEqual(retrieved.options[0].color_hex, "#FF0000")
