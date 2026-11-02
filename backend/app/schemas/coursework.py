"""Stable read contracts for user-facing coursework lists."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class CourseListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    external_id: str
    name: str
    section: str | None = None
    description: str | None = None
    room: str | None = None
    teacher_name: str | None = None
    course_state: str | None = None
    alternate_link: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AssignmentMaterialListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    material_type: str
    title: str
    url: str | None = None
    drive_file_id: str | None = None
    mime_type: str | None = None


class AssignmentListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    external_id: str
    course_id: int
    course_name: str
    course_code: str
    title: str
    work_type: str | None = None
    is_quiz: bool
    description: str | None = None
    materials: list[AssignmentMaterialListItem]
    due_at: datetime | str | None = None
    due_date: datetime | str | None = None
    url: str | None = None
    state: str | None = None
    submission_state: str | None = None
    status: str
    google_doc_id: str | None = None


class AcademicRecordListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    external_id: str
    course_id: int | None = None
    title: str
    date: datetime | None = None
    time: str | None = None
    room: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
