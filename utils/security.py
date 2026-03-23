import hashlib

def hpw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()