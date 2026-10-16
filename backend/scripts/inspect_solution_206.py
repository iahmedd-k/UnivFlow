import subprocess, base64

py_code = """
from app.db.database import get_db
from app.db.models import Assignment, AssignmentStatus
db = next(get_db())
a = db.query(Assignment).filter(Assignment.id == 204).first()
if a:
    a.status = AssignmentStatus.DRAFT
    db.commit()
    print('RESET 204 TO:', a.status)
"""
b64 = base64.b64encode(py_code.encode()).decode()

cmd = [
    "ssh",
    "-i", "backend/Azure_Secrets/UnivFlow_key.pem",
    "-o", "StrictHostKeyChecking=no",
    "azureuser@univlfow.koreacentral.cloudapp.azure.com",
    f"cd univflow-deploy && docker compose --env-file .env.production -f docker-compose.azure.yml exec -T api python -c \"import base64; exec(base64.b64decode('{b64}'))\""
]

res = subprocess.run(cmd, capture_output=True, text=True)
print(res.stdout)
print(res.stderr)
