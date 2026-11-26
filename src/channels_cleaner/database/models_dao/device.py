from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from channels_cleaner.database.models import Device


class DeviceDAO:
    session: AsyncSession

    async def list_devices(self) -> list[Device]:
        statement = (
            select(Device)
            .order_by(Device.last_seen_at.desc(), Device.id.desc())
            .execution_options(populate_existing=True)
        )

        result = await self.session.execute(statement)
        return list(result.scalars())

    async def add_device(self, name: str, user_agent: str, token_hash: str, ip: str | None, now: datetime) -> Device:
        device = Device(
            name=name, user_agent=user_agent, token_hash=token_hash, created_at=now, last_seen_at=now, last_ip=ip
        )
        self.session.add(device)

        # The id comes from SQLite: the device list names devices by it
        await self.session.flush()
        return device

    async def rename_device(self, device_id: int, name: str) -> None:
        statement = update(Device).where(Device.id == device_id).values(name=name)

        await self.session.execute(statement)

    async def delete_device(self, device_id: int) -> None:
        statement = delete(Device).where(Device.id == device_id)

        await self.session.execute(statement)

    async def touch_device(self, device_id: int, ip: str | None, now: datetime) -> None:
        statement = update(Device).where(Device.id == device_id).values(last_seen_at=now, last_ip=ip)

        await self.session.execute(statement)
