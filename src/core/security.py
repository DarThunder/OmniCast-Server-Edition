from pathlib import Path
from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

from core.configs import SECRET_KEY

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_ed25519_signature(public_key_raw: str, message: str, signature_hex: str) -> bool:
    try:
        pub_bytes = bytes.fromhex(public_key_raw)
        sig_bytes = bytes.fromhex(signature_hex)
        msg_bytes = message.encode("utf-8")

        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        public_key.verify(sig_bytes, msg_bytes)
        return True
    except (ValueError, InvalidSignature):
        return False

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)