from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.timetable.router import router as timetable_router

def test_timetable_endpoints():
    test_app = FastAPI()
    test_app.include_router(timetable_router)
    client = TestClient(test_app)
    
    # Test GET /timetable/classes
    res_classes = client.get("/timetable/classes")
    print(f"\nGET /timetable/classes status: {res_classes.status_code}")
    assert res_classes.status_code == 200
    classes = res_classes.json()
    print(f"Total classes returned: {len(classes)}")
    assert len(classes) == 17
    
    # Check that rooms are populated correctly
    rooms = {c.get("room") for c in classes}
    print(f"Distinct rooms returned: {rooms}")
    expected_rooms = {"C-305", "C-204", "Lab 5", "C-201", "Lab 15", "C-301", "C-302", "C-205", "Lab 6", "C-203"}
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

if __name__ == "__main__":
    test_timetable_endpoints()
    print("\nAll timetable endpoint tests passed successfully!")
