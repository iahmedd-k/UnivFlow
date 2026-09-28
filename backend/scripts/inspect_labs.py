import sqlite3

conn = sqlite3.connect('uniflow.db')
cursor = conn.cursor()

for table in ['courses', 'assignments', 'assignment_materials', 'assignment_solutions']:
    print(f"\n=== SCHEMA OF {table} ===")
    for col in cursor.execute(f"PRAGMA table_info({table})"):
        print(f"  {col[1]} ({col[2]})")
    
    rows = cursor.execute(f"SELECT * FROM {table}").fetchall()
    print(f"Total rows in {table}: {len(rows)}")
    for r in rows[:5]:
        print(" ", r)
