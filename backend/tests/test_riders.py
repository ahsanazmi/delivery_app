from uuid import uuid4

from app.db.session import get_db
from app.main import app
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.services.orders import assign_rider_to_order, list_rider_orders


def test_assign_rider_and_list_rider_orders(client):
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    rider = User(
        name="Aamir Rider",
        email="aamir@example.com",
        password_hash="hashed",
        role=UserRole.RIDER,
    )
    db.add(rider)
    db.flush()

    customer = User(
        name="Customer",
        email="customer@example.com",
        password_hash="hashed",
        role=UserRole.CUSTOMER,
    )
    db.add(customer)
    db.flush()

    order = Order(
        user_id=customer.id,
        restaurant_id="rest_1",
        restaurant_name="Tea House",
        restaurant_phone="1234567890",
        order_number="ORD-TEST-1",
        status=OrderStatus.PENDING,
        payment_method="cod",
        subtotal=250,
        delivery_fee=25,
        total=275,
        item_count=2,
        address_line="Main Road 12",
        city="Lahore",
        postal_code="54000",
        latitude=31.5204,
        longitude=74.3587,
    )
    db.add(order)
    db.flush()

    assigned = assign_rider_to_order(db, order, rider.id)
    assert assigned.rider_id == rider.id
    assert assigned.status == OrderStatus.CONFIRMED

    rider_orders = list_rider_orders(db, rider.id)
    assert [item.id for item in rider_orders] == [order.id]
