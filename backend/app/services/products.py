from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus
from app.models.product import MenuCategory, Product
from app.models.restaurant import Restaurant
from app.schemas.product import MenuCategoryCreate, MenuCategoryUpdate, ProductCreate, ProductUpdate


def list_menu_categories(db: Session, restaurant_id: UUID) -> list[MenuCategory]:
    statement = (
        select(MenuCategory)
        .where(MenuCategory.restaurant_id == restaurant_id, MenuCategory.is_active.is_(True))
        .order_by(MenuCategory.display_order.asc(), MenuCategory.name.asc())
    )
    return list(db.scalars(statement))


def list_menu_categories_for_owner(db: Session, restaurant_id: UUID) -> list[MenuCategory]:
    """Unlike list_menu_categories (customer-facing), the owner also sees
    categories they've disabled — they need to see it to re-enable it."""
    statement = (
        select(MenuCategory)
        .where(MenuCategory.restaurant_id == restaurant_id)
        .order_by(MenuCategory.display_order.asc(), MenuCategory.name.asc())
    )
    return list(db.scalars(statement))


def get_menu_category_or_404(db: Session, restaurant_id: UUID, category_id: UUID) -> MenuCategory:
    """Scoped to restaurant_id — a category_id that exists but belongs to a
    different restaurant is indistinguishable from one that doesn't exist at
    all, which is exactly the point: it never leaks whether it exists."""
    category = db.scalar(
        select(MenuCategory).where(MenuCategory.id == category_id, MenuCategory.restaurant_id == restaurant_id)
    )
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


def create_menu_category(db: Session, restaurant_id: UUID, payload: MenuCategoryCreate) -> MenuCategory:
    category = MenuCategory(
        restaurant_id=restaurant_id,
        name=payload.name.strip(),
        display_order=payload.display_order,
        image_url=str(payload.image_url) if payload.image_url else None,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_menu_category(db: Session, category: MenuCategory, payload: MenuCategoryUpdate) -> MenuCategory:
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("image_url") is not None:
        updates["image_url"] = str(updates["image_url"])
    if updates.get("name") is not None:
        updates["name"] = updates["name"].strip()
    for field, value in updates.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


def delete_menu_category(db: Session, category: MenuCategory) -> None:
    """A real delete, not a soft one — "disable" (is_active=False, via
    update_menu_category) is the reversible option; this is the permanent
    one. Products referencing this category keep existing (their category_id
    just becomes NULL via the FK's ON DELETE SET NULL) rather than being
    deleted themselves."""
    db.delete(category)
    db.commit()


def list_products(db: Session, restaurant_id: UUID, *, category_id: UUID | None = None) -> list[Product]:
    statement = select(Product).where(
        Product.restaurant_id == restaurant_id,
        Product.is_active.is_(True),
        Product.is_available.is_(True),
    )
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    statement = statement.order_by(Product.name.asc())
    return list(db.scalars(statement))


def search_products(
    db: Session,
    *,
    q: str | None = None,
    restaurant_id: UUID | None = None,
    category_id: UUID | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[Product]:
    statement = (
        select(Product)
        .join(Restaurant, Restaurant.id == Product.restaurant_id)
        .where(
            Restaurant.is_active.is_(True),
            Restaurant.approval_status == ApprovalStatus.APPROVED,
            Product.is_active.is_(True),
            Product.is_available.is_(True),
        )
    )
    if restaurant_id is not None:
        statement = statement.where(Product.restaurant_id == restaurant_id)
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    if q:
        query = f"%{q.strip().lower()}%"
        statement = statement.where(func.lower(Product.name).like(query))
    statement = statement.order_by(Product.name.asc()).offset(offset).limit(limit)
    return list(db.scalars(statement))


def get_customer_visible_product_or_404(db: Session, product_id: UUID) -> Product:
    product = db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.is_active.is_(True),
            Product.is_available.is_(True),
        )
    )
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


def list_products_for_owner(db: Session, restaurant_id: UUID) -> list[Product]:
    """Unlike list_products (customer-facing), the owner sees every product
    in their menu regardless of is_available — they need to see it to turn
    availability back on. is_active=False is the one exception: that's
    "deleted" (see delete_product), so it's excluded here the same way it's
    excluded from every customer-facing query — the owner's own list must
    agree their delete actually removed it."""
    statement = (
        select(Product)
        .where(Product.restaurant_id == restaurant_id, Product.is_active.is_(True))
        .order_by(Product.name.asc())
    )
    return list(db.scalars(statement))


def get_owner_product_or_404(db: Session, restaurant_id: UUID, product_id: UUID) -> Product:
    """Scoped to restaurant_id, same reasoning as get_menu_category_or_404 —
    a product belonging to a different restaurant is treated as not found,
    never leaking that it exists. Also excludes a soft-deleted product
    (is_active=False, see delete_product) — a deleted product is a 404 on
    GET/PATCH/DELETE alike, not something an owner can keep editing or
    "delete" a second time."""
    product = db.scalar(
        select(Product).where(
            Product.id == product_id, Product.restaurant_id == restaurant_id, Product.is_active.is_(True)
        )
    )
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


def _assert_category_belongs_to_restaurant(db: Session, restaurant_id: UUID, category_id: UUID | None) -> None:
    """The one rule this whole phase exists to enforce: an owner can only
    assign a product to a menu category that's actually theirs — never
    another restaurant's category, even if they happen to know its id."""
    if category_id is None:
        return
    category = db.scalar(
        select(MenuCategory).where(MenuCategory.id == category_id, MenuCategory.restaurant_id == restaurant_id)
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="category_id must belong to your own restaurant",
        )


def create_product(db: Session, restaurant_id: UUID, payload: ProductCreate) -> Product:
    _assert_category_belongs_to_restaurant(db, restaurant_id, payload.category_id)
    product = Product(
        restaurant_id=restaurant_id,
        category_id=payload.category_id,
        name=payload.name.strip(),
        description=payload.description,
        image_url=str(payload.image_url) if payload.image_url else None,
        price=payload.price,
        is_available=payload.is_available,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def update_product(db: Session, restaurant_id: UUID, product: Product, payload: ProductUpdate) -> Product:
    updates = payload.model_dump(exclude_unset=True)
    if "category_id" in updates:
        _assert_category_belongs_to_restaurant(db, restaurant_id, updates["category_id"])
    if updates.get("image_url") is not None:
        updates["image_url"] = str(updates["image_url"])
    if updates.get("name") is not None:
        updates["name"] = updates["name"].strip()
    for field, value in updates.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, product: Product) -> None:
    """Data Consistency Audit — a soft delete (is_active=False), not a
    hard one. OrderItem snapshots product_name/unit_price and has no live
    FK to Product at all, so a hard delete never breaks order history —
    but CartItem *does* hold a real FK with ON DELETE CASCADE, so a hard
    delete of a product still sitting in some customer's cart silently
    removed that CartItem row at the database level, before
    sync_cart_with_catalog ever got a chance to notice and report it via
    removed_items. Soft-deleting instead keeps the Product row (and any
    CartItem still pointing at it) intact, so the existing
    is_active/is_available check in sync_cart_with_catalog catches it and
    reports it exactly like any other now-unavailable item — no silent
    loss. get_customer_visible_product_or_404 and every customer-facing
    listing already filter on is_active, so a "deleted" product
    disappears from discovery immediately either way."""
    product.is_active = False
    db.commit()
