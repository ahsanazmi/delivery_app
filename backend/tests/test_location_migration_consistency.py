"""Maps & Location System Phase 4 — Database Migration.

The actual schema changes for this module's domain model landed as part
of Phase 2 (addresses.district/formatted_address/place_id, migration
20261004_45) and Phase 3 (restaurants.formatted_address/place_id,
migration 20261004_46) — both already applied and verified against the
local dev database. This phase's own dedicated job is the migration
chain check (below) and proving the specific invariant its own brief
names explicitly: "Historical orders should retain the delivery
address/location snapshot that existed when the order was placed" —
editing or deleting a saved Address must never change an existing
Order's own copy.

No new index/foreign key was added this phase: Order has no query
pattern (anywhere in the codebase) that filters/sorts by postal_code,
city, or lat/lng — every existing Order index is keyed on user_id,
restaurant_id, rider_id, or status (see Order.__table_args__) — so a
speculative geo-index isn't justified yet, matching this whole
protocol's "do not introduce unnecessary infrastructure" instruction.
"""

import subprocess
import sys
from decimal import Decimal

from app.core.security import hash_password
from app.db.session import get_db
from app.models.address import Address
from app.models.order import Order
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order


def test_alembic_migration_chain_has_a_single_linear_head():
    """Runs the real Alembic CLI against this repo's actual migration
    files (not a stub) — the same check performed manually via `alembic
    heads` throughout this module's development, now a permanent,
    automated regression guard against a future branching migration."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True, text=True, cwd=__file__.rsplit("/tests/", 1)[0],
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(heads) == 1, f"expected exactly one migration head, found: {heads}"


def _customer_with_order(client):
    db = next(client.app.dependency_overrides[get_db]())
    customer = User(name="Cust", email="loc-p4-cust@example.com", phone="9700000200", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="Owner", email="loc-p4-owner@example.com", phone="9700000201", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()

    restaurant = Restaurant(
        owner_id=owner.id, name="Diner P4", phone="9876543210", address="R Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()

    address = create_address(db, customer.id, {
        "recipient_name": "Cust", "phone": "9999999999", "address_line": "Original Line",
        "city": "Original City", "district": "Original District", "state": "ST", "postal_code": "111111",
        "latitude": Decimal("10.0000000"), "longitude": Decimal("20.0000000"),
    })

    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    order = create_order(db, customer, address.id)

    return db, customer, address, order


def test_editing_a_saved_address_never_changes_an_existing_orders_snapshot(client):
    db, customer, address, order = _customer_with_order(client)
    order_id = order.id

    # The customer moves and edits their saved address after the order
    # was already placed and snapshotted.
    address.address_line = "New Line"
    address.city = "New City"
    address.district = "New District"
    address.postal_code = "222222"
    address.latitude = Decimal("99.0000000")
    address.longitude = Decimal("88.0000000")
    db.commit()

    refreshed_order = db.get(Order, order_id)
    assert refreshed_order.address_line == "Original Line"
    assert refreshed_order.city == "Original City"
    assert refreshed_order.postal_code == "111111"
    assert refreshed_order.latitude == Decimal("10.0000000")
    assert refreshed_order.longitude == Decimal("20.0000000")


def test_deleting_a_saved_address_never_changes_an_existing_orders_snapshot(client):
    """Order has no foreign key to Address at all (confirmed in this
    module's own Phase 1 audit) — deleting the address entirely must be
    just as harmless to the order as editing it."""
    db, customer, address, order = _customer_with_order(client)
    order_id = order.id
    address_id = address.id

    db.delete(db.get(Address, address_id))
    db.commit()

    assert db.get(Address, address_id) is None
    refreshed_order = db.get(Order, order_id)
    assert refreshed_order is not None
    assert refreshed_order.address_line == "Original Line"
    assert refreshed_order.city == "Original City"
