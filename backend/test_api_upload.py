import httpx

img_path = r"C:\Users\Dell\.gemini\antigravity-ide\brain\c2c0e953-82c5-4e32-aedd-42e7e6aa578e\.user_uploaded\media_1790458795605.png"

# First clear previous schedule to test fresh upload
httpx.delete("http://127.0.0.1:8001/api/v1/timetable/classes/all")

with open(img_path, "rb") as f:
    files = {"image": ("timetable.png", f, "image/png")}
    resp = httpx.post("http://127.0.0.1:8001/api/v1/timetable/parse-image?auto_save=true", files=files, timeout=30.0)
    print("Raw response body:\n", resp.text)
    if resp.status_code == 200:
        data = resp.json()
        print("Success:", data.get("success"))
        print("Semester:", data.get("semester_name"))
        print("Saved count:", data.get("saved_count"))
        print("Total in DB:", data.get("total_classes"))
        print("\nClasses in schedule:")
        for c in data.get("classes", []):
            print(f"[{c['weekday_name']:9s}] {c['start_time']}-{c['end_time']}: {c['subject']} | Room: {c['room']} | Teacher: {c['teacher']}")
    else:
        print("Error:", resp.text)
