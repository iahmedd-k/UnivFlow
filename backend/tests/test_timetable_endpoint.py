import hashlib
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db, Base
from app.db.models import TimetableEntry
from app.auth.clerk_auth import get_current_user_optional
from app.timetable.router import router as timetable_router

CLASSES_DATA = [
    # Monday (0)
    {"weekday": 0, "subject": "Parallel and Distributed Computing (CS426)", "start_time": "16:00", "end_time": "17:00", "room": "C-305"},
    {"weekday": 0, "subject": "Deep Learning (CS455)", "start_time": "17:00", "end_time": "18:00", "room": "C-204"},
    {"weekday": 0, "subject": "Software Design & Architecture Lab", "start_time": "18:00", "end_time": "21:00", "room": "Lab 5"},
    
    # Tuesday (1)
    {"weekday": 1, "subject": "Computer Organization and Assembly Language", "start_time": "12:00", "end_time": "12:50", "room": "C-302"},
    {"weekday": 1, "subject": "Professional Practices (CS470)", "start_time": "14:00", "end_time": "15:00", "room": "C-305"},
    {"weekday": 1, "subject": "Software Design & Architecture", "start_time": "15:00", "end_time": "16:00", "room": "C-201"},
    {"weekday": 1, "subject": "Parallel and Distributed Computing Lab (CS426L)", "start_time": "17:00", "end_time": "20:00", "room": "Lab 15"},
    {"weekday": 1, "subject": "Principles of Marketing (MK101)", "start_time": "20:00", "end_time": "21:00", "room": "C-305"},
    
    # Wednesday (2)
    {"weekday": 2, "subject": "Computer Organization and Assembly Language", "start_time": "13:00", "end_time": "13:50", "room": "C-302"},
    {"weekday": 2, "subject": "Computer Organization and Assembly Language Lab", "start_time": "14:00", "end_time": "16:40", "room": "Lab 13"},
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


def test_timetable_endpoints():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed the 17 timetable classes for the default/legacy user
    for item in CLASSES_DATA:
        subj = item["subject"].strip()
        w = item["weekday"]
        st = item["start_time"]
        et = item["end_time"]
        identity = f"legacy|{subj.lower()}|{w}|{st}|{et}|fall 2026"
        ext_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        entry = TimetableEntry(
            user_id="legacy",
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

    test_app = FastAPI()
    test_app.include_router(timetable_router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user_optional] = lambda: None

    client = TestClient(test_app)

    try:
        # Test GET /timetable/classes
        res_classes = client.get("/timetable/classes")
        print(f"\nGET /timetable/classes status: {res_classes.status_code}")
        assert res_classes.status_code == 200
        classes = res_classes.json()
        print(f"Total classes returned: {len(classes)}")
        assert len(classes) == 20

        # Check that rooms are populated correctly
        rooms = {c.get("room") for c in classes}
        print(f"Distinct rooms returned: {rooms}")
        expected_rooms = {"C-305", "C-204", "Lab 5", "C-201", "Lab 15", "C-301", "C-302", "C-205", "Lab 6", "C-203", "Lab 13"}
        for r in expected_rooms:
            assert r in rooms, f"Expected room {r} to be in {rooms}"

        # Test GET /timetable/today
        res_today = client.get("/timetable/today")
        print(f"\nGET /timetable/today status: {res_today.status_code}")
        assert res_today.status_code == 200
        today = res_today.json()
        print(f"Today classes returned: {len(today)}")
        for c in today:
            print(f"  {c['start_time']} - {c['end_time']} | {c['subject']} | Room: {c.get('room') or '-'}")
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


if __name__ == "__main__":
    test_timetable_endpoints()
    print("\nAll timetable endpoint tests passed successfully!")
