from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import DbSession, require_customer
from app.models.cart import Cart
from app.models.user import User
from app.models.restaurant import Restaurant
from app.schemas.cart import CartItemCreate, CartItemRead, CartItemUpdate, CartRead, CartRestaurantRead
from app.schemas.coupon import ApplyCouponRequest
from app.services.cart import (
    add_item,
    calculate_cart_totals,
    clear_cart,
    get_cart_for_user,
    remove_item,
    sync_cart_with_catalog,
    update_item_quantity,
)
from app.services.coupons import apply_coupon_to_cart, remove_coupon_from_cart

router = APIRouter()


def serialize_cart(db: Session, cart: Cart, removed_items: list[str]) -> CartRead:
    restaurant = db.get(Restaurant, cart.restaurant_id) if cart.restaurant_id else None
    totals = calculate_cart_totals(db, cart)
    items = sorted(cart.items, key=lambda item: item.product_name)
    return CartRead(
        restaurant=CartRestaurantRead.model_validate(restaurant) if restaurant else None,
        items=[CartItemRead.model_validate(item) for item in items],
        subtotal=totals["subtotal"],
        delivery_fee=totals["delivery_fee"],
        tax=totals["tax"],
        discount=totals["discount"],
        total=totals["total"],
        total_items=totals["total_items"],
        removed_items=removed_items,
        coupon_code=totals["coupon_code"],
        coupon_message=totals["coupon_message"],
    )


@router.get("/cart", response_model=CartRead)
def get_cart(db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    removed = sync_cart_with_catalog(db, cart)
    return serialize_cart(db, cart, removed)


@router.post("/cart/items", response_model=CartRead, status_code=status.HTTP_201_CREATED)
def add_cart_item(payload: CartItemCreate, db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    # Drop anything that went stale (unavailable product, closed restaurant)
    # before evaluating the new item against the cart's restaurant, so a dead
    # leftover item can't block adding from a different restaurant, and so
    # existing items' prices are current before totals are recalculated below.
    removed = sync_cart_with_catalog(db, cart)
    try:
        add_item(db, cart, payload.product_id, payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.refresh(cart)
    return serialize_cart(db, cart, removed)


@router.patch("/cart/items/{item_id}", response_model=CartRead)
def update_cart_item(item_id: UUID, payload: CartItemUpdate, db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    # If the target item went stale since it was added, sync drops it here —
    # the update then correctly 404s instead of bumping the quantity of an
    # item that can no longer actually be ordered.
    removed = sync_cart_with_catalog(db, cart)
    result = update_item_quantity(db, cart, item_id, payload.quantity)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")
    db.refresh(cart)
    return serialize_cart(db, cart, removed)


@router.delete("/cart/items/{item_id}", response_model=CartRead)
def remove_cart_item(item_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    existed_before_sync = any(item.id == item_id for item in cart.items)
    removed = sync_cart_with_catalog(db, cart)
    # Sync may have already dropped this exact item (it went stale) — that
    # still satisfies "remove this item" and isn't a 404, unlike an item_id
    # that was never in this cart to begin with.
    remove_item(db, cart, item_id)
    if not existed_before_sync:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")
    db.refresh(cart)
    return serialize_cart(db, cart, removed)


@router.delete("/cart", response_model=CartRead)
def clear_cart_endpoint(db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    clear_cart(db, cart)
    db.refresh(cart)
    return serialize_cart(db, cart, [])


@router.post("/cart/apply-coupon", response_model=CartRead)
def apply_coupon(payload: ApplyCouponRequest, db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    # Sync first so the minimum-order/eligibility check inside
    # apply_coupon_to_cart is evaluated against current prices and items,
    # never a stale subtotal that includes an item about to be dropped.
    removed = sync_cart_with_catalog(db, cart)
    apply_coupon_to_cart(db, current_user.id, cart, payload.code)
    db.refresh(cart)
    return serialize_cart(db, cart, removed)


@router.delete("/cart/coupon", response_model=CartRead)
def remove_coupon(db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    remove_coupon_from_cart(db, cart)
    removed = sync_cart_with_catalog(db, cart)
    return serialize_cart(db, cart, removed)
