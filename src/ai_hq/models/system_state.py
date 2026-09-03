from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_hq.config import OperatingMode
from ai_hq.db import Base


class SystemState(Base):
    __tablename__ = "system_state"

    def __init__(self, **kwargs):
        kwargs.setdefault("operating_mode", OperatingMode.SAFE.value)
        kwargs.setdefault("simulation_mode", True)
        super().__init__(**kwargs)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    operating_mode: Mapped[str] = mapped_column(String(16), default=OperatingMode.SAFE.value, nullable=False)
    simulation_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
