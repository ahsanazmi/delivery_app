from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUser, DbSession
from app.models.cart import Cart, CartItem
from app.schemas.cart import CartItemCreate, CartItemRead, CartItemUpdate, CartRead
from app.services.cart import calculate_cart_totals, clear_cart, create_cart_for_user, get_cart_for_user, remove_item, update_item_quantity, upsert_item

router = APIRouter()


def _serialize_cart(cart: Cart) -> CartRead:
    items = sorted(cart.items, key=lambda item: item.product_name)
    totals = calculate_cart_totals(cart)
    return CartRead(
        id=cart.id,
        user_id=cart.user_id,
        restaurant_id=cart.restaurant_id,
        items=[CartItemRead.model_validate(item) for item in items],
        subtotal=totals["subtotal"],
        total_items=totals["total_items"],
        total=totals["total"],
        created_at=cart.created_at,
        updated_at=cart.updated_at,
    )


@router.get("", response_model=CartRead)
def get_cart(db: DbSession, current_user: CurrentUser) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    return _serialize_cart(cart)


@router.post("/items", response_model=CartRead, status_code=status.HTTP_201_CREATED)
def add_item(payload: CartItemCreate, db: DbSession, current_user: CurrentUser) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    try:
        upsert_item(db, cart, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.refresh(cart)
    return _serialize_cart(cart)


@router.patch("/items/{item_id}", response_model=CartRead)
def update_item(item_id: UUID, payload: CartItemUpdate, db: DbSession, current_user: CurrentUser) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    result = update_item_quantity(db, cart, item_id, payload.quantity)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")
    db.refresh(cart)
    return _serialize_cart(cart)


@router.delete("/items/{item_id}", response_model=CartRead)
def remove_item_endpoint(item_id: UUID, db: DbSession, current_user: CurrentUser) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    removed = remove_item(db, cart, item_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")
    db.refresh(cart)
    return _serialize_cart(cart)


@router.delete("", response_model=CartRead)
def clear_cart_endpoint(db: DbSession, current_user: CurrentUser) -> CartRead:
    cart = get_cart_for_user(db, current_user.id)
    clear_cart(db, cart)
    db.refresh(cart)
    return _serialize_cart(cart)
