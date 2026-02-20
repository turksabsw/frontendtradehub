"""
Scheduled tasks for TradeHub Catalog module.

Tasks moved from the monolithic tr_tradehub app during decomposition:
- media_processor: Hourly task to process pending media assets
- ranking: Daily task to recalculate product search rankings
"""

import frappe
from frappe.utils import nowdate, now_datetime, getdate, add_days


def media_processor():
    """
    Hourly scheduled task to process pending media assets.

    This task:
    1. Finds Media Asset records with status='Pending'
    2. Generates thumbnails for images
    3. Optimizes images for web delivery
    4. Updates CDN links
    5. Updates Media Asset status to 'Processed'

    Business Rules:
    - Process max 50 assets per run to avoid timeout
    - Prioritize product images over other media types
    - Skip assets larger than 50MB (flag for manual review)
    """
    frappe.logger("tradehub_catalog").info("Running media_processor scheduled task")

    try:
        # Get pending media assets
        pending_assets = frappe.get_all(
            "Media Asset",
            filters={
                "status": "Pending",
                "file_size": ["<", 50 * 1024 * 1024]  # Less than 50MB
            },
            fields=["name", "file_url", "file_type", "media_library"],
            order_by="creation asc",
            limit=50
        )

        processed_count = 0
        failed_count = 0

        for asset in pending_assets:
            try:
                process_media_asset(asset)
                processed_count += 1
            except Exception as e:
                failed_count += 1
                frappe.log_error(
                    message=f"Failed to process media asset {asset.name}: {str(e)}",
                    title="Media Processor Error"
                )
                # Mark as failed for manual review
                frappe.db.set_value("Media Asset", asset.name, "status", "Failed")

        frappe.db.commit()

        frappe.logger("tradehub_catalog").info(
            f"Media processor completed: {processed_count} processed, {failed_count} failed"
        )

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title="Media Processor Task Failed"
        )


def process_media_asset(asset):
    """
    Process a single media asset.

    Steps:
    1. Download file if from external URL
    2. Generate variants (thumbnail, small, medium, large)
    3. Optimize for web delivery
    4. Upload to CDN
    5. Update Media Asset with processed URLs

    Args:
        asset: Dict with name, file_url, file_type, media_library
    """
    file_type = asset.get("file_type", "").lower()

    if file_type in ["image/jpeg", "image/png", "image/webp", "jpg", "png", "webp"]:
        # Image processing
        process_image_asset(asset)
    elif file_type in ["video/mp4", "video/webm", "mp4", "webm"]:
        # Video processing
        process_video_asset(asset)
    elif file_type in ["application/pdf", "pdf"]:
        # PDF processing (generate thumbnail of first page)
        process_pdf_asset(asset)
    else:
        # Skip unsupported types, mark as processed
        frappe.db.set_value("Media Asset", asset.get("name"), "status", "Processed")

    frappe.db.set_value("Media Asset", asset.get("name"), {
        "status": "Processed",
        "processed_at": now_datetime()
    })


def process_image_asset(asset):
    """
    Process image asset - generate thumbnails and optimize.

    Generates:
    - thumbnail: 100x100
    - small: 300x300
    - medium: 600x600
    - large: 1200x1200
    """
    # In real implementation, this would use Pillow or similar
    # to generate resized versions and optimize file size
    frappe.logger("tradehub_catalog").debug(
        f"Processing image asset: {asset.get('name')}"
    )


def process_video_asset(asset):
    """
    Process video asset - generate thumbnail and optimize.
    """
    # In real implementation, this would use ffmpeg
    # to generate thumbnail from video frame
    frappe.logger("tradehub_catalog").debug(
        f"Processing video asset: {asset.get('name')}"
    )


def process_pdf_asset(asset):
    """
    Process PDF asset - generate thumbnail of first page.
    """
    # In real implementation, this would use pdf2image or similar
    # to generate thumbnail from first page
    frappe.logger("tradehub_catalog").debug(
        f"Processing PDF asset: {asset.get('name')}"
    )


def ranking():
    """
    Daily scheduled task to recalculate product search rankings.

    This task:
    1. Fetches all published products
    2. Calculates ranking score based on multiple factors
    3. Updates Product.ranking_score field
    4. Updates search index if configured

    Ranking Factors:
    - Sales velocity (orders in last 30 days)
    - Conversion rate
    - Review score
    - Stock availability
    - Content completeness
    - Seller score
    """
    frappe.logger("tradehub_catalog").info("Running product ranking scheduled task")

    try:
        # Get ranking weight configuration
        weights = get_ranking_weights()

        # Get all published products
        products = frappe.get_all(
            "Product",
            filters={"status": "Published"},
            fields=["name"]
        )

        for product in products:
            try:
                calculate_product_ranking(product.name, weights)
            except Exception as e:
                frappe.log_error(
                    message=f"Failed to rank product {product.name}: {str(e)}",
                    title="Product Ranking Error"
                )

        frappe.db.commit()

        frappe.logger("tradehub_catalog").info(
            f"Product ranking completed: {len(products)} products processed"
        )

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title="Product Ranking Task Failed"
        )


def get_ranking_weights():
    """
    Get ranking weight configuration from Ranking Weight Config DocType.

    Returns:
        Dict with weight factors (0.0 to 1.0 each)
    """
    default_weights = {
        "sales_velocity": 0.25,
        "conversion_rate": 0.20,
        "review_score": 0.20,
        "stock_availability": 0.15,
        "content_completeness": 0.10,
        "seller_score": 0.10
    }

    # Try to get from Ranking Weight Config
    try:
        config = frappe.get_doc("Ranking Weight Config", "Default")
        return {
            "sales_velocity": config.sales_velocity_weight or 0.25,
            "conversion_rate": config.conversion_rate_weight or 0.20,
            "review_score": config.review_score_weight or 0.20,
            "stock_availability": config.stock_availability_weight or 0.15,
            "content_completeness": config.content_completeness_weight or 0.10,
            "seller_score": config.seller_score_weight or 0.10
        }
    except Exception:
        return default_weights


def calculate_product_ranking(product_name, weights):
    """
    Calculate ranking score for a single product.

    Args:
        product_name: Name of the Product document
        weights: Dict with ranking weight factors

    Returns:
        float: Ranking score (0-100)
    """
    # Get product details
    product = frappe.get_doc("Product", product_name)

    # Calculate individual factor scores
    sales_score = calculate_sales_velocity_score(product_name)
    conversion_score = calculate_conversion_score(product_name)
    review_score = calculate_review_score(product_name)
    stock_score = calculate_stock_score(product_name)
    content_score = calculate_content_completeness_score(product)
    seller_score = calculate_seller_score_for_product(product_name)

    # Calculate weighted total
    ranking_score = (
        sales_score * weights["sales_velocity"] +
        conversion_score * weights["conversion_rate"] +
        review_score * weights["review_score"] +
        stock_score * weights["stock_availability"] +
        content_score * weights["content_completeness"] +
        seller_score * weights["seller_score"]
    )

    # Normalize to 0-100
    ranking_score = min(100, max(0, ranking_score))

    # Update product ranking score
    frappe.db.set_value("Product", product_name, "ranking_score", ranking_score)

    return ranking_score


def calculate_sales_velocity_score(product_name):
    """
    Calculate sales velocity score based on orders in last 30 days.
    """
    # In real implementation, would query Order DocType
    # For now, return placeholder
    return 50.0


def calculate_conversion_score(product_name):
    """
    Calculate conversion score (views to orders ratio).
    """
    # In real implementation, would query analytics data
    return 50.0


def calculate_review_score(product_name):
    """
    Calculate review score based on average rating.
    """
    # In real implementation, would query Review DocType
    # from tradehub_compliance
    avg_rating = frappe.db.get_value(
        "Review",
        {"subject_type": "Product", "subject_name": product_name, "status": "Published"},
        "avg(rating)"
    ) or 0

    # Convert 0-5 rating to 0-100 score
    return min(100, (avg_rating / 5.0) * 100)


def calculate_stock_score(product_name):
    """
    Calculate stock availability score.
    """
    # In real implementation, would check Listing stock quantities
    total_stock = frappe.db.get_value(
        "Listing",
        {"product": product_name, "status": "Active"},
        "sum(stock_quantity)"
    ) or 0

    # Score based on stock level
    if total_stock >= 100:
        return 100.0
    elif total_stock >= 50:
        return 80.0
    elif total_stock >= 10:
        return 50.0
    elif total_stock > 0:
        return 30.0
    else:
        return 0.0


def calculate_content_completeness_score(product):
    """
    Calculate content completeness score based on filled fields.
    """
    required_fields = [
        "product_name", "description", "category", "brand"
    ]
    optional_fields = [
        "short_description", "meta_title", "meta_description"
    ]

    filled_required = sum(1 for f in required_fields if product.get(f))
    filled_optional = sum(1 for f in optional_fields if product.get(f))

    required_score = (filled_required / len(required_fields)) * 70
    optional_score = (filled_optional / len(optional_fields)) * 30

    return required_score + optional_score


def calculate_seller_score_for_product(product_name):
    """
    Calculate average seller score for sellers listing this product.
    """
    # Get all active listings for this product
    avg_score = frappe.db.sql("""
        SELECT AVG(ss.composite_score)
        FROM `tabListing` l
        JOIN `tabSeller Score` ss ON ss.seller_profile = l.seller_profile
        WHERE l.product = %s AND l.status = 'Active'
    """, product_name)

    if avg_score and avg_score[0][0]:
        return min(100, float(avg_score[0][0]))
    return 50.0
