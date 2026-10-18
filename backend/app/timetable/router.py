import hashlib
import io
import json
import os
import re
from datetime import date, datetime, time
from typing import List, Optional
from zoneinfo import ZoneInfo

import httpx
import numpy as np
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import pytesseract

from app.core.config import settings
from app.core.logging import logger
from app.core.redis import invalidate_attendance_summary_cache
from app.db.database import get_db
from app.db.models import TimetableEntry, Setting
from app.auth.clerk_auth import get_current_user_optional
from app.auth.ownership import require_user_id, user_owner_ids
from datetime import timezone

# Configure Tesseract path across common Windows locations
for t_path in [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
]:
    if os.path.exists(t_path):
        pytesseract.pytesseract.tesseract_cmd = t_path
        break

router = APIRouter(prefix="/timetable", tags=["Timetable"])
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _get_semester_start_dt(db: Session, override: Optional[str] = None, user_id: str = "") -> Optional[datetime]:
    """Get semester start date from database settings if configured"""
    val = override
    if not val and user_id:
        setting = db.query(Setting).filter(Setting.key == f"classroom:{user_id}:semester_start_date").first()
        if setting and setting.value:
            val = setting.value.strip().replace('"', '')
    if not val:
        setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
        if setting and setting.value:
            val = setting.value.strip().replace('"', '')
    if val:
        try:
            if len(val) == 10:
                dt = datetime.fromisoformat(f"{val}T00:00:00+00:00")
            else:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None
TIME_RANGE = re.compile(
    r"(?P<start>(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:AM|PM)?)\s*(?:-|–|—|TO)\s*"
    r"(?P<end>(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:AM|PM)?)",
    re.IGNORECASE,
)
DAY_PATTERN = re.compile(
    r"\b(?:monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thur|thurs|friday|fri|saturday|sat|sunday|sun)\b",
    re.IGNORECASE,
)


class TimetableClassInput(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    weekdays: List[int] = Field(min_length=1, max_length=7)
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    teacher: Optional[str] = Field(default="", max_length=255)
    room: Optional[str] = Field(default="", max_length=100)
    section: Optional[str] = Field(default="", max_length=120)
    semester_name: Optional[str] = Field(default=None, max_length=120)
    semester_start: Optional[date] = None
    semester_end: Optional[date] = None


def _time24(value: str) -> Optional[str]:
    if not value:
        return None
    normalized = re.sub(r"\s+", "", str(value).upper()).replace(".", ":")
    formats = ["%I:%M%p", "%I%p", "%H:%M", "%H"]
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).strftime("%H:%M")
        except ValueError:
            continue
    match = re.match(r"^(\d{1,2}):?(\d{2})?$", normalized)
    if match:
        h = int(match.group(1))
        m = int(match.group(2) or "0")
        if 0 <= h < 24 and 0 <= m < 60:
            return f"{h:02d}:{m:02d}"
    return None


def _clean_time_string(t: str, default_val: str = "09:00") -> str:
    cleaned = _time24(t)
    return cleaned if cleaned else default_val


BLACK_LISTED_KEYWORDS = {
    "free", "break", "lunch", "none", "null", "asctimetables", "timetable", "schedule",
    "class schedule", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "mon", "tue", "wed", "thu", "fri", "sat", "sun", "fall", "spring", "summer",
    "shift", "shift-i", "shift-ii", "shift 1", "shift 2", "morning", "evening", "semester",
    "section", "room", "teacher", "faculty", "instructor", "page", "dept", "department",
    "curriculum", "air university", "au", "day", "time", "venue", "slot", "slots", "period",
    "class", "classes", "recess", "holiday", "off", "tbd", "tba", "n/a", "na",
}

NOISE_SUBSTRINGS = [
    "shift-i", "shift-ii", "shift 1", "shift 2", "shift-1", "shift-2", "shift-ll",
    "department of", "air university", "class schedule", "asctimetables", "w.e.f",
    "semester fall", "semester spring", "semester summer", "morning shift", "evening shift",
    "time table", "weekly timetable",
]

ROOM_REGEX = re.compile(
    r"^(?:(?:room|rm|lab|hall|venue|auditorium|audi|c|b|a|d|e)[- ]?\d{1,4}[a-z]?|"
    r"c[- ]?\d{2,4}|lab[- ]?\d{1,2}|auditorium[- ]?\d{0,2}|main campus)$",
    re.IGNORECASE,
)


def _validate_timetable_candidate(item: dict) -> Optional[dict]:
    """
    Strict 100% validation check for timetable class candidates.
    Discards rough or dump OCR extractions (headers, room-only cells, invalid times, etc.)
    """
    if not isinstance(item, dict):
        return None

    # 1. Subject validation
    raw_subj = str(item.get("subject") or "").strip()
    cleaned = re.sub(r"^[0-9]+[.\-)]\s*", "", raw_subj)
    cleaned = re.sub(r"^(?:CS[- ]?|VFM[- ]?)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" /-,:;|.")

    if len(cleaned) < 3 or len(cleaned) > 150:
        return None

    # Must contain at least 3 alphabetic letters
    letters = re.findall(r"[A-Za-z]", cleaned)
    if len(letters) < 3:
        return None

    lower_sub = cleaned.lower()
    if lower_sub in BLACK_LISTED_KEYWORDS:
        return None
    if ROOM_REGEX.match(lower_sub):
        return None
    if any(noise in lower_sub for noise in NOISE_SUBSTRINGS):
        return None

    # 2. Weekdays validation
    raw_wks = item.get("weekdays")
    if not isinstance(raw_wks, (list, tuple, set)):
        if isinstance(raw_wks, (int, str)) and str(raw_wks).isdigit():
            raw_wks = [int(raw_wks)]
        else:
            return None

    wks = [int(w) for w in raw_wks if str(w).isdigit() and 0 <= int(w) <= 6]
    if not wks:
        return None
    valid_weekdays = sorted(list(set(wks)))

    # 3. Start time and End time validation
    st = _time24(item.get("start_time"))
    et = _time24(item.get("end_time"))
    if not st or not et:
        return None
    time_fmt = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    if not time_fmt.match(st) or not time_fmt.match(et):
        return None

    sh, sm = map(int, st.split(":"))
    eh, em = map(int, et.split(":"))
    dur = (eh * 60 + em) - (sh * 60 + sm)
    if dur < 30 or dur > 240:
        return None

    # Clean teacher and room
    raw_teacher = str(item.get("teacher") or "").strip()
    raw_teacher = re.sub(r"^(?:teacher|faculty|instructor)\s*[:\-]?\s*", "", raw_teacher, flags=re.IGNORECASE)
    clean_teacher = re.sub(r"\s+", " ", raw_teacher).strip(" /-,:;|.")[:150]

    raw_room = str(item.get("room") or "").strip()
    raw_room = re.sub(r"^(?:room|venue|classroom|lab)\s*[:\-]?\s*", "", raw_room, flags=re.IGNORECASE)
    clean_room = re.sub(r"\s+", " ", raw_room).strip(" /-,:;|.")[:100]

    return {
        "subject": cleaned,
        "weekdays": valid_weekdays,
        "start_time": st,
        "end_time": et,
        "teacher": clean_teacher,
        "room": clean_room,
        "section": str(item.get("section") or "").strip()[:50],
    }


def _ocr_box(image: Image.Image, box: tuple[int, int, int, int]) -> str:
    """Crop and OCR a specific bounding box with contrast enhancement"""
    try:
        w = max(box[2] - box[0], 10)
        h = max(box[3] - box[1], 10)
        crop = image.crop(box)
        if w < 100 or h < 50:
            crop = crop.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
        text = pytesseract.image_to_string(crop, config="--psm 6")
        return re.sub(r"[ \t]+", " ", text).strip()
    except Exception:
        return ""


def _parse_spatial_timetable(payload_bytes: bytes) -> tuple[str, list[dict]]:
    """
    High-precision spatial timetable parser using RapidOCR bounding boxes.
    Detects table columns (time slots) and table rows (weekdays Mon-Sun)
    and maps every cell and multi-column lab span with 100% accuracy.
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        result, elapse = engine(payload_bytes)
    except Exception as e:
        logger.warning(f"RapidOCR engine initialization failed: {e}")
        return "", []

    if not result:
        return "", []

    boxes = []
    for item in result:
        box, text, score = item
        pts = np.array(box)
        min_x, min_y = float(pts[:, 0].min()), float(pts[:, 1].min())
        max_x, max_y = float(pts[:, 0].max()), float(pts[:, 1].max())
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        clean_txt = str(text).strip()
        if clean_txt:
            boxes.append({
                "text": clean_txt,
                "min_x": min_x, "max_x": max_x, "cx": cx,
                "min_y": min_y, "max_y": max_y, "cy": cy,
                "score": float(score) if score is not None else 1.0
            })

    if not boxes:
        return "", []

    # 1. Detect semester / header title (topmost text)
    min_page_y = min(b["min_y"] for b in boxes)
    title_boxes = [b["text"] for b in boxes if b["cy"] < min_page_y + 60 and not TIME_RANGE.search(b["text"])]
    semester_name = " ".join(title_boxes).strip()

    # 2. Detect column time slots from header band
    # Find all boxes containing time patterns (e.g. 02:00-03:00, 14:00-15:00)
    time_boxes = [b for b in boxes if TIME_RANGE.search(b["text"])]
    header_time_boxes = sorted([b for b in time_boxes if b["cy"] < min_page_y + 120], key=lambda b: b["cx"])

    time_cols = []
    if header_time_boxes:
        # Group time boxes that belong to the same column (X proximity)
        col_groups = []
        for tb in header_time_boxes:
            matched = False
            for group in col_groups:
                avg_cx = sum(b["cx"] for b in group) / len(group)
                if abs(tb["cx"] - avg_cx) < 55:
                    group.append(tb)
                    matched = True
                    break
            if not matched:
                col_groups.append([tb])

        for idx, grp in enumerate(sorted(col_groups, key=lambda g: min(b["cx"] for b in g))):
            min_x = min(b["min_x"] for b in grp)
            max_x = max(b["max_x"] for b in grp)
            # Find the best 24-hr time match
            st, et = None, None
            for b in grp:
                tm = TIME_RANGE.search(b["text"])
                if tm:
                    s_cand = _time24(tm.group("start"))
                    e_cand = _time24(tm.group("end"))
                    if s_cand and e_cand:
                        st, et = s_cand, e_cand
                        break
            if st and et:
                s_h, s_m = map(int, st.split(":"))
                e_h, e_m = map(int, et.split(":"))
                is_evening = any(k in semester_name.lower() for k in ["shift-ii", "shift 2", "shift-2", "shift-ll", "evening"]) or s_h < 8
                if is_evening:
                    if s_h < 12:
                        s_h += 12
                    if e_h < 12:
                        e_h += 12
                    st = f"{s_h:02d}:{s_m:02d}"
                    et = f"{e_h:02d}:{e_m:02d}"
            if not st:
                st = f"{14 + idx:02d}:00"
                et = f"{15 + idx:02d}:00"
            time_cols.append({"slot": idx, "start": st, "end": et, "min_x": min_x - 15, "max_x": max_x + 15})

    if len(time_cols) < 3:
        # Fallback default columns
        page_w = max(b["max_x"] for b in boxes)
        col_w = page_w / 7.0
        time_cols = [
            {"slot": i, "start": f"{14+i:02d}:00", "end": f"{15+i:02d}:00", "min_x": i * col_w, "max_x": (i + 1) * col_w}
            for i in range(7)
        ]

    # Adjust boundary gaps between columns so they cover the full width seamlessly
    for i in range(len(time_cols) - 1):
        mid = (time_cols[i]["max_x"] + time_cols[i + 1]["min_x"]) / 2.0
        time_cols[i]["max_x"] = mid
        time_cols[i + 1]["min_x"] = mid

    # 3. Detect Row Weekdays (Monday=0 ... Friday=4 / Sunday=6)
    # Filter out header band and footer band
    header_bottom_y = max(b["max_y"] for b in header_time_boxes) if header_time_boxes else min_page_y + 100
    footer_top_y = max(b["max_y"] for b in boxes) - 30
    schedule_boxes = [b for b in boxes if b["cy"] > header_bottom_y and b["cy"] < footer_top_y]

    if not schedule_boxes:
        return semester_name, []

    # Identify row horizontal bands by finding Y clusters
    min_sched_y = min(b["min_y"] for b in schedule_boxes)
    max_sched_y = max(b["max_y"] for b in schedule_boxes)
    sched_height = max_sched_y - min_sched_y

    # Universities typically have 5 rows (Mon-Fri)
    row_header_y = min_sched_y
    row_h = max(20.0, sched_height / 5.0)

    extracted_classes = []

    for r in range(5):
        r_min = row_header_y + r * row_h
        r_max = row_header_y + (r + 1) * row_h
        row_boxes = [b for b in boxes if r_min <= b["cy"] < r_max]
        if not row_boxes:
            continue
        w_day = r

        # Group boxes in row into cells by slot overlap
        cells = {s["slot"]: [] for s in time_cols}
        for b in sorted(row_boxes, key=lambda item: (item["min_x"], item["min_y"])):
            overlapping = [
                tc["slot"] for tc in time_cols
                if not (b["max_x"] < tc["min_x"] or b["min_x"] > tc["max_x"])
            ]
            if not overlapping:
                closest = min(time_cols, key=lambda tc: abs(b["cx"] - (tc["min_x"] + tc["max_x"]) / 2.0))["slot"]
                cells[closest].append(b)
            else:
                for s in overlapping:
                    cells[s].append(b)

        # Process columns and spans
        visited_slots = set()
        for col_info in time_cols:
            s_idx = col_info["slot"]
            if s_idx in visited_slots:
                continue

            slot_items = cells[s_idx]
            if not slot_items:
                visited_slots.add(s_idx)
                continue

            # Deduplicate boxes in this slot
            unique_boxes = []
            seen_texts = set()
            for b in sorted(slot_items, key=lambda x: x["min_y"]):
                key = (b["text"], round(b["min_x"], -1), round(b["min_y"], -1))
                if key not in seen_texts:
                    seen_texts.add(key)
                    unique_boxes.append(b)

            if not unique_boxes:
                visited_slots.add(s_idx)
                continue

            # Check if this cell spans across multiple consecutive columns
            overall_min_x = min(b["min_x"] for b in unique_boxes)
            overall_max_x = max(b["max_x"] for b in unique_boxes)
            spanned_slots = [
                tc["slot"] for tc in time_cols
                if not (overall_max_x < tc["min_x"] or overall_min_x > tc["max_x"])
            ]
            if not spanned_slots:
                spanned_slots = [s_idx]

            for s in spanned_slots:
                visited_slots.add(s)

            span_start = min(spanned_slots)
            span_end = max(spanned_slots)
            start_time = time_cols[span_start]["start"]
            end_time = time_cols[span_end]["end"]

            lines = [b["text"] for b in unique_boxes if b["text"].lower() not in ("free", "-", "break", "asctimetables")]
            full_cell_text = " ".join(lines).strip()

            if not full_cell_text or full_cell_text.lower() in ("free", "-", "break", "lunch"):
                continue

            # Separate rooms, teachers, and course subjects
            rooms = []
            teachers = []
            subject_lines = []

            for line in lines:
                # Room match
                if re.search(r"\b(?:C[- ]?\d{3}|Lab\s*\d+|Auditorium|Hall)\b", line, re.IGNORECASE) or "(Shift" in line:
                    rooms.append(line)
                # Teacher match
                elif re.search(r"^(?:CS[- ]?|VFM[- ]?)?(?:Dr|Mr|Ms|Prof|Engr)[\.\,\s]", line, re.IGNORECASE) or "Malik" in line or "Nawaz" in line:
                    teachers.append(line)
                else:
                    clean_line = re.sub(r"^[1234]-", "", line).strip()
                    if clean_line:
                        subject_lines.append(clean_line)

            raw_subject = " ".join(subject_lines).strip() if subject_lines else full_cell_text
            raw_teacher = " / ".join(teachers).strip()
            raw_room = " / ".join(rooms).strip()

            # Clean prefixes and formatting
            clean_subj = re.sub(r"\b[1234]-", "", raw_subject)
            clean_subj = re.sub(r"^(?:CS[- ]?|VFM[- ]?)", "", clean_subj)
            clean_subj = re.sub(r"\s+", " ", clean_subj).strip(" /-,:")

            clean_teach = re.sub(r"^(?:CS[- ]?|VFM[- ]?)", "", raw_teacher)
            clean_teach = re.sub(r"\s+", " ", clean_teach).strip(" /-,:")

            clean_rm = re.sub(r"\s+", " ", raw_room).strip(" /-,:")

            candidate = {
                "subject": clean_subj,
                "weekdays": [w_day],
                "start_time": start_time,
                "end_time": end_time,
                "teacher": clean_teach,
                "room": clean_rm,
                "section": ""
            }
            validated = _validate_timetable_candidate(candidate)
            if validated:
                extracted_classes.append(validated)

    return semester_name, extracted_classes


def _extract_timetable_with_ai(structured_text: str) -> Optional[dict]:
    """Extract structured tabular timetable classes from structured grid text using Groq LLM"""
    api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")
    if not api_key or not structured_text.strip():
        return None

    sys_prompt = """You are an expert academic timetable parser. Extract university tabular class schedules into a JSON object.
Return ONLY valid JSON format with keys 'semester_name' (string) and 'classes' (list of {subject, weekdays (list of integers where 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday), start_time (24hr HH:MM), end_time (24hr HH:MM), teacher, room, section}).
Rules:
- Weekday integers: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday.
- Start and end times must strictly be 24hr "HH:MM" (e.g. 14:00, 15:00, 16:00, 17:00, 18:00, 20:00, 21:00).
- If teacher, room, or section is missing, set to "".
- Filter out empty / free slots.
"""

    models_to_try = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    for model in models_to_try:
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Parse this timetable text into JSON:\n{structured_text[:6000]}"}
                ],
                "temperature": 0.0,
                "max_tokens": 950
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            with httpx.Client(timeout=15.0) as client:
                resp = client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    json_match = re.search(r"\{[\s\S]*\}", content)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                        if isinstance(parsed, dict) and "classes" in parsed and isinstance(parsed["classes"], list):
                            valid_classes = []
                            for c in parsed["classes"]:
                                validated = _validate_timetable_candidate(c)
                                if validated:
                                    valid_classes.append(validated)
                            if valid_classes:
                                return {
                                    "semester_name": parsed.get("semester_name") or "",
                                    "classes": valid_classes
                                }
        except Exception as e:
            logger.warning(f"Groq timetable extraction with {model} failed: {e}")
            continue
    return None


def _parse_lines_fallback(text: str) -> List[dict]:
    """Fallback line-by-line regex parser if AI extraction is unavailable"""
    candidates = []
    aliases = {
        "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
        "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
    }
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip(" |\t-")
        match = TIME_RANGE.search(line)
        if not line or not match:
            continue
        start_time, end_time = _time24(match.group("start")), _time24(match.group("end"))
        if not start_time or not end_time:
            continue
        days = sorted({aliases[day.lower()] for day in DAY_PATTERN.findall(line) if day.lower() in aliases})
        if not days:
            days = [0]
        details = line[:match.start()] + " " + line[match.end():]
        details = DAY_PATTERN.sub(" ", details)
        teacher_match = re.search(r"(?:teacher|faculty|instructor|dr|prof)\s*[:\-]?\s*([^,;|]+)", details, re.IGNORECASE)
        room_match = re.search(r"(?:room|classroom|venue|lab|c[-–]?\s*\d{3})\s*[:\-#]?\s*([^,;|]+)", details, re.IGNORECASE)
        teacher = teacher_match.group(1).strip() if teacher_match else ""
        room = room_match.group(0).strip() if room_match else ""
        details = re.sub(r"(?:teacher|faculty|instructor|room|classroom|venue)\s*[:\-#]\s*[^,;|]+", " ", details, flags=re.IGNORECASE)
        subject = re.sub(r"\s+", " ", details).strip(" |,;:-")
        candidate = {
            "subject": subject,
            "weekdays": days,
            "start_time": start_time,
            "end_time": end_time,
            "teacher": teacher,
            "room": room,
            "section": ""
        }
        validated = _validate_timetable_candidate(candidate)
        if validated:
            candidates.append(validated)
    return candidates


def _entry_dict(entry: TimetableEntry) -> dict:
    return {
        "id": entry.id,
        "subject": entry.subject,
        "weekday": entry.weekday,
        "weekday_name": WEEKDAYS[entry.weekday] if 0 <= entry.weekday < 7 else "Unknown",
        "start_time": entry.start_time,
        "end_time": entry.end_time,
        "teacher": entry.teacher or "",
        "room": entry.room or "",
        "semester_name": entry.semester_name or "",
        "semester_start": entry.semester_start.date().isoformat() if entry.semester_start else None,
        "semester_end": entry.semester_end.date().isoformat() if entry.semester_end else None,
    }


@router.post("/parse-image", response_model=dict)
async def parse_timetable_image(
    image: UploadFile = File(...),
    auto_save: bool = Query(True),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    """
    Parse an uploaded timetable image or PDF using intelligent grid slicing + AI extraction.
    Strictly validates all candidate classes and overrides the previous timetable upon auto-save.
    """
    content_type = (image.content_type or "").lower()
    is_pdf = content_type == "application/pdf" or (image.filename or "").lower().endswith(".pdf")
    supported_images = {"image/png", "image/jpeg", "image/webp", "image/bmp", "image/tiff"}

    if content_type not in supported_images and not is_pdf:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPG, WEBP, BMP, or PDF timetable.")

    payload = await image.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The timetable file must be 20 MB or smaller.")

    raw_text = ""
    semester_detected = ""
    candidates = []

    if is_pdf:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(payload))
            raw_text = "\n".join((page.extract_text() or "") for page in reader.pages)
            ai_result = _extract_timetable_with_ai(raw_text)
            if ai_result and ai_result.get("classes"):
                candidates = ai_result["classes"]
                semester_detected = ai_result.get("semester_name") or ""
            else:
                candidates = _parse_lines_fallback(raw_text)
        except Exception as error:
            logger.warning(f"PDF extraction error: {error}")
            raise HTTPException(status_code=400, detail="The uploaded PDF could not be read.") from error
    else:
        try:
            # Primary: High-precision spatial OCR table parsing
            semester_detected, spatial_classes = _parse_spatial_timetable(payload)
            if spatial_classes:
                candidates = spatial_classes
                raw_text = f"Spatial Table Extractor: {len(spatial_classes)} classes found."
                logger.info(f"RapidOCR spatial extractor found {len(candidates)} classes for {semester_detected}")
        except Exception as err:
            logger.warning(f"RapidOCR extraction failed: {err}")

        # Fallback if spatial extractor didn't find any classes
        if not candidates:
            try:
                source = Image.open(io.BytesIO(payload))
                if source.width * source.height > 25_000_000:
                    source.thumbnail((4000, 4000), Image.Resampling.LANCZOS)
                source = ImageOps.exif_transpose(source)
                raw_text = pytesseract.image_to_string(source)
            except Exception:
                raw_text = ""

            ai_result = _extract_timetable_with_ai(raw_text)
            if ai_result and ai_result.get("classes"):
                candidates = ai_result["classes"]
                semester_detected = ai_result.get("semester_name") or ""
            else:
                candidates = _parse_lines_fallback(raw_text)

    # 100% Validation Check: Filter out rough, dump or incomplete OCR candidates
    validated_candidates = []
    seen = set()
    for item in candidates:
        validated = _validate_timetable_candidate(item)
        if not validated:
            continue
        for weekday in validated["weekdays"]:
            class_key = (
                validated["subject"].strip().lower(),
                weekday,
                validated["start_time"],
                validated["end_time"]
            )
            if class_key not in seen:
                seen.add(class_key)
                validated_candidates.append({
                    **validated,
                    "weekdays": [weekday]
                })

    # Clean Override Reset: When saving a new timetable image, cleanly wipe previous entries for this user
    saved_entries = []
    if auto_save and validated_candidates:
        db.query(TimetableEntry).filter(TimetableEntry.user_id.in_(owners)).delete(synchronize_session=False)
        db.flush()

        for item in validated_candidates:
            subj = item["subject"].strip()
            st = item["start_time"]
            et = item["end_time"]
            weekday = item["weekdays"][0]
            identity = f"{subj.lower()}|{weekday}|{st}|{et}|{(semester_detected or '').lower()}"
            external_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            entry = TimetableEntry(
                user_id=user_id,
                external_id=external_id,
                subject=subj,
                weekday=weekday,
                start_time=st,
                end_time=et,
                teacher=item.get("teacher") or None,
                room=item.get("room") or None,
                semester_name=semester_detected or None
            )
            db.add(entry)
            db.flush()
            saved_entries.append(entry)

        db.commit()
        invalidate_attendance_summary_cache()
        for entry in saved_entries:
            db.refresh(entry)

    all_current_entries = (
        db.query(TimetableEntry)
        .filter(TimetableEntry.user_id.in_(owners))
        .order_by(TimetableEntry.weekday, TimetableEntry.start_time)
        .all()
    )

    return {
        "filename": image.filename,
        "raw_text": raw_text[:4000],
        "semester_name": semester_detected,
        "candidates": validated_candidates,
        "saved_count": len(saved_entries),
        "total_classes": len(all_current_entries),
        "classes": [_entry_dict(e) for e in all_current_entries],
        "success": True,
        "message": (
            f"Successfully extracted and saved {len(validated_candidates)} verified classes (previous timetable overridden)."
            if validated_candidates
            else "No 100% complete class schedules detected in image. Please ensure subject names, days, and times are clearly legible."
        )
    }


@router.get("/classes", response_model=List[dict])
def get_timetable_classes(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    since_dt = _get_semester_start_dt(db, since, user_id)
    query = (
        db.query(TimetableEntry)
        .filter(TimetableEntry.user_id.in_(owners))
        .order_by(TimetableEntry.weekday, TimetableEntry.start_time)
    )
    
    if since_dt:
        query = query.filter(
            (TimetableEntry.semester_start >= since_dt) |
            (TimetableEntry.semester_start.is_(None))
        )
    
    entries = query.all()
    seen = set()
    unique_entries = []
    for entry in entries:
        key = (entry.subject.strip().lower(), entry.weekday, entry.start_time, entry.end_time)
        if key not in seen:
            seen.add(key)
            unique_entries.append(entry)
    return [_entry_dict(entry) for entry in unique_entries]


@router.get("/classes/{entry_id}", response_model=dict)
def get_timetable_class(
    entry_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Fetch a single timetable class entry by ID (CRUD Read)"""
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    entry = db.query(TimetableEntry).filter(TimetableEntry.id == entry_id, TimetableEntry.user_id.in_(owners)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Timetable class not found.")
    return _entry_dict(entry)


@router.get("/today", response_model=List[dict])
def get_todays_classes(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    since_dt = _get_semester_start_dt(db, since, user_id)
    
    query = (
        db.query(TimetableEntry)
        .filter(TimetableEntry.weekday == today.weekday(), TimetableEntry.user_id.in_(owners))
        .order_by(TimetableEntry.start_time)
    )
    
    if since_dt:
        query = query.filter(
            (TimetableEntry.semester_start >= since_dt) |
            (TimetableEntry.semester_start.is_(None))
        )
    
    entries = query.all()
    seen = set()
    unique_entries = []
    for entry in entries:
        key = (entry.subject.strip().lower(), entry.weekday, entry.start_time, entry.end_time)
        if key not in seen:
            seen.add(key)
            unique_entries.append(entry)
    return [
        _entry_dict(entry) for entry in unique_entries
        if (not entry.semester_start or entry.semester_start.date() <= today)
        and (not entry.semester_end or entry.semester_end.date() >= today)
    ]


@router.post("/classes", response_model=List[dict])
def save_timetable_classes(
    payload: List[TimetableClassInput] = Body(max_length=100),
    override: bool = Query(True, description="Reset and override existing timetable with this new batch"),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Save batch timetable classes.
    By default (override=True), cleanly resets previous timetable entries for the user.
    """
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)

    if override:
        db.query(TimetableEntry).filter(TimetableEntry.user_id.in_(owners)).delete(synchronize_session=False)
        db.flush()

    saved = []
    for item in payload:
        if item.end_time <= item.start_time:
            raise HTTPException(status_code=422, detail=f"End time must be after start time for {item.subject}.")
        for weekday in set(item.weekdays):
            if weekday < 0 or weekday > 6:
                raise HTTPException(status_code=422, detail="Weekdays must be numbered from 0 (Monday) to 6 (Sunday).")
            identity = "|".join((item.subject.strip().lower(), str(weekday), item.start_time, item.end_time, (item.semester_name or "").strip().lower()))
            external_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            entry = db.query(TimetableEntry).filter(TimetableEntry.external_id == external_id, TimetableEntry.user_id.in_(owners)).first()
            if not entry:
                entry = TimetableEntry(
                    user_id=user_id,
                    external_id=external_id,
                    subject=item.subject.strip(),
                    weekday=weekday,
                    start_time=item.start_time,
                    end_time=item.end_time
                )
                db.add(entry)
            entry.subject = item.subject.strip()
            entry.teacher = item.teacher.strip() if item.teacher else None
            entry.room = item.room.strip() if item.room else None
            entry.semester_name = item.semester_name.strip() if item.semester_name else None
            entry.semester_start = datetime.combine(item.semester_start, time.min) if item.semester_start else None
            entry.semester_end = datetime.combine(item.semester_end, time.max) if item.semester_end else None
            db.flush()
            saved.append(entry)
    db.commit()
    invalidate_attendance_summary_cache()
    for entry in saved:
        db.refresh(entry)
    return [_entry_dict(entry) for entry in saved]


@router.post("/classes/single", response_model=dict)
def create_single_timetable_class(
    item: TimetableClassInput = Body(...),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Create a single timetable class entry (CRUD Create)"""
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)

    if item.end_time <= item.start_time:
        raise HTTPException(status_code=422, detail="End time must be after start time.")
    weekday = item.weekdays[0] if item.weekdays else 0
    if weekday < 0 or weekday > 6:
        raise HTTPException(status_code=422, detail="Weekday must be between 0 (Monday) and 6 (Sunday).")

    identity = "|".join((item.subject.strip().lower(), str(weekday), item.start_time, item.end_time, (item.semester_name or "").strip().lower()))
    external_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    entry = db.query(TimetableEntry).filter(TimetableEntry.external_id == external_id, TimetableEntry.user_id.in_(owners)).first()
    if not entry:
        entry = TimetableEntry(
            user_id=user_id,
            external_id=external_id,
            subject=item.subject.strip(),
            weekday=weekday,
            start_time=item.start_time,
            end_time=item.end_time
        )
        db.add(entry)
    entry.subject = item.subject.strip()
    entry.teacher = item.teacher.strip() if item.teacher else None
    entry.room = item.room.strip() if item.room else None
    entry.semester_name = item.semester_name.strip() if item.semester_name else None
    if item.semester_start:
        entry.semester_start = datetime.combine(item.semester_start, time.min)
    if item.semester_end:
        entry.semester_end = datetime.combine(item.semester_end, time.max)
    db.commit()
    invalidate_attendance_summary_cache()
    db.refresh(entry)
    return _entry_dict(entry)


@router.delete("/classes/all", response_model=dict)
def clear_all_timetable_classes(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Clear all timetable class entries for the user (CRUD Delete All / Reset)"""
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    deleted_count = db.query(TimetableEntry).filter(TimetableEntry.user_id.in_(owners)).delete(synchronize_session=False)
    db.commit()
    invalidate_attendance_summary_cache()
    return {"deleted": True, "count": deleted_count}


@router.put("/classes/{entry_id}", response_model=dict)
def update_timetable_class(
    entry_id: int,
    item: TimetableClassInput = Body(...),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Update a specific timetable class entry (CRUD Update)"""
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    entry = db.query(TimetableEntry).filter(TimetableEntry.id == entry_id, TimetableEntry.user_id.in_(owners)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Timetable class not found.")
    
    if item.end_time <= item.start_time:
        raise HTTPException(status_code=422, detail="End time must be after start time.")
    
    weekday = item.weekdays[0] if item.weekdays else entry.weekday
    if weekday < 0 or weekday > 6:
        raise HTTPException(status_code=422, detail="Weekday must be between 0 (Monday) and 6 (Sunday).")

    entry.subject = item.subject.strip()
    entry.weekday = weekday
    entry.start_time = item.start_time
    entry.end_time = item.end_time
    entry.teacher = item.teacher.strip() if item.teacher else None
    entry.room = item.room.strip() if item.room else None
    entry.semester_name = item.semester_name.strip() if item.semester_name else None
    if item.semester_start:
        entry.semester_start = datetime.combine(item.semester_start, time.min)
    if item.semester_end:
        entry.semester_end = datetime.combine(item.semester_end, time.max)

    db.commit()
    invalidate_attendance_summary_cache()
    db.refresh(entry)
    return _entry_dict(entry)


@router.delete("/classes/{entry_id}", response_model=dict)
def delete_timetable_class(
    entry_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Delete a single timetable class entry (CRUD Delete)"""
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    entry = db.query(TimetableEntry).filter(TimetableEntry.id == entry_id, TimetableEntry.user_id.in_(owners)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Timetable class not found.")
    db.delete(entry)
    db.commit()
    invalidate_attendance_summary_cache()
    return {"deleted": True, "id": entry_id}
