from uuid import UUID

from sqlalchemy.orm import Session

from app.models.address import Address
from app.models.delivery_partner import ApprovalStatus
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.addresses import get_address_for_user, list_addresses
from app.services.cart import calculate_cart_totals, get_cart_for_user, sync_cart_with_catalog
from app.services.admin_settings import get_platform_settings
from app.services.restaurant_hours import compute_is_accepting_orders, get_hours_for_restaurant
from app.services.service_areas import is_address_serviceable


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
    if address is not None and not is_address_serviceable(db, address):
        issues.append("We don't currently deliver to this address's area.")

    return issues


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
    }
