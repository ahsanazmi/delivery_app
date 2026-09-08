from fastapi import APIRouter

router = APIRouter()

@router.post("/orders")
async def create_order(payload: dict):
    # naive stub: echo back with an id
    return {"order_id": 123, "status": "created", "payload": payload}
