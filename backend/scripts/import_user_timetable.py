import hashlib
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.db.models import TimetableEntry, Setting

CLASSES_DATA = [
    # Monday (0)
    {"weekday": 0, "subject": "Parallel and Distributed Computing (CS426)", "start_time": "16:00", "end_time": "17:00", "room": "C-305", "teacher": "Dr. Saeed Akbar"},
    {"weekday": 0, "subject": "Deep Learning (CS455)", "start_time": "17:00", "end_time": "18:00", "room": "C-204", "teacher": "Mr. Mohabbat Ali"},
    {"weekday": 0, "subject": "Software Design & Architecture Lab", "start_time": "18:00", "end_time": "21:00", "room": "Lab 5", "teacher": "Mr. Shakir Hussain"},
    
    # Tuesday (1)
    {"weekday": 1, "subject": "Computer Organization and Assembly Language", "start_time": "12:00", "end_time": "12:50", "room": "Main Campus", "teacher": "Mr. Ali Arshad"},
    {"weekday": 1, "subject": "Professional Practices (CS470)", "start_time": "14:00", "end_time": "15:00", "room": "C-305", "teacher": "Mr. Qadeer Yasin"},
    {"weekday": 1, "subject": "Software Design & Architecture", "start_time": "15:00", "end_time": "16:00", "room": "C-201", "teacher": "Dr. Bilal Ahmad"},
    {"weekday": 1, "subject": "Parallel and Distributed Computing Lab (CS426L)", "start_time": "17:00", "end_time": "20:00", "room": "Lab 15", "teacher": "Dr. Saeed Akbar"},
    {"weekday": 1, "subject": "Principles of Marketing (MK101)", "start_time": "20:00", "end_time": "21:00", "room": "C-305", "teacher": "Dr. Muhammad Nawaz Khan"},
    
    # Wednesday (2)
    {"weekday": 2, "subject": "Computer Organization and Assembly Language", "start_time": "13:00", "end_time": "13:50", "room": "Main Campus", "teacher": "Mr. Ali Arshad"},
    {"weekday": 2, "subject": "Computer Organization and Assembly Language Lab", "start_time": "14:00", "end_time": "16:40", "room": "Main Campus", "teacher": "Mr. Ali Arshad"},
    {"weekday": 2, "subject": "Parallel and Distributed Computing (CS426)", "start_time": "16:00", "end_time": "17:00", "room": "C-301", "teacher": "Dr. Saeed Akbar"},
    {"weekday": 2, "subject": "Principles of Marketing (MK101)", "start_time": "17:00", "end_time": "18:00", "room": "C-204", "teacher": "Dr. Muhammad Nawaz Khan"},
    {"weekday": 2, "subject": "Entrepreneurship (BA353)", "start_time": "19:00", "end_time": "20:00", "room": "C-302", "teacher": "Dr. Muhammad Nawaz Khan"},
    
    # Thursday (3)
    {"weekday": 3, "subject": "Advisory Class", "start_time": "16:00", "end_time": "17:00", "room": "C-205", "teacher": "Mr. Muhammad Bilal Khan"},
    {"weekday": 3, "subject": "Principles of Marketing (MK101)", "start_time": "17:00", "end_time": "18:00", "room": "C-204", "teacher": "Dr. Muhammad Nawaz Khan"},
    {"weekday": 3, "subject": "Deep Learning Lab (CS455L)", "start_time": "18:00", "end_time": "21:00", "room": "Lab 6", "teacher": "Mr. Mohabbat Ali"},
    
    # Friday (4)
    {"weekday": 4, "subject": "Deep Learning (CS455)", "start_time": "15:00", "end_time": "16:00", "room": "C-204", "teacher": "Mr. Mohabbat Ali"},
    {"weekday": 4, "subject": "Software Design & Architecture", "start_time": "16:00", "end_time": "17:00", "room": "C-205", "teacher": "Dr. Bilal Ahmad"},
    {"weekday": 4, "subject": "Professional Practices (CS470)", "start_time": "17:00", "end_time": "18:00", "room": "C-203", "teacher": "Mr. Qadeer Yasin"},
    {"weekday": 4, "subject": "Entrepreneurship (BA353)", "start_time": "18:00", "end_time": "19:00", "room": "C-205", "teacher": "Dr. Muhammad Nawaz Khan"},
]

def main():
    db = SessionLocal()
    target_users = ["user_3JtgZ7iYWmteFJWdZB60SEuqmb5", "dev_student_user", "legacy"]
    
    for uid in target_users:
        deleted = db.query(TimetableEntry).filter(TimetableEntry.user_id == uid).delete(synchronize_session=False)
        print(f"User {uid}: deleted {deleted} old entries")
        
        for item in CLASSES_DATA:
            subj = item["subject"].strip()
            w = item["weekday"]
            st = item["start_time"]
            et = item["end_time"]
            identity = f"{uid}|{subj.lower()}|{w}|{st}|{et}|fall 2026"
            ext_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            entry = TimetableEntry(
                user_id=uid,
                external_id=ext_id,
                subject=subj,
                weekday=w,
                start_time=st,
                end_time=et,
                room=item["room"],
                teacher=item.get("teacher", ""),
                semester_name="Fall 2026",
            )
            db.add(entry)

    db.commit()
    print("[OK] Committed clean 20 timetable entries (17 BSCS-VII-A + 3 COAL) for all target users!")
    
    for uid in target_users:
        rows = db.query(TimetableEntry).filter(TimetableEntry.user_id == uid).all()
        print(f"\nUser {uid} now has {len(rows)} timetable entries:")
        for r in sorted(rows, key=lambda x: (x.weekday, x.start_time)):
            print(f"  Day {r.weekday} | {r.start_time} - {r.end_time} | {r.subject:<46} | Room: {r.room:<8} | Teacher: {r.teacher}")
            
    db.close()

if __name__ == "__main__":
    main()
