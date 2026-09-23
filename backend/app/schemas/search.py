from pydantic import BaseModel

from app.schemas.category import CategoryRead
from app.schemas.product import ProductRead
from app.schemas.restaurant import CustomerRestaurantRead


class SearchResponse(BaseModel):
    restaurants: list[CustomerRestaurantRead]
    products: list[ProductRead]
    categories: list[CategoryRead]
    page: int
    limit: int
