from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cart import Cart, CartItem
from app.models.coupon import Coupon
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.services import products as product_service
from app.services import restaurants as restaurant_service
from app.services.coupons import calculate_coupon_discount, validate_coupon_for_cart


def create_cart_for_user(db: Session, user_id: UUID) -> Cart:
    cart = db.query(Cart).filter(Cart.user_id == user_id).first()
    if cart:
        return cart
    cart = Cart(user_id=user_id)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


def get_cart_for_user(db: Session, user_id: UUID) -> Cart:
    return create_cart_for_user(db, user_id)


def sync_cart_with_catalog(db: Session, cart: Cart) -> list[str]:
    """Re-validate every cart item against the current catalog.

    Drops items whose product or restaurant is no longer active/available, and
    refreshes the cached name/price of items that are still valid. Returns the
    names of any items that were removed, so the caller can surface that to the
    customer.
    """
    removed_names: list[str] = []
    for item in list(cart.items):
        product = db.get(Product, item.product_id)
        restaurant = db.get(Restaurant, item.restaurant_id)
        still_valid = (
            product is not None
            and product.is_active
            and product.is_available
            and restaurant is not None
            and restaurant.is_active
        )
        if not still_valid:
            removed_names.append(item.product_name)
            db.delete(item)
            continue
        if item.unit_price != product.price or item.product_name != product.name:
            item.unit_price = product.price
            item.product_name = product.name

    db.flush()
    if not cart.items:
        cart.restaurant_id = None
    db.commit()
    db.refresh(cart)
    return removed_names


def calculate_cart_totals(db: Session, cart: Cart) -> dict:
    subtotal = sum((item.unit_price * item.quantity for item in cart.items), Decimal("0.00"))
    restaurant = db.get(Restaurant, cart.restaurant_id) if cart.restaurant_id else None
    delivery_fee = restaurant.delivery_fee if restaurant else Decimal("0.00")
    # No tax policy exists yet — computed here authoritatively (never from the
    # client) rather than hardcoded inline, so wiring up a real rate later
    # doesn't touch the API shape.
    tax = Decimal("0.00")

    discount = Decimal("0.00")
    coupon_code: str | None = None
    coupon_message: str | None = None
    if cart.coupon_id:
        coupon = db.get(Coupon, cart.coupon_id)
        if coupon is None:
            cart.coupon_id = None
            db.commit()
        else:
            try:
                validate_coupon_for_cart(db, coupon, cart.user_id, cart, subtotal)
                discount = calculate_coupon_discount(coupon, subtotal)
                coupon_code = coupon.code
            except HTTPException as exc:
                # The coupon that was applied is no longer valid (e.g. the cart
                # dropped below the minimum order after an item was removed) —
                # self-heal the same way sync_cart_with_catalog does for items,
                # and tell the customer why.
                coupon_message = f"Coupon {coupon.code} removed: {exc.detail}"
                cart.coupon_id = None
                db.commit()

    total = subtotal + delivery_fee + tax - discount
    return {
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "tax": tax,
        "discount": discount,
        "total": total,
        "total_items": sum(item.quantity for item in cart.items),
        "coupon_code": coupon_code,
        "coupon_message": coupon_message,
    }


def add_item(db: Session, cart: Cart, product_id: UUID, quantity: int) -> CartItem:
    product = product_service.get_customer_visible_product_or_404(db, product_id)
    restaurant = restaurant_service.get_active_restaurant_or_404(db, product.restaurant_id)

    if cart.restaurant_id and cart.restaurant_id != restaurant.id:
        raise ValueError("Cart already contains items from a different restaurant.")

    cart.restaurant_id = restaurant.id

    cart_item = (
        db.query(CartItem).filter(CartItem.cart_id == cart.id, CartItem.product_id == product.id).first()
    )
    if cart_item:
        cart_item.quantity += quantity
        cart_item.unit_price = product.price
        cart_item.product_name = product.name
        db.commit()
        db.refresh(cart_item)
        return cart_item

    cart_item = CartItem(
        cart_id=cart.id,
        product_id=product.id,
        restaurant_id=restaurant.id,
        product_name=product.name,
        unit_price=product.price,
        quantity=quantity,
    )
    db.add(cart_item)
    db.commit()
    db.refresh(cart_item)
    return cart_item


def update_item_quantity(db: Session, cart: Cart, item_id: UUID, quantity: int) -> CartItem | None:
    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.cart_id == cart.id).first()
    if not item:
        return None
    item.quantity = max(1, quantity)
    db.commit()
    db.refresh(item)
    return item


def remove_item(db: Session, cart: Cart, item_id: UUID) -> bool:
    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.cart_id == cart.id).first()
    if not item:
        return False
    db.delete(item)
    db.commit()
    if not cart.items:
        cart.restaurant_id = None
        cart.coupon_id = None
        db.commit()
    return True


def clear_cart(db: Session, cart: Cart) -> None:
    db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    cart.restaurant_id = None
    cart.coupon_id = None
    db.commit()
