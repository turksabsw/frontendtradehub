# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, get_datetime, date_diff
)
import json


class MarketplaceShipment(Document):
    """
    Marketplace Shipment DocType for TR-TradeHub.

    Tracks shipments for marketplace orders with support for:
    - Multiple Turkish carriers (Yurtici, Aras, MNG, etc.)
    - International carriers (UPS, DHL, FedEx)
    - Real-time tracking integration
    - Return shipment handling
    - Delivery confirmation with proof

    Features:
    - Automatic tracking URL generation
    - Status workflow management
    - Cost calculation and tracking
    - Label generation support
    - Return shipment creation
    - Sub Order integration
    """

    def before_insert(self):
        """Set default values before creating a new shipment."""
        # Generate unique shipment ID
        if not self.shipment_id:
            self.shipment_id = self.generate_shipment_id()

        # Set created timestamp
        if not self.created_at:
            self.created_at = now_datetime()

        # Copy addresses from sub order if not provided
        if self.sub_order:
            self.copy_addresses_from_sub_order()

    def validate(self):
        """Validate shipment data before saving."""
        self.validate_sub_order()
        self.validate_carrier()
        self.validate_addresses()
        self.validate_package_details()
        self.validate_status_transitions()
        self.calculate_costs()
        self.calculate_volumetric_weight()
        self.generate_tracking_url_if_needed()

    def on_update(self):
        """Actions after shipment is updated."""
        self.clear_shipment_cache()
        self.update_sub_order_status()
        self.log_status_change()

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_shipment_id(self):
        """Generate a unique shipment identifier."""
        return f"SHP-{frappe.generate_hash(length=10).upper()}"

    def copy_addresses_from_sub_order(self):
        """Copy addresses from the linked Sub Order."""
        if not self.sub_order:
            return

        sub_order = frappe.get_doc("Sub Order", self.sub_order)

        # Copy seller as sender (get seller address from profile)
        if not self.seller:
            self.seller = sub_order.seller

        # Copy recipient info from sub order shipping address
        if not self.recipient_name:
            self.recipient_name = sub_order.shipping_address_name or sub_order.buyer_name
        if not self.recipient_phone:
            self.recipient_phone = sub_order.shipping_phone or sub_order.buyer_phone
        if not self.destination_address_line1:
            self.destination_address_line1 = sub_order.shipping_address_line1
        if not self.destination_address_line2:
            self.destination_address_line2 = sub_order.shipping_address_line2
        if not self.destination_city:
            self.destination_city = sub_order.shipping_city
        if not self.destination_state:
            self.destination_state = sub_order.shipping_state
        if not self.destination_postal_code:
            self.destination_postal_code = sub_order.shipping_postal_code
        if not self.destination_country:
            self.destination_country = sub_order.shipping_country or "Turkey"

        # Get sender info from seller profile
        if self.seller and not self.sender_name:
            seller_profile = frappe.get_doc("Seller Profile", self.seller)
            self.sender_name = seller_profile.seller_name
            self.sender_phone = seller_profile.phone

            # Get seller address if available
            if hasattr(seller_profile, 'address_line1') and seller_profile.address_line1:
                if not self.origin_address_line1:
                    self.origin_address_line1 = seller_profile.address_line1
                if not self.origin_city and hasattr(seller_profile, 'city'):
                    self.origin_city = seller_profile.city
                if not self.origin_country:
                    self.origin_country = "Turkey"

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_sub_order(self):
        """Validate sub order reference."""
        if not self.sub_order:
            frappe.throw(_("Sub Order is required"))

        if not frappe.db.exists("Sub Order", self.sub_order):
            frappe.throw(_("Sub Order {0} does not exist").format(self.sub_order))

    def validate_carrier(self):
        """Validate carrier information."""
        if not self.carrier:
            frappe.throw(_("Carrier is required"))

        # Validate tracking number format for known carriers
        if self.tracking_number:
            if self.carrier == "Yurtici Kargo":
                # Yurtici tracking numbers are typically numeric
                if not self.tracking_number.replace("-", "").isdigit():
                    frappe.msgprint(
                        _("Warning: Yurtici Kargo tracking numbers are typically numeric")
                    )
            elif self.carrier == "Aras Kargo":
                # Aras tracking typically alphanumeric
                pass

    def validate_addresses(self):
        """Validate origin and destination addresses."""
        # Validate destination (required)
        if not self.destination_address_line1:
            frappe.throw(_("Destination address is required"))
        if not self.destination_city:
            frappe.throw(_("Destination city is required"))

        # Origin validation for non-pending shipments
        if self.status not in ["Pending"]:
            if not self.origin_address_line1:
                frappe.throw(_("Origin address is required for non-pending shipments"))
            if not self.origin_city:
                frappe.throw(_("Origin city is required"))

    def validate_package_details(self):
        """Validate package weight and dimensions."""
        if cint(self.package_count) < 1:
            self.package_count = 1

        if flt(self.total_weight) < 0:
            frappe.throw(_("Weight cannot be negative"))

        # Validate dimensions
        for dim in ["total_length", "total_width", "total_height"]:
            if flt(getattr(self, dim, 0)) < 0:
                frappe.throw(_("{0} cannot be negative").format(dim))

    def validate_status_transitions(self):
        """Validate shipment status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Marketplace Shipment", self.name, "status")

        # Define valid transitions
        valid_transitions = {
            "Pending": ["Label Generated", "Pickup Scheduled", "Cancelled"],
            "Label Generated": ["Pickup Scheduled", "Picked Up", "Cancelled"],
            "Pickup Scheduled": ["Picked Up", "Cancelled"],
            "Picked Up": ["In Transit", "Exception"],
            "In Transit": ["Out for Delivery", "Delivered", "Exception", "Returning"],
            "Out for Delivery": ["Delivered", "Failed Delivery", "Exception"],
            "Delivered": ["Returning"],
            "Failed Delivery": ["Out for Delivery", "Returning", "Exception"],
            "Returning": ["Returned"],
            "Returned": [],
            "Exception": ["In Transit", "Returning", "Cancelled"],
            "Cancelled": []
        }

        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Cannot change status from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    # =================================================================
    # Calculation Methods
    # =================================================================

    def calculate_costs(self):
        """Calculate total shipping costs."""
        self.total_cost = (
            flt(self.shipping_cost)
            + flt(self.insurance_cost)
            + flt(self.handling_cost)
            + flt(self.additional_charges)
        )

    def calculate_volumetric_weight(self):
        """Calculate volumetric weight from dimensions."""
        if flt(self.total_length) > 0 and flt(self.total_width) > 0 and flt(self.total_height) > 0:
            # Standard divisor for volumetric weight (5000 for cm, 139 for inches)
            divisor = 5000 if self.dimension_unit == "cm" else 139

            # Convert to correct unit if needed
            length = flt(self.total_length)
            width = flt(self.total_width)
            height = flt(self.total_height)

            if self.dimension_unit == "m":
                length *= 100
                width *= 100
                height *= 100

            self.volumetric_weight = (length * width * height) / divisor

    # =================================================================
    # Status Methods
    # =================================================================

    def generate_label(self):
        """Generate shipping label via carrier API."""
        if self.label_generated:
            frappe.throw(_("Label already generated"))

        # Validate required fields
        if not self.origin_address_line1 or not self.origin_city:
            frappe.throw(_("Origin address is required to generate label"))

        # This would call the carrier API to generate label
        # For now, mark as generated
        self.db_set("label_generated", 1)
        self.db_set("status", "Label Generated")
        self.clear_shipment_cache()

        return {
            "status": "success",
            "label_url": self.label_url
        }

    def schedule_pickup(self, pickup_date=None, time_from=None, time_to=None):
        """Schedule carrier pickup."""
        if self.status not in ["Pending", "Label Generated"]:
            frappe.throw(_("Cannot schedule pickup from current status"))

        self.db_set("pickup_date", pickup_date or add_days(nowdate(), 1))
        if time_from:
            self.db_set("pickup_time_from", time_from)
        if time_to:
            self.db_set("pickup_time_to", time_to)

        self.db_set("status", "Pickup Scheduled")
        self.clear_shipment_cache()

        return {"status": "success"}

    def mark_picked_up(self):
        """Mark shipment as picked up by carrier."""
        if self.status not in ["Pickup Scheduled", "Label Generated"]:
            frappe.throw(_("Shipment cannot be marked as picked up from current status"))

        self.db_set("status", "Picked Up")
        self.db_set("picked_up_at", now_datetime())
        self.clear_shipment_cache()

        # Update sub order
        self.update_sub_order_status()

        return {"status": "success"}

    def mark_in_transit(self):
        """Mark shipment as in transit."""
        if self.status != "Picked Up":
            frappe.throw(_("Shipment must be picked up before marking in transit"))

        self.db_set("status", "In Transit")
        self.db_set("in_transit_at", now_datetime())
        self.clear_shipment_cache()

        self.update_sub_order_status()

        return {"status": "success"}

    def mark_out_for_delivery(self):
        """Mark shipment as out for delivery."""
        if self.status != "In Transit":
            frappe.throw(_("Shipment must be in transit before out for delivery"))

        self.db_set("status", "Out for Delivery")
        self.db_set("out_for_delivery_at", now_datetime())
        self.clear_shipment_cache()

        self.update_sub_order_status()

        # Notify buyer
        self.notify_buyer("out_for_delivery")

        return {"status": "success"}

    def mark_delivered(self, delivered_to=None, delivery_notes=None):
        """Mark shipment as delivered."""
        if self.status not in ["Out for Delivery", "In Transit"]:
            frappe.throw(_("Shipment cannot be marked delivered from current status"))

        self.db_set("status", "Delivered")
        self.db_set("delivery_status", "Delivered")
        self.db_set("delivered_at", now_datetime())
        self.db_set("actual_delivery_date", nowdate())
        self.db_set("delivery_time", now_datetime().strftime("%H:%M:%S"))

        if delivered_to:
            self.db_set("delivered_to", delivered_to)
        if delivery_notes:
            self.db_set("delivery_notes", delivery_notes)

        self.db_set("delivery_attempts", cint(self.delivery_attempts) + 1)
        self.clear_shipment_cache()

        # Update sub order to delivered
        self.update_sub_order_status()

        # Notify buyer
        self.notify_buyer("delivered")

        return {"status": "success"}

    def mark_failed_delivery(self, reason=None):
        """Mark delivery attempt as failed."""
        if self.status != "Out for Delivery":
            frappe.throw(_("Can only mark failed delivery from Out for Delivery status"))

        self.db_set("status", "Failed Delivery")
        self.db_set("delivery_status", "Failed")
        self.db_set("delivery_attempts", cint(self.delivery_attempts) + 1)

        if reason:
            notes = f"Failed attempt {self.delivery_attempts + 1}: {reason}\n"
            if self.delivery_notes:
                notes += self.delivery_notes
            self.db_set("delivery_notes", notes)

        self.clear_shipment_cache()

        return {"status": "success"}

    def mark_exception(self, reason=None):
        """Mark shipment with exception status."""
        self.db_set("status", "Exception")
        self.db_set("exception_at", now_datetime())

        if reason:
            notes = f"Exception: {reason}\n"
            if self.carrier_notes:
                notes += self.carrier_notes
            self.db_set("carrier_notes", notes)

        self.clear_shipment_cache()

        return {"status": "success"}

    def initiate_return(self, reason=None):
        """Initiate return shipment."""
        if self.status not in ["Delivered", "Failed Delivery", "Exception"]:
            frappe.throw(_("Cannot initiate return from current status"))

        self.db_set("status", "Returning")
        self.db_set("return_reason", reason)
        self.db_set("return_status", "Pending")
        self.clear_shipment_cache()

        # Update sub order
        if self.sub_order:
            frappe.db.set_value("Sub Order", self.sub_order, "fulfillment_status", "Returning")

        return {"status": "success"}

    def complete_return(self):
        """Mark return as completed."""
        if self.status != "Returning":
            frappe.throw(_("Shipment must be in returning status"))

        self.db_set("status", "Returned")
        self.db_set("return_status", "Completed")
        self.clear_shipment_cache()

        # Update sub order
        if self.sub_order:
            frappe.db.set_value("Sub Order", self.sub_order, "fulfillment_status", "Returned")

        return {"status": "success"}

    def cancel_shipment(self, reason=None):
        """Cancel the shipment."""
        if self.status in ["Delivered", "Returned"]:
            frappe.throw(_("Cannot cancel delivered or returned shipments"))

        self.db_set("status", "Cancelled")

        if reason:
            self.db_set("internal_notes", f"Cancelled: {reason}\n{self.internal_notes or ''}")

        self.clear_shipment_cache()

        return {"status": "success"}

    # =================================================================
    # Tracking Methods
    # =================================================================

    def generate_tracking_url_if_needed(self):
        """Generate tracking URL based on carrier if not provided."""
        if self.tracking_url or not self.tracking_number:
            return

        self.tracking_url = self.get_carrier_tracking_url()

    def get_carrier_tracking_url(self):
        """Get tracking URL for the carrier."""
        if not self.tracking_number:
            return None

        carrier_urls = {
            "Yurtici Kargo": f"https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={self.tracking_number}",
            "Aras Kargo": f"https://www.araskargo.com.tr/trmall/kargotakip.aspx?q={self.tracking_number}",
            "MNG Kargo": f"https://www.mngkargo.com.tr/gonderi-takip/?no={self.tracking_number}",
            "SuratKargo": f"https://www.suratkargo.com.tr/gonderi-takip?takipNo={self.tracking_number}",
            "PTT Kargo": f"https://gonderitakip.ptt.gov.tr/?barkod={self.tracking_number}",
            "UPS": f"https://www.ups.com/track?tracknum={self.tracking_number}",
            "DHL": f"https://www.dhl.com/tr-en/home/tracking.html?tracking-id={self.tracking_number}",
            "FedEx": f"https://www.fedex.com/fedextrack/?tracknumbers={self.tracking_number}",
            "Trendyol Express": f"https://www.trendyol.com/kargo-takip/{self.tracking_number}",
            "HepsiJet": f"https://www.hepsijet.com/takip/{self.tracking_number}"
        }

        return carrier_urls.get(self.carrier)

    def sync_tracking(self):
        """Sync tracking status from carrier API."""
        if not self.tracking_number:
            return {"error": "No tracking number"}

        # This would call the carrier API to get tracking updates
        # For now, just update sync timestamp
        self.db_set("last_sync_at", now_datetime())

        return {"status": "success", "message": "Tracking synced"}

    def get_tracking_events(self):
        """Get tracking events for this shipment."""
        events = frappe.get_all(
            "Tracking Event",
            filters={"shipment": self.name},
            fields=["name", "event_type", "event_date", "location", "description", "status"],
            order_by="event_date DESC"
        )
        return events

    # =================================================================
    # Sub Order Integration
    # =================================================================

    def update_sub_order_status(self):
        """Update the linked sub order's status based on shipment status."""
        if not self.sub_order:
            return

        status_mapping = {
            "Picked Up": "Shipped",
            "In Transit": "In Transit",
            "Out for Delivery": "Out for Delivery",
            "Delivered": "Delivered",
            "Exception": "On Hold",
            "Returning": "On Hold",
            "Returned": "Refunded"
        }

        new_sub_order_status = status_mapping.get(self.status)
        if new_sub_order_status:
            try:
                sub_order = frappe.get_doc("Sub Order", self.sub_order)

                # Update tracking info
                if self.tracking_number:
                    sub_order.db_set("tracking_number", self.tracking_number)
                if self.carrier:
                    sub_order.db_set("carrier", self.carrier)
                if self.tracking_url:
                    sub_order.db_set("tracking_url", self.tracking_url)

                # Update status
                sub_order.db_set("fulfillment_status", new_sub_order_status)

                if self.status == "Delivered":
                    sub_order.mark_delivered(delivery_date=self.actual_delivery_date)

            except Exception as e:
                frappe.log_error(
                    f"Failed to update sub order status: {str(e)}",
                    "Shipment Sub Order Update Error"
                )

    # =================================================================
    # Notification Methods
    # =================================================================

    def notify_buyer(self, event_type):
        """Send notification to buyer."""
        if not self.sub_order:
            return

        try:
            buyer = frappe.db.get_value("Sub Order", self.sub_order, "buyer")
            if buyer:
                frappe.publish_realtime(
                    f"shipment_{event_type}",
                    {
                        "shipment_id": self.shipment_id,
                        "tracking_number": self.tracking_number,
                        "carrier": self.carrier,
                        "status": self.status,
                        "tracking_url": self.tracking_url
                    },
                    user=buyer
                )
        except Exception as e:
            frappe.log_error(
                f"Failed to notify buyer: {str(e)}",
                "Shipment Notification Error"
            )

    # =================================================================
    # Logging Methods
    # =================================================================

    def log_status_change(self):
        """Log status change as a tracking event."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Marketplace Shipment", self.name, "status")

        if old_status and self.status != old_status:
            try:
                frappe.get_doc({
                    "doctype": "Tracking Event",
                    "shipment": self.name,
                    "event_type": "Status Change",
                    "event_date": now_datetime(),
                    "previous_status": old_status,
                    "new_status": self.status,
                    "description": f"Status changed from {old_status} to {self.status}"
                }).insert(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(
                    f"Failed to log status change: {str(e)}",
                    "Shipment Status Log Error"
                )

    # =================================================================
    # Utility Methods
    # =================================================================

    def clear_shipment_cache(self):
        """Clear cached shipment data."""
        frappe.cache().delete_value(f"shipment:{self.name}")
        if self.shipment_id:
            frappe.cache().delete_value(f"shipment_by_id:{self.shipment_id}")
        if self.tracking_number:
            frappe.cache().delete_value(f"shipment_by_tracking:{self.tracking_number}")

    def get_summary(self):
        """Get shipment summary for display."""
        return {
            "shipment_id": self.shipment_id,
            "name": self.name,
            "sub_order": self.sub_order,
            "carrier": self.carrier,
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url,
            "status": self.status,
            "delivery_status": self.delivery_status,
            "recipient_name": self.recipient_name,
            "destination_city": self.destination_city,
            "destination_country": self.destination_country,
            "total_weight": self.total_weight,
            "total_cost": self.total_cost,
            "pickup_date": self.pickup_date,
            "expected_delivery_date": self.expected_delivery_date,
            "actual_delivery_date": self.actual_delivery_date,
            "is_return": self.is_return
        }

    def get_tracking_info(self):
        """Get tracking information for display."""
        return {
            "carrier": self.carrier,
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url or self.get_carrier_tracking_url(),
            "status": self.status,
            "delivery_status": self.delivery_status,
            "picked_up_at": self.picked_up_at,
            "in_transit_at": self.in_transit_at,
            "out_for_delivery_at": self.out_for_delivery_at,
            "delivered_at": self.delivered_at,
            "delivery_attempts": self.delivery_attempts,
            "delivered_to": self.delivered_to,
            "expected_delivery_date": self.expected_delivery_date,
            "actual_delivery_date": self.actual_delivery_date,
            "events": self.get_tracking_events()
        }

    def create_return_shipment(self, reason=None):
        """Create a return shipment for this delivery."""
        if self.status != "Delivered":
            frappe.throw(_("Can only create return for delivered shipments"))

        return_shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.sub_order,
            "seller": self.seller,
            "is_return": 1,
            "return_reason": reason,
            "original_shipment": self.name,
            "carrier": self.carrier,
            "shipment_type": "Standard",
            # Swap origin and destination
            "sender_name": self.recipient_name,
            "sender_phone": self.recipient_phone,
            "origin_address_line1": self.destination_address_line1,
            "origin_address_line2": self.destination_address_line2,
            "origin_city": self.destination_city,
            "origin_state": self.destination_state,
            "origin_postal_code": self.destination_postal_code,
            "origin_country": self.destination_country,
            "recipient_name": self.sender_name,
            "recipient_phone": self.sender_phone,
            "destination_address_line1": self.origin_address_line1,
            "destination_address_line2": self.origin_address_line2,
            "destination_city": self.origin_city,
            "destination_state": self.origin_state,
            "destination_postal_code": self.origin_postal_code,
            "destination_country": self.origin_country,
            # Copy package details
            "package_count": self.package_count,
            "total_weight": self.total_weight,
            "weight_unit": self.weight_unit,
            "description": f"Return: {self.description or ''}"
        })

        return_shipment.insert()

        return {
            "status": "success",
            "return_shipment": return_shipment.name,
            "return_shipment_id": return_shipment.shipment_id
        }


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def create_shipment(sub_order, carrier, **kwargs):
    """
    Create a new shipment for a sub order.

    Args:
        sub_order: Sub Order name
        carrier: Carrier name
        **kwargs: Additional shipment fields

    Returns:
        dict: Created shipment details
    """
    if not frappe.db.exists("Sub Order", sub_order):
        return {"error": _("Sub Order not found")}

    shipment = frappe.get_doc({
        "doctype": "Marketplace Shipment",
        "sub_order": sub_order,
        "carrier": carrier,
        **kwargs
    })
    shipment.insert()

    return {
        "status": "success",
        "name": shipment.name,
        "shipment_id": shipment.shipment_id
    }


@frappe.whitelist()
def get_shipment(shipment_name=None, shipment_id=None, tracking_number=None):
    """
    Get shipment details.

    Args:
        shipment_name: Frappe document name
        shipment_id: Customer-facing shipment ID
        tracking_number: Carrier tracking number

    Returns:
        dict: Shipment details
    """
    # Find shipment by various identifiers
    name = shipment_name
    if shipment_id and not name:
        name = frappe.db.get_value(
            "Marketplace Shipment", {"shipment_id": shipment_id}, "name"
        )
    if tracking_number and not name:
        name = frappe.db.get_value(
            "Marketplace Shipment", {"tracking_number": tracking_number}, "name"
        )

    if not name:
        return {"error": _("Shipment not found")}

    shipment = frappe.get_doc("Marketplace Shipment", name)
    return {
        "shipment": shipment.get_summary(),
        "tracking": shipment.get_tracking_info()
    }


@frappe.whitelist()
def update_shipment_status(shipment_name, action, **kwargs):
    """
    Update shipment status.

    Args:
        shipment_name: Shipment name
        action: Action to perform
        **kwargs: Additional parameters

    Returns:
        dict: Updated status
    """
    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)

    if action == "generate_label":
        return shipment.generate_label()
    elif action == "schedule_pickup":
        return shipment.schedule_pickup(
            pickup_date=kwargs.get("pickup_date"),
            time_from=kwargs.get("time_from"),
            time_to=kwargs.get("time_to")
        )
    elif action == "picked_up":
        return shipment.mark_picked_up()
    elif action == "in_transit":
        return shipment.mark_in_transit()
    elif action == "out_for_delivery":
        return shipment.mark_out_for_delivery()
    elif action == "delivered":
        return shipment.mark_delivered(
            delivered_to=kwargs.get("delivered_to"),
            delivery_notes=kwargs.get("delivery_notes")
        )
    elif action == "failed_delivery":
        return shipment.mark_failed_delivery(reason=kwargs.get("reason"))
    elif action == "exception":
        return shipment.mark_exception(reason=kwargs.get("reason"))
    elif action == "initiate_return":
        return shipment.initiate_return(reason=kwargs.get("reason"))
    elif action == "complete_return":
        return shipment.complete_return()
    elif action == "cancel":
        return shipment.cancel_shipment(reason=kwargs.get("reason"))
    else:
        frappe.throw(_("Invalid action: {0}").format(action))


@frappe.whitelist()
def add_tracking_number(shipment_name, tracking_number, awb_number=None):
    """
    Add tracking number to shipment.

    Args:
        shipment_name: Shipment name
        tracking_number: Carrier tracking number
        awb_number: Air Waybill number (optional)

    Returns:
        dict: Updated shipment
    """
    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)
    shipment.tracking_number = tracking_number
    if awb_number:
        shipment.awb_number = awb_number
    shipment.save()

    return {
        "status": "success",
        "tracking_url": shipment.tracking_url
    }


@frappe.whitelist()
def get_sub_order_shipments(sub_order):
    """
    Get all shipments for a sub order.

    Args:
        sub_order: Sub Order name

    Returns:
        list: Shipments for the sub order
    """
    shipments = frappe.get_all(
        "Marketplace Shipment",
        filters={"sub_order": sub_order},
        fields=[
            "name", "shipment_id", "carrier", "tracking_number",
            "status", "delivery_status", "pickup_date",
            "expected_delivery_date", "actual_delivery_date",
            "is_return", "total_cost"
        ],
        order_by="creation DESC"
    )
    return shipments


@frappe.whitelist()
def get_seller_shipments(seller, status=None, page=1, page_size=20):
    """
    Get shipments for a seller.

    Args:
        seller: Seller Profile name
        status: Filter by status
        page: Page number
        page_size: Results per page

    Returns:
        dict: Shipments with pagination
    """
    filters = {"seller": seller}
    if status:
        filters["status"] = status

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Marketplace Shipment", filters)

    shipments = frappe.get_all(
        "Marketplace Shipment",
        filters=filters,
        fields=[
            "name", "shipment_id", "sub_order", "carrier",
            "tracking_number", "status", "delivery_status",
            "recipient_name", "destination_city",
            "pickup_date", "expected_delivery_date",
            "actual_delivery_date", "total_cost"
        ],
        order_by="creation DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "shipments": shipments,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def sync_shipment_tracking(shipment_name):
    """
    Sync tracking information from carrier.

    Args:
        shipment_name: Shipment name

    Returns:
        dict: Sync result
    """
    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)
    return shipment.sync_tracking()


@frappe.whitelist()
def create_return_shipment(shipment_name, reason=None):
    """
    Create a return shipment.

    Args:
        shipment_name: Original shipment name
        reason: Return reason

    Returns:
        dict: Return shipment details
    """
    shipment = frappe.get_doc("Marketplace Shipment", shipment_name)
    return shipment.create_return_shipment(reason=reason)


@frappe.whitelist()
def get_shipment_statistics(seller=None, days=30):
    """
    Get shipment statistics.

    Args:
        seller: Filter by seller
        days: Number of days to analyze

    Returns:
        dict: Shipment statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    filters = {"creation": [">=", from_date]}
    if seller:
        filters["seller"] = seller

    stats = frappe.db.sql("""
        SELECT
            status,
            COUNT(*) as count,
            SUM(total_cost) as total_cost,
            AVG(DATEDIFF(
                COALESCE(delivered_at, NOW()),
                created_at
            )) as avg_delivery_days
        FROM `tabMarketplace Shipment`
        WHERE creation >= %(from_date)s
        {seller_filter}
        GROUP BY status
    """.format(
        seller_filter=f"AND seller = %(seller)s" if seller else ""
    ), {"from_date": from_date, "seller": seller}, as_dict=True)

    status_data = {
        s.status: {
            "count": s.count,
            "total_cost": s.total_cost,
            "avg_delivery_days": round(s.avg_delivery_days or 0, 1)
        } for s in stats
    }

    total_shipments = sum(s.count for s in stats)
    delivered = status_data.get("Delivered", {}).get("count", 0)

    return {
        "period_days": cint(days),
        "total_shipments": total_shipments,
        "delivered": delivered,
        "delivery_rate": round(delivered / total_shipments * 100, 1) if total_shipments > 0 else 0,
        "status_breakdown": status_data
    }
