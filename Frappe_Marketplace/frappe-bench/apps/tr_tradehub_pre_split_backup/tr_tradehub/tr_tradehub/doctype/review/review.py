# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, get_datetime, date_diff, strip_html_tags
)
import json
import re


class Review(Document):
    """
    Review DocType for TR-TradeHub.

    Handles product and seller reviews with:
    - Order verification (verified purchase)
    - Rating system (1-5 stars + detailed ratings)
    - Media attachments (images, video)
    - Moderation workflow
    - Seller response capability
    - Helpfulness voting
    """

    def before_insert(self):
        """Set default values before creating a new review."""
        # Generate unique review ID
        if not self.review_id:
            self.review_id = self.generate_review_id()

        # Set reviewer if not provided
        if not self.reviewer:
            self.reviewer = frappe.session.user

        # Set submitted timestamp
        self.submitted_at = now_datetime()

        # Capture request metadata
        self.capture_request_metadata()

        # Set display name
        if not self.display_name:
            self.set_display_name()

        # Verify order if applicable
        if self.marketplace_order:
            self.verify_order()

        # Auto-populate seller from listing
        if self.review_type == "Product" and self.listing and not self.seller:
            self.seller = frappe.db.get_value("Listing", self.listing, "seller")

        # Auto-populate category from listing
        if self.listing and not self.category:
            self.category = frappe.db.get_value("Listing", self.listing, "category")

    def validate(self):
        """Validate review data before saving."""
        self.validate_reviewer()
        self.validate_rating()
        self.validate_review_content()
        self.validate_target()
        self.validate_detailed_ratings()
        self.validate_media()
        self.validate_duplicate_review()

        # Check for order verification if order is provided
        if self.marketplace_order and not self.is_verified_purchase:
            self.verify_order()

        # Calculate helpfulness score
        self.calculate_helpfulness_score()

    def on_update(self):
        """Actions after review is updated."""
        # Track edit count
        if not self.is_new():
            self.db_set("edit_count", cint(self.edit_count) + 1)
            self.db_set("last_edited_at", now_datetime())

        # Update listing/seller ratings if published
        if self.status == "Published":
            self.update_target_ratings()

    def on_trash(self):
        """Actions when review is deleted."""
        # Update listing/seller ratings
        self.update_target_ratings(removing=True)

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_review_id(self):
        """Generate a unique review identifier."""
        return f"RVW-{frappe.generate_hash(length=10).upper()}"

    def capture_request_metadata(self):
        """Capture IP address and user agent."""
        if hasattr(frappe.request, "remote_addr"):
            self.ip_address = frappe.request.remote_addr
        if hasattr(frappe.request, "headers"):
            self.user_agent = frappe.request.headers.get("User-Agent", "")[:500]

    def set_display_name(self):
        """Set the display name for the review."""
        if self.is_anonymous:
            # Mask the name for anonymous reviews
            full_name = self.reviewer_name or frappe.db.get_value(
                "User", self.reviewer, "full_name"
            )
            if full_name:
                # Show first letter + asterisks + last letter (e.g., "A***z")
                if len(full_name) > 2:
                    self.display_name = f"{full_name[0]}***{full_name[-1]}"
                else:
                    self.display_name = f"{full_name[0]}***"
            else:
                self.display_name = "Anonymous"
        else:
            self.display_name = self.reviewer_name or frappe.db.get_value(
                "User", self.reviewer, "full_name"
            ) or self.reviewer

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_reviewer(self):
        """Validate reviewer information."""
        if not self.reviewer:
            frappe.throw(_("Reviewer is required"))

        if not frappe.db.exists("User", self.reviewer):
            frappe.throw(_("Reviewer {0} does not exist").format(self.reviewer))

        # Ensure user is not a guest
        if self.reviewer == "Guest":
            frappe.throw(_("Guest users cannot leave reviews"))

    def validate_rating(self):
        """Validate rating is within bounds."""
        if not self.rating:
            frappe.throw(_("Rating is required"))

        # Frappe Rating field stores value as 0-1 (fractional)
        # Convert to 1-5 scale if needed
        if flt(self.rating) > 5:
            self.rating = 5
        elif flt(self.rating) < 1:
            self.rating = 1

    def validate_review_content(self):
        """Validate review text meets requirements."""
        if not self.review_text:
            frappe.throw(_("Review text is required"))

        # Strip HTML and check minimum length
        plain_text = strip_html_tags(self.review_text or "")
        if len(plain_text.strip()) < 20:
            frappe.throw(
                _("Review must be at least 20 characters long")
            )

        if len(plain_text) > 5000:
            frappe.throw(
                _("Review cannot exceed 5000 characters")
            )

        # Check for potential spam patterns
        if self.contains_spam_patterns(plain_text):
            self.moderation_status = "Flagged"
            self.flags = json.dumps(["potential_spam"])

    def validate_target(self):
        """Validate review target based on type."""
        if self.review_type == "Product":
            if not self.listing:
                frappe.throw(_("Listing is required for product reviews"))

            if not frappe.db.exists("Listing", self.listing):
                frappe.throw(
                    _("Listing {0} does not exist").format(self.listing)
                )

            # Check listing is active
            listing_status = frappe.db.get_value(
                "Listing", self.listing, "status"
            )
            if listing_status not in ["Active", "Paused", "Out of Stock"]:
                frappe.throw(
                    _("Cannot review listing in {0} status").format(listing_status)
                )

        elif self.review_type == "Seller":
            if not self.seller:
                frappe.throw(_("Seller is required for seller reviews"))

            if not frappe.db.exists("Seller Profile", self.seller):
                frappe.throw(
                    _("Seller {0} does not exist").format(self.seller)
                )

            # Check seller is active
            seller_status = frappe.db.get_value(
                "Seller Profile", self.seller, "status"
            )
            if seller_status != "Active":
                frappe.throw(_("Cannot review inactive seller"))

    def validate_detailed_ratings(self):
        """Validate detailed rating values."""
        rating_fields = [
            "product_quality_rating",
            "value_for_money_rating",
            "shipping_rating",
            "seller_communication_rating",
            "accuracy_rating"
        ]

        for field in rating_fields:
            value = cint(getattr(self, field, 0))
            if value < 0 or value > 5:
                setattr(self, field, min(max(value, 0), 5))

    def validate_media(self):
        """Validate media attachments."""
        if self.images:
            try:
                images = json.loads(self.images) if isinstance(self.images, str) else self.images
                if isinstance(images, list) and len(images) > 5:
                    frappe.throw(_("Maximum 5 images allowed per review"))
            except json.JSONDecodeError:
                self.images = "[]"

        if self.video_url:
            # Validate video URL format
            video_patterns = [
                r"youtube\.com",
                r"youtu\.be",
                r"vimeo\.com",
                r"dailymotion\.com"
            ]
            if not any(re.search(p, self.video_url) for p in video_patterns):
                frappe.throw(
                    _("Video URL must be from YouTube, Vimeo, or Dailymotion")
                )

    def validate_duplicate_review(self):
        """Check for duplicate reviews."""
        if self.is_new():
            filters = {
                "reviewer": self.reviewer,
                "review_type": self.review_type,
                "status": ["not in", ["Removed", "Rejected"]]
            }

            if self.review_type == "Product" and self.listing:
                filters["listing"] = self.listing
            elif self.review_type == "Seller" and self.seller:
                filters["seller"] = self.seller

            existing = frappe.db.exists("Review", filters)
            if existing:
                frappe.throw(
                    _("You have already reviewed this {0}").format(
                        "product" if self.review_type == "Product" else "seller"
                    )
                )

    def contains_spam_patterns(self, text):
        """Check for common spam patterns."""
        spam_patterns = [
            r"(buy|cheap|discount|sale|offer)\s+now",
            r"http[s]?://(?!youtube|vimeo)",
            r"bit\.ly|goo\.gl|tinyurl",
            r"\b(viagra|cialis|lottery|casino)\b",
            r"(.)\1{5,}",  # Repeated characters
            r"[A-Z]{10,}"  # ALL CAPS
        ]

        text_lower = text.lower()
        for pattern in spam_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    # =================================================================
    # Order Verification Methods
    # =================================================================

    def verify_order(self):
        """Verify that the reviewer has purchased the item."""
        if not self.marketplace_order:
            return False

        # Check order exists and belongs to reviewer
        order = frappe.db.get_value(
            "Marketplace Order",
            self.marketplace_order,
            ["buyer", "status", "order_date", "docstatus"],
            as_dict=True
        )

        if not order:
            frappe.throw(_("Order {0} not found").format(self.marketplace_order))

        if order.buyer != self.reviewer:
            frappe.throw(_("You can only review products from your own orders"))

        if order.docstatus == 2:  # Cancelled
            frappe.throw(_("Cannot review cancelled orders"))

        # Check order is delivered/completed
        valid_statuses = ["Delivered", "Completed"]
        if order.status not in valid_statuses:
            frappe.throw(
                _("You can only review after the order is delivered. Current status: {0}").format(
                    order.status
                )
            )

        # For product reviews, verify the listing was in the order
        if self.review_type == "Product" and self.listing:
            item_exists = frappe.db.exists(
                "Marketplace Order Item",
                {
                    "parent": self.marketplace_order,
                    "listing": self.listing
                }
            )

            if not item_exists:
                frappe.throw(
                    _("The product {0} was not found in order {1}").format(
                        self.listing, self.marketplace_order
                    )
                )

            # Get order item details
            order_item = frappe.db.get_value(
                "Marketplace Order Item",
                {
                    "parent": self.marketplace_order,
                    "listing": self.listing
                },
                ["name", "seller"],
                as_dict=True
            )

            if order_item:
                self.order_item = order_item.name
                if not self.seller:
                    self.seller = order_item.seller

        # For seller reviews, verify the seller was in the order
        elif self.review_type == "Seller" and self.seller:
            seller_in_order = frappe.db.exists(
                "Marketplace Order Item",
                {
                    "parent": self.marketplace_order,
                    "seller": self.seller
                }
            )

            if not seller_in_order:
                frappe.throw(
                    _("Seller {0} was not part of order {1}").format(
                        self.seller, self.marketplace_order
                    )
                )

        # Set verification fields
        self.is_verified_purchase = 1
        self.purchase_date = order.order_date
        self.verification_date = now_datetime()

        return True

    @staticmethod
    def check_review_eligibility(reviewer, listing=None, seller=None, order=None):
        """
        Check if a user is eligible to review a product/seller.

        Args:
            reviewer: User email
            listing: Listing name (for product reviews)
            seller: Seller Profile name (for seller reviews)
            order: Specific order to verify against

        Returns:
            dict: Eligibility status and reason
        """
        result = {
            "eligible": False,
            "has_purchased": False,
            "already_reviewed": False,
            "eligible_orders": [],
            "reason": None
        }

        # Check if already reviewed
        existing_review = None
        if listing:
            existing_review = frappe.db.exists(
                "Review",
                {
                    "reviewer": reviewer,
                    "listing": listing,
                    "review_type": "Product",
                    "status": ["not in", ["Removed", "Rejected"]]
                }
            )
        elif seller:
            existing_review = frappe.db.exists(
                "Review",
                {
                    "reviewer": reviewer,
                    "seller": seller,
                    "review_type": "Seller",
                    "status": ["not in", ["Removed", "Rejected"]]
                }
            )

        if existing_review:
            result["already_reviewed"] = True
            result["reason"] = _("You have already reviewed this item")
            return result

        # Find eligible orders (delivered orders containing the item)
        if listing:
            orders = frappe.db.sql("""
                SELECT DISTINCT mo.name, mo.order_date, mo.status
                FROM `tabMarketplace Order` mo
                JOIN `tabMarketplace Order Item` moi ON moi.parent = mo.name
                WHERE mo.buyer = %(reviewer)s
                AND moi.listing = %(listing)s
                AND mo.status IN ('Delivered', 'Completed')
                AND mo.docstatus != 2
                ORDER BY mo.order_date DESC
                LIMIT 10
            """, {"reviewer": reviewer, "listing": listing}, as_dict=True)
        elif seller:
            orders = frappe.db.sql("""
                SELECT DISTINCT mo.name, mo.order_date, mo.status
                FROM `tabMarketplace Order` mo
                JOIN `tabMarketplace Order Item` moi ON moi.parent = mo.name
                WHERE mo.buyer = %(reviewer)s
                AND moi.seller = %(seller)s
                AND mo.status IN ('Delivered', 'Completed')
                AND mo.docstatus != 2
                ORDER BY mo.order_date DESC
                LIMIT 10
            """, {"reviewer": reviewer, "seller": seller}, as_dict=True)
        else:
            result["reason"] = _("Listing or seller is required")
            return result

        if orders:
            result["has_purchased"] = True
            result["eligible"] = True
            result["eligible_orders"] = [
                {"name": o.name, "date": o.order_date, "status": o.status}
                for o in orders
            ]
        else:
            result["reason"] = _("You must purchase this item before reviewing")

        return result

    # =================================================================
    # Rating Calculation Methods
    # =================================================================

    def calculate_helpfulness_score(self):
        """Calculate the helpfulness score based on votes."""
        total_votes = cint(self.helpful_count) + cint(self.unhelpful_count)
        if total_votes == 0:
            self.helpfulness_score = 0
        else:
            # Wilson score lower bound (simplified)
            helpful = cint(self.helpful_count)
            self.helpfulness_score = (helpful / total_votes) * 100

    def update_target_ratings(self, removing=False):
        """Update the average rating of the reviewed listing/seller."""
        if self.review_type == "Product" and self.listing:
            self._update_listing_rating(removing)
        elif self.seller:
            self._update_seller_rating(removing)

    def _update_listing_rating(self, removing=False):
        """Update listing average rating."""
        if not frappe.db.exists("Listing", self.listing):
            return

        # Calculate new average from all published reviews
        stats = frappe.db.sql("""
            SELECT
                AVG(rating) as avg_rating,
                COUNT(*) as review_count
            FROM `tabReview`
            WHERE listing = %(listing)s
            AND status = 'Published'
            AND name != %(exclude_self)s
        """, {
            "listing": self.listing,
            "exclude_self": self.name if removing else ""
        }, as_dict=True)[0]

        # Update listing
        frappe.db.set_value(
            "Listing",
            self.listing,
            {
                "average_rating": flt(stats.avg_rating) or 0,
                "review_count": cint(stats.review_count)
            },
            update_modified=False
        )

    def _update_seller_rating(self, removing=False):
        """Update seller average rating."""
        if not frappe.db.exists("Seller Profile", self.seller):
            return

        # Calculate new average from all published reviews
        stats = frappe.db.sql("""
            SELECT
                AVG(rating) as avg_rating,
                COUNT(*) as review_count
            FROM `tabReview`
            WHERE seller = %(seller)s
            AND status = 'Published'
            AND name != %(exclude_self)s
        """, {
            "seller": self.seller,
            "exclude_self": self.name if removing else ""
        }, as_dict=True)[0]

        # Update seller profile
        frappe.db.set_value(
            "Seller Profile",
            self.seller,
            {
                "average_rating": flt(stats.avg_rating) or 0,
                "review_count": cint(stats.review_count)
            },
            update_modified=False
        )

    # =================================================================
    # Status Methods
    # =================================================================

    def submit_for_review(self):
        """Submit review for moderation."""
        if self.status not in ["Draft"]:
            frappe.throw(_("Only draft reviews can be submitted"))

        self.db_set("status", "Pending Review")
        self.db_set("moderation_status", "Pending")
        self.db_set("submitted_at", now_datetime())

    def approve(self, moderator=None):
        """Approve the review for publication."""
        if self.moderation_status not in ["Pending", "Under Review", "Flagged"]:
            frappe.throw(_("Review is not pending moderation"))

        self.db_set("status", "Published")
        self.db_set("moderation_status", "Approved")
        self.db_set("moderated_by", moderator or frappe.session.user)
        self.db_set("moderated_at", now_datetime())
        self.db_set("published_at", now_datetime())

        # Update target ratings
        self.update_target_ratings()

        # Notify reviewer
        self.notify_reviewer("approved")

    def reject(self, reason=None, notes=None, moderator=None):
        """Reject the review."""
        if self.moderation_status not in ["Pending", "Under Review", "Flagged"]:
            frappe.throw(_("Review is not pending moderation"))

        self.db_set("status", "Rejected")
        self.db_set("moderation_status", "Rejected")
        self.db_set("moderated_by", moderator or frappe.session.user)
        self.db_set("moderated_at", now_datetime())

        if reason:
            self.db_set("rejection_reason", reason)
        if notes:
            self.db_set("moderation_notes", notes)

        # Notify reviewer
        self.notify_reviewer("rejected")

    def hide(self, reason=None):
        """Hide the review from public view."""
        self.db_set("status", "Hidden")

        if reason:
            existing_notes = self.moderation_notes or ""
            self.db_set(
                "moderation_notes",
                f"Hidden: {reason}\n\n{existing_notes}"
            )

        # Update target ratings
        self.update_target_ratings(removing=True)

    def remove(self, reason=None):
        """Remove the review (soft delete)."""
        self.db_set("status", "Removed")

        if reason:
            existing_notes = self.moderation_notes or ""
            self.db_set(
                "moderation_notes",
                f"Removed: {reason}\n\n{existing_notes}"
            )

        # Update target ratings
        self.update_target_ratings(removing=True)

    def flag(self, flag_type=None, reporter=None):
        """Flag review for moderation."""
        self.db_set("report_count", cint(self.report_count) + 1)

        if cint(self.report_count) >= 3:
            self.db_set("moderation_status", "Flagged")

        # Add flag to flags list
        flags = json.loads(self.flags or "[]")
        flag_entry = {
            "type": flag_type,
            "reporter": reporter or frappe.session.user,
            "timestamp": now_datetime().isoformat()
        }
        flags.append(flag_entry)
        self.db_set("flags", json.dumps(flags))

    # =================================================================
    # Helpfulness Methods
    # =================================================================

    def vote_helpful(self, user):
        """Record a helpful vote."""
        # Check if user already voted
        vote_key = f"review_vote:{self.name}:{user}"
        existing_vote = frappe.cache().get_value(vote_key)

        if existing_vote == "helpful":
            return {"status": "already_voted", "message": _("You already voted")}

        if existing_vote == "unhelpful":
            # Change vote
            self.db_set("unhelpful_count", max(0, cint(self.unhelpful_count) - 1))

        self.db_set("helpful_count", cint(self.helpful_count) + 1)
        frappe.cache().set_value(vote_key, "helpful", expires_in_sec=86400 * 365)

        self.calculate_helpfulness_score()
        self.db_set("helpfulness_score", self.helpfulness_score)

        return {"status": "success", "message": _("Vote recorded")}

    def vote_unhelpful(self, user):
        """Record an unhelpful vote."""
        vote_key = f"review_vote:{self.name}:{user}"
        existing_vote = frappe.cache().get_value(vote_key)

        if existing_vote == "unhelpful":
            return {"status": "already_voted", "message": _("You already voted")}

        if existing_vote == "helpful":
            # Change vote
            self.db_set("helpful_count", max(0, cint(self.helpful_count) - 1))

        self.db_set("unhelpful_count", cint(self.unhelpful_count) + 1)
        frappe.cache().set_value(vote_key, "unhelpful", expires_in_sec=86400 * 365)

        self.calculate_helpfulness_score()
        self.db_set("helpfulness_score", self.helpfulness_score)

        return {"status": "success", "message": _("Vote recorded")}

    # =================================================================
    # Seller Response Methods
    # =================================================================

    def add_seller_response(self, response_text, responder=None):
        """Add seller response to the review."""
        if not response_text:
            frappe.throw(_("Response text is required"))

        # Verify responder is the seller
        if not responder:
            responder = frappe.session.user

        seller_user = frappe.db.get_value("Seller Profile", self.seller, "user")
        if responder != seller_user and not frappe.has_permission("Review", "write"):
            frappe.throw(_("Only the seller can respond to this review"))

        self.db_set("seller_response", response_text)
        self.db_set("seller_response_by", responder)
        self.db_set("seller_response_at", now_datetime())
        self.db_set("has_seller_response", 1)

        # Notify reviewer
        self.notify_reviewer("seller_response")

        return {"status": "success", "message": _("Response added")}

    def edit_seller_response(self, response_text):
        """Edit seller response."""
        if not self.has_seller_response:
            frappe.throw(_("No response to edit"))

        self.db_set("seller_response", response_text)
        self.db_set("seller_response_at", now_datetime())

        return {"status": "success", "message": _("Response updated")}

    def remove_seller_response(self):
        """Remove seller response."""
        self.db_set("seller_response", None)
        self.db_set("seller_response_by", None)
        self.db_set("seller_response_at", None)
        self.db_set("has_seller_response", 0)
        self.db_set("response_helpful_count", 0)

        return {"status": "success", "message": _("Response removed")}

    # =================================================================
    # Notification Methods
    # =================================================================

    def notify_reviewer(self, event_type):
        """Send notification to reviewer."""
        try:
            if event_type == "approved":
                subject = _("Your review has been published")
                message = _("Your review for {0} has been approved and published.").format(
                    self.listing_title or self.seller_name
                )
            elif event_type == "rejected":
                subject = _("Your review was not approved")
                message = _("Your review for {0} was not approved. Reason: {1}").format(
                    self.listing_title or self.seller_name,
                    self.rejection_reason or "Not specified"
                )
            elif event_type == "seller_response":
                subject = _("Seller responded to your review")
                message = _("The seller has responded to your review for {0}.").format(
                    self.listing_title or self.seller_name
                )
            else:
                return

            frappe.publish_realtime(
                "review_notification",
                {
                    "type": event_type,
                    "review": self.name,
                    "subject": subject,
                    "message": message
                },
                user=self.reviewer
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to notify reviewer: {str(e)}",
                "Review Notification Error"
            )

    # =================================================================
    # Display Methods
    # =================================================================

    def get_display_data(self):
        """Get review data for display."""
        return {
            "name": self.name,
            "review_id": self.review_id,
            "review_type": self.review_type,
            "rating": self.rating,
            "title": self.title,
            "review_text": self.review_text,
            "pros": self.pros,
            "cons": self.cons,
            "display_name": self.display_name,
            "is_anonymous": self.is_anonymous,
            "is_verified_purchase": self.is_verified_purchase,
            "helpful_count": self.helpful_count,
            "unhelpful_count": self.unhelpful_count,
            "images": json.loads(self.images or "[]"),
            "video_url": self.video_url,
            "published_at": self.published_at,
            "detailed_ratings": {
                "product_quality": self.product_quality_rating,
                "value_for_money": self.value_for_money_rating,
                "shipping": self.shipping_rating,
                "seller_communication": self.seller_communication_rating,
                "accuracy": self.accuracy_rating
            },
            "seller_response": {
                "has_response": self.has_seller_response,
                "response": self.seller_response,
                "response_at": self.seller_response_at
            } if self.has_seller_response else None,
            "listing": self.listing,
            "listing_title": self.listing_title,
            "seller": self.seller,
            "seller_name": self.seller_name
        }


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def create_review(review_type, listing=None, seller=None, rating=None,
                  title=None, review_text=None, pros=None, cons=None,
                  order=None, images=None, video_url=None,
                  detailed_ratings=None, is_anonymous=False):
    """
    Create a new review.

    Args:
        review_type: Product, Seller, or Order Experience
        listing: Listing name (for product reviews)
        seller: Seller Profile name (for seller reviews)
        rating: Overall rating (1-5)
        title: Review title
        review_text: Review content
        pros: Pros text
        cons: Cons text
        order: Marketplace Order for verification
        images: JSON array of image URLs
        video_url: Video URL
        detailed_ratings: JSON object with detailed ratings
        is_anonymous: Boolean for anonymous reviews

    Returns:
        dict: Created review details
    """
    # Check eligibility first
    eligibility = Review.check_review_eligibility(
        frappe.session.user,
        listing=listing,
        seller=seller
    )

    if not eligibility["eligible"]:
        if eligibility["already_reviewed"]:
            frappe.throw(_("You have already reviewed this item"))
        else:
            frappe.throw(eligibility["reason"] or _("You are not eligible to review"))

    # Parse detailed ratings
    if detailed_ratings and isinstance(detailed_ratings, str):
        detailed_ratings = json.loads(detailed_ratings)

    review = frappe.get_doc({
        "doctype": "Review",
        "review_type": review_type,
        "listing": listing,
        "seller": seller,
        "rating": rating,
        "title": title,
        "review_text": review_text,
        "pros": pros,
        "cons": cons,
        "marketplace_order": order,
        "images": images if isinstance(images, str) else json.dumps(images or []),
        "video_url": video_url,
        "is_anonymous": cint(is_anonymous),
        "status": "Pending Review"
    })

    # Apply detailed ratings
    if detailed_ratings:
        review.product_quality_rating = detailed_ratings.get("product_quality", 0)
        review.value_for_money_rating = detailed_ratings.get("value_for_money", 0)
        review.shipping_rating = detailed_ratings.get("shipping", 0)
        review.seller_communication_rating = detailed_ratings.get("seller_communication", 0)
        review.accuracy_rating = detailed_ratings.get("accuracy", 0)

    review.insert()

    return {
        "status": "success",
        "review": review.name,
        "review_id": review.review_id,
        "message": _("Review submitted for moderation")
    }


@frappe.whitelist()
def get_review(review_name=None, review_id=None):
    """
    Get review details.

    Args:
        review_name: Frappe document name
        review_id: Review ID

    Returns:
        dict: Review details
    """
    if not review_name and not review_id:
        frappe.throw(_("Either review_name or review_id is required"))

    if review_id and not review_name:
        review_name = frappe.db.get_value("Review", {"review_id": review_id}, "name")

    if not review_name:
        return {"error": _("Review not found")}

    review = frappe.get_doc("Review", review_name)
    return review.get_display_data()


@frappe.whitelist()
def get_listing_reviews(listing, page=1, page_size=10, sort_by="recent",
                        rating_filter=None, verified_only=False):
    """
    Get reviews for a listing.

    Args:
        listing: Listing name
        page: Page number
        page_size: Results per page
        sort_by: recent, helpful, rating_high, rating_low
        rating_filter: Filter by specific rating (1-5)
        verified_only: Only show verified purchase reviews

    Returns:
        dict: Reviews with pagination and statistics
    """
    filters = {
        "listing": listing,
        "status": "Published",
        "review_type": "Product"
    }

    if rating_filter:
        filters["rating"] = cint(rating_filter)

    if verified_only:
        filters["is_verified_purchase"] = 1

    # Determine sort order
    order_by = "published_at DESC"
    if sort_by == "helpful":
        order_by = "helpful_count DESC, published_at DESC"
    elif sort_by == "rating_high":
        order_by = "rating DESC, published_at DESC"
    elif sort_by == "rating_low":
        order_by = "rating ASC, published_at DESC"

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Review", filters)

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "rating", "title", "review_text",
            "display_name", "is_anonymous", "is_verified_purchase",
            "helpful_count", "unhelpful_count", "images", "video_url",
            "published_at", "has_seller_response", "seller_response",
            "seller_response_at", "is_featured", "is_pinned",
            "product_quality_rating", "value_for_money_rating",
            "shipping_rating", "seller_communication_rating", "accuracy_rating"
        ],
        order_by=order_by,
        start=start,
        limit_page_length=cint(page_size)
    )

    # Get rating statistics
    stats = get_listing_review_stats(listing)

    return {
        "reviews": reviews,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size),
        "statistics": stats
    }


@frappe.whitelist()
def get_seller_reviews(seller, page=1, page_size=10, sort_by="recent",
                       rating_filter=None):
    """
    Get reviews for a seller.

    Args:
        seller: Seller Profile name
        page: Page number
        page_size: Results per page
        sort_by: recent, helpful, rating_high, rating_low
        rating_filter: Filter by specific rating (1-5)

    Returns:
        dict: Reviews with pagination and statistics
    """
    filters = {
        "seller": seller,
        "status": "Published"
    }

    if rating_filter:
        filters["rating"] = cint(rating_filter)

    order_by = "published_at DESC"
    if sort_by == "helpful":
        order_by = "helpful_count DESC, published_at DESC"
    elif sort_by == "rating_high":
        order_by = "rating DESC, published_at DESC"
    elif sort_by == "rating_low":
        order_by = "rating ASC, published_at DESC"

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Review", filters)

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "review_type", "rating", "title", "review_text",
            "display_name", "is_anonymous", "is_verified_purchase",
            "helpful_count", "unhelpful_count", "images", "video_url",
            "published_at", "has_seller_response", "seller_response",
            "seller_response_at", "listing", "listing_title"
        ],
        order_by=order_by,
        start=start,
        limit_page_length=cint(page_size)
    )

    # Get statistics
    stats = get_seller_review_stats(seller)

    return {
        "reviews": reviews,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size),
        "statistics": stats
    }


@frappe.whitelist()
def get_my_reviews(page=1, page_size=10, status=None):
    """
    Get reviews by the current user.

    Args:
        page: Page number
        page_size: Results per page
        status: Filter by status

    Returns:
        dict: User's reviews with pagination
    """
    filters = {
        "reviewer": frappe.session.user
    }

    if status:
        filters["status"] = status

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Review", filters)

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "review_type", "rating", "title",
            "status", "listing", "listing_title", "seller", "seller_name",
            "is_verified_purchase", "published_at", "submitted_at",
            "has_seller_response"
        ],
        order_by="creation DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "reviews": reviews,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size)
    }


@frappe.whitelist()
def check_review_eligibility(listing=None, seller=None):
    """
    Check if current user can review a listing/seller.

    Args:
        listing: Listing name
        seller: Seller Profile name

    Returns:
        dict: Eligibility status
    """
    return Review.check_review_eligibility(
        frappe.session.user,
        listing=listing,
        seller=seller
    )


@frappe.whitelist()
def vote_review(review_name, vote_type):
    """
    Vote on a review's helpfulness.

    Args:
        review_name: Review document name
        vote_type: 'helpful' or 'unhelpful'

    Returns:
        dict: Vote result
    """
    review = frappe.get_doc("Review", review_name)

    if vote_type == "helpful":
        return review.vote_helpful(frappe.session.user)
    elif vote_type == "unhelpful":
        return review.vote_unhelpful(frappe.session.user)
    else:
        frappe.throw(_("Invalid vote type"))


@frappe.whitelist()
def report_review(review_name, report_type, details=None):
    """
    Report a review for moderation.

    Args:
        review_name: Review document name
        report_type: spam, inappropriate, fake, etc.
        details: Additional details

    Returns:
        dict: Report result
    """
    review = frappe.get_doc("Review", review_name)
    review.flag(flag_type=report_type, reporter=frappe.session.user)

    return {
        "status": "success",
        "message": _("Thank you for your report. Our team will review it.")
    }


@frappe.whitelist()
def add_seller_response(review_name, response_text):
    """
    Add seller response to a review.

    Args:
        review_name: Review document name
        response_text: Response content

    Returns:
        dict: Response result
    """
    review = frappe.get_doc("Review", review_name)
    return review.add_seller_response(response_text)


@frappe.whitelist()
def get_listing_review_stats(listing):
    """
    Get review statistics for a listing.

    Args:
        listing: Listing name

    Returns:
        dict: Review statistics
    """
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_reviews,
            AVG(rating) as average_rating,
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star,
            SUM(CASE WHEN is_verified_purchase = 1 THEN 1 ELSE 0 END) as verified_count,
            SUM(CASE WHEN images IS NOT NULL AND images != '[]' THEN 1 ELSE 0 END) as with_images,
            AVG(product_quality_rating) as avg_quality,
            AVG(value_for_money_rating) as avg_value,
            AVG(shipping_rating) as avg_shipping,
            AVG(accuracy_rating) as avg_accuracy
        FROM `tabReview`
        WHERE listing = %(listing)s
        AND status = 'Published'
    """, {"listing": listing}, as_dict=True)[0]

    total = cint(stats.total_reviews)

    return {
        "total_reviews": total,
        "average_rating": flt(stats.average_rating, 1) if stats.average_rating else 0,
        "verified_count": cint(stats.verified_count),
        "with_images_count": cint(stats.with_images),
        "rating_distribution": {
            "5": cint(stats.five_star),
            "4": cint(stats.four_star),
            "3": cint(stats.three_star),
            "2": cint(stats.two_star),
            "1": cint(stats.one_star)
        },
        "rating_percentages": {
            "5": round(cint(stats.five_star) / total * 100, 1) if total else 0,
            "4": round(cint(stats.four_star) / total * 100, 1) if total else 0,
            "3": round(cint(stats.three_star) / total * 100, 1) if total else 0,
            "2": round(cint(stats.two_star) / total * 100, 1) if total else 0,
            "1": round(cint(stats.one_star) / total * 100, 1) if total else 0
        },
        "detailed_averages": {
            "quality": flt(stats.avg_quality, 1) if stats.avg_quality else 0,
            "value": flt(stats.avg_value, 1) if stats.avg_value else 0,
            "shipping": flt(stats.avg_shipping, 1) if stats.avg_shipping else 0,
            "accuracy": flt(stats.avg_accuracy, 1) if stats.avg_accuracy else 0
        }
    }


@frappe.whitelist()
def get_seller_review_stats(seller):
    """
    Get review statistics for a seller.

    Args:
        seller: Seller Profile name

    Returns:
        dict: Review statistics
    """
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_reviews,
            AVG(rating) as average_rating,
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star,
            SUM(CASE WHEN is_verified_purchase = 1 THEN 1 ELSE 0 END) as verified_count,
            AVG(seller_communication_rating) as avg_communication
        FROM `tabReview`
        WHERE seller = %(seller)s
        AND status = 'Published'
    """, {"seller": seller}, as_dict=True)[0]

    total = cint(stats.total_reviews)

    return {
        "total_reviews": total,
        "average_rating": flt(stats.average_rating, 1) if stats.average_rating else 0,
        "verified_count": cint(stats.verified_count),
        "rating_distribution": {
            "5": cint(stats.five_star),
            "4": cint(stats.four_star),
            "3": cint(stats.three_star),
            "2": cint(stats.two_star),
            "1": cint(stats.one_star)
        },
        "avg_communication_rating": flt(stats.avg_communication, 1) if stats.avg_communication else 0
    }


@frappe.whitelist()
def get_review_statistics(days=30, seller=None):
    """
    Get review statistics for admin dashboard.

    Args:
        days: Number of days to analyze
        seller: Filter by seller (optional)

    Returns:
        dict: Review statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    seller_filter = "AND seller = %(seller)s" if seller else ""

    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_reviews,
            SUM(CASE WHEN status = 'Pending Review' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status = 'Published' THEN 1 ELSE 0 END) as published,
            SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END) as rejected,
            SUM(CASE WHEN moderation_status = 'Flagged' THEN 1 ELSE 0 END) as flagged,
            AVG(rating) as avg_rating,
            SUM(CASE WHEN is_verified_purchase = 1 THEN 1 ELSE 0 END) as verified_count
        FROM `tabReview`
        WHERE creation >= %(from_date)s
        {seller_filter}
    """.format(seller_filter=seller_filter), {
        "from_date": from_date,
        "seller": seller
    }, as_dict=True)[0]

    return {
        "period_days": cint(days),
        "total_reviews": cint(stats.total_reviews),
        "pending_moderation": cint(stats.pending),
        "published": cint(stats.published),
        "rejected": cint(stats.rejected),
        "flagged": cint(stats.flagged),
        "average_rating": flt(stats.avg_rating, 1) if stats.avg_rating else 0,
        "verified_percentage": round(
            cint(stats.verified_count) / cint(stats.total_reviews) * 100, 1
        ) if stats.total_reviews else 0
    }


@frappe.whitelist()
def moderate_review(review_name, action, reason=None, notes=None):
    """
    Moderate a review (approve/reject).

    Args:
        review_name: Review document name
        action: 'approve', 'reject', 'hide', 'remove'
        reason: Rejection reason
        notes: Moderation notes

    Returns:
        dict: Moderation result
    """
    if not frappe.has_permission("Review", "write"):
        frappe.throw(_("Not permitted to moderate reviews"))

    review = frappe.get_doc("Review", review_name)

    if action == "approve":
        review.approve()
    elif action == "reject":
        review.reject(reason=reason, notes=notes)
    elif action == "hide":
        review.hide(reason=reason)
    elif action == "remove":
        review.remove(reason=reason)
    else:
        frappe.throw(_("Invalid action: {0}").format(action))

    return {
        "status": "success",
        "review_status": review.status,
        "message": _("Review {0}d successfully").format(action)
    }


@frappe.whitelist()
def get_pending_reviews(page=1, page_size=20):
    """
    Get reviews pending moderation.

    Args:
        page: Page number
        page_size: Results per page

    Returns:
        dict: Pending reviews with pagination
    """
    if not frappe.has_permission("Review", "write"):
        frappe.throw(_("Not permitted to view pending reviews"))

    filters = {
        "moderation_status": ["in", ["Pending", "Flagged", "Under Review"]]
    }

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Review", filters)

    reviews = frappe.get_all(
        "Review",
        filters=filters,
        fields=[
            "name", "review_id", "review_type", "rating", "title",
            "review_text", "reviewer", "reviewer_name", "listing",
            "listing_title", "seller", "seller_name", "is_verified_purchase",
            "report_count", "moderation_status", "flags", "submitted_at"
        ],
        order_by="submitted_at ASC",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "reviews": reviews,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size)
    }
