import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from core.audit import log_action
from core.database import get_db, redis_client
from core.configs import SECRET_KEY
from models.db import User
from models.schemas import UserCreate, RefreshTokenRequest
from core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_ed25519_signature
)

router = APIRouter(tags=["Auth"])

AT_TTL_SECONDS = 15 * 60
RT_TTL_SECONDS = 30 * 24 * 3600

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="El usuario ya existe")

    hashed_pw = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        hashed_password=hashed_pw,
        public_key=getattr(user, "public_key", None),
    )

    db.add(new_user)
    db.commit()

    log_action(db, None, "REGISTER", f"Nuevo usuario registrado: {user.username}")
    return {"message": "Usuario registrado exitosamente"}

@router.post("/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_refresh_token(data={"sub": user.username})

    redis_client.set(f"token:at:{access_token}", user.username, ex=AT_TTL_SECONDS)
    redis_client.set(f"token:rt:{refresh_token}", user.username, ex=RT_TTL_SECONDS)

    log_action(db, user.id, "LOGIN", "Inicio de sesión exitoso")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }

@router.post("/refresh")
def refresh_access_token(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(data.refresh_token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tipo de token inválido",
            )
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido",
            )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )

    rt_key = f"token:rt:{data.refresh_token}"
    if not redis_client.getdel(rt_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token ya utilizado o revocado",
        )

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if getattr(user, "public_key", None):
        if not data.nonce or not data.signature:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Este usuario requiere nonce y firma Ed25519 para refrescar",
            )
        nonce_key = f"auth_challenge:{data.nonce}"
        if not redis_client.getdel(nonce_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="El nonce es inválido o ha expirado",
            )
        if not verify_ed25519_signature(user.public_key, data.nonce, data.signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firma criptográfica inválida para el nonce proporcionado",
            )

    redis_client.delete(rt_key)

    new_access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = create_refresh_token(data={"sub": user.username})

    redis_client.set(f"token:at:{new_access_token}", user.username, ex=AT_TTL_SECONDS)
    redis_client.set(f"token:rt:{new_refresh_token}", user.username, ex=RT_TTL_SECONDS)
    log_action(db, user.id, "TOKEN_REFRESH", "Tokens rotados exitosamente")

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }