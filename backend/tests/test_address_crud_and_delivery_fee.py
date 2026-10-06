"""Maps & Location System Phase 35 — Automated Testing.

Fills the two gaps this phase's checklist named that weren't already
fully covered elsewhere: the full address CRUD lifecycle proven together
(not just fragments — ownership is already covered in test_security.py
and the IDOR sweep, and individual fields in test_location_domain_model.py),
and a dedicated proof that delivery fee can never be client-supplied.
"""

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.user import User, UserRole


def _customer_token(client, email="crud-p35@example.com", phone="9700000098") -> str:
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    user = User(name="Customer", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
    db.close()
    return token


def test_full_address_crud_lifecycle_over_http(client):
    headers = {"Authorization": f"Bearer {_customer_token(client)}"}

    create = client.post(
        "/api/v1/addresses", headers=headers,
        json={
            "recipient_name": "Customer", "phone": "9999999999", "address_line": "15 Market Road",
            "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        },
    )
    assert create.status_code == 201
    address_id = create.json()["id"]

    listing = client.get("/api/v1/addresses", headers=headers)
    assert listing.status_code == 200
    assert any(a["id"] == address_id for a in listing.json())

    detail = client.get(f"/api/v1/addresses/{address_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["address_line"] == "15 Market Road"

    update = client.patch(f"/api/v1/addresses/{address_id}", headers=headers, json={"landmark": "Near the tower"})
    assert update.status_code == 200
    assert update.json()["landmark"] == "Near the tower"

    second = client.post(
        "/api/v1/addresses", headers=headers,
        json={
            "recipient_name": "Customer", "phone": "9999999999", "address_line": "22 MG Road",
            "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        },
    )
    assert second.status_code == 201
    second_id = second.json()["id"]

    set_default = client.patch(f"/api/v1/addresses/{second_id}/default", headers=headers)
    assert set_default.status_code == 200
    assert set_default.json()["is_default"] is True

    delete = client.delete(f"/api/v1/addresses/{address_id}", headers=headers)
    assert delete.status_code == 200

    after_delete = client.get(f"/api/v1/addresses/{address_id}", headers=headers)
    assert after_delete.status_code == 404


def test_delivery_fee_cannot_be_supplied_by_the_client(client):
    """Maps & Location System Phase 18/35 — delivery fee is always the
    restaurant's own flat, backend-configured amount; CustomerOrderCreate
    has no delivery_fee field at all, so a client attempting to smuggle
    one in the request body has it silently dropped before create_order
    ever runs, never influencing the stored order."""
    from decimal import Decimal

    from app.models.product import Product
    from app.models.restaurant import Restaurant
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user

    headers = {"Authorization": f"Bearer {_customer_token(client, email='crud-fee-p35@example.com', phone='9700000097')}"}

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    owner = User(name="Owner", email="crud-fee-owner-p35@example.com", phone="9700000096", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Fee Test Diner", phone="9876543211", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("45.00"),
    )
    db.add(restaurant)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()

    customer_id = client.get("/api/v1/customer/profile", headers=headers).json()["id"]
    from uuid import UUID

    cart = create_cart_for_user(db, UUID(customer_id))
    add_item(db, cart, product.id, 1)
    address = create_address(db, UUID(customer_id), {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "560001",
    })
    address_id = address.id
    db.close()

    create = client.post(
        "/api/v1/customer/orders", headers=headers,
        json={"address_id": str(address_id), "delivery_fee": "0.01", "delivery_fee_override": "0.01"},
    )
    assert create.status_code == 201
    assert create.json()["delivery_fee"] == "45.00"
