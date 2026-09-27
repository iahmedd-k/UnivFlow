import re
import json
import os
import httpx
from app.core.config import settings

api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")

structured_asc_text = """
TIMETABLE HEADER: BSCS-VII-A (Shift-II)
TIME SLOTS:
Slot 0: 14:00-15:00
Slot 1: 15:00-16:00
Slot 2: 16:00-17:00
Slot 3: 17:00-18:00
Slot 4: 18:00-19:00
Slot 5: 19:00-20:00
Slot 6: 20:00-21:00

[ROW 1: MONDAY]
- Slot 2 (16:00-17:00): Teacher: CS-Dr Saeed Akbar | Subject: Parallel and Distributed Computing (CS426) | Room: C-305 (Shift-II)
- Slot 3 (17:00-18:00): Teacher: CS Mr. Mohabbat Ali | Subject: Deep Learning (CS455) | Room: C-204 (Shift-II)
- Slot 4 to 6 (18:00-21:00): Teacher: CS-Mr Shakir Hussain / CS-Mr. Junaid Yousaf | Subject: Software Design & Architecture Lab / Big Data Analytics Lab | Room: Lab 6 (Shift-II)

[ROW 2: TUESDAY]
- Slot 0 (14:00-15:00): Teacher: CS-Mr. Qadeer Yaseen | Subject: Professional Practices (CS470) | Room: C-305 (Shift-II)
- Slot 1 (15:00-16:00): Teacher: CS-Dr. Bilal Ahmed / CS-Mr. Zulfiqar Khan | Subject: Software Design & Architecture / Big Data Analytics | Room: C-201 (Shift-II)
- Slot 3 to 5 (17:00-20:00): Teacher: CS-Dr Saeed Akbar | Subject: Parallel and Distributed Computing Lab (CS426L) | Room: Lab 15 (Shift-II)
- Slot 6 (20:00-21:00): Teacher: VFM-Dr. Ishtiaq Ahmed Malik | Subject: Principles of Marketing (MK101) | Room: C-305 (Shift-II)

[ROW 3: WEDNESDAY]
- Slot 2 (16:00-17:00): Teacher: CS-Dr Saeed Akbar | Subject: Parallel and Distributed Computing (CS426) | Room: C-301 (Shift-II)
- Slot 3 (17:00-18:00): Teacher: VFM-Dr. Ishtiaq Ahmed Malik | Subject: Principles of Marketing (MK101) | Room: C-204 (Shift-II)
- Slot 5 (19:00-20:00): Teacher: VFM-Dr. Muhammad Nawaz | Subject: Entrepreneurship (BA353) | Room: C-302 (Shift-II)

[ROW 4: THURSDAY]
- Slot 2 (16:00-17:00): Teacher: CS Mr. M Bilal Khan | Subject: Advisory Class | Room: C-205 (Shift-II)
- Slot 3 (17:00-18:00): Teacher: VFM-Dr. Ishtiaq Ahmed Malik | Subject: Principles of Marketing (MK101) | Room: C-204 (Shift-II)
- Slot 4 to 6 (18:00-21:00): Teacher: CS Mr. Mohabbat Ali | Subject: Deep Learning Lab (CS455L) | Room: Lab 5 (Shift-II)

[ROW 5: FRIDAY]
- Slot 1 (15:00-16:00): Teacher: CS Mr. Mohabbat Ali | Subject: Deep Learning (CS455) | Room: C-204 (Shift-II)
- Slot 2 (16:00-17:00): Teacher: CS-Dr. Bilal Ahmed / CS-Mr. Zulfiqar Khan | Subject: Software Design & Architecture / Big Data Analytics | Room: C-205 (Shift-II)
- Slot 3 (17:00-18:00): Teacher: CS-Mr. Qadeer Yaseen | Subject: Professional Practices (CS470) | Room: C-203 (Shift-II)
- Slot 4 (18:00-19:00): Teacher: VFM-Dr. Muhammad Nawaz | Subject: Entrepreneurship (BA353) | Room: C-205 (Shift-II)
"""

sys_prompt = """You are a timetable parser. Extract university tabular class schedules from grid text into a JSON object.
Return ONLY valid JSON format with keys 'semester_name' (string) and 'classes' (list of {subject, weekdays (list of integers where 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday), start_time (24hr HH:MM), end_time (24hr HH:MM), teacher, room, section}).
Do not include markdown or explanations.
"""

payload = {
    "model": "qwen/qwen3.8-27b",
    "messages": [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Output JSON:\n{structured_asc_text}"}
    ],
    "temperature": 0.0,
    "max_tokens": 4000
}

headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20.0)
content = r.json()["choices"][0]["message"]["content"]
clean_json_str = re.search(r"\{[\s\S]*\}", content).group(0)
data = json.loads(clean_json_str)

print(f"Successfully extracted {len(data.get('classes', []))} classes for {data.get('semester_name')}:")
for c in data.get("classes", []):
    days_str = ", ".join(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d] for d in c["weekdays"])
    print(f" - [{days_str:15}] {c['start_time']} - {c['end_time']} | {c['subject']:45} | Room: {c.get('room',''):15} | Teacher: {c.get('teacher','')}")
