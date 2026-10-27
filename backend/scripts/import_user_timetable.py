import hashlib
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.db.models import TimetableEntry

CLASSES_DATA = [
    # Monday (0)
    {"weekday": 0, "subject": "Parallel and Distributed Computing (CS426)", "start_time": "16:00", "end_time": "17:00", "room": "C-305"},
    {"weekday": 0, "subject": "Deep Learning (CS455)", "start_time": "17:00", "end_time": "18:00", "room": "C-204"},
    {"weekday": 0, "subject": "Software Design & Architecture Lab", "start_time": "18:00", "end_time": "21:00", "room": "Lab 5"},
    
    # Tuesday (1)
    {"weekday": 1, "subject": "Professional Practices (CS470)", "start_time": "14:00", "end_time": "15:00", "room": "C-305"},
    {"weekday": 1, "subject": "Software Design & Architecture", "start_time": "15:00", "end_time": "16:00", "room": "C-201"},
    {"weekday": 1, "subject": "Parallel and Distributed Computing Lab (CS426L)", "start_time": "17:00", "end_time": "20:00", "room": "Lab 15"},
    {"weekday": 1, "subject": "Principles of Marketing (MK101)", "start_time": "20:00", "end_time": "21:00", "room": "C-305"},
    
    # Wednesday (2)
    {"weekday": 2, "subject": "Parallel and Distributed Computing (CS426)", "start_time": "16:00", "end_time": "17:00", "room": "C-301"},
    {"weekday": 2, "subject": "Principles of Marketing (MK101)", "start_time": "17:00", "end_time": "18:00", "room": "C-204"},
    {"weekday": 2, "subject": "Entrepreneurship (BA353)", "start_time": "19:00", "end_time": "20:00", "room": "C-302"},
    
    # Thursday (3)
    {"weekday": 3, "subject": "Advisory Class", "start_time": "16:00", "end_time": "17:00", "room": "C-205"},
    {"weekday": 3, "subject": "Principles of Marketing (MK101)", "start_time": "17:00", "end_time": "18:00", "room": "C-204"},
    {"weekday": 3, "subject": "Deep Learning Lab (CS455L)", "start_time": "18:00", "end_time": "21:00", "room": "Lab 6"},
    
    # Friday (4)
    {"weekday": 4, "subject": "Deep Learning (CS455)", "start_time": "15:00", "end_time": "16:00", "room": "C-204"},
    {"weekday": 4, "subject": "Software Design & Architecture", "start_time": "16:00", "end_time": "17:00", "room": "C-205"},
    {"weekday": 4, "subject": "Professional Practices (CS470)", "start_time": "17:00", "end_time": "18:00", "room": "C-203"},
    {"weekday": 4, "subject": "Entrepreneurship (BA353)", "start_time": "18:00", "end_time": "19:00", "room": "C-205"},
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
                semester_name="Fall 2026",
            )
            db.add(entry)

    db.commit()
    print("[OK] Committed timetable entries for all target users!")
    
    for uid in target_users:
        rows = db.query(TimetableEntry).filter(TimetableEntry.user_id == uid).all()
        print(f"\nUser {uid} has {len(rows)} timetable entries:")
        for r in sorted(rows, key=lambda x: (x.weekday, x.start_time)):
            print(f"  Day {r.weekday} ({r.weekday}) | {r.start_time} - {r.end_time} | {r.subject:<46} | Room: {r.room}")
            
    db.close()

if __name__ == "__main__":
    main()
