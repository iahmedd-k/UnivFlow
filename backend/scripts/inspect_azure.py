import subprocess

cmd = [
    "ssh",
    "-i", "backend/Azure_Secrets/UnivFlow_key.pem",
    "-o", "StrictHostKeyChecking=no",
    "azureuser@univlfow.koreacentral.cloudapp.azure.com",
    "cd univflow-deploy && docker compose --env-file .env.production -f docker-compose.azure.yml exec api python -c \""
    "from app.db.database import get_db; "
    "from app.db.models import Assignment, BrowserAutomationJob, Setting; "
    "db = next(get_db()); "
    "print('SETTINGS:', [(s.key, s.value[:30] if s.value else None) for s in db.query(Setting).filter(Setting.key.like('%claude%')).all()]); "
    "print('JOBS:', [(j.id, j.assignment_id, j.status, j.error) for j in db.query(BrowserAutomationJob).order_by(BrowserAutomationJob.id.desc()).limit(10).all()]); "
    "print('ASSIGNMENT 206:', [(a.id, a.title, a.status) for a in db.query(Assignment).filter(Assignment.id == 206).all()]); "
    "\""
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:")
print(res.stdout)
print("STDERR:")
print(res.stderr)
