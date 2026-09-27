import os, json, re, httpx
from rapidocr_onnxruntime import RapidOCR
import numpy as np
from app.core.config import settings

img_path = r"C:\Users\Dell\.gemini\antigravity-ide\brain\c2c0e953-82c5-4e32-aedd-42e7e6aa578e\.user_uploaded\media_1790458795605.png"
engine = RapidOCR()
result, elapse = engine(img_path)

ocr_lines = []
for item in result or []:
    box, text, score = item
    pts = np.array(box)
    min_x, min_y = pts.min(axis=0)
    max_x, max_y = pts.max(axis=0)
    ocr_lines.append(f"y=[{int(min_y):3d}-{int(max_y):3d}] x=[{int(min_x):3d}-{int(max_x):3d}] | {text}")

ocr_payload = "\n".join(ocr_lines)

sys_prompt = """You are an expert timetable parsing engine. Given OCR text boxes with spatial coordinates (y=vertical, x=horizontal), parse every class in the weekly university schedule into JSON.

Grid layout rules:
- Top title (y ~0-50): Semester/Batch name (e.g. BSCS-VII-A (Shift-II)).
- Header row (y ~60-100): Columns are time slots (14:00-15:00, 15:00-16:00, 16:00-17:00, 17:00-18:00, 18:00-19:00, 19:00-20:00, 20:00-21:00).
- Row 1 (y ~100-185): MONDAY (weekday 0).
- Row 2 (y ~185-280): TUESDAY (weekday 1).
- Row 3 (y ~280-370): WEDNESDAY (weekday 2).
- Row 4 (y ~370-455): THURSDAY (weekday 3).
- Row 5 (y ~455-555): FRIDAY (weekday 4).
- Labs spanning multiple time columns (e.g., 18:00 to 21:00 or 17:00 to 20:00) should have their full start_time and end_time.
- Start and end times must strictly be 24-hour 'HH:MM' (e.g. '14:00', '15:00', '16:00', '17:00', '18:00', '20:00', '21:00').
- Do NOT output empty or free slots.
- Clean up course codes and prefixes (e.g. '2-Parallel and Distributed Computing (CS426)' -> 'Parallel and Distributed Computing (CS426)').

Return ONLY valid JSON format:
{
  "semester_name": "BSCS-VII-A (Shift-II)",
  "classes": [
    {
      "subject": "Parallel and Distributed Computing (CS426)",
      "weekdays": [0],
      "start_time": "16:00",
      "end_time": "17:00",
      "teacher": "Dr. Saeed Akbar",
      "room": "C-305 (Shift-II)",
      "section": ""
    }
  ]
}
"""

api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")
payload = {
    "model": "openai/gpt-oss-20b",
    "messages": [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Parse this timetable OCR bounding boxes into JSON:\n{ocr_payload}"}
    ],
    "temperature": 0.0,
    "max_tokens": 2000
}
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
with httpx.Client(timeout=30.0) as client:
    resp = client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
    print("Status:", resp.status_code)
    if resp.status_code == 200:
        ans = resp.json()["choices"][0]["message"]["content"]
        print("Raw response:\n", ans)
        match = re.search(r"\{[\s\S]*\}", ans)
        if match:
            data = json.loads(match.group(0))
            print("Detected semester:", data.get("semester_name"))
            print("Extracted count:", len(data.get("classes", [])))
            for idx, c in enumerate(data.get("classes", [])):
                print(f"{idx+1}. Day {c.get('weekdays')} {c.get('start_time')}-{c.get('end_time')}: {c.get('subject')} | Teacher: {c.get('teacher')} | Room: {c.get('room')}")
    else:
        print("Error:", resp.text)
