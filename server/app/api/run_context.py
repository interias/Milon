"""Run intent, atomic exertion edits and station weather context."""
from typing import Annotated, Literal
from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from .. import run_context

router = APIRouter(prefix="/running/context", tags=["running"])
ActivityId = Annotated[str, Path(pattern=r"^[0-9]{1,30}$")]


class ContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["easy", "long", "tempo"] | None = None
    training_effort: StrictInt | None = Field(None, ge=1, le=5)

    @model_validator(mode="after")
    def not_empty(self):
        if not self.model_fields_set:
            raise ValueError("Mindestens eine Angabe ändern.")
        return self


@router.get("/{activity_id}")
def get_context(activity_id: ActivityId):
    return run_context.context(activity_id)


@router.patch("/{activity_id}")
def update_context(activity_id: ActivityId, body: ContextInput):
    return run_context.update(activity_id, body.model_dump(exclude_unset=True))
