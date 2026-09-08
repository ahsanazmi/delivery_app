from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.cart import Cart, CartItem


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


def calculate_cart_totals(cart: Cart) -> dict[str, Decimal | int]:
    subtotal = sum((item.unit_price * item.quantity for item in cart.items), Decimal("0.00"))
    return {
        "subtotal": subtotal,
        "delivery_fee": Decimal("0.00"),
        "tax": Decimal("0.00"),
        "total": subtotal,
        "total_items": sum(item.quantity for item in cart.items),
    }


def upsert_item(db: Session, cart: Cart, item_data: dict) -> CartItem:
    product_id = str(item_data["product_id"])
    restaurant_id = str(item_data["restaurant_id"])

    if cart.restaurant_id and cart.restaurant_id != restaurant_id:
        raise ValueError("Cart already contains items from a different restaurant.")

    cart.restaurant_id = restaurant_id

    cart_item = db.query(CartItem).filter(CartItem.cart_id == cart.id, CartItem.product_id == product_id).first()
    if cart_item:
        cart_item.quantity = int(item_data["quantity"]) + cart_item.quantity
        cart_item.unit_price = item_data["unit_price"]
        cart_item.product_name = str(item_data["product_name"])
        cart_item.restaurant_id = restaurant_id
        db.commit()
        db.refresh(cart_item)
        return cart_item

    cart_item = CartItem(
        cart_id=cart.id,
        product_id=product_id,
        restaurant_id=restaurant_id,
        product_name=str(item_data["product_name"]),
        unit_price=item_data["unit_price"],
        quantity=int(item_data["quantity"]),
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
        db.commit()
    return True


def clear_cart(db: Session, cart: Cart) -> None:
    db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    cart.restaurant_id = None
    db.commit()
