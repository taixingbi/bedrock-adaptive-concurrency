from __future__ import annotations

from app.controllers.fixed import FixedController


class TenantAdmitController(FixedController):
    """Static global C plus nested tenant/class caps on the limiter."""

    name = "tenant_admit"
