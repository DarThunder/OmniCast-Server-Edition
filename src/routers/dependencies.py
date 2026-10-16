import jwt
import secrets
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.configs import SECRET_KEY
from core.database import get_db, redis_client
from models.db import User
from core.security import oauth2_scheme

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Se requiere un token de acceso válido"
            )
            
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Token inválido"
            )
    except jwt.PyJWTError:
        nonce = secrets.token_urlsafe(32)
        redis_client.set(f"auth_challenge:{nonce}", "pending", ex=30)
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "token_expired", "nonce": nonce},
            headers={"WWW-Authenticate": f'Bearer error="token_expired", nonce="{nonce}"'}
        )
        
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Usuario no encontrado"
        )
    return user