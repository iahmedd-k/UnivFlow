import subprocess

cmd = [
    "ssh",
    "-i", "backend/Azure_Secrets/UnivFlow_key.pem",
    "-o", "StrictHostKeyChecking=no",
    "azureuser@univlfow.koreacentral.cloudapp.azure.com",
    "docker logs --tail=300 univflow-deploy-api-1 | grep -iE '206|claude|playwright|solution' | tail -n 50"
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:")
print(res.stdout)
print("STDERR:")
print(res.stderr)
