"""Create the first administrator without exposing a public admin-registration route."""

import argparse
from getpass import getpass

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.services.auth import get_user_by_email


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Say Hi Chai administrator")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--phone")
    args = parser.parse_args()

    password = getpass("Admin password: ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")

    with SessionLocal() as db:
        if get_user_by_email(db, args.email):
            raise SystemExit("A user with this email already exists.")
        admin = User(
            name=args.name.strip(),
            email=args.email.lower().strip(),
            phone=args.phone.strip() if args.phone else None,
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
        )
        db.add(admin)
        db.commit()
        print(f"Created administrator {admin.email} ({admin.id})")


if __name__ == "__main__":
    main()
