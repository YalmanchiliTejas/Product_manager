import secrets
from cryptography.fernet import Fernet

print("FERNET_KEY=" + Fernet.generate_key().decode("utf-8"))
print("SESSION_MIDDLEWARE_SECRET=" + secrets.token_urlsafe(48))
print("GRAPH_CLIENT_STATE_SECRET=" + secrets.token_urlsafe(48))
