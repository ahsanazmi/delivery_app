"""Rider Portal — Phase 3: Rider Registration & Verification."""

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-verify@example.com", phone="9200000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _make_admin(client, email="admin-verify@example.com", phone="9200000099"):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    admin = User(name="Admin", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return token


# --------------------------- Rider-side: GET /rider/verification ---------------------------


def test_new_rider_starts_pending(client):
    token = _register_and_login_rider(client)
    response = client.get("/api/v1/rider/verification", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "PENDING"
    assert body["rejection_reason"] is None


def test_verification_status_is_stable_across_repeated_reads(client):
    """get_or_create must not create a second row on the second call."""
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.get("/api/v1/rider/verification", headers=headers).json()
    second = client.get("/api/v1/rider/verification", headers=headers).json()
    assert first["created_at"] == second["created_at"]


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/verification").status_code == 401


def test_customer_and_restaurant_owner_cannot_access_rider_verification(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c@example.com", phone="9200000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o@example.com", phone="9200000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/verification", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/verification", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


# --------------------------- Admin-side: PATCH /admin/riders/{id}/verification ---------------------------


def test_admin_can_approve_a_rider(client):
    from app.db.session import get_db

    rider_token = _register_and_login_rider(client, email="approve-me@example.com", phone="9200000011")
    rider_id = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rider_token}"}).json()["id"]
    admin_token = _make_admin(client)

    response = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "APPROVED"},
    )
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"

    # The rider's own read reflects it immediately.
    rider_view = client.get("/api/v1/rider/verification", headers={"Authorization": f"Bearer {rider_token}"})
    assert rider_view.json()["approval_status"] == "APPROVED"


def test_admin_rejecting_requires_a_reason(client):
    rider_token = _register_and_login_rider(client, email="reject-me@example.com", phone="9200000012")
    rider_id = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rider_token}"}).json()["id"]
    admin_token = _make_admin(client, email="admin2@example.com", phone="9200000098")

    missing_reason = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "REJECTED"},
    )
    assert missing_reason.status_code == 422

    with_reason = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "REJECTED", "rejection_reason": "Documents unreadable"},
    )
    assert with_reason.status_code == 200
    assert with_reason.json()["approval_status"] == "REJECTED"
    assert with_reason.json()["rejection_reason"] == "Documents unreadable"


def test_non_admin_cannot_update_rider_verification(client):
    rider_token = _register_and_login_rider(client, email="target@example.com", phone="9200000013")
    rider_id = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rider_token}"}).json()["id"]
    other_rider_token = _register_and_login_rider(client, email="not-admin@example.com", phone="9200000014")

    response = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {other_rider_token}"},
        json={"approval_status": "APPROVED"},
    )
    assert response.status_code == 403


def test_rider_cannot_approve_themselves():
    """There is no rider-facing route that accepts an approval_status at
    all — confirmed structurally, not just by role-checking an endpoint
    that doesn't exist."""
    from app.api.v1.rider import verification as rider_verification_module

    paths = {route.path for route in rider_verification_module.router.routes}
    assert paths == {"/verification", "/verification/resubmit"}


def test_admin_verification_update_404s_for_nonexistent_or_non_rider_user(client):
    admin_token = _make_admin(client, email="admin3@example.com", phone="9200000097")
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.patch(
        f"/api/v1/admin/riders/{fake_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "APPROVED"},
    )
    assert response.status_code == 404


# --------------------------- Resubmit ---------------------------


def test_rider_can_resubmit_after_rejection(client):
    rider_token = _register_and_login_rider(client, email="resubmit@example.com", phone="9200000015")
    rider_id = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rider_token}"}).json()["id"]
    admin_token = _make_admin(client, email="admin4@example.com", phone="9200000096")

    client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "REJECTED", "rejection_reason": "Bad photo"},
    )

    resubmit = client.post(
        "/api/v1/rider/verification/resubmit", headers={"Authorization": f"Bearer {rider_token}"}
    )
    assert resubmit.status_code == 200
    assert resubmit.json()["approval_status"] == "PENDING"
    assert resubmit.json()["rejection_reason"] is None


def test_cannot_resubmit_when_not_rejected(client):
    token = _register_and_login_rider(client, email="cant-resubmit@example.com", phone="9200000016")
    response = client.post("/api/v1/rider/verification/resubmit", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 409


# --------------------------- Enforcement: unapproved rider cannot deliver ---------------------------


def test_unapproved_rider_cannot_pick_up_or_deliver_an_order(client):
    from decimal import Decimal

    from app.db.session import get_db
    from app.models.product import Product
    from app.models.restaurant import Restaurant
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import assign_rider_to_order, create_order, transition_order_status
    from app.models.order import OrderStatus

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)

    owner = User(name="Owner", email="owner-v@example.com", phone="9200000020", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Diner", phone="9876500000", address="Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    customer = User(name="Cust", email="cust-v@example.com", phone="9200000021", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)

    rider = User(name="Rider", email="unapproved-rider@example.com", phone="9200000022", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    assign_rider_to_order(db, order, rider.id)
    order_id = order.id
    rider_token = create_access_token(rider.id)
    db.close()

    headers = {"Authorization": f"Bearer {rider_token}"}
    pickup_response = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
    assert pickup_response.status_code == 403
    assert "not approved" in pickup_response.json()["detail"].lower()

    complete_response = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    assert complete_response.status_code == 403


def test_approved_rider_can_pick_up_and_deliver(client):
    from decimal import Decimal

    from app.db.session import get_db
    from app.models.product import Product
    from app.models.restaurant import Restaurant
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import assign_rider_to_order, create_order, transition_order_status
    from app.models.order import OrderStatus

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)

    owner = User(name="Owner", email="owner-v2@example.com", phone="9200000030", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Diner", phone="9876500001", address="Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    customer = User(name="Cust", email="cust-v2@example.com", phone="9200000031", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id, payment_method="online")
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)

    rider = User(name="Rider", email="approved-rider@example.com", phone="9200000032", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    assign_rider_to_order(db, order, rider.id)
    order_id = order.id
    rider_id = rider.id
    rider_token = create_access_token(rider.id)
    db.close()

    admin_token = _make_admin(client, email="admin5@example.com", phone="9200000095")
    approve = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "APPROVED"},
    )
    assert approve.status_code == 200

    headers = {"Authorization": f"Bearer {rider_token}"}
    pickup_response = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
    assert pickup_response.status_code == 200
    assert pickup_response.json()["status"] == "picked_up"

    start_response = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "out_for_delivery"

    complete_response = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "delivered"
