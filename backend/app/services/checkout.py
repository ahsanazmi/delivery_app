from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.address import Address
from app.models.delivery_partner import ApprovalStatus
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.addresses import get_address_for_user, list_addresses
from app.services.cart import calculate_cart_totals, get_cart_for_user, sync_cart_with_catalog
from app.services.admin_settings import get_platform_settings
from app.services.location_service import distance_km as _distance_km
from app.services.restaurant_hours import compute_is_accepting_orders, get_hours_for_restaurant
from app.services.service_areas import is_address_serviceable

_MIN_LATITUDE, _MAX_LATITUDE = Decimal("-90"), Decimal("90")
_MIN_LONGITUDE, _MAX_LONGITUDE = Decimal("-180"), Decimal("180")


def validate_delivery_location(address: Address | None, restaurant: Restaurant | None) -> list[str]:
    """Maps & Location System Phase 13 — Delivery Location Validation.
    Coordinates on an address are optional by design (manual entry
    without ever touching the map/search flow must keep working, per
    Phase 2), so this never blocks a checkout purely for missing
    latitude/longitude — only for a location that's actually broken:
    a lone lat with no lng (or vice versa), a coordinate outside its
    valid range, or a restaurant with no usable location at all.
    Both AddressCreate and Restaurant's own schemas/DB constraints
    already reject out-of-range or partial coordinates going in — this
    is the defensive, checkout-time re-check, catching any address row
    written before those guards existed or by a path that bypassed them.
    """
    issues: list[str] = []

    if address is not None:
        has_latitude = address.latitude is not None
        has_longitude = address.longitude is not None
        if has_latitude != has_longitude:
            issues.append("This address has an incomplete pinned location. Please update it on the map.")
        elif has_latitude and has_longitude:
            if not (_MIN_LATITUDE <= address.latitude <= _MAX_LATITUDE):
                issues.append("This address has an invalid latitude.")
            if not (_MIN_LONGITUDE <= address.longitude <= _MAX_LONGITUDE):
                issues.append("This address has an invalid longitude.")

    if restaurant is not None:
        if restaurant.latitude is None or restaurant.longitude is None:
            issues.append("This restaurant's location isn't configured yet.")
        elif not (_MIN_LATITUDE <= restaurant.latitude <= _MAX_LATITUDE) or not (
            _MIN_LONGITUDE <= restaurant.longitude <= _MAX_LONGITUDE
        ):
            issues.append("This restaurant's location is invalid.")

    return issues


def _checkout_issues(
    db: Session, cart_items: list, restaurant: Restaurant | None, subtotal, address: Address | None = None
) -> list[str]:
    if not cart_items:
        return ["Your cart is empty."]

    # Admin Portal Phase 22 — a platform-wide business rule; blocks every
    # checkout the same way an unserviceable address already does below,
    # rather than a separate code path.
    if get_platform_settings(db).maintenance_mode:
        return ["The platform is temporarily under maintenance. Please try again shortly."]

    issues: list[str] = []
    if restaurant is None or not restaurant.is_active or restaurant.approval_status != ApprovalStatus.APPROVED:
        return ["This restaurant is no longer available."]

    # Never just the manual toggle — a restaurant marked "open" outside its
    # own configured operating hours still can't actually take this order.
    hours = get_hours_for_restaurant(db, restaurant.id)
    if not compute_is_accepting_orders(restaurant, hours):
        issues.append("This restaurant is currently closed.")

    if subtotal < restaurant.minimum_order:
        shortfall = restaurant.minimum_order - subtotal
        issues.append(f"Minimum order is {restaurant.minimum_order}; add {shortfall} more to check out.")

    # Admin Portal Phase 16 — customer ordering must respect service-area
    # configuration. Only actually blocks anything once at least one
    # ServiceArea exists (see is_address_serviceable's own fail-open note).
    # Maps & Location System Phase 15 — Delivery Eligibility: this exact
    # message is the one the phase itself specifies for an ineligible
    # address, returned regardless of whether the frontend ever showed
    # this restaurant as orderable — eligibility is decided here, once,
    # authoritatively, not by whatever the UI happened to render.
    if address is not None and not is_address_serviceable(db, address):
        issues.append("Delivery is currently unavailable at this location.")

    issues.extend(validate_delivery_location(address, restaurant))

    return issues


def _restaurant_customer_distance_km(address: Address | None, restaurant: Restaurant | None) -> float | None:
    """Maps & Location System Phase 19 — Checkout Location Integration.
    None whenever either side has no pinned coordinates — coordinates are
    optional (Phase 13), so this is shown only "where appropriate," never
    required."""
    if address is None or restaurant is None:
        return None
    if address.latitude is None or address.longitude is None:
        return None
    return _distance_km(address.latitude, address.longitude, restaurant.latitude, restaurant.longitude)


def _load_cart_state(db: Session, user: User) -> dict:
    cart = get_cart_for_user(db, user.id)
    removed_items = sync_cart_with_catalog(db, cart)
    restaurant = db.get(Restaurant, cart.restaurant_id) if cart.restaurant_id else None
    totals = calculate_cart_totals(db, cart)
    return {
        "cart": cart,
        "restaurant": restaurant,
        "removed_items": removed_items,
        **totals,
    }


def get_checkout_preview(db: Session, user: User) -> dict:
    state = _load_cart_state(db, user)
    addresses = list_addresses(db, user.id)
    selected_address = addresses[0] if addresses else None
    issues = _checkout_issues(db, state["cart"].items, state["restaurant"], state["subtotal"], selected_address)
    if not addresses:
        issues.append("Add a delivery address before checking out.")

    return {
        "addresses": addresses,
        "selected_address": selected_address,
        "restaurant": state["restaurant"],
        "items": state["cart"].items,
        "subtotal": state["subtotal"],
        "delivery_fee": state["delivery_fee"],
        "tax": state["tax"],
        "discount": state["discount"],
        "total": state["total"],
        "total_items": state["total_items"],
        "removed_items": state["removed_items"],
        "coupon_code": state["coupon_code"],
        "coupon_message": state["coupon_message"],
        "distance_km": _restaurant_customer_distance_km(selected_address, state["restaurant"]),
        "issues": issues,
    }


def validate_checkout(db: Session, user: User, address_id: UUID) -> dict:
    state = _load_cart_state(db, user)
    address: Address | None = get_address_for_user(db, user.id, address_id)
    issues = _checkout_issues(db, state["cart"].items, state["restaurant"], state["subtotal"], address)

    if not address:
        issues.append("Select a valid delivery address.")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "cart": state["cart"],
        "address": address,
        "restaurant": state["restaurant"],
        "items": state["cart"].items,
        "subtotal": state["subtotal"],
        "delivery_fee": state["delivery_fee"],
        "tax": state["tax"],
        "discount": state["discount"],
        "total": state["total"],
        "total_items": state["total_items"],
        "removed_items": state["removed_items"],
        "coupon_code": state["coupon_code"],
        "coupon_id": state["cart"].coupon_id,
        "distance_km": _restaurant_customer_distance_km(address, state["restaurant"]),
    }
