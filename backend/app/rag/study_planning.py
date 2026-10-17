"""Professional study planning service.

Implements evidence-based scheduling:
- Syllabus topic extraction (LLM-assisted, deterministic fallback)
- Two planning modes: coverage (interleaved learn→next-day-review) and
  spaced repetition (exam-anchored, reviews at +1d/+3d/+7d/+14d/+28d)
- Topic weighting by difficulty, urgency and importance
- Daily capacity caps + burnout protection (light days)
- Day-by-day session emission with [learn]/[review]/[final_review] labels
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services.ai_solution import _call_groq
from app.core.config import settings

logger = logging.getLogger(__name__)

# Default spaced-repetition review offsets (days after first learn session)
SPACED_REVIEW_OFFSETS = [1, 3, 7, 14, 28]
# Default session lengths (minutes)
DEFAULT_LEARN_MINUTES = 60
DEFAULT_REVIEW_MINUTES = 25
# Daily caps to prevent burnout
DEFAULT_MAX_HOURS_PER_DAY = 3
DEFAULT_LIGHT_DAY_MINUTES = 60
LIGHT_DAY_INTERVAL = 7  # every 7th day is a light day


class StudyPlanningError(Exception):
    pass


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _safe_json_loads(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def _safe_json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def extract_topics_from_syllabus(syllabus: str, exam_title: Optional[str] = None) -> list[dict]:
    """Extract a structured topic list from a syllabus using the LLM.

    Falls back to a deterministic line-based extraction if the LLM is
    unavailable or returns invalid JSON.
    """
    system_prompt = (
        "You are an academic curriculum parser. Extract a clean, ordered list of "
        "study topics from the syllabus text below. Return ONLY valid JSON with "
        "this shape: {\"topics\": [{\"title\": \"...\", \"difficulty\": 1, \"weight\": 1}]} "
        "where difficulty is 1-5 (1=easiest, 5=hardest) and weight is 1-5 "
        "(importance for the exam). Keep titles short and actionable. "
        "Detect 5 to 12 distinct topics. Do not invent topics not implied by "
        "the syllabus."
    )
    user_prompt = f"SYLLABUS:\n{syllabus[:12000]}\n\nEXAM: {exam_title or 'Upcoming exam'}"
    try:
        raw = _call_groq(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=settings.groq_chat_model,
            temperature=0.2,
            max_tokens=1500,
        )
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            data = json.loads(match.group(0))
            topics = data.get("topics", [])
            if isinstance(topics, list) and topics:
                cleaned = []
                for t in topics:
                    title = str(t.get("title", "")).strip()
                    if not title:
                        continue
                    cleaned.append({
                        "title": title,
                        "difficulty": max(1, min(5, int(t.get("difficulty", 3)))),
                        "weight": max(1, min(5, int(t.get("weight", 3)))),
                    })
                if cleaned:
                    return cleaned
    except Exception as e:
        logger.warning(f"LLM topic extraction failed: {e}")

    # Deterministic fallback: split syllabus into non-empty lines/paragraphs
    lines = [ln.strip("- •*0123456789. \t") for ln in syllabus.splitlines()]
    topics = []
    for i, ln in enumerate(lines):
        if len(ln) > 6 and len(topics) < 12:
            topics.append({
                "title": ln[:120],
                "difficulty": 3,
                "weight": 3,
            })
    if not topics:
        topics = [{"title": "General course review", "difficulty": 3, "weight": 3}]
    return topics


def _compute_topic_priority(topic: dict, exam_date: Optional[date], today: date) -> float:
    """Weighted priority score for a topic (higher = study sooner).

    P = 0.4*difficulty + 0.4*urgency + 0.2*weight
    """
    difficulty = max(1, min(5, topic.get("difficulty", 3)))
    weight = max(1, min(5, topic.get("weight", 3)))
    urgency = 1.0
    if exam_date:
        days_left = max(0, (exam_date - today).days)
        urgency = 1.0 / (days_left + 1)  # closer exam = higher urgency
    return 0.4 * difficulty + 0.4 * urgency + 0.2 * weight


def generate_study_plan(
    *,
    syllabus: str,
    exam_title: Optional[str],
    exam_date: Optional[date],
    start_date: date,
    end_date: date,
    hours_per_day: float,
    session_minutes: int,
    plan_mode: str,  # "coverage" | "spaced_repetition"
    topics: Optional[list[dict]] = None,
    document_context: str = "",
) -> dict[str, Any]:
    """Generate a day-by-day study plan.

    Returns a dict with: topics, preferences, stats, summary, sessions
    where sessions is a list of {session_date, session_type, topic,
    duration_minutes, order_index}.
    """
    if end_date < start_date:
        raise StudyPlanningError("End date must be on or after the start date.")

    if hours_per_day <= 0:
        raise StudyPlanningError("hours_per_day must be greater than 0.")

    today = start_date
    topics = topics or extract_topics_from_syllabus(syllabus, exam_title)

    # Sort topics by priority (difficulty/urgency/weight)
    ranked_topics = sorted(
        topics,
        key=lambda t: _compute_topic_priority(t, exam_date, today),
        reverse=True,
    )

    total_days = (end_date - start_date).days + 1
    daily_minutes = int(hours_per_day * 60)
    sessions: list[dict] = []
    day_cursor = start_date

    # Track which topics have been "learned" so we can schedule reviews
    learned_topics: list[dict] = []  # {topic, first_learned_date}
    topic_index = 0  # index into ranked_topics for the next new topic

    def add_session(day: date, s_type: str, topic_title: str, minutes: int, order: int):
        sessions.append({
            "session_date": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
            "session_type": s_type,
            "topic": topic_title,
            "duration_minutes": minutes,
            "order_index": order,
        })

    def day_has_capacity(day_minutes_used: int, additional: int) -> bool:
        return day_minutes_used + additional <= daily_minutes

    if plan_mode == "spaced_repetition":
        # Exam-anchored: learn each topic once, then schedule reviews at
        # expanding intervals, all before the exam date.
        exam_day = exam_date or end_date

        # First pass: schedule "learn" sessions across the preparation window,
        # spacing new topics out so cramming is avoided.
        learn_days = []
        d = start_date
        while d <= exam_day:
            learn_days.append(d)
            d += timedelta(days=1)

        learn_slot_idx = 0
        for topic in ranked_topics:
            # Find the next day with capacity for a learn session
            placed = False
            for _ in range(len(learn_days)):
                day = learn_days[learn_slot_idx % len(learn_days)]
                learn_slot_idx += 1
                used = sum(s["duration_minutes"] for s in sessions if s["session_date"].date() == day)
                if day_has_capacity(used, DEFAULT_LEARN_MINUTES):
                    add_session(day, "learn", topic["title"], DEFAULT_LEARN_MINUTES,
                                len([s for s in sessions if s["session_date"].date() == day]))
                    learned_topics.append({"topic": topic["title"], "first_learned_date": day})
                    placed = True
                    break
            if not placed:
                # No capacity left before exam; still record topic as pending
                logger.warning(f"No capacity to schedule learn session for '{topic['title']}'")

        # Second pass: schedule spaced reviews for each learned topic
        for lt in learned_topics:
            first = lt["first_learned_date"]
            for offset in SPACED_REVIEW_OFFSETS:
                review_day = first + timedelta(days=offset)
                if review_day > exam_day:
                    continue
                used = sum(s["duration_minutes"] for s in sessions if s["session_date"].date() == review_day)
                if day_has_capacity(used, DEFAULT_REVIEW_MINUTES):
                    add_session(review_day, "review", lt["topic"], DEFAULT_REVIEW_MINUTES,
                                len([s for s in sessions if s["session_date"].date() == review_day]))

        # Final review the day before the exam (or on exam day if no room)
        final_review_day = exam_day - timedelta(days=1)
        if final_review_day < start_date:
            final_review_day = exam_day
        used = sum(s["duration_minutes"] for s in sessions if s["session_date"].date() == final_review_day)
        if day_has_capacity(used, DEFAULT_REVIEW_MINUTES):
            add_session(final_review_day, "final_review", "Final exam review", DEFAULT_REVIEW_MINUTES,
                        len([s for s in sessions if s["session_date"].date() == final_review_day]))

    else:
        # Coverage mode: interleaved learn → next-day review → next topic.
        # Distribute topics across days, with a 25-min review of yesterday's
        # topic first thing each day (when available).
        day_cursor = start_date
        previous_topic = None
        topic_queue = list(ranked_topics)

        while topic_queue or previous_topic is not None:
            if day_cursor > end_date:
                break

            day_used = 0
            order = 0

            # 1. Review of yesterday's topic (next-day review)
            if previous_topic is not None:
                used = sum(s["duration_minutes"] for s in sessions if s["session_date"].date() == day_cursor)
                if day_has_capacity(used, DEFAULT_REVIEW_MINUTES):
                    add_session(day_cursor, "review", previous_topic, DEFAULT_REVIEW_MINUTES, order)
                    day_used += DEFAULT_REVIEW_MINUTES
                    order += 1

            # 2. Learn a new topic if capacity remains
            if topic_queue and day_used < daily_minutes:
                topic = topic_queue.pop(0)
                used = sum(s["duration_minutes"] for s in sessions if s["session_date"].date() == day_cursor)
                remaining = daily_minutes - day_used
                learn_minutes = min(DEFAULT_LEARN_MINUTES, remaining)
                if learn_minutes >= 20:
                    add_session(day_cursor, "learn", topic["title"], learn_minutes, order)
                    day_used += learn_minutes
                    order += 1
                    previous_topic = topic["title"]
                    learned_topics.append({"topic": topic["title"], "first_learned_date": day_cursor})
                else:
                    # Not enough room today; put topic back and move to next day
                    topic_queue.insert(0, topic)

            day_cursor += timedelta(days=1)

            # Every 7th day: light review day (burnout protection)
            if (day_cursor - start_date).days % LIGHT_DAY_INTERVAL == 0 and day_cursor <= end_date:
                used = sum(s["duration_minutes"] for s in sessions if s["session_date"].date() == day_cursor)
                if day_has_capacity(used, DEFAULT_LIGHT_DAY_MINUTES):
                    review_topic = previous_topic or (ranked_topics[0]["title"] if ranked_topics else "General review")
                    add_session(day_cursor, "review", f"Light review: {review_topic}", DEFAULT_LIGHT_DAY_MINUTES, 0)

        # Final review tail: remaining days before end_date become revision
        if day_cursor <= end_date and previous_topic is not None:
            while day_cursor <= end_date:
                used = sum(s["duration_minutes"] for s in sessions if s["session_date"].date() == day_cursor)
                if day_has_capacity(used, DEFAULT_REVIEW_MINUTES):
                    add_session(day_cursor, "final_review", f"Revision: {previous_topic}", DEFAULT_REVIEW_MINUTES,
                                len([s for s in sessions if s["session_date"].date() == day_cursor]))
                day_cursor += timedelta(days=1)

    # Sort sessions by date then order_index
    sessions.sort(key=lambda s: (s["session_date"], s["order_index"]))

    total_scheduled = sum(s["duration_minutes"] for s in sessions)
    learn_count = sum(1 for s in sessions if s["session_type"] == "learn")
    review_count = sum(1 for s in sessions if s["session_type"] in ("review", "final_review"))

    stats = {
        "total_days": total_days,
        "total_sessions": len(sessions),
        "learn_sessions": learn_count,
        "review_sessions": review_count,
        "total_minutes_scheduled": total_scheduled,
        "total_hours_scheduled": round(total_scheduled / 60, 1),
        "topics_count": len(topics),
        "plan_mode": plan_mode,
    }

    summary_lines = [
        f"# Study Plan: {exam_title or 'Course Study'}",
        f"**Period:** {start_date.strftime('%b %d, %Y')} → {end_date.strftime('%b %d, %Y')} ({total_days} days)",
        f"**Daily capacity:** {hours_per_day} hour(s)/day",
        f"**Mode:** {plan_mode.replace('_', ' ').title()}",
        f"**Topics:** {len(topics)}",
        f"**Sessions:** {len(sessions)} ({learn_count} learn, {review_count} review)",
        f"**Scheduled study time:** {stats['total_hours_scheduled']} hours",
        "",
        "## Topics",
    ]
    for i, t in enumerate(topics, 1):
        summary_lines.append(f"{i}. {t['title']} (difficulty {t['difficulty']}/5, weight {t['weight']}/5)")
    summary_lines.append("")
    summary_lines.append("## Method")
    summary_lines.append("Sessions use spaced repetition (+1d, +3d, +7d, +14d, +28d review offsets) "
                         "and interleaved learning so you revisit material just as it starts to fade. "
                     "Each 'Recall' session should be active retrieval — close the book and reproduce "
                     "the key ideas before checking.")

    summary = "\n".join(summary_lines)

    return {
        "topics": topics,
        "preferences": {
            "hours_per_day": hours_per_day,
            "session_minutes": session_minutes,
            "plan_mode": plan_mode,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "exam_date": exam_date.isoformat() if exam_date else None,
            "document_context": document_context,
        },
        "stats": stats,
        "summary": summary,
        "sessions": sessions,
    }
