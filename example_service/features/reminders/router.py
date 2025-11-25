"""API router for the reminders feature."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from example_service.core.dependencies.services import get_reminder_service
from example_service.features.reminders.schemas import ReminderCreate, ReminderResponse
from example_service.features.reminders.service import ReminderService

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get(
    "/",
    response_model=list[ReminderResponse],
    summary="List reminders",
    description="Return all reminders ordered by most recent.",
)
async def list_reminders(
    service: ReminderService = Depends(get_reminder_service),
) -> list[ReminderResponse]:
    reminders = await service.list_reminders()
    return [ReminderResponse.model_validate(reminder) for reminder in reminders]


@router.get(
    "/{reminder_id}",
    response_model=ReminderResponse,
    summary="Get a reminder",
    description="Fetch a reminder by its identifier.",
    responses={404: {"description": "Reminder not found"}},
)
async def get_reminder(
    reminder_id: UUID,
    service: ReminderService = Depends(get_reminder_service),
) -> ReminderResponse:
    reminder = await service.get_reminder(reminder_id)
    if reminder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    return ReminderResponse.model_validate(reminder)


@router.post(
    "/",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reminder",
    description="Create a new reminder entry.",
)
async def create_reminder(
    payload: ReminderCreate,
    service: ReminderService = Depends(get_reminder_service),
) -> ReminderResponse:
    reminder = await service.create_reminder(payload)
    return ReminderResponse.model_validate(reminder)
