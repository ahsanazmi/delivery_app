"""Version 1 API endpoints."""

from . import admin, addresses, auth, coupons, notifications, payments, restaurants, reviews, rider, users

# expose the customer package (sibling of endpoints) as `customer`
from .. import customer

__all__ = [
	"admin",
	"addresses",
	"auth",
	"coupons",
	"notifications",
	"payments",
	"restaurants",
	"reviews",
	"rider",
	"users",
	"customer",
]
