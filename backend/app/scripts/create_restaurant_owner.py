"""Create a restaurant owner account plus one approved restaurant for
them to manage — RESTAURANT_OWNER has no public self-registration route
(see app/api/v1/endpoints/auth.py's own register() guard), and there is
no admin API endpoint that creates one either (admin/restaurant_owners.py
is list/suspend/activate only) — so, matching create_admin.py's own
reasoning, this is deliberately a direct, non-HTTP bootstrap path."""

import argparse
from decimal import Decimal
from getpass import getpass

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.auth import get_user_by_email


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Say Hi Chai restaurant owner + restaurant")
    parser.add_argument("--owner-name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--phone")
    parser.add_argument("--restaurant-name", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--restaurant-phone", required=True)
    parser.add_argument("--latitude", type=Decimal, required=True)
    parser.add_argument("--longitude", type=Decimal, required=True)
    args = parser.parse_args()

    password = getpass("Owner password: ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")

    with SessionLocal() as db:
        if get_user_by_email(db, args.email):
            raise SystemExit("A user with this email already exists.")
        owner = User(
            name=args.owner_name.strip(),
            email=args.email.lower().strip(),
            phone=args.phone.strip() if args.phone else None,
            password_hash=hash_password(password),
            role=UserRole.RESTAURANT_OWNER,
        )
        db.add(owner)
        db.flush()

        restaurant = Restaurant(
            owner_id=owner.id,
            name=args.restaurant_name.strip(),
            phone=args.restaurant_phone.strip(),
            address=args.address.strip(),
            latitude=args.latitude,
            longitude=args.longitude,
        )
        db.add(restaurant)
        db.commit()
        print(f"Created restaurant owner {owner.email} ({owner.id}) with restaurant {restaurant.name} ({restaurant.id})")


if __name__ == "__main__":
    main()
