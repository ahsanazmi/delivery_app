"""E2E Validation Phase 11 — cart defects found during live testing."""

from app.core.security import create_access_token, hash_password
from app.models import User, UserRole
from app.models.delivery_partner import ApprovalStatus
from tests.test_discovery_visibility import _approved_restaurant_with_product, _db


def _customer_headers(db, email):
    customer = User(name="Cart Shopper", email=email, password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token(customer.id)}"}


def test_repeated_adds_cannot_stack_one_line_past_the_per_item_limit(client):
    db = _db(client)
    _, product = _approved_restaurant_with_product(db, "limit-owner@example.com", "Limit Kitchen")
    headers = _customer_headers(db, "limit-shopper@example.com")

    assert client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(product.id), "quantity": 60}).status_code == 201
    over = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(product.id), "quantity": 41})
    assert over.status_code == 422  # not 409: the app reads 409 as "different restaurant"
    exactly = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(product.id), "quantity": 40})
    assert exactly.status_code == 201
    assert exactly.json()["items"][0]["quantity"] == 100


def test_items_of_a_restaurant_that_is_no_longer_approved_are_dropped_from_the_cart(client):
    db = _db(client)
    restaurant, product = _approved_restaurant_with_product(db, "suspend-owner@example.com", "Soon Suspended")
    headers = _customer_headers(db, "suspend-shopper@example.com")
    assert client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(product.id), "quantity": 1}).status_code == 201

    restaurant.approval_status = ApprovalStatus.SUSPENDED
    db.commit()

    cart = client.get("/api/v1/customer/cart", headers=headers).json()
    assert cart["items"] == []
    assert cart["removed_items"] == ["Masala Chai"]
