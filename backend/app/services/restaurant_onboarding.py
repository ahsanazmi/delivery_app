from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.delivery_partner import ApprovalStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.restaurant_onboarding import RestaurantOnboardingRequest
from app.services.admin_settings import get_platform_settings
from app.services.auth import get_user_by_email, get_user_by_phone


def create_owner_with_restaurant(
    db: Session, payload: RestaurantOnboardingRequest, *, approval_status: ApprovalStatus
) -> tuple[User, Restaurant]:
    """Adds (but does not commit) a new RESTAURANT_OWNER and their restaurant,
    so each caller can attach its own notification/audit entry to the same
    transaction. Minimum order and delivery fee start at the platform
    defaults, exactly like services.restaurants.create_restaurant."""
    if get_user_by_email(db, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    if payload.owner_phone and get_user_by_phone(db, payload.owner_phone):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this phone number already exists")

    owner = User(
        name=payload.owner_name,
        email=payload.email,
        phone=payload.owner_phone,
        password_hash=hash_password(payload.password),
        role=UserRole.RESTAURANT_OWNER,
    )
    db.add(owner)
    db.flush()

    platform_settings = get_platform_settings(db)
    restaurant = Restaurant(
        owner_id=owner.id,
        name=payload.restaurant_name,
        description=payload.description.strip() if payload.description and payload.description.strip() else None,
        phone=payload.restaurant_phone,
        email=payload.email,
        address=payload.address,
        latitude=payload.latitude,
        longitude=payload.longitude,
        formatted_address=payload.formatted_address,
        place_id=payload.place_id,
        minimum_order=platform_settings.default_minimum_order,
        delivery_fee=platform_settings.default_delivery_fee,
        approval_status=approval_status,
    )
    db.add(restaurant)
    db.flush()
    return owner, restaurant
