from fastapi import APIRouter

from app.api.v1.endpoints import admin, addresses, auth, cart, coupons, notifications, orders, payments, restaurants, reviews, rider, users, customer

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(restaurants.router, prefix="/restaurants", tags=["restaurants"])
api_router.include_router(cart.router, prefix="/cart", tags=["cart"])
api_router.include_router(addresses.router, prefix="/addresses", tags=["addresses"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(coupons.router, prefix="/coupons", tags=["coupons"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(rider.router, prefix="/rider", tags=["rider"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(customer.profile.router, prefix="/customer", tags=["customer"])
