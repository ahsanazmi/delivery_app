"""Integration Phase 4 — Cart Validation, over the real HTTP endpoints.

Covers the phase's explicit checklist (add/remove/increase/decrease
quantity/clear, restaurant consistency, product availability, price
changes) and the hard requirement that subtotal/discount/tax/delivery_fee/
total are always recalculated server-side and never trusted from the
client, no matter what a request body claims.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole


def _seed_restaurant_and_products(client, *, delivery_fee="30.00", owner_email="cartowner@example.com"):
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    owner = User(name="Owner", email=owner_email, phone="9300000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal(delivery_fee),
    )
    db.add(restaurant)
    db.commit()
    dosa = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
    tea = Product(restaurant_id=restaurant.id, name="Tea", price=Decimal("40.00"))
    db.add_all([dosa, tea])
    db.commit()
    ids = {"restaurant_id": restaurant.id, "dosa_id": dosa.id, "tea_id": tea.id}
    db.close()
    return ids


def _customer_headers(client, email="cartcustomer@example.com", phone="9300000099"):
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="Cart Customer", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    token = create_access_token(customer.id)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def test_add_increase_decrease_and_remove_item_recalculate_totals_each_time(client):
    ids = _seed_restaurant_and_products(client)
    headers = _customer_headers(client)

    added = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["dosa_id"]), "quantity": 1})
    assert added.status_code == 201
    assert added.json()["subtotal"] == "120.00"
    assert added.json()["total"] == "150.00"  # 120 + 30 delivery

    item_id = added.json()["items"][0]["id"]

    increased = client.patch(f"/api/v1/customer/cart/items/{item_id}", headers=headers, json={"quantity": 3})
    assert increased.status_code == 200
    assert increased.json()["subtotal"] == "360.00"
    assert increased.json()["total"] == "390.00"

    decreased = client.patch(f"/api/v1/customer/cart/items/{item_id}", headers=headers, json={"quantity": 1})
    assert decreased.status_code == 200
    assert decreased.json()["subtotal"] == "120.00"

    removed = client.delete(f"/api/v1/customer/cart/items/{item_id}", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["subtotal"] == "0.00"
    assert removed.json()["total"] == "0.00"
    assert removed.json()["items"] == []


def test_removing_a_nonexistent_item_is_a_404(client):
    _seed_restaurant_and_products(client)
    headers = _customer_headers(client)
    from uuid import uuid4

    response = client.delete(f"/api/v1/customer/cart/items/{uuid4()}", headers=headers)
    assert response.status_code == 404


def test_quantity_cannot_go_below_one_or_above_one_hundred(client):
    ids = _seed_restaurant_and_products(client)
    headers = _customer_headers(client)
    added = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["dosa_id"]), "quantity": 1})
    item_id = added.json()["items"][0]["id"]

    assert client.patch(f"/api/v1/customer/cart/items/{item_id}", headers=headers, json={"quantity": 0}).status_code == 422
    assert client.patch(f"/api/v1/customer/cart/items/{item_id}", headers=headers, json={"quantity": 101}).status_code == 422
    assert client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["dosa_id"]), "quantity": 0}).status_code == 422


def test_clear_cart_zeroes_out_every_total(client):
    ids = _seed_restaurant_and_products(client)
    headers = _customer_headers(client)
    client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["dosa_id"]), "quantity": 2})
    client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["tea_id"]), "quantity": 1})

    cleared = client.delete("/api/v1/customer/cart", headers=headers)
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["items"] == []
    assert body["subtotal"] == "0.00"
    assert body["delivery_fee"] == "0.00"
    assert body["tax"] == "0.00"
    assert body["discount"] == "0.00"
    assert body["total"] == "0.00"
    assert body["restaurant"] is None


def test_restaurant_consistency_is_enforced_on_every_add(client):
    ids_a = _seed_restaurant_and_products(client, owner_email="ownera-p4@example.com")
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    owner_b = User(name="Owner B", email="ownerb-p4@example.com", phone="9300000002", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner_b)
    db.commit()
    restaurant_b = Restaurant(
        owner_id=owner_b.id, name="Other Place", phone="9876500000", address="Other Road",
        latitude=Decimal("12.2"), longitude=Decimal("77.2"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant_b)
    db.commit()
    other_product = Product(restaurant_id=restaurant_b.id, name="Burger", price=Decimal("200.00"))
    db.add(other_product)
    db.commit()
    other_product_id = other_product.id
    db.close()

    headers = _customer_headers(client)
    first = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids_a["dosa_id"]), "quantity": 1})
    assert first.status_code == 201

    conflict = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(other_product_id), "quantity": 1})
    assert conflict.status_code == 409

    # The first restaurant's item is untouched by the rejected cross-restaurant add.
    cart = client.get("/api/v1/customer/cart", headers=headers)
    assert cart.json()["restaurant"]["id"] == str(ids_a["restaurant_id"])
    assert len(cart.json()["items"]) == 1


def test_product_going_unavailable_is_dropped_on_the_next_cart_touch_not_just_on_get(client):
    ids = _seed_restaurant_and_products(client)
    headers = _customer_headers(client)
    client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["dosa_id"]), "quantity": 1})
    tea_added = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["tea_id"]), "quantity": 1})
    dosa_item_id = [i["id"] for i in tea_added.json()["items"] if i["product_name"] == "Masala Dosa"][0]

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    tea = db.get(Product, ids["tea_id"])
    tea.is_available = False
    db.commit()
    db.close()

    # Updating the *other* (still-valid) item must silently drop the now-unavailable
    # Tea item and recompute totals — not just when the customer happens to GET the cart.
    updated = client.patch(f"/api/v1/customer/cart/items/{dosa_item_id}", headers=headers, json={"quantity": 2})
    assert updated.status_code == 200
    names = [i["product_name"] for i in updated.json()["items"]]
    assert "Tea" not in names
    assert updated.json()["removed_items"] == ["Tea"]
    assert updated.json()["subtotal"] == "240.00"  # 2 * 120, tea's 40 excluded


def test_price_increase_is_reflected_on_the_next_cart_touch_not_just_on_get(client):
    ids = _seed_restaurant_and_products(client)
    headers = _customer_headers(client)
    added = client.post("/api/v1/customer/cart/items", headers=headers, json={"product_id": str(ids["dosa_id"]), "quantity": 1})
    assert added.json()["subtotal"] == "120.00"
    item_id = added.json()["items"][0]["id"]

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    dosa = db.get(Product, ids["dosa_id"])
    dosa.price = Decimal("150.00")
    db.commit()
    db.close()

    # Removing an unrelated coupon (a mutation, not a GET) must still surface the new price.
    touched = client.delete("/api/v1/customer/cart/coupon", headers=headers)
    assert touched.status_code == 200
    assert touched.json()["items"][0]["unit_price"] == "150.00"
    assert touched.json()["subtotal"] == "150.00"


def test_client_supplied_totals_are_ignored_and_always_recalculated_server_side(client):
    ids = _seed_restaurant_and_products(client)
    headers = _customer_headers(client)

    # Attempt to smuggle manipulated totals into the add-to-cart request body.
    response = client.post(
        "/api/v1/customer/cart/items",
        headers=headers,
        json={
            "product_id": str(ids["dosa_id"]),
            "quantity": 1,
            "subtotal": "0.01",
            "total": "0.01",
            "discount": "999.00",
            "tax": "0.00",
            "delivery_fee": "0.00",
            "unit_price": "0.01",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["subtotal"] == "120.00"
    assert body["delivery_fee"] == "30.00"
    assert body["total"] == "150.00"
    assert body["items"][0]["unit_price"] == "120.00"


def test_customer_cannot_touch_another_customers_cart_item(client):
    ids = _seed_restaurant_and_products(client)
    headers_a = _customer_headers(client, email="cart-a@example.com", phone="9300000010")
    headers_b = _customer_headers(client, email="cart-b@example.com", phone="9300000011")

    added = client.post("/api/v1/customer/cart/items", headers=headers_a, json={"product_id": str(ids["dosa_id"]), "quantity": 1})
    item_id = added.json()["items"][0]["id"]

    # Customer B tries to update/remove Customer A's cart item by guessing its id.
    update_attempt = client.patch(f"/api/v1/customer/cart/items/{item_id}", headers=headers_b, json={"quantity": 5})
    assert update_attempt.status_code == 404

    remove_attempt = client.delete(f"/api/v1/customer/cart/items/{item_id}", headers=headers_b)
    assert remove_attempt.status_code == 404

    # Customer A's item and quantity are untouched.
    cart_a = client.get("/api/v1/customer/cart", headers=headers_a)
    assert cart_a.json()["items"][0]["quantity"] == 1
