import logging
import re
import secrets
from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai_engine import DEPARTMENTS
from ..config import settings
from ..database import get_db
from ..models import Otp, User, utcnow
from ..security import create_token, current_user, hash_otp

log = logging.getLogger("civicmind.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

PHONE_RE = re.compile(r"^\+?\d{10,13}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def norm_contact(value: str) -> str:
    v = (value or "").strip().replace(" ", "").replace("-", "").lower()
    if not (PHONE_RE.match(v) or EMAIL_RE.match(v)):
        raise HTTPException(400, "Enter a valid mobile number (10-13 digits) or email address.")
    return v


def user_out(u: User) -> dict:
    return {"id": u.id, "role": u.role, "name": u.name, "contact": u.contact, "department": u.department, "ward": u.ward}


class OtpRequest(BaseModel):
    contact: str
    role: Literal["citizen", "official"]
    mode: Literal["login", "register"]
    name: Optional[str] = None
    department: Optional[str] = None
    ward: Optional[str] = None
    invite_code: Optional[str] = None


class OtpVerify(BaseModel):
    contact: str
    code: str


@router.post("/request-otp")
def request_otp(body: OtpRequest, db: Session = Depends(get_db)):
    contact = norm_contact(body.contact)
    existing = db.query(User).filter(User.contact == contact).first()
    payload = {"mode": body.mode, "role": body.role}

    if body.mode == "register":
        if existing:
            raise HTTPException(409, "This contact is already registered. Please log in instead.")
        name = (body.name or "").strip()
        if len(name) < 2:
            raise HTTPException(400, "Please enter your full name.")
        payload["name"] = name[:120]
        if body.role == "official":
            if body.department not in DEPARTMENTS:
                raise HTTPException(400, "Please choose your department.")
            if settings.OFFICIAL_INVITE_CODE and (body.invite_code or "") != settings.OFFICIAL_INVITE_CODE:
                raise HTTPException(403, "Invalid official invite code.")
            payload["department"] = body.department
            payload["ward"] = (body.ward or "").strip()[:80]
    else:
        if not existing:
            raise HTTPException(404, "No account found for this contact. Please register first.")
        if existing.role != body.role:
            raise HTTPException(400, f"This contact is registered as a {existing.role}. Switch the role tab and try again.")

    recent = db.query(Otp).filter(Otp.contact == contact, Otp.created_at >= utcnow() - timedelta(minutes=10)).count()
    if recent >= 5:
        raise HTTPException(429, "Too many OTP requests. Please wait a few minutes.")

    code = settings.DEMO_OTP if settings.OTP_MODE == "demo" else f"{secrets.randbelow(10 ** 6):06d}"
    if settings.OTP_MODE != "demo":
        log.warning("OTP for %s is %s (OTP_MODE=%s - wire an SMS/email provider for production)", contact, code, settings.OTP_MODE)
    db.add(Otp(contact=contact, code_hash=hash_otp(contact, code), payload=payload,
               expires_at=utcnow() + timedelta(seconds=settings.OTP_TTL_SECONDS)))
    db.commit()
    out = {"ok": True, "message": "OTP sent.", "expires_in": settings.OTP_TTL_SECONDS}
    if settings.OTP_MODE == "demo":
        out["demo_otp"] = code
    return out


@router.post("/verify-otp")
def verify_otp(body: OtpVerify, db: Session = Depends(get_db)):
    contact = norm_contact(body.contact)
    otp = (db.query(Otp).filter(Otp.contact == contact, Otp.used == False)  # noqa: E712
           .order_by(Otp.id.desc()).first())
    if not otp or otp.expires_at < utcnow():
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if otp.attempts >= 5:
        raise HTTPException(429, "Too many wrong attempts. Please request a new OTP.")
    otp.attempts += 1
    if otp.code_hash != hash_otp(contact, (body.code or "").strip()):
        db.commit()
        raise HTTPException(400, "Incorrect OTP.")
    otp.used = True
    p = otp.payload or {}
    if p.get("mode") == "register":
        if db.query(User).filter(User.contact == contact).first():
            db.commit()
            raise HTTPException(409, "This contact is already registered. Please log in.")
        user = User(role=p["role"], name=p["name"], contact=contact, department=p.get("department"), ward=p.get("ward"))
        db.add(user)
    else:
        user = db.query(User).filter(User.contact == contact).first()
        if not user:
            db.commit()
            raise HTTPException(404, "Account not found.")
    db.commit()
    return {"token": create_token(user), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
