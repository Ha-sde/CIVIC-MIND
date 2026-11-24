import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User


def hash_otp(contact: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{contact}:{code}".encode(), hashlib.sha256).hexdigest()


def create_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.ACCESS_TOKEN_HOURS)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, settings.SECRET_KEY, algorithm="HS256")


def _user_from_header(authorization: Optional[str], db: Session) -> Optional[User]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(authorization[7:], settings.SECRET_KEY, algorithms=["HS256"])
        return db.get(User, int(payload["sub"]))
    except Exception:
        return None


def optional_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Optional[User]:
    return _user_from_header(authorization, db)


def current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    user = _user_from_header(authorization, db)
    if not user:
        raise HTTPException(401, "Please log in to continue.")
    return user


def citizen_only(user: User = Depends(current_user)) -> User:
    if user.role != "citizen":
        raise HTTPException(403, "This action is for citizens.")
    return user


def official_only(user: User = Depends(current_user)) -> User:
    if user.role != "official":
        raise HTTPException(403, "This action is for government officials.")
    return user
