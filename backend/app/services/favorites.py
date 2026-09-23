from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus
from app.models.favorite import Favorite
from app.models.restaurant import Restaurant
from app.services.restaurants import get_active_restaurant_or_404


def list_favorite_restaurants(db: Session, user_id: UUID) -> list[Restaurant]:
    statement = (
        select(Restaurant)
        .join(Favorite, Favorite.restaurant_id == Restaurant.id)
        .where(
            Favorite.user_id == user_id,
            Restaurant.is_active.is_(True),
            Restaurant.approval_status == ApprovalStatus.APPROVED,
        )
        .order_by(Favorite.created_at.desc())
    )
    return list(db.scalars(statement))


def add_favorite(db: Session, user_id: UUID, restaurant_id: UUID) -> None:
    # Validates the restaurant is real and active before letting a customer favorite it.
    get_active_restaurant_or_404(db, restaurant_id)

    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == user_id, Favorite.restaurant_id == restaurant_id)
        .first()
    )
    if existing:
        return
    db.add(Favorite(user_id=user_id, restaurant_id=restaurant_id))
    db.commit()


def remove_favorite(db: Session, user_id: UUID, restaurant_id: UUID) -> None:
    db.query(Favorite).filter(Favorite.user_id == user_id, Favorite.restaurant_id == restaurant_id).delete()
    db.commit()
