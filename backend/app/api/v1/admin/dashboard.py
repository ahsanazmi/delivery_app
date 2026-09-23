from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import AdminDashboardResponse
from app.services.admin_dashboard import get_admin_dashboard

router = APIRouter()


@router.get("/dashboard", response_model=AdminDashboardResponse)
def get_dashboard(db: DbSession, current_admin: User = Depends(require_admin)) -> AdminDashboardResponse:
    return get_admin_dashboard(db)
