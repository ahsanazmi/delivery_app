from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.address import Address
from app.models.service_area import ServiceArea, ServiceAreaPostalCode


def get_service_area_for_postal_code(db: Session, postal_code: str) -> ServiceArea | None:
    """The active ServiceArea covering this postal code, if any — used to
    give admins (Maps & Location System Phase 11) zone context for a
    delivery location without duplicating the postal-code-matching logic
    already used to gate checkout in is_address_serviceable below. Orders
    snapshot their own address fields rather than referencing an Address
    row (see Order's own docstring), hence taking a bare postal_code here
    instead of an Address."""
    return db.scalar(
        select(ServiceArea)
        .join(ServiceAreaPostalCode, ServiceAreaPostalCode.service_area_id == ServiceArea.id)
        .where(ServiceAreaPostalCode.postal_code == postal_code, ServiceArea.is_active.is_(True))
    )


def is_address_serviceable(db: Session, address: Address) -> bool:
    """Whether this address's postal code falls inside an active
    ServiceArea. Fails open (returns True) when no service areas have ever
    been configured at all — this is a brand-new, opt-in feature, and every
    address created before it existed must keep working exactly as before.
    Once an admin configures at least one zone, only postal codes actually
    covered by an active zone are considered serviceable."""
    any_configured = db.scalar(select(func.count()).select_from(ServiceArea)) or 0
    if any_configured == 0:
        return True

    return (
        db.scalar(
            select(func.count())
            .select_from(ServiceAreaPostalCode)
            .join(ServiceArea, ServiceArea.id == ServiceAreaPostalCode.service_area_id)
            .where(ServiceAreaPostalCode.postal_code == address.postal_code, ServiceArea.is_active.is_(True))
        )
        or 0
    ) > 0
