from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_customer
from app.models.user import User
from app.schemas.address import AddressRead
from app.schemas.cart import CartItemRead, CartRestaurantRead
from app.schemas.checkout import CheckoutResponse, OrderValidateRequest, OrderValidateResponse
from app.services.checkout import get_checkout_preview, validate_checkout

router = APIRouter()


@router.get("/checkout", response_model=CheckoutResponse)
def checkout_preview(db: DbSession, current_user: User = Depends(require_customer)) -> CheckoutResponse:
    result = get_checkout_preview(db, current_user)
    return CheckoutResponse(
        addresses=[AddressRead.model_validate(a) for a in result["addresses"]],
        selected_address=AddressRead.model_validate(result["selected_address"]) if result["selected_address"] else None,
        restaurant=CartRestaurantRead.model_validate(result["restaurant"]) if result["restaurant"] else None,
        items=[CartItemRead.model_validate(i) for i in result["items"]],
        subtotal=result["subtotal"],
        delivery_fee=result["delivery_fee"],
        tax=result["tax"],
        discount=result["discount"],
        total=result["total"],
        total_items=result["total_items"],
        removed_items=result["removed_items"],
        coupon_code=result["coupon_code"],
        coupon_message=result["coupon_message"],
        issues=result["issues"],
    )


@router.post("/orders/validate", response_model=OrderValidateResponse)
def order_validate(payload: OrderValidateRequest, db: DbSession, current_user: User = Depends(require_customer)) -> OrderValidateResponse:
    result = validate_checkout(db, current_user, payload.address_id)
    return OrderValidateResponse(
        valid=result["valid"],
        issues=result["issues"],
        address=AddressRead.model_validate(result["address"]) if result["address"] else None,
        restaurant=CartRestaurantRead.model_validate(result["restaurant"]) if result["restaurant"] else None,
        items=[CartItemRead.model_validate(i) for i in result["items"]],
        subtotal=result["subtotal"],
        delivery_fee=result["delivery_fee"],
        tax=result["tax"],
        discount=result["discount"],
        total=result["total"],
        total_items=result["total_items"],
        removed_items=result["removed_items"],
        coupon_code=result["coupon_code"],
    )
