"""E2E Validation Phase 10 — restaurant discovery defects found live."""

from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models import Product, User, UserRole
from app.models.delivery_partner import ApprovalStatus
from tests.test_restaurant_portal_final_suite import _owner, _restaurant


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _approved_restaurant_with_product(db, owner_email, name, product_name="Masala Chai"):
    restaurant = _restaurant(db, _owner(db, email=owner_email, phone=f"90{abs(hash(owner_email)) % 10**8:08d}"), name=name)
    restaurant.approval_status = ApprovalStatus.APPROVED
    product = Product(restaurant_id=restaurant.id, name=product_name, price=Decimal("40.00"))
    db.add(product)
    db.commit()
    return restaurant, product


@pytest.mark.parametrize("make_hidden", [
    lambda r: setattr(r, "approval_status", ApprovalStatus.PENDING),
    lambda r: setattr(r, "is_active", False),
], ids=["pending-restaurant", "deactivated-restaurant"])
def test_a_hidden_restaurants_product_is_not_served_or_addable_to_a_cart(client, make_hidden):
    db = _db(client)
    restaurant, product = _approved_restaurant_with_product(db, "hidden-owner@example.com", "Hidden Kitchen")
    make_hidden(restaurant)
    db.commit()
    customer = User(name="Shopper", email="shopper@example.com", password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(customer.id)}"}

    assert client.get(f"/api/v1/customer/products/{product.id}").status_code == 404
    add = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(product.id), "quantity": 1})
    assert add.status_code == 404


def test_a_visible_restaurants_product_is_still_served(client):
    db = _db(client)
    _, product = _approved_restaurant_with_product(db, "visible-owner@example.com", "Open Kitchen")
    assert client.get(f"/api/v1/customer/products/{product.id}").status_code == 200


def test_like_wildcards_in_customer_search_are_matched_literally(client):
    db = _db(client)
    _approved_restaurant_with_product(db, "w1@example.com", "Chai Point", product_name="Ginger Tea")
    _approved_restaurant_with_product(db, "w2@example.com", "100% Juice Bar", product_name="Fresh_Orange")

    def found(q):
        body = client.get("/api/v1/customer/search", params={"q": q}).json()
        return str(body)

    assert "Chai Point" not in found("%")          # previously "%" matched everything
    assert "100% Juice Bar" in found("100%")        # a literal % still matches itself
    assert "Fresh_Orange" in found("h_O")           # literal underscore
    assert "Ginger Tea" not in found("_")
