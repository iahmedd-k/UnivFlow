import subprocess, base64

py_code = """
from app.db.database import get_db
from app.db.models import Assignment, AssignmentSolution, Submission
db = next(get_db())
a = db.query(Assignment).filter(Assignment.id == 206).first()
sol = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == 206).first()
sub = db.query(Submission).filter(Submission.assignment_id == 206).first()
print("Assignment 206 Status:", a.status.value if a and a.status else None)
if sol:
    print(f"AssignmentSolution ID: {sol.id}, Provider: {sol.ai_provider}")
    print(f"Validated Content Length: {len(sol.validated_content or '')} chars")
    print(f"Draft Content Length: {len(sol.draft_content or '')} chars")
if sub:
    print(f"Submission Doc ID: {sub.google_doc_id}")
    print(f"Google Doc URL: https://docs.google.com/document/d/{sub.google_doc_id}/edit")


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
