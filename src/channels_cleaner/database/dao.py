from sqlalchemy.ext.asyncio import AsyncSession

from channels_cleaner.database.models_dao import AccountDAO, ApplyJobDAO, ChannelDAO, DecisionDAO, DeviceDAO, SettingDAO


class DAO(AccountDAO, ApplyJobDAO, ChannelDAO, DecisionDAO, DeviceDAO, SettingDAO):
    """Writes are Core statements that don't refresh loaded objects, so selects of objects use populate_existing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
