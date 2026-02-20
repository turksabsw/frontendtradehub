# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestMediaAsset(FrappeTestCase):
    """Test cases for Media Asset DocType."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_asset = None

    def tearDown(self):
        """Clean up test data."""
        if self.test_asset and frappe.db.exists("Media Asset", self.test_asset.name):
            frappe.delete_doc("Media Asset", self.test_asset.name, force=True)

    def create_test_asset(self, **kwargs):
        """Create a test media asset."""
        asset_data = {
            "doctype": "Media Asset",
            "title": kwargs.get("title", "Test Image"),
            "asset_type": kwargs.get("asset_type", "Image"),
            "file_url": kwargs.get("file_url", "/files/test_image.jpg"),
            "status": kwargs.get("status", "Active")
        }
        asset_data.update(kwargs)

        asset = frappe.get_doc(asset_data)
        asset.insert()
        self.test_asset = asset
        return asset

    def test_asset_creation(self):
        """Test basic media asset creation."""
        asset = self.create_test_asset(
            title="Product Image 1",
            file_url="/files/product1.jpg"
        )

        self.assertIsNotNone(asset.name)
        self.assertIsNotNone(asset.asset_code)
        self.assertTrue(asset.asset_code.startswith("MDA-"))
        self.assertEqual(asset.asset_type, "Image")
        self.assertEqual(asset.status, "Active")

    def test_asset_code_generation(self):
        """Test unique asset code generation."""
        asset1 = self.create_test_asset(title="Image 1")
        asset1_code = asset1.asset_code

        # Create another asset
        asset2_data = {
            "doctype": "Media Asset",
            "title": "Image 2",
            "asset_type": "Image",
            "file_url": "/files/test2.jpg",
            "status": "Active"
        }
        asset2 = frappe.get_doc(asset2_data)
        asset2.insert()

        # Codes should be different
        self.assertNotEqual(asset1_code, asset2.asset_code)

        # Cleanup
        frappe.delete_doc("Media Asset", asset2.name, force=True)

    def test_file_extension_extraction(self):
        """Test file extension is extracted from URL."""
        asset = self.create_test_asset(file_url="/files/image.png")

        self.assertEqual(asset.file_extension, "png")

    def test_original_filename_extraction(self):
        """Test original filename is extracted from URL."""
        asset = self.create_test_asset(
            file_url="/files/my_product_photo.jpg"
        )

        self.assertEqual(asset.original_filename, "my_product_photo.jpg")

    def test_title_from_filename(self):
        """Test title is set from filename if not provided."""
        asset_data = {
            "doctype": "Media Asset",
            "asset_type": "Image",
            "file_url": "/files/beautiful_sunset.jpg",
            "status": "Active"
        }
        asset = frappe.get_doc(asset_data)
        asset.insert()
        self.test_asset = asset

        self.assertEqual(asset.title, "beautiful_sunset")

    def test_video_asset_type(self):
        """Test video asset type."""
        asset = self.create_test_asset(
            title="Product Video",
            asset_type="Video",
            file_url="/files/demo.mp4"
        )

        self.assertEqual(asset.asset_type, "Video")

    def test_document_asset_type(self):
        """Test document asset type."""
        asset = self.create_test_asset(
            title="Product Manual",
            asset_type="Document",
            file_url="/files/manual.pdf"
        )

        self.assertEqual(asset.asset_type, "Document")

    def test_entity_linking(self):
        """Test linking asset to an entity."""
        # First create a test entity (Category for simplicity)
        if not frappe.db.exists("Category", "Test Category"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "Test Category"
            })
            category.insert()

        asset = self.create_test_asset(
            title="Category Banner",
            entity_type="Category",
            entity_name="Test Category"
        )

        self.assertEqual(asset.entity_type, "Category")
        self.assertEqual(asset.entity_name, "Test Category")

    def test_primary_asset_uniqueness(self):
        """Test that only one asset can be primary per entity."""
        # Create first primary asset
        if not frappe.db.exists("Category", "Test Category 2"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "Test Category 2"
            })
            category.insert()

        asset1 = self.create_test_asset(
            title="Primary Image 1",
            entity_type="Category",
            entity_name="Test Category 2",
            is_primary=1
        )

        self.assertEqual(asset1.is_primary, 1)

        # Create second primary asset for same entity
        asset2_data = {
            "doctype": "Media Asset",
            "title": "Primary Image 2",
            "asset_type": "Image",
            "file_url": "/files/test3.jpg",
            "status": "Active",
            "entity_type": "Category",
            "entity_name": "Test Category 2",
            "is_primary": 1
        }
        asset2 = frappe.get_doc(asset2_data)
        asset2.insert()

        # Refresh asset1 to check if is_primary was unset
        asset1.reload()

        # First asset should no longer be primary
        self.assertEqual(asset1.is_primary, 0)
        self.assertEqual(asset2.is_primary, 1)

        # Cleanup
        frappe.delete_doc("Media Asset", asset2.name, force=True)

    def test_asset_position(self):
        """Test asset position field."""
        asset = self.create_test_asset(
            title="Gallery Image",
            position=5
        )

        self.assertEqual(asset.position, 5)

    def test_alt_text_and_caption(self):
        """Test alt text and caption fields."""
        asset = self.create_test_asset(
            title="Product Shot",
            alt_text="Front view of product",
            caption="Our flagship product from multiple angles"
        )

        self.assertEqual(asset.alt_text, "Front view of product")
        self.assertEqual(asset.caption, "Our flagship product from multiple angles")

    def test_tags(self):
        """Test tags field."""
        asset = self.create_test_asset(
            title="Lifestyle Photo",
            tags="product, lifestyle, outdoor, summer"
        )

        self.assertIn("lifestyle", asset.tags)
        self.assertIn("outdoor", asset.tags)

    def test_folder_organization(self):
        """Test folder field for organization."""
        asset = self.create_test_asset(
            title="Banner Image",
            folder="banners/homepage"
        )

        self.assertEqual(asset.folder, "banners/homepage")

    def test_moderation_approve(self):
        """Test asset moderation approval."""
        asset = self.create_test_asset(
            title="Pending Image",
            moderation_status="Pending"
        )

        asset.approve()
        asset.reload()

        self.assertEqual(asset.moderation_status, "Approved")
        self.assertIsNotNone(asset.moderated_by)
        self.assertIsNotNone(asset.moderated_at)

    def test_moderation_reject(self):
        """Test asset moderation rejection."""
        asset = self.create_test_asset(
            title="Problematic Image",
            moderation_status="In Review"
        )

        asset.reject("Contains prohibited content")
        asset.reload()

        self.assertEqual(asset.moderation_status, "Rejected")
        self.assertEqual(asset.moderation_notes, "Contains prohibited content")
        self.assertEqual(asset.status, "Archived")

    def test_moderation_reject_requires_reason(self):
        """Test that rejection requires a reason."""
        asset = self.create_test_asset(
            title="Test Image",
            moderation_status="In Review"
        )

        with self.assertRaises(frappe.ValidationError):
            asset.reject(None)

    def test_moderation_flag(self):
        """Test asset flagging."""
        asset = self.create_test_asset(
            title="Suspicious Image",
            moderation_status="Approved"
        )

        asset.flag("Reported by user for review")
        asset.reload()

        self.assertEqual(asset.moderation_status, "Flagged")
        self.assertIn("Reported by user", asset.moderation_notes)

    def test_usage_count_increment(self):
        """Test usage count increment."""
        asset = self.create_test_asset(title="Shared Image")

        initial_count = asset.usage_count or 0
        asset.increment_usage()
        asset.reload()

        self.assertEqual(asset.usage_count, initial_count + 1)

    def test_usage_count_decrement(self):
        """Test usage count decrement."""
        asset = self.create_test_asset(title="Shared Image")

        # First increment
        asset.increment_usage()
        asset.increment_usage()
        asset.reload()

        count_after_increment = asset.usage_count

        # Then decrement
        asset.decrement_usage()
        asset.reload()

        self.assertEqual(asset.usage_count, count_after_increment - 1)

    def test_usage_count_not_negative(self):
        """Test usage count doesn't go negative."""
        asset = self.create_test_asset(title="Test Image")
        asset.db_set("usage_count", 0)

        asset.decrement_usage()
        asset.reload()

        self.assertEqual(asset.usage_count, 0)

    def test_record_access(self):
        """Test recording last access time."""
        asset = self.create_test_asset(title="Accessed Image")

        asset.record_access()
        asset.reload()

        self.assertIsNotNone(asset.last_accessed_at)

    def test_get_url_original(self):
        """Test getting original URL."""
        asset = self.create_test_asset(
            file_url="/files/original.jpg"
        )

        url = asset.get_url("original")
        self.assertEqual(url, "/files/original.jpg")

    def test_get_url_with_optimized(self):
        """Test getting optimized URL when available."""
        asset = self.create_test_asset(
            file_url="/files/original.jpg"
        )
        asset.db_set("is_optimized", 1)
        asset.db_set("optimized_url", "/files/original_optimized.webp")
        asset.reload()

        url = asset.get_url("original")
        self.assertEqual(url, "/files/original_optimized.webp")

    def test_get_url_thumbnail(self):
        """Test getting thumbnail URL."""
        asset = self.create_test_asset(
            file_url="/files/original.jpg"
        )
        asset.db_set("thumbnail_url", "/files/original_thumb.jpg")
        asset.reload()

        url = asset.get_url("thumbnail")
        self.assertEqual(url, "/files/original_thumb.jpg")

    def test_get_formatted_file_size(self):
        """Test file size formatting."""
        asset = self.create_test_asset(title="Large Image")

        # Test bytes
        asset.file_size = 500
        self.assertEqual(asset.get_formatted_file_size(), "500 B")

        # Test KB
        asset.file_size = 2048
        self.assertEqual(asset.get_formatted_file_size(), "2.0 KB")

        # Test MB
        asset.file_size = 5 * 1024 * 1024
        self.assertEqual(asset.get_formatted_file_size(), "5.0 MB")

    def test_get_dimensions(self):
        """Test dimensions formatting."""
        asset = self.create_test_asset(title="Sized Image")

        asset.width = 1920
        asset.height = 1080

        self.assertEqual(asset.get_dimensions(), "1920x1080")

    def test_get_dimensions_none(self):
        """Test dimensions when not set."""
        asset = self.create_test_asset(title="Unsized Image")

        self.assertIsNone(asset.get_dimensions())

    def test_cannot_delete_in_use_asset(self):
        """Test that assets in use cannot be deleted."""
        asset = self.create_test_asset(title="In Use Image")
        asset.db_set("usage_count", 5)
        asset.reload()

        with self.assertRaises(frappe.ValidationError):
            asset.delete()

    def test_cdn_settings(self):
        """Test CDN-related fields."""
        asset = self.create_test_asset(
            title="CDN Image",
            cdn_enabled=1,
            cdn_provider="Cloudflare"
        )

        self.assertEqual(asset.cdn_enabled, 1)
        self.assertEqual(asset.cdn_provider, "Cloudflare")

    def test_adult_content_flag(self):
        """Test adult content flag."""
        asset = self.create_test_asset(
            title="Flagged Image",
            is_adult_content=1
        )

        self.assertEqual(asset.is_adult_content, 1)


class TestMediaAssetAPI(FrappeTestCase):
    """Test cases for Media Asset API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_assets = []

    def tearDown(self):
        """Clean up test data."""
        for asset in self.test_assets:
            if frappe.db.exists("Media Asset", asset.name):
                frappe.delete_doc("Media Asset", asset.name, force=True)

    def create_test_asset(self, **kwargs):
        """Create a test media asset."""
        asset_data = {
            "doctype": "Media Asset",
            "title": kwargs.get("title", "Test API Image"),
            "asset_type": kwargs.get("asset_type", "Image"),
            "file_url": kwargs.get("file_url", "/files/api_test.jpg"),
            "status": kwargs.get("status", "Active")
        }
        asset_data.update(kwargs)

        asset = frappe.get_doc(asset_data)
        asset.insert()
        self.test_assets.append(asset)
        return asset

    def test_get_media_asset_by_name(self):
        """Test getting asset by name."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import get_media_asset

        asset = self.create_test_asset(title="API Test Image")

        result = get_media_asset(asset_name=asset.name)

        self.assertEqual(result["name"], asset.name)
        self.assertEqual(result["title"], "API Test Image")

    def test_get_media_asset_by_code(self):
        """Test getting asset by code."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import get_media_asset

        asset = self.create_test_asset(title="Code Test Image")

        result = get_media_asset(asset_code=asset.asset_code)

        self.assertEqual(result["asset_code"], asset.asset_code)

    def test_get_entity_assets(self):
        """Test getting assets for an entity."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import get_entity_assets

        # Create category for testing
        if not frappe.db.exists("Category", "API Test Category"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "API Test Category"
            })
            category.insert()

        # Create multiple assets for the entity
        for i in range(3):
            self.create_test_asset(
                title=f"Entity Image {i}",
                file_url=f"/files/entity_{i}.jpg",
                entity_type="Category",
                entity_name="API Test Category",
                position=i
            )

        assets = get_entity_assets("Category", "API Test Category")

        self.assertEqual(len(assets), 3)

    def test_upload_media_asset(self):
        """Test uploading a new asset via API."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import upload_media_asset

        result = upload_media_asset(
            file_url="/files/uploaded_test.jpg",
            title="Uploaded Image",
            alt_text="Test upload"
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("asset_name", result)
        self.assertIn("asset_code", result)

        # Cleanup
        if result.get("asset_name"):
            frappe.delete_doc("Media Asset", result["asset_name"], force=True)

    def test_set_primary_asset(self):
        """Test setting primary asset via API."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import set_primary_asset

        # Create category
        if not frappe.db.exists("Category", "Primary Test Category"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "Primary Test Category"
            })
            category.insert()

        # Create assets
        asset1 = self.create_test_asset(
            title="Not Primary",
            entity_type="Category",
            entity_name="Primary Test Category",
            is_primary=0
        )

        result = set_primary_asset(asset1.name)

        self.assertEqual(result["status"], "success")

        asset1.reload()
        self.assertEqual(asset1.is_primary, 1)

    def test_reorder_assets(self):
        """Test reordering assets via API."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import reorder_assets
        import json

        # Create category
        if not frappe.db.exists("Category", "Reorder Test Category"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "Reorder Test Category"
            })
            category.insert()

        # Create assets
        assets = []
        for i in range(3):
            asset = self.create_test_asset(
                title=f"Reorder Image {i}",
                file_url=f"/files/reorder_{i}.jpg",
                entity_type="Category",
                entity_name="Reorder Test Category",
                position=i
            )
            assets.append(asset)

        # Reverse order
        new_order = [assets[2].name, assets[1].name, assets[0].name]

        result = reorder_assets(
            "Category",
            "Reorder Test Category",
            json.dumps(new_order)
        )

        self.assertEqual(result["status"], "success")

        # Verify new positions
        assets[0].reload()
        assets[2].reload()

        self.assertEqual(assets[2].position, 0)
        self.assertEqual(assets[0].position, 2)

    def test_moderate_asset_approve(self):
        """Test approving asset via API."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import moderate_asset

        asset = self.create_test_asset(
            title="Moderate Test",
            moderation_status="Pending"
        )

        result = moderate_asset(asset.name, "approve")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["moderation_status"], "Approved")

    def test_moderate_asset_reject(self):
        """Test rejecting asset via API."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import moderate_asset

        asset = self.create_test_asset(
            title="Reject Test",
            moderation_status="In Review"
        )

        result = moderate_asset(
            asset.name,
            "reject",
            reason="Violates content policy"
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["moderation_status"], "Rejected")

    def test_get_media_statistics(self):
        """Test getting media statistics."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import get_media_statistics

        # Create some test assets
        for i in range(2):
            self.create_test_asset(
                title=f"Stats Image {i}",
                file_url=f"/files/stats_{i}.jpg"
            )

        stats = get_media_statistics()

        self.assertIn("total", stats)
        self.assertIn("by_type", stats)
        self.assertIn("by_status", stats)
        self.assertGreaterEqual(stats["total"], 2)

    def test_find_duplicate(self):
        """Test finding duplicate by checksum."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import find_duplicate

        asset = self.create_test_asset(title="Original Image")
        asset.db_set("checksum", "abc123def456")

        result = find_duplicate("abc123def456")

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], asset.name)

    def test_find_duplicate_not_found(self):
        """Test finding duplicate when none exists."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import find_duplicate

        result = find_duplicate("nonexistent_checksum_xyz")

        self.assertIsNone(result)

    def test_delete_media_asset(self):
        """Test deleting asset via API."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import delete_media_asset

        asset = self.create_test_asset(title="Delete Test")
        asset_name = asset.name

        # Remove from test_assets list to prevent double deletion
        self.test_assets.remove(asset)

        result = delete_media_asset(asset_name)

        self.assertEqual(result["status"], "success")
        self.assertFalse(frappe.db.exists("Media Asset", asset_name))

    def test_delete_in_use_asset_fails(self):
        """Test that deleting in-use asset fails."""
        from tradehub_catalog.tradehub_catalog.doctype.media_asset.media_asset import delete_media_asset

        asset = self.create_test_asset(title="In Use Asset")
        asset.db_set("usage_count", 3)

        result = delete_media_asset(asset.name)

        self.assertIn("error", result)
        self.assertTrue(frappe.db.exists("Media Asset", asset.name))
