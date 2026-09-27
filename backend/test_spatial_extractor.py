import re
from rapidocr_onnxruntime import RapidOCR
import numpy as np

img_path = r"C:\Users\Dell\.gemini\antigravity-ide\brain\c2c0e953-82c5-4e32-aedd-42e7e6aa578e\.user_uploaded\media_1790458795605.png"
engine = RapidOCR()
result, elapse = engine(img_path)

# Extract boxes
boxes = []
for item in result or []:
    box, text, score = item
    pts = np.array(box)
    min_x, min_y = pts.min(axis=0)
    max_x, max_y = pts.max(axis=0)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    boxes.append({
        "text": text.strip(),
        "min_x": min_x, "max_x": max_x, "cx": cx,
        "min_y": min_y, "max_y": max_y, "cy": cy,
        "score": score
    })

# 1. Detect Header Title (top y < 55)
title_candidates = [b["text"] for b in boxes if b["cy"] < 55]
title = " ".join(title_candidates)
print(f"Title / Batch: {title}")

# 2. Detect Time Columns from Header (55 < y < 105)
header_boxes = sorted([b for b in boxes if 55 <= b["cy"] <= 105], key=lambda b: b["cx"])
# Find distinct column centers
time_cols = [
    {"slot": 0, "start": "14:00", "end": "15:00", "min_x": 0, "max_x": 118},
    {"slot": 1, "start": "15:00", "end": "16:00", "min_x": 118, "max_x": 228},
    {"slot": 2, "start": "16:00", "end": "17:00", "min_x": 228, "max_x": 345},
    {"slot": 3, "start": "17:00", "end": "18:00", "min_x": 345, "max_x": 465},
    {"slot": 4, "start": "18:00", "end": "19:00", "min_x": 465, "max_x": 585},
    {"slot": 5, "start": "19:00", "end": "20:00", "min_x": 585, "max_x": 700},
    {"slot": 6, "start": "20:00", "end": "21:00", "min_x": 700, "max_x": 900},
]

# 3. Detect Row Boundaries (y bands)
# Monday: 100-185, Tuesday: 185-280, Wednesday: 280-370, Thursday: 370-455, Friday: 455-560
row_bands = [
    {"weekday": 0, "name": "Monday", "min_y": 100, "max_y": 185},
    {"weekday": 1, "name": "Tuesday", "min_y": 185, "max_y": 280},
    {"weekday": 2, "name": "Wednesday", "min_y": 280, "max_y": 370},
    {"weekday": 3, "name": "Thursday", "min_y": 370, "max_y": 455},
    {"weekday": 4, "name": "Friday", "min_y": 455, "max_y": 560},
]

extracted_classes = []

for row in row_bands:
    w_day = row["weekday"]
    w_name = row["name"]
    row_boxes = [b for b in boxes if row["min_y"] <= b["cy"] < row["max_y"]]
    
    # Group boxes in row into clusters by horizontal span
    # Check if a box spans multiple columns (e.g. min_x in col 4, max_x in col 6)
    # Or cluster boxes that overlap in X
    sorted_row_boxes = sorted(row_boxes, key=lambda b: (b["min_x"], b["min_y"]))
    
    # Assign each box to one or more column slots
    cells = {s: [] for s in range(7)}
    for b in sorted_row_boxes:
        # Find which slot(s) this box overlaps
        overlapping_slots = [
            tc["slot"] for tc in time_cols
            if not (b["max_x"] < tc["min_x"] or b["min_x"] > tc["max_x"])
        ]
        if not overlapping_slots:
            # Assign to closest slot center
            closest_slot = min(time_cols, key=lambda tc: abs(b["cx"] - (tc["min_x"] + tc["max_x"]) / 2))["slot"]
            cells[closest_slot].append(b)
        elif len(overlapping_slots) == 1:
            cells[overlapping_slots[0]].append(b)
        else:
            # Multi-slot span! (e.g. 3-hour lab)
            # Store in first slot with span info
            cells[overlapping_slots[0]].append(b)
            # Mark spanned slots
            for extra_slot in overlapping_slots[1:]:
                cells[extra_slot].append({"_spanned_from": overlapping_slots[0]})

    # Now parse cell contents
    s_idx = 0
    while s_idx < 7:
        slot_items = cells[s_idx]
        if not slot_items:
            s_idx += 1
            continue
        
        # Check if this was spanned from previous slot
        if len(slot_items) == 1 and isinstance(slot_items[0], dict) and "_spanned_from" in slot_items[0]:
            s_idx += 1
            continue

        real_boxes = [b for b in slot_items if isinstance(b, dict) and "text" in b]
        if not real_boxes:
            s_idx += 1
            continue

        # Sort top-to-bottom
        real_boxes = sorted(real_boxes, key=lambda b: b["min_y"])
        
        # Determine span
        overall_min_x = min(b["min_x"] for b in real_boxes)
        overall_max_x = max(b["max_x"] for b in real_boxes)
        
        active_slots = [
            tc["slot"] for tc in time_cols
            if not (overall_max_x < tc["min_x"] or overall_min_x > tc["max_x"])
        ]
        span_start_slot = min(active_slots) if active_slots else s_idx
        span_end_slot = max(active_slots) if active_slots else s_idx
        
        start_time = time_cols[span_start_slot]["start"]
        end_time = time_cols[span_end_slot]["end"]
        
        lines = [b["text"] for b in real_boxes if b["text"].lower() not in ("free", "-", "ated:11/09/2026", "asctimetables")]
        full_cell_text = " ".join(lines).strip()
        
        if not full_cell_text or full_cell_text.lower() in ("free", "-", "break"):
            s_idx = span_end_slot + 1
            continue

        # Parse teacher, room, subject from lines
        teacher = ""
        room = ""
        subject_parts = []
        
        for line in lines:
            if re.search(r"^(?:CS[- ]?|VFM[- ]?)?(?:Dr|Mr|Ms|Prof|Engr)[\.\s]", line, re.IGNORECASE) or "Malik" in line or "Nawaz" in line:
                teacher = (teacher + " " + line).strip(" /")
            elif re.search(r"^(?:C[- ]?\d{3}|Lab\s*\d+|Auditorium|Hall)", line, re.IGNORECASE) or "(Shift" in line:
                room = (room + " " + line).strip(" /")
            else:
                # Clean prefix numbers like 1-, 2-, 3-
                cleaned_subj = re.sub(r"^[1234]-", "", line).strip()
                if cleaned_subj:
                    subject_parts.append(cleaned_subj)

        subject = " ".join(subject_parts).strip(" /")
        if not subject and full_cell_text:
            subject = full_cell_text

        # Clean subject
        subject = re.sub(r"\s+", " ", subject).strip(" /-,")
        teacher = re.sub(r"\s+", " ", teacher).strip(" /-,")
        room = re.sub(r"\s+", " ", room).strip(" /-,")

        extracted_classes.append({
            "weekday": w_day,
            "weekday_name": w_name,
            "start_time": start_time,
            "end_time": end_time,
            "subject": subject,
            "teacher": teacher,
            "room": room
        })

        s_idx = span_end_slot + 1

print(f"\nExtracted {len(extracted_classes)} classes:")
for idx, c in enumerate(extracted_classes):
    print(f"{idx+1:2d}. {c['weekday_name']:9s} {c['start_time']}-{c['end_time']}: {c['subject']} | Teacher: {c['teacher']} | Room: {c['room']}")
