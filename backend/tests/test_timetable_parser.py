from app.portal.router import _timetable_rows, _extract_cell_details, _to_24h


def test_time_conversions():
    assert _to_24h("0830") == "08:30"
    assert _to_24h("1000") == "10:00"
    assert _to_24h("08:30") == "08:30"
    assert _to_24h("8:30 AM") == "08:30"
    assert _to_24h("02:00 PM") == "14:00"
    assert _to_24h("1430") == "14:30"


def test_cell_extraction():
    subj, room, teacher = _extract_cell_details("CS-310 Artificial Intelligence\nC-204\nDr. Ahmed")
    assert "Artificial Intelligence" in subj
    assert room == "C-204"
    assert teacher == "Dr. Ahmed"

    subj2, room2, teacher2 = _extract_cell_details("Software Engineering (Lab 2) Engr. Ali")
    assert "Software Engineering" in subj2
    assert "Lab 2" in room2
    assert teacher2 == "Engr. Ali"


def test_grid_timetable_parsing():
    table = [
        ["Time", "Monday", "Tuesday", "Wednesday"],
        ["08:30 - 10:00", "CS310 Artificial Intelligence\nC-204\nDr. Ahmed", "SE301 Software Eng\nLab 2\nEngr. Ali", ""],
        ["10:00 - 11:30", "", "CS315 Computer Networks\nE-301", "CS320 DB\nLT-1\nDr. Sana"],
    ]
    results = _timetable_rows([table])
    assert len(results) == 4
    for r in results:
        assert r["subject"]
        assert 0 <= r["weekday"] <= 6
        assert r["start_time"] and r["end_time"]
        assert r["room"]


def test_military_time_timetable_parsing():
    table = [
        ["Days / Slots", "0830-1000", "1000-1130"],
        ["Monday", "CS310 AI (C-204)", "CS315 CN (E-301)"],
        ["Tuesday", "SE301 SE (Lab 2)", "CS320 DB (LT-1)"],
    ]
    results = _timetable_rows([table])
    assert len(results) == 4
    monday_ai = next(r for r in results if "AI" in r["subject"])
    assert monday_ai["weekday"] == 0
    assert monday_ai["start_time"] == "08:30"
    assert monday_ai["end_time"] == "10:00"
    assert monday_ai["room"] == "C-204"


def test_multiline_text_timetable_parsing():
    text = """
    MONDAY
    08:30 - 10:00
    CS310 Artificial Intelligence
    Room: C-204
    Instructor: Dr. Ahmed

    10:00 - 11:30
    CS315 Computer Networks
    Room: E-301
    Instructor: Dr. Usman
    """
    results = _timetable_rows([], text=text)
    assert len(results) == 2
    assert results[0]["weekday"] == 0
    assert results[0]["start_time"] == "08:30"
    assert results[0]["end_time"] == "10:00"
