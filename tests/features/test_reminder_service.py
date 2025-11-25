"""Tests for the reminders service layer."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from example_service.features.reminders.schemas import ReminderCreate
from example_service.features.reminders.service import ReminderService
from example_service.infra.database.base import Base


@pytest.fixture
async def session() -> AsyncSession:
    """Provide an isolated in-memory database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_reminders(session: AsyncSession) -> None:
    service = ReminderService(session)

    await service.create_reminder(ReminderCreate(title="Pay bills"))
    reminders = await service.list_reminders()

    assert len(reminders) == 1
    assert reminders[0].title == "Pay bills"


@pytest.mark.asyncio
async def test_get_reminder_round_trip(session: AsyncSession) -> None:
    service = ReminderService(session)

    created = await service.create_reminder(ReminderCreate(title="Submit report"))
    fetched = await service.get_reminder(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Submit report"
