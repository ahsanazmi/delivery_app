"""E2E Validation Phase 4 — GET /reviews/average/{target_type}/{target_id}
returned an unhandled 500 for any target_type outside ReviewTarget."""

import uuid


def test_unknown_target_type_is_a_422_not_a_500(client):
    response = client.get(f"/api/v1/reviews/average/bogus/{uuid.uuid4()}")
    assert response.status_code == 422


def test_known_target_type_with_no_reviews_averages_to_zero(client):
    target_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/reviews/average/restaurant/{target_id}")
    assert response.status_code == 200
    assert response.json() == {"target_type": "restaurant", "target_id": target_id, "average_rating": 0.0}


def test_the_legacy_create_endpoint_can_no_longer_create_a_review(client):
    # E2E Validation Phase 23 (A1) — previously any customer could post
    # unlimited published reviews for any target, with no order behind them.
    from app.core.security import create_access_token, hash_password
    from app.db.session import get_db
    from app.models.review import Review
    from app.models.user import User, UserRole

    db = next(client.app.dependency_overrides[get_db]())
    customer = User(name="Faker", email="faker@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(customer.id)}"}
    target = str(uuid.uuid4())

    for _ in range(3):
        response = client.post("/api/v1/reviews", headers=headers, json={
            "target_type": "restaurant", "target_id": target, "restaurant_id": target, "rating": 1, "comment": "fake",
        })
        assert response.status_code == 410

    assert db.query(Review).count() == 0
    assert client.get(f"/api/v1/reviews/restaurant/{target}").json() == []
