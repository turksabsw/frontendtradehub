# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Shipment DocType for Trade Hub B2B Marketplace.

This module implements shipment management for logistics and tracking.
Shipments are linked to Orders/Sub Orders and include carrier info, tracking,
customs documentation, and delivery confirmation.

Status Workflow:
- Draft: Shipment is being prepared
- Pending Pickup: Waiting for carrier pickup
- Picked Up: Package collected by carrier
- In Transit: Package is in transit
- At Customs: Package is at customs clearance
- Customs Cleared: Customs clearance completed
- Out for Delivery: Package out for final delivery
- Delivered: Package delivered to recipient
- Exception: Delivery exception occurred
- Returned: Package returned to sender
- Cancelled: Shipment cancelled

Key features:
- Multi-tenant data isolation via Order's tenant
- Marketplace Sub Order integration
- Carrier API integration for labels and tracking
- Comprehensive tracking information
- Customs documentation support
- Insurance and Incoterm management
- Proof of delivery capture
- Exception handling workflow
- fetch_from pattern for order, buyer, seller, and tenant information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    flt, cint, getdate, nowdate, now_datetime,
    get_datetime, add_days
)


# Incoterm descriptions
INCOTERM_DESCRIPTIONS = {
    "EXW": "Ex Works - Buyer bears all transportation costs and risks",
    "FOB": "Free on Board - Seller covers costs to port of shipment",
    "CIF": "Cost, Insurance, Freight - Seller covers costs, insurance, and freight to destination port",
    "DDP": "Delivered Duty Paid - Seller bears all costs including duties",
    "DAP": "Delivered at Place - Seller delivers to named destination, buyer handles import",
    "FCA": "Free Carrier - Seller delivers to carrier at named place",
    "CPT": "Carriage Paid To - Seller pays freight to destination",
    "CIP": "Carriage and Insurance Paid - Seller pays freight and insurance to destination",
    "DAT": "Delivered at Terminal - Seller delivers to terminal at destination",
    "DPU": "Delivered at Place Unloaded - Seller delivers and unloads at destination"
}

# Valid status transitions
STATUS_TRANSITIONS = {
    "Draft": ["Pending Pickup", "Cancelled"],
    "Pending Pickup": ["Picked Up", "Cancelled"],
    "Picked Up": ["In Transit", "Exception", "Cancelled"],
    "In Transit": ["At Customs", "Out for Delivery", "Delivered", "Exception", "Returned"],
    "At Customs": ["Customs Cleared", "Exception", "Returned"],
    "Customs Cleared": ["In Transit", "Out for Delivery", "Exception"],
    "Out for Delivery": ["Delivered", "Exception", "Returned"],
    "Delivered": [],
    "Exception": ["In Transit", "Out for Delivery", "Returned", "Delivered", "Cancelled"],
    "Returned": ["Cancelled"],
    "Cancelled": []
}

# Tracking status mapping
TRACKING_STATUS_MAP = {
    "Draft": "Pending",
    "Pending Pickup": "Label Created",
    "Picked Up": "Picked Up",
    "In Transit": "In Transit",
    "At Customs": "At Customs",
    "Customs Cleared": "At Hub",
    "Out for Delivery": "Out for Delivery",
    "Delivered": "Delivered",
    "Exception": "Exception",
    "Returned": "Returned",
    "Cancelled": "Pending"
}


class Shipment(Document):
    """
    Shipment DocType for B2B logistics management.

    Each Shipment represents a shipping transaction for an order.

    Features:
    - Link to Order with auto-fetched details
    - Carrier information and tracking
    - Customs clearance workflow
    - Insurance management
    - Proof of delivery
    - Exception handling
    - Multi-tenant isolation via Order's tenant
    """

    def before_insert(self):
        """Set defaults before inserting a new Shipment."""
        self.set_default_shipment_date()
        self.set_shipment_number()
        self.set_tenant_from_order()
        self.set_incoterm_description()
        self.copy_destination_from_order()

    def validate(self):
        """Validate Shipment data before saving."""
        self.validate_order()
        self.validate_status_transition()
        self.validate_tenant_isolation()
        self.validate_tracking_number()
        self.validate_customs_info()
        self.calculate_dimensional_weight()
        self.calculate_total_shipping_cost()
        self.set_incoterm_description()
        self.update_tracking_status()
        self.update_dates_on_status_change()

    def on_update(self):
        """Actions after Shipment is updated."""
        self.update_order_shipping_info()
        self.send_status_notification()
        self.clear_shipment_cache()

    def on_trash(self):
        """Actions before Shipment is deleted."""
        self.check_status_for_deletion()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_shipment_date(self):
        """Set default shipment date to today if not provided."""
        if not self.shipment_date:
            self.shipment_date = nowdate()

    def set_shipment_number(self):
        """Set shipment number for display purposes."""
        if not self.shipment_number:
            self.shipment_number = self.name or ""

    def set_tenant_from_order(self):
        """
        Set tenant from order if not already set.
        This provides multi-tenant isolation.
        """
        if self.order and not self.tenant:
            order_tenant = frappe.db.get_value("Order", self.order, "tenant")
            if order_tenant:
                self.tenant = order_tenant

    def set_incoterm_description(self):
        """Set description for the selected Incoterm."""
        if self.incoterm:
            self.incoterm_description = INCOTERM_DESCRIPTIONS.get(
                self.incoterm, ""
            )

    def copy_destination_from_order(self):
        """Copy delivery address from order if not provided."""
        if not self.order:
            return

        if not self.destination_address:
            order = frappe.get_doc("Order", self.order)
            self.destination_address = order.delivery_address
            self.destination_city = order.delivery_city
            self.destination_state = order.delivery_state
            self.destination_country = order.delivery_country
            self.destination_postal_code = order.delivery_postal_code
            self.destination_contact_person = order.delivery_contact_person

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_order(self):
        """Validate order link exists and is in valid status."""
        if not self.order:
            frappe.throw(_("Order is required"))

        order_status = frappe.db.get_value("Order", self.order, "status")
        valid_statuses = [
            "Confirmed", "Processing", "Ready to Ship", "Shipped", "Delivered"
        ]
        if order_status and order_status not in valid_statuses:
            frappe.throw(
                _("Cannot create Shipment: Order status is {0}. "
                  "Order must be Confirmed, Processing, or Ready to Ship.").format(
                    order_status
                )
            )

    def validate_status_transition(self):
        """Validate status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Shipment", self.name, "status")
        if old_status and old_status != self.status:
            valid_transitions = STATUS_TRANSITIONS.get(old_status, [])
            if self.status not in valid_transitions:
                frappe.throw(
                    _("Cannot change status from {0} to {1}. "
                      "Valid transitions are: {2}").format(
                        old_status, self.status,
                        ", ".join(valid_transitions) if valid_transitions else "None"
                    )
                )

    def validate_tenant_isolation(self):
        """
        Validate that Shipment belongs to user's tenant.
        Inherits tenant from Order to ensure multi-tenant data isolation.
        """
        if not self.tenant:
            return

        # System Manager can access all tenants
        if "System Manager" in frappe.get_roles():
            return

        # Get current user's tenant
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
        current_tenant = get_current_tenant()

        if current_tenant and self.tenant != current_tenant:
            frappe.throw(
                _("Access denied: You can only access Shipments in your tenant")
            )

    def validate_tracking_number(self):
        """Validate tracking number format if provided."""
        if self.tracking_number and not self.carrier:
            frappe.msgprint(
                _("Tracking number provided without carrier. "
                  "Please select a carrier for proper tracking."),
                indicator="orange"
            )

    def validate_customs_info(self):
        """Validate customs information if required."""
        if self.requires_customs:
            if not self.hs_code:
                frappe.msgprint(
                    _("HS Code is recommended for customs clearance"),
                    indicator="orange"
                )
            if not self.customs_value:
                frappe.msgprint(
                    _("Customs value is recommended for customs clearance"),
                    indicator="orange"
                )
            if not self.country_of_origin:
                frappe.msgprint(
                    _("Country of origin is recommended for customs clearance"),
                    indicator="orange"
                )

    # =========================================================================
    # CALCULATION METHODS
    # =========================================================================

    def calculate_dimensional_weight(self):
        """Calculate dimensional weight from dimensions."""
        if self.length and self.width and self.height:
            # Standard dimensional weight divisor
            divisor = 5000  # Common divisor for kg/cm
            self.dimensional_weight = flt(
                (flt(self.length) * flt(self.width) * flt(self.height)) / divisor,
                3
            )

    def calculate_total_shipping_cost(self):
        """Calculate total shipping cost."""
        self.total_shipping_cost = flt(
            flt(self.freight_cost) +
            flt(self.insurance_cost) +
            flt(self.customs_duty_amount) +
            flt(self.customs_tax_amount),
            2
        )

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def update_tracking_status(self):
        """Update tracking status based on shipment status."""
        if self.status:
            self.tracking_status = TRACKING_STATUS_MAP.get(
                self.status, self.tracking_status
            )
            self.last_tracking_update = now_datetime()

    def update_dates_on_status_change(self):
        """Update date fields based on status changes."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Shipment", self.name, "status")
        if old_status == self.status:
            return

        current_datetime = now_datetime()

        if self.status == "Picked Up":
            if not self.pickup_date:
                self.pickup_date = getdate(current_datetime)

        elif self.status == "In Transit":
            if not self.in_transit_date:
                self.in_transit_date = current_datetime

        elif self.status == "At Customs":
            if not self.customs_clearance_start:
                self.customs_clearance_start = current_datetime

        elif self.status == "Customs Cleared":
            if not self.customs_clearance_date:
                self.customs_clearance_date = getdate(current_datetime)

        elif self.status == "Out for Delivery":
            if not self.out_for_delivery_date:
                self.out_for_delivery_date = current_datetime

        elif self.status == "Delivered":
            if not self.actual_delivery_date:
                self.actual_delivery_date = getdate(current_datetime)
                self.delivery_time = current_datetime.strftime("%H:%M:%S")

        elif self.status == "Exception":
            if not self.exception_date:
                self.exception_date = current_datetime
            self.has_exception = 1

    def set_status(self, new_status, reason=None):
        """
        Change the status of the Shipment.

        Args:
            new_status: The new status to set
            reason: Optional reason for status change

        Returns:
            bool: True if status was changed successfully
        """
        valid_transitions = STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in valid_transitions:
            frappe.throw(
                _("Cannot change status from {0} to {1}").format(
                    self.status, new_status
                )
            )

        if reason:
            self.internal_notes = (self.internal_notes or "") + \
                f"\nStatus changed to {new_status}: {reason}"

        self.status = new_status
        self.save()
        return True

    def schedule_pickup(self, pickup_date=None, pickup_time=None):
        """
        Schedule carrier pickup.

        Args:
            pickup_date: Optional pickup date
            pickup_time: Optional pickup time

        Returns:
            bool: True if scheduled successfully
        """
        if self.status != "Draft":
            frappe.throw(_("Only Draft shipments can be scheduled for pickup"))

        if pickup_date:
            self.pickup_date = pickup_date
        if pickup_time:
            self.pickup_time = pickup_time

        return self.set_status("Pending Pickup")

    def mark_picked_up(self, tracking_number=None):
        """
        Mark shipment as picked up by carrier.

        Args:
            tracking_number: Optional tracking number

        Returns:
            bool: True if marked successfully
        """
        if self.status != "Pending Pickup":
            frappe.throw(_("Only Pending Pickup shipments can be marked as picked up"))

        if tracking_number:
            self.tracking_number = tracking_number

        return self.set_status("Picked Up")

    def mark_in_transit(self):
        """
        Mark shipment as in transit.

        Returns:
            bool: True if marked successfully
        """
        if self.status not in ["Picked Up", "Customs Cleared"]:
            frappe.throw(
                _("Only Picked Up or Customs Cleared shipments can be marked in transit")
            )

        return self.set_status("In Transit")

    def start_customs_clearance(self):
        """
        Mark shipment as at customs.

        Returns:
            bool: True if marked successfully
        """
        if self.status != "In Transit":
            frappe.throw(_("Only In Transit shipments can enter customs clearance"))

        self.requires_customs = 1
        self.customs_status = "Under Review"
        return self.set_status("At Customs")

    def clear_customs(self, duty_amount=None, tax_amount=None):
        """
        Mark customs as cleared.

        Args:
            duty_amount: Customs duty amount
            tax_amount: Customs tax amount

        Returns:
            bool: True if cleared successfully
        """
        if self.status != "At Customs":
            frappe.throw(_("Only shipments at customs can be cleared"))

        self.customs_status = "Cleared"
        if duty_amount is not None:
            self.customs_duty_amount = duty_amount
        if tax_amount is not None:
            self.customs_tax_amount = tax_amount

        return self.set_status("Customs Cleared")

    def mark_out_for_delivery(self):
        """
        Mark shipment as out for delivery.

        Returns:
            bool: True if marked successfully
        """
        valid_statuses = ["In Transit", "Customs Cleared"]
        if self.status not in valid_statuses:
            frappe.throw(
                _("Only In Transit or Customs Cleared shipments can be marked out for delivery")
            )

        return self.set_status("Out for Delivery")

    def mark_delivered(self, signature=None, pod_image=None, notes=None):
        """
        Mark shipment as delivered.

        Args:
            signature: Name of person who signed
            pod_image: Proof of delivery image
            notes: Delivery notes

        Returns:
            bool: True if marked successfully
        """
        if self.status not in ["Out for Delivery", "In Transit", "Exception"]:
            frappe.throw(
                _("Only Out for Delivery or In Transit shipments can be marked as delivered")
            )

        self.pod_received = 1
        if signature:
            self.pod_signature = signature
        if pod_image:
            self.pod_image = pod_image
        if notes:
            self.pod_notes = notes

        return self.set_status("Delivered")

    def report_exception(self, exception_type, description):
        """
        Report a delivery exception.

        Args:
            exception_type: Type of exception
            description: Description of the exception

        Returns:
            bool: True if reported successfully
        """
        self.has_exception = 1
        self.exception_type = exception_type
        self.exception_description = description

        return self.set_status("Exception")

    def resolve_exception(self, resolution_notes=None, next_status="In Transit"):
        """
        Resolve a delivery exception.

        Args:
            resolution_notes: Notes about the resolution
            next_status: Status to transition to after resolution

        Returns:
            bool: True if resolved successfully
        """
        if self.status != "Exception":
            frappe.throw(_("Only shipments with exceptions can be resolved"))

        self.exception_resolved = 1
        self.exception_resolution_date = now_datetime()

        if resolution_notes:
            self.internal_notes = (self.internal_notes or "") + \
                f"\nException resolved: {resolution_notes}"

        return self.set_status(next_status)

    def mark_returned(self, reason=None):
        """
        Mark shipment as returned.

        Args:
            reason: Reason for return

        Returns:
            bool: True if marked successfully
        """
        valid_statuses = ["In Transit", "Out for Delivery", "Exception", "At Customs"]
        if self.status not in valid_statuses:
            frappe.throw(
                _("Shipment cannot be marked as returned from {0} status").format(
                    self.status
                )
            )

        if reason:
            self.internal_notes = (self.internal_notes or "") + \
                f"\nReturn reason: {reason}"

        return self.set_status("Returned")

    def cancel_shipment(self, reason=None):
        """
        Cancel the shipment.

        Args:
            reason: Reason for cancellation

        Returns:
            bool: True if cancelled successfully
        """
        if self.status in ["Delivered"]:
            frappe.throw(_("Cannot cancel delivered shipments"))

        if reason:
            self.internal_notes = (self.internal_notes or "") + \
                f"\nCancellation reason: {reason}"

        return self.set_status("Cancelled")

    # =========================================================================
    # TRACKING MANAGEMENT
    # =========================================================================

    def add_tracking_event(self, event_status, location, timestamp=None, description=None):
        """
        Add a tracking event to the shipment.

        Args:
            event_status: Status of the tracking event
            location: Location of the event
            timestamp: Optional timestamp (defaults to now)
            description: Optional event description

        Returns:
            dict: The added tracking event
        """
        import json

        events = json.loads(self.tracking_events or "[]")

        event = {
            "status": event_status,
            "location": location,
            "timestamp": (timestamp or now_datetime()).isoformat(),
            "description": description
        }

        events.append(event)
        self.tracking_events = json.dumps(events)
        self.last_tracking_update = now_datetime()

        self.save()

        return event

    def update_tracking(self, tracking_number=None, tracking_url=None, tracking_status=None):
        """
        Update tracking information.

        Args:
            tracking_number: New tracking number
            tracking_url: New tracking URL
            tracking_status: New tracking status

        Returns:
            dict: Updated tracking info
        """
        if tracking_number:
            self.tracking_number = tracking_number
        if tracking_url:
            self.tracking_url = tracking_url
        if tracking_status:
            self.tracking_status = tracking_status

        self.last_tracking_update = now_datetime()
        self.save()

        return {
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url,
            "tracking_status": self.tracking_status,
            "last_update": self.last_tracking_update
        }

    # =========================================================================
    # ORDER UPDATES
    # =========================================================================

    def update_order_shipping_info(self):
        """Update linked order with shipping information."""
        if not self.order or self.is_new():
            return

        old_status = frappe.db.get_value("Shipment", self.name, "status")
        if old_status == self.status:
            return

        order = frappe.get_doc("Order", self.order)

        # Update order tracking info
        if self.tracking_number:
            order.tracking_number = self.tracking_number
        if self.carrier_name:
            order.shipping_carrier = self.carrier_name

        # Update order status based on shipment status
        if self.status == "Picked Up" and order.status in ["Ready to Ship", "Confirmed"]:
            order.status = "Shipped"
            order.shipped_date = now_datetime()
        elif self.status == "Delivered" and order.status == "Shipped":
            order.status = "Delivered"
            order.delivered_date = now_datetime()

        order.flags.ignore_permissions = True
        order.save()

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    def send_status_notification(self):
        """Send notification on status change."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Shipment", self.name, "status")
        if old_status == self.status:
            return

        # Future: Implement notification system
        # This would send email/push notifications to relevant parties
        pass

    # =========================================================================
    # DELETION CHECKS
    # =========================================================================

    def check_status_for_deletion(self):
        """Check if Shipment can be deleted based on status."""
        if self.status not in ["Draft", "Cancelled"]:
            frappe.throw(
                _("Cannot delete Shipment with status {0}. "
                  "Only Draft or Cancelled shipments can be deleted.").format(
                    self.status
                )
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_shipment_cache(self):
        """Clear cached Shipment data."""
        cache_keys = [
            f"shipment:{self.name}",
            f"order_shipments:{self.order}",
            f"seller_shipments:{self.seller}",
            f"buyer_shipments:{self.buyer}",
            f"tenant_shipments:{self.tenant}",
        ]
        if self.sub_order:
            cache_keys.append(f"sub_order_shipments:{self.sub_order}")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # CARRIER API INTEGRATION
    # =========================================================================

    def generate_label_from_api(self):
        """
        Generate shipping label via carrier API.

        Returns:
            dict: Label generation result with tracking number and label URL
        """
        if not self.carrier:
            frappe.throw(_("Carrier is required to generate a label"))

        carrier = frappe.get_doc("Carrier", self.carrier)

        if not carrier.has_api_integration or not carrier.supports_label_api:
            frappe.throw(
                _("Carrier {0} does not support API label generation").format(
                    self.carrier_name
                )
            )

        # Build shipment data for API
        shipment_data = self._build_label_request_data()

        # Generate label via carrier API
        result = carrier.create_shipment_label(shipment_data)

        if result.get("status") == "success":
            # Update shipment with label info
            self.tracking_number = result.get("tracking_number")
            self.label_generated = 1
            self.label_url = result.get("label_url")
            self.carrier_shipment_id = result.get("shipment_id")

            # Generate tracking URL if carrier has template
            if carrier.tracking_url_template and self.tracking_number:
                self.tracking_url = carrier.get_tracking_url(self.tracking_number)

            self.tracking_status = "Label Created"
            self.last_tracking_update = now_datetime()

            self.save()

            frappe.msgprint(_("Shipping label generated successfully"))
            return result
        else:
            frappe.throw(
                _("Failed to generate label: {0}").format(
                    result.get("message", "Unknown error")
                )
            )

    def _build_label_request_data(self):
        """
        Build label request data for carrier API.

        Returns:
            dict: Label request data
        """
        return {
            "sender": {
                "name": self.seller_name or "",
                "company": self.seller_company or "",
                "address": self.origin_address or "",
                "city": self.origin_city or "",
                "state": self.origin_state or "",
                "postal_code": self.origin_postal_code or "",
                "country": self.origin_country or "Turkey",
                "phone": self.origin_phone or "",
                "contact_person": self.origin_contact_person or ""
            },
            "receiver": {
                "name": self.buyer_name or "",
                "company": self.buyer_company or "",
                "address": self.destination_address or "",
                "city": self.destination_city or "",
                "state": self.destination_state or "",
                "postal_code": self.destination_postal_code or "",
                "country": self.destination_country or "Turkey",
                "phone": self.destination_phone or "",
                "contact_person": self.destination_contact_person or ""
            },
            "package": {
                "weight": flt(self.total_weight),
                "length": flt(self.length),
                "width": flt(self.width),
                "height": flt(self.height),
                "quantity": cint(self.package_count) or 1,
                "description": self.package_description or ""
            },
            "service_type": self.shipment_type or "Standard",
            "reference": self.name,
            "order_reference": self.sub_order_id or self.order_number or "",
            "cod_amount": flt(self.order_total) if self.incoterm == "COD" else 0,
            "insurance_value": flt(self.insurance_value) if self.is_insured else 0,
            "contents": self.package_description or "Commercial goods"
        }

    def fetch_tracking_from_api(self):
        """
        Fetch tracking information from carrier API.

        Returns:
            dict: Tracking information with events
        """
        if not self.carrier or not self.tracking_number:
            return {"status": "error", "message": _("Carrier and tracking number required")}

        carrier = frappe.get_doc("Carrier", self.carrier)

        result = carrier.get_tracking_from_api(self.tracking_number)

        if result.get("status") == "success":
            # Update tracking information
            current_status = result.get("current_status")
            if current_status:
                self.tracking_status = current_status

            self.last_tracking_update = now_datetime()

            # Update shipment status based on tracking
            self._update_status_from_tracking(result)

            # Store tracking events
            if result.get("events"):
                import json
                self.tracking_events = json.dumps(result.get("events"))

            # Check for delivery
            if result.get("delivered"):
                if self.status not in ["Delivered", "Cancelled"]:
                    self.actual_delivery_date = getdate(
                        result.get("delivery_date") or nowdate()
                    )
                    self.status = "Delivered"
                    self.tracking_status = "Delivered"

            self.save()

        return result

    def _update_status_from_tracking(self, tracking_result):
        """
        Update shipment status based on tracking result.

        Args:
            tracking_result: Tracking API result dict
        """
        current_status = tracking_result.get("current_status", "").upper()

        # Map common tracking statuses to shipment statuses
        status_mapping = {
            "PICKED UP": "Picked Up",
            "IN_TRANSIT": "In Transit",
            "IN TRANSIT": "In Transit",
            "OUT_FOR_DELIVERY": "Out for Delivery",
            "OUT FOR DELIVERY": "Out for Delivery",
            "DELIVERED": "Delivered",
            "EXCEPTION": "Exception",
            "RETURNED": "Returned",
            "AT_CUSTOMS": "At Customs",
            "CUSTOMS_CLEARED": "Customs Cleared"
        }

        new_status = status_mapping.get(current_status)
        if new_status and new_status != self.status:
            # Validate transition
            valid_transitions = STATUS_TRANSITIONS.get(self.status, [])
            if new_status in valid_transitions:
                self.status = new_status

    def update_tracking_status(self, status, payload=None):
        """
        Update tracking status from webhook or API.

        Args:
            status: New tracking status
            payload: Optional additional payload data

        Returns:
            dict: Update result
        """
        import json

        self.tracking_status = status
        self.last_tracking_update = now_datetime()

        # Add tracking event if payload provided
        if payload:
            events = json.loads(self.tracking_events or "[]")
            events.append({
                "status": status,
                "timestamp": now_datetime().isoformat(),
                "location": payload.get("location", ""),
                "description": payload.get("description", "")
            })
            self.tracking_events = json.dumps(events)

        # Map tracking status to shipment status
        self._update_status_from_tracking({"current_status": status})

        self.save()

        return {"status": "success", "tracking_status": self.tracking_status}

    # =========================================================================
    # SUB ORDER INTEGRATION (MARKETPLACE)
    # =========================================================================

    def set_from_sub_order(self, sub_order_name):
        """
        Set shipment details from a Sub Order.

        Args:
            sub_order_name: Sub Order document name
        """
        sub_order = frappe.get_doc("Sub Order", sub_order_name)

        self.sub_order = sub_order_name
        self.order = sub_order.parent_order

        # Copy seller info
        self.seller = sub_order.seller
        if sub_order.seller:
            seller = frappe.db.get_value(
                "Seller Profile",
                sub_order.seller,
                ["company_name", "primary_email", "primary_phone", "warehouse_address",
                 "warehouse_city", "warehouse_state", "warehouse_country", "warehouse_postal_code"],
                as_dict=True
            )
            if seller:
                self.seller_company = seller.company_name
                self.seller_email = seller.primary_email
                self.seller_phone = seller.primary_phone
                self.origin_address = seller.warehouse_address
                self.origin_city = seller.warehouse_city
                self.origin_state = seller.warehouse_state
                self.origin_country = seller.warehouse_country
                self.origin_postal_code = seller.warehouse_postal_code

        # Copy buyer info from parent order
        if sub_order.parent_order:
            order = frappe.get_doc("Order", sub_order.parent_order)
            self.buyer = order.buyer
            self.buyer_name = order.buyer_name
            self.buyer_company = order.buyer_company
            self.buyer_email = order.buyer_email
            self.buyer_phone = order.buyer_phone

            # Copy shipping address
            self.destination_address = order.delivery_address
            self.destination_city = order.delivery_city
            self.destination_state = order.delivery_state
            self.destination_country = order.delivery_country
            self.destination_postal_code = order.delivery_postal_code
            self.destination_contact_person = order.delivery_contact_person

        # Set tenant from sub order
        self.tenant = sub_order.tenant

    def update_sub_order_on_delivery(self):
        """
        Update linked Sub Order when shipment is delivered.
        Triggers the seller payout workflow.
        """
        if not self.sub_order:
            return

        if self.status != "Delivered":
            return

        try:
            sub_order = frappe.get_doc("Sub Order", self.sub_order)

            # Update sub order status
            if sub_order.status not in ["Delivered", "Completed", "Cancelled"]:
                sub_order.db_set("status", "Delivered")
                sub_order.db_set("delivered_at", now_datetime())

                # Handle delivery confirmation - triggers payout
                if hasattr(sub_order, 'handle_delivery_confirmation'):
                    sub_order.handle_delivery_confirmation()

            frappe.db.commit()

        except Exception as e:
            frappe.log_error(
                f"Failed to update Sub Order {self.sub_order} on delivery: {str(e)}",
                "Shipment Delivery Error"
            )

    def handle_delivery_confirmation(self):
        """
        Handle delivery confirmation callback from webhook.
        Called when carrier confirms delivery.
        """
        self.status = "Delivered"
        self.actual_delivery_date = getdate(nowdate())
        self.delivery_time = now_datetime().strftime("%H:%M:%S")
        self.tracking_status = "Delivered"
        self.pod_received = 1

        self.save()

        # Update sub order
        self.update_sub_order_on_delivery()

    def notify_buyer_of_shipment(self):
        """
        Send shipment notification to buyer.
        Called when shipment is picked up or in transit.
        """
        if not self.buyer_email:
            return

        # Future: Implement email notification
        # frappe.sendmail(
        #     recipients=[self.buyer_email],
        #     subject=_("Your order has been shipped"),
        #     template="shipment_notification",
        #     args={
        #         "shipment": self,
        #         "tracking_url": self.tracking_url,
        #         "tracking_number": self.tracking_number
        #     }
        # )
        pass

    def get_estimated_delivery(self):
        """
        Calculate estimated delivery date based on carrier transit days.

        Returns:
            date: Estimated delivery date
        """
        if self.estimated_delivery_date:
            return self.estimated_delivery_date

        transit_days = 5  # Default

        if self.carrier:
            carrier_transit = frappe.db.get_value(
                "Carrier", self.carrier, "default_transit_days"
            )
            if carrier_transit:
                transit_days = cint(carrier_transit)

        # Calculate from pickup or shipment date
        base_date = self.pickup_date or self.shipment_date or nowdate()
        return add_days(base_date, transit_days)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_shipment_list(order=None, seller=None, buyer=None, status=None,
                      tenant=None, carrier=None, limit=20, offset=0):
    """
    Get list of Shipments with optional filters.

    Args:
        order: Optional order filter
        seller: Optional seller filter
        buyer: Optional buyer filter
        status: Optional status filter
        tenant: Optional tenant filter
        carrier: Optional carrier filter
        limit: Number of records to return (default 20)
        offset: Starting position (default 0)

    Returns:
        list: List of Shipment records
    """
    filters = {}

    if order:
        filters["order"] = order
    if seller:
        filters["seller"] = seller
    if buyer:
        filters["buyer"] = buyer
    if status:
        filters["status"] = status
    if tenant:
        filters["tenant"] = tenant
    if carrier:
        filters["carrier"] = carrier

    shipments = frappe.get_all(
        "Shipment",
        filters=filters,
        fields=[
            "name", "shipment_number", "status", "shipment_type",
            "shipment_date", "order", "order_number",
            "buyer_name", "seller_name", "carrier_name",
            "tracking_number", "tracking_status",
            "destination_city", "destination_country",
            "estimated_delivery_date", "actual_delivery_date"
        ],
        order_by="shipment_date desc",
        start=cint(offset),
        page_length=cint(limit)
    )

    return shipments


@frappe.whitelist()
def get_shipment_details(shipment_name):
    """
    Get detailed Shipment information.

    Args:
        shipment_name: The Shipment document name

    Returns:
        dict: Shipment details with tracking history
    """
    shipment = frappe.get_doc("Shipment", shipment_name)

    import json
    tracking_events = json.loads(shipment.tracking_events or "[]")

    return {
        "shipment": shipment.as_dict(),
        "tracking_events": tracking_events
    }


@frappe.whitelist()
def create_shipment(order, shipment_type="Standard", carrier=None,
                    origin_address=None, origin_city=None, origin_country=None,
                    pickup_date=None, incoterm="EXW"):
    """
    Create a new Shipment for an order.

    Args:
        order: The Order document name
        shipment_type: Type of shipment
        carrier: Optional carrier
        origin_address: Origin/pickup address
        origin_city: Origin city
        origin_country: Origin country
        pickup_date: Scheduled pickup date
        incoterm: Incoterm (default EXW)

    Returns:
        dict: Created Shipment info
    """
    doc = frappe.new_doc("Shipment")
    doc.order = order
    doc.shipment_type = shipment_type
    doc.carrier = carrier
    doc.origin_address = origin_address
    doc.origin_city = origin_city
    doc.origin_country = origin_country
    doc.pickup_date = pickup_date
    doc.incoterm = incoterm

    doc.insert()

    return {
        "name": doc.name,
        "message": _("Shipment created successfully"),
        "status": doc.status
    }


@frappe.whitelist()
def schedule_shipment_pickup(shipment_name, pickup_date=None, pickup_time=None):
    """
    Schedule pickup for a shipment.

    Args:
        shipment_name: The Shipment document name
        pickup_date: Scheduled pickup date
        pickup_time: Scheduled pickup time

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.schedule_pickup(pickup_date, pickup_time)

    return {
        "success": True,
        "message": _("Pickup scheduled"),
        "status": doc.status
    }


@frappe.whitelist()
def mark_shipment_picked_up(shipment_name, tracking_number=None):
    """
    Mark shipment as picked up.

    Args:
        shipment_name: The Shipment document name
        tracking_number: Tracking number

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.mark_picked_up(tracking_number)

    return {
        "success": True,
        "message": _("Shipment picked up"),
        "status": doc.status,
        "tracking_number": doc.tracking_number
    }


@frappe.whitelist()
def update_shipment_tracking(shipment_name, tracking_number=None,
                             tracking_url=None, tracking_status=None):
    """
    Update shipment tracking information.

    Args:
        shipment_name: The Shipment document name
        tracking_number: New tracking number
        tracking_url: New tracking URL
        tracking_status: New tracking status

    Returns:
        dict: Updated tracking info
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    return doc.update_tracking(tracking_number, tracking_url, tracking_status)


@frappe.whitelist()
def add_shipment_tracking_event(shipment_name, event_status, location,
                                timestamp=None, description=None):
    """
    Add a tracking event to shipment.

    Args:
        shipment_name: The Shipment document name
        event_status: Status of the event
        location: Location of the event
        timestamp: Event timestamp
        description: Event description

    Returns:
        dict: Added tracking event
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    return doc.add_tracking_event(event_status, location, timestamp, description)


@frappe.whitelist()
def mark_shipment_in_transit(shipment_name):
    """
    Mark shipment as in transit.

    Args:
        shipment_name: The Shipment document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.mark_in_transit()

    return {
        "success": True,
        "message": _("Shipment in transit"),
        "status": doc.status
    }


@frappe.whitelist()
def start_shipment_customs(shipment_name):
    """
    Start customs clearance for shipment.

    Args:
        shipment_name: The Shipment document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.start_customs_clearance()

    return {
        "success": True,
        "message": _("Customs clearance started"),
        "status": doc.status
    }


@frappe.whitelist()
def clear_shipment_customs(shipment_name, duty_amount=None, tax_amount=None):
    """
    Clear customs for shipment.

    Args:
        shipment_name: The Shipment document name
        duty_amount: Customs duty amount
        tax_amount: Customs tax amount

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.clear_customs(
        flt(duty_amount) if duty_amount else None,
        flt(tax_amount) if tax_amount else None
    )

    return {
        "success": True,
        "message": _("Customs cleared"),
        "status": doc.status,
        "total_customs": flt(doc.customs_duty_amount) + flt(doc.customs_tax_amount)
    }


@frappe.whitelist()
def mark_shipment_out_for_delivery(shipment_name):
    """
    Mark shipment as out for delivery.

    Args:
        shipment_name: The Shipment document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.mark_out_for_delivery()

    return {
        "success": True,
        "message": _("Shipment out for delivery"),
        "status": doc.status
    }


@frappe.whitelist()
def mark_shipment_delivered(shipment_name, signature=None, pod_image=None, notes=None):
    """
    Mark shipment as delivered.

    Args:
        shipment_name: The Shipment document name
        signature: Recipient signature name
        pod_image: Proof of delivery image
        notes: Delivery notes

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.mark_delivered(signature, pod_image, notes)

    return {
        "success": True,
        "message": _("Shipment delivered"),
        "status": doc.status,
        "delivery_date": doc.actual_delivery_date
    }


@frappe.whitelist()
def report_shipment_exception(shipment_name, exception_type, description):
    """
    Report a delivery exception.

    Args:
        shipment_name: The Shipment document name
        exception_type: Type of exception
        description: Exception description

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.report_exception(exception_type, description)

    return {
        "success": True,
        "message": _("Exception reported"),
        "status": doc.status,
        "exception_type": doc.exception_type
    }


@frappe.whitelist()
def resolve_shipment_exception(shipment_name, resolution_notes=None, next_status="In Transit"):
    """
    Resolve a shipment exception.

    Args:
        shipment_name: The Shipment document name
        resolution_notes: Resolution notes
        next_status: Status to transition to

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.resolve_exception(resolution_notes, next_status)

    return {
        "success": True,
        "message": _("Exception resolved"),
        "status": doc.status
    }


@frappe.whitelist()
def cancel_shipment(shipment_name, reason=None):
    """
    Cancel a shipment.

    Args:
        shipment_name: The Shipment document name
        reason: Cancellation reason

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Shipment", shipment_name)
    doc.cancel_shipment(reason)

    return {
        "success": True,
        "message": _("Shipment cancelled"),
        "status": doc.status
    }


@frappe.whitelist()
def get_order_shipments(order_name, limit=10):
    """
    Get all shipments for an order.

    Args:
        order_name: The Order document name
        limit: Number of records to return

    Returns:
        list: List of shipments
    """
    return get_shipment_list(order=order_name, limit=limit)


@frappe.whitelist()
def get_shipment_statistics(seller=None, buyer=None, tenant=None,
                            date_from=None, date_to=None):
    """
    Get Shipment statistics.

    Args:
        seller: Optional seller filter
        buyer: Optional buyer filter
        tenant: Optional tenant filter
        date_from: Start date
        date_to: End date

    Returns:
        dict: Statistics including counts, delivery rates, etc.
    """
    filters = {}

    if seller:
        filters["seller"] = seller
    if buyer:
        filters["buyer"] = buyer
    if tenant:
        filters["tenant"] = tenant
    if date_from:
        filters["shipment_date"] = [">=", date_from]
    if date_to:
        if "shipment_date" in filters:
            filters["shipment_date"] = ["between", [date_from, date_to]]
        else:
            filters["shipment_date"] = ["<=", date_to]

    # Get counts by status
    status_counts = frappe.db.get_all(
        "Shipment",
        filters=filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    status_dict = {s.status: s.count for s in status_counts}
    total = sum(status_dict.values())

    # Calculate delivery metrics
    delivered = status_dict.get("Delivered", 0)
    returned = status_dict.get("Returned", 0)
    exceptions = status_dict.get("Exception", 0)

    delivery_rate = (delivered / total * 100) if total > 0 else 0
    exception_rate = (exceptions / total * 100) if total > 0 else 0

    # Calculate average delivery time
    avg_delivery = frappe.db.sql("""
        SELECT AVG(DATEDIFF(actual_delivery_date, shipment_date)) as avg_days
        FROM `tabShipment`
        WHERE status = 'Delivered'
        AND actual_delivery_date IS NOT NULL
        {filters}
    """.format(
        filters="AND seller = %(seller)s" if seller else ""
    ), {"seller": seller} if seller else {}, as_dict=True)

    avg_delivery_days = flt(avg_delivery[0].avg_days if avg_delivery else 0, 1)

    return {
        "total_shipments": total,
        "status_breakdown": status_dict,
        "in_transit_count": status_dict.get("In Transit", 0),
        "delivered_count": delivered,
        "returned_count": returned,
        "exception_count": exceptions,
        "delivery_rate": flt(delivery_rate, 1),
        "exception_rate": flt(exception_rate, 1),
        "average_delivery_days": avg_delivery_days
    }


@frappe.whitelist()
def get_incoterm_description(incoterm):
    """
    Get description for an Incoterm.

    Args:
        incoterm: The Incoterm code

    Returns:
        str: Description of the Incoterm
    """
    return INCOTERM_DESCRIPTIONS.get(incoterm, "")


# =============================================================================
# MARKETPLACE SHIPMENT API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def create_shipment_from_sub_order(sub_order_name, carrier=None, shipment_type="Standard"):
    """
    Create a Shipment from a marketplace Sub Order.

    Args:
        sub_order_name: Sub Order document name
        carrier: Optional carrier code
        shipment_type: Type of shipment (default: Standard)

    Returns:
        dict: Created shipment info
    """
    # Validate sub order exists and is in valid status
    sub_order = frappe.get_doc("Sub Order", sub_order_name)

    valid_statuses = ["Confirmed", "Processing", "Ready to Ship"]
    if sub_order.status not in valid_statuses:
        frappe.throw(
            _("Cannot create shipment: Sub Order status must be {0}").format(
                ", ".join(valid_statuses)
            )
        )

    # Check if shipment already exists
    existing = frappe.db.exists("Shipment", {"sub_order": sub_order_name})
    if existing:
        frappe.throw(
            _("Shipment already exists for this Sub Order: {0}").format(existing)
        )

    # Create shipment
    shipment = frappe.new_doc("Shipment")
    shipment.shipment_type = shipment_type
    shipment.carrier = carrier

    # Set details from sub order
    shipment.set_from_sub_order(sub_order_name)

    shipment.insert()

    # Update sub order status
    sub_order.db_set("status", "Ready to Ship")

    return {
        "name": shipment.name,
        "shipment_number": shipment.shipment_number,
        "status": shipment.status,
        "message": _("Shipment created successfully")
    }


@frappe.whitelist()
def generate_shipping_label(shipment_name):
    """
    Generate shipping label for a shipment via carrier API.

    Args:
        shipment_name: Shipment document name

    Returns:
        dict: Label generation result
    """
    shipment = frappe.get_doc("Shipment", shipment_name)

    if shipment.label_generated:
        return {
            "status": "already_generated",
            "tracking_number": shipment.tracking_number,
            "label_url": shipment.label_url
        }

    result = shipment.generate_label_from_api()
    return result


@frappe.whitelist()
def fetch_shipment_tracking(shipment_name):
    """
    Fetch tracking information for a shipment from carrier API.

    Args:
        shipment_name: Shipment document name

    Returns:
        dict: Tracking information
    """
    shipment = frappe.get_doc("Shipment", shipment_name)
    return shipment.fetch_tracking_from_api()


@frappe.whitelist()
def bulk_fetch_tracking():
    """
    Fetch tracking for all active shipments.
    Called by scheduled job.

    Returns:
        dict: Processing summary
    """
    # Find shipments that need tracking updates
    shipments = frappe.db.sql("""
        SELECT s.name, s.tracking_number, s.carrier
        FROM `tabShipment` s
        INNER JOIN `tabCarrier` c ON s.carrier = c.name
        WHERE s.status IN ('Pending Pickup', 'Picked Up', 'In Transit', 'At Customs', 'Out for Delivery')
        AND s.tracking_number IS NOT NULL
        AND c.has_api_integration = 1
        AND c.tracking_api_enabled = 1
    """, as_dict=True)

    updated = 0
    failed = 0
    errors = []

    for shipment in shipments:
        try:
            doc = frappe.get_doc("Shipment", shipment.name)
            result = doc.fetch_tracking_from_api()
            if result.get("status") == "success":
                updated += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            errors.append(f"{shipment.name}: {str(e)}")
            frappe.log_error(
                f"Failed to fetch tracking for {shipment.name}: {str(e)}",
                "Shipment Tracking Error"
            )

    frappe.db.commit()

    return {
        "status": "completed",
        "updated": updated,
        "failed": failed,
        "total": len(shipments),
        "errors": errors[:10]  # Limit error list
    }


@frappe.whitelist()
def get_sub_order_shipments(sub_order_name):
    """
    Get all shipments for a Sub Order.

    Args:
        sub_order_name: Sub Order document name

    Returns:
        list: List of shipments
    """
    return frappe.get_all(
        "Shipment",
        filters={"sub_order": sub_order_name},
        fields=[
            "name", "shipment_number", "status", "shipment_type",
            "carrier_name", "tracking_number", "tracking_status",
            "estimated_delivery_date", "actual_delivery_date",
            "label_generated", "label_url"
        ],
        order_by="creation desc"
    )


@frappe.whitelist()
def ship_sub_order(sub_order_name, carrier, tracking_number=None, generate_label=False):
    """
    Complete workflow to ship a Sub Order.
    Creates shipment, optionally generates label, and updates status.

    Args:
        sub_order_name: Sub Order document name
        carrier: Carrier code
        tracking_number: Optional manual tracking number
        generate_label: Whether to generate label via API

    Returns:
        dict: Shipping result
    """
    # Create shipment
    shipment_result = create_shipment_from_sub_order(sub_order_name, carrier)
    shipment_name = shipment_result.get("name")

    shipment = frappe.get_doc("Shipment", shipment_name)

    # Set tracking number or generate label
    if generate_label:
        try:
            label_result = shipment.generate_label_from_api()
            tracking_number = label_result.get("tracking_number")
        except Exception as e:
            frappe.msgprint(
                _("Label generation failed: {0}. Please add tracking manually.").format(str(e))
            )

    if tracking_number:
        shipment.tracking_number = tracking_number
        # Generate tracking URL
        if shipment.carrier:
            carrier_doc = frappe.get_doc("Carrier", shipment.carrier)
            if carrier_doc.tracking_url_template:
                shipment.tracking_url = carrier_doc.get_tracking_url(tracking_number)

    # Move to Pending Pickup
    shipment.status = "Pending Pickup"
    shipment.tracking_status = "Label Created" if shipment.label_generated else "Pending"
    shipment.save()

    # Update Sub Order status
    sub_order = frappe.get_doc("Sub Order", sub_order_name)
    sub_order.db_set("status", "Shipped")
    sub_order.db_set("tracking_number", tracking_number)
    sub_order.db_set("shipped_at", now_datetime())

    frappe.db.commit()

    return {
        "shipment": shipment.name,
        "shipment_number": shipment.shipment_number,
        "tracking_number": tracking_number,
        "label_url": shipment.label_url,
        "tracking_url": shipment.tracking_url,
        "status": shipment.status,
        "message": _("Sub Order shipped successfully")
    }


@frappe.whitelist()
def confirm_delivery(shipment_name, signature=None, pod_image=None, notes=None):
    """
    Confirm delivery of a shipment.
    Triggers Sub Order delivery and seller payout workflow.

    Args:
        shipment_name: Shipment document name
        signature: Recipient signature name
        pod_image: Proof of delivery image
        notes: Delivery notes

    Returns:
        dict: Confirmation result
    """
    shipment = frappe.get_doc("Shipment", shipment_name)

    # Mark as delivered
    shipment.mark_delivered(signature, pod_image, notes)

    # Update sub order
    shipment.update_sub_order_on_delivery()

    return {
        "status": "success",
        "shipment": shipment_name,
        "delivery_date": shipment.actual_delivery_date,
        "message": _("Delivery confirmed and seller payout scheduled")
    }


@frappe.whitelist()
def get_seller_active_shipments(seller, limit=20):
    """
    Get active shipments for a seller.

    Args:
        seller: Seller Profile name
        limit: Number of records to return

    Returns:
        list: List of active shipments
    """
    return frappe.get_all(
        "Shipment",
        filters={
            "seller": seller,
            "status": ["in", ["Draft", "Pending Pickup", "Picked Up", "In Transit",
                              "At Customs", "Customs Cleared", "Out for Delivery"]]
        },
        fields=[
            "name", "shipment_number", "status", "shipment_type",
            "sub_order", "sub_order_id", "buyer_name",
            "carrier_name", "tracking_number", "tracking_status",
            "destination_city", "destination_country",
            "estimated_delivery_date", "shipment_date"
        ],
        order_by="shipment_date desc",
        limit_page_length=cint(limit)
    )


@frappe.whitelist()
def get_buyer_shipments(buyer, limit=20):
    """
    Get shipments for a buyer.

    Args:
        buyer: Buyer Profile name
        limit: Number of records to return

    Returns:
        list: List of shipments
    """
    return frappe.get_all(
        "Shipment",
        filters={"buyer": buyer},
        fields=[
            "name", "shipment_number", "status", "shipment_type",
            "sub_order", "sub_order_id", "seller_name",
            "carrier_name", "tracking_number", "tracking_url",
            "tracking_status", "estimated_delivery_date",
            "actual_delivery_date", "shipment_date"
        ],
        order_by="shipment_date desc",
        limit_page_length=cint(limit)
    )
