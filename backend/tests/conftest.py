import os

# Starlette's TestClient sends `Host: testserver`; the app refuses unknown hosts.
os.environ.setdefault("SALEVAULT_ALLOWED_HOSTS", '["localhost", "127.0.0.1", "testserver"]')
