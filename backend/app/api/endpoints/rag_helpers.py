from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Iterable

from fastapi import HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.ownership import user_owner_ids
from app.db.models import Assignment, AssignmentMaterial, Course
from app.db.models.enums import AssignmentStatus


def _classify_material(
    material_title: str,
    assignment_title: str,
    work_type: str,
    mime_type: str,
    material_type: str,
    granular: bool = False,
):
    wt = (work_type or "").upper()
    mt = (material_type or "").lower()
    t = f"{material_title or ''} {assignment_title or ''}".lower()
    m = (mime_type or "").lower()

    if granular:
        if (
            "presentation" in m or "powerpoint" in m
            or any(t.endswith(ext) for ext in [".ppt", ".pptx", ".key"])
            or any(k in t for k in ["slide", "presentation", "ppt", "keynote", "lecture"])
        ):
            return "slides", "Lecture Slides", "presentation"
        if any(k in t for k in ["syllabus", "course outline", "grading policy", "course policy"]):
            return "syllabus", "Course Syllabus", "book-open"
        if any(k in t for k in ["lab ", "lab-", "lab#", "manual", "experiment", "practical", "lab task"]):
            return "labs", "Lab Assignments", "flask"
        if wt in ("ANNOUNCEMENT", "POST") or mt == "announcement" or "announcement" in t:
            return "announcements", "Class Announcements", "bell"
        if (
            wt in ("ASSIGNMENT", "SHORT_ANSWER_QUESTION", "MULTIPLE_CHOICE_QUESTION")
        ) or any(k in t for k in ["task", "assignment", "hw", "homework", "quiz", "midterm", "final", "exam", "project"]):
            return "coursework", "Coursework & Tasks", "file-text"
        return "handouts", "Handouts & Readings", "book"

    if wt in ("ANNOUNCEMENT", "POST") or mt == "announcement" or "announcement" in t:
        return "announcement", "Class Announcements", "bell"
    if (
        wt in ("ASSIGNMENT", "SHORT_ANSWER_QUESTION", "MULTIPLE_CHOICE_QUESTION")
    ) or any(k in t for k in ["lab ", "lab-", "lab#", "manual", "task", "assignment", "hw", "homework", "quiz", "midterm", "final", "exam"]):
        return "assignment", "Labs & Assignments", "flask"
    icon = "presentation" if ("presentation" in m or "slide" in t) else "book"
    return "material", "Slides & Handouts", icon


def _classify_file_type(mime_type: str, title: str, category: str):
    m = (mime_type or "").lower()
    t = (title or "").lower()
    if "pdf" in m or t.endswith(".pdf"):
        return "pdf"
    if "presentation" in m or any(t.endswith(ext) for ext in [".ppt", ".pptx", ".key"]):
        return "slide"
    if "document" in m or any(t.endswith(ext) for ext in [".doc", ".docx", ".odt"]):
        return "doc"
    if "sheet" in m or any(t.endswith(ext) for ext in [".xls", ".xlsx", ".csv"]):
        return "sheet"
    if m.startswith("text/") or any(t.endswith(ext) for ext in [".py", ".c", ".cpp", ".java", ".js", ".ts", ".html", ".css", ".json", ".sql", ".sh"]):
        return "code"
    if category == "announcement":
        return "announcement"
    return "text"


def _read_materials(
    db: Session,
    document_ids: Iterable[str | int],
    max_chars: int = 30_000,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(str(value) for value in document_ids))
    if not ids:
        return []

    material_ids = {
        int(value[4:]) if value.startswith("mat_") and value[4:].isdigit() else int(value)
        for value in ids
        if (value.isdigit() or (value.startswith("mat_") and value[4:].isdigit()))
    }
    drive_ids = [value for value in ids if not value.startswith(("mat_", "asg_")) and not value.isdigit()]
    material_query = (
        db.query(AssignmentMaterial, Assignment)
        .join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .filter(or_(
            AssignmentMaterial.id.in_(material_ids) if material_ids else False,
            AssignmentMaterial.drive_file_id.in_(drive_ids) if drive_ids else False,
        ))
    )
    if user_id:
        owners = user_owner_ids(user_id)
        material_query = material_query.filter(
            AssignmentMaterial.user_id.in_(owners),
            Assignment.user_id.in_(owners),
            Course.user_id.in_(owners),
        )

    by_id: dict[str, dict[str, Any]] = {}
    for material, assignment in material_query.all():
        item = {
            "id": f"mat_{material.id}",
            "title": material.title or assignment.title or "Course material",
            "content": (material.content or assignment.description or "")[:max_chars],
            "url": material.url or assignment.url,
            "mime_type": material.mime_type or "",
        }
        by_id[f"mat_{material.id}"] = item
        by_id[str(material.id)] = item
        if material.drive_file_id:
            by_id[material.drive_file_id] = item

    assignment_ids = [int(value[4:]) for value in ids if value.startswith("asg_") and value[4:].isdigit()]
    if assignment_ids:
        assignment_query = (
            db.query(Assignment)
            .join(Course, Course.id == Assignment.course_id)
            .filter(Assignment.id.in_(assignment_ids))
        )
        if user_id:
            owners = user_owner_ids(user_id)
            assignment_query = assignment_query.filter(
                Assignment.user_id.in_(owners),
                Course.user_id.in_(owners),
            )
        for assignment in assignment_query.all():
            by_id[f"asg_{assignment.id}"] = {
                "id": f"asg_{assignment.id}",
                "title": assignment.title or "Course assignment",
                "content": (assignment.description or "")[:max_chars],
                "url": assignment.url,
                "mime_type": "text/plain",
            }

    return [by_id[value] for value in ids if value in by_id]


def _retrieve_passages(documents: Iterable[dict[str, Any]], query: str, limit: int = 3) -> list[str]:
    terms = {term.lower() for term in re.findall(r"[\w'-]{3,}", query or "")}
    passages: list[str] = []
    for item in documents:
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n+", content) if sentence.strip()]
        ranked = sorted(
            enumerate(sentences),
            key=lambda entry: (
                -sum(term in entry[1].lower() for term in terms),
                entry[0],
            ),
        )
        selected = [sentence for _, sentence in ranked[:limit] if not terms or any(term in sentence.lower() for term in terms)]
        if not selected:
            selected = sentences[:limit]
        for sentence in selected:
            passages.append(f"PASSAGE FROM {item.get('title') or 'Course material'}:\n{sentence}")
            if len(passages) >= limit:
                return passages
    return passages


def list_classroom_materials(
    db: Session,
    user_id: str,
    limit: int = 500,
    course_id: int | None = None,
    category: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    owners = user_owner_ids(user_id)
    material_query = (
        db.query(AssignmentMaterial, Assignment, Course)
        .join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
        .filter(
            Assignment.user_id.in_(owners),
            Course.user_id.in_(owners),
            AssignmentMaterial.user_id.in_(owners),
        )
    )
    if course_id is not None:
        material_query = material_query.filter(Course.id == course_id)
    if query and query.strip():
        term = f"%{query.strip()}%"
        material_query = material_query.filter(or_(
            AssignmentMaterial.title.ilike(term),
            Assignment.title.ilike(term),
            Course.name.ilike(term),
        ))

    result: list[dict[str, Any]] = []
    for material, assignment, course in (
        material_query.order_by(AssignmentMaterial.created_at.desc(), AssignmentMaterial.id.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    ):
        category_key, category_label, icon = _classify_material(
            material.title or "",
            assignment.title or "",
            assignment.work_type or "",
            material.mime_type or "",
            material.material_type or "",
        )
        if category and category != "all":
            compatible = {
                "material": {"material", "slides", "handouts", "syllabus"},
                "assignment": {"assignment", "labs", "coursework"},
                "announcement": {"announcement", "announcements"},
            }
            if category_key not in compatible.get(category, {category}):
                continue
        result.append({
            "id": f"mat_{material.id}",
            "title": material.title or assignment.title or "Course material",
            "course_id": course.id,
            "course_name": course.name,
            "category": category_key,
            "file_type": _classify_file_type(
                material.mime_type or "",
                material.title or assignment.title or "",
                category_key,
            ),
            "url": material.url or assignment.url or "",
            "mime_type": material.mime_type or "",
            "file_size": material.file_size,
            "has_content": bool(material.content or assignment.description),
            "icon": icon,
        })
    return result


def _extract_text_from_upload(filename: str, content_type: str, data: bytes) -> str:
    suffix = (filename or "").lower()
    mime = (content_type or "").lower()
    if suffix.endswith(".pptx") or "presentation" in mime:
        try:
            import xml.etree.ElementTree as ET

            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = sorted(
                    (
                        name for name in archive.namelist()
                        if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                    ),
                    key=lambda name: int(re.search(r"\d+", name.rsplit("/", 1)[-1]).group())
                    if re.search(r"\d+", name.rsplit("/", 1)[-1])
                    else 0,
                )
                slides = []
                for name in names:
                    root = ET.fromstring(archive.read(name))
                    words = [element.text for element in root.iter() if element.tag.endswith("}t") and element.text]
                    if words:
                        slides.append("\n".join(words))
                return "\n\n".join(slides)
        except (OSError, zipfile.BadZipFile, ET.ParseError):
            return ""
    if suffix.endswith(".pdf") or "pdf" in mime:
        try:
            from pypdf import PdfReader

            return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        except Exception:
            return ""
    if suffix.endswith(".docx") or "wordprocessingml" in mime:
        try:
            import docx

            return "\n".join(paragraph.text for paragraph in docx.Document(io.BytesIO(data)).paragraphs if paragraph.text)
        except Exception:
            return ""
    if mime.startswith("text/") or any(suffix.endswith(ext) for ext in (
        ".txt", ".md", ".py", ".c", ".cpp", ".java", ".js", ".ts", ".html",
        ".css", ".json", ".csv", ".xml",
    )):
        return data.decode("utf-8", errors="replace")
    return ""


async def upload_study_material(
    course_id: int,
    file: UploadFile,
    current_user: dict | None,
    db: Session,
) -> dict[str, Any]:
    user_id = str((current_user or {}).get("id") or "dev_student_user")
    owners = user_owner_ids(user_id)
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.user_id.in_(owners),
    ).first()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 25MB)")
    filename = file.filename or "Uploaded Document"
    content_type = file.content_type or "application/octet-stream"
    content = _extract_text_from_upload(filename, content_type, data)
    if not content.strip():
        raise HTTPException(status_code=422, detail="No readable text could be extracted from this file.")

    container_title = f"Course Uploads - {course.name}"
    container = db.query(Assignment).filter(
        Assignment.user_id.in_(owners),
        Assignment.course_id == course.id,
        Assignment.work_type == "MATERIAL",
        Assignment.title == container_title,
    ).first()
    if container is None:
        container = Assignment(
            user_id=user_id,
            external_id=f"uploads_{course.id}",
            course_id=course.id,
            title=container_title,
            work_type="MATERIAL",
            description="Uploaded lecture slides, notes, handouts, and study materials.",
            status=AssignmentStatus.SUBMITTED,
        )
        db.add(container)
        db.flush()

    material = AssignmentMaterial(
        user_id=user_id,
        assignment_id=container.id,
        material_type="upload",
        title=filename,
        mime_type=content_type,
        content=content[:30_000],
        file_size=len(data),
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    category_key, _, _ = _classify_material(filename, container.title, "MATERIAL", content_type, "upload")
    material_response = {
        "id": f"mat_{material.id}",
        "title": filename,
        "course_id": course.id,
        "course_name": course.name,
        "category": category_key,
        "file_type": _classify_file_type(content_type, filename, category_key),
        "url": "",
        "mime_type": content_type,
        "file_size": len(data),
        "has_content": True,
    }
    return {"status": "success", "material": material_response}
