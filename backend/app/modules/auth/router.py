import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSession, get_db
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.entities import User
from app.modules.auth.schemas import (
    AuthTokenResponse,
    CsrfTokenResponse,
    TravelStyleUpdateRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Auth & Profil"])
bearer_scheme = HTTPBearer(auto_error=False)

SESSION_COOKIE_NAME = "tm_access_token"
CSRF_COOKIE_NAME = "tm_csrf_token"
CSRF_HEADER_NAMES = ("X-CSRF-Token", "X-XSRF-Token")
MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
}


def _set_auth_and_csrf_cookies(response: Response, access_token: str, csrf_token: str) -> None:
    cfg = get_settings()
    max_age_sec = int(cfg.ACCESS_TOKEN_EXPIRE_MINUTES) * 60
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=max_age_sec,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        samesite="lax",
        secure=False,
        path="/",
        max_age=max_age_sec,
    )


def _verify_csrf_for_cookie_session(request: Request) -> None:
    if request.method.upper() not in MUTATING_HTTP_METHODS:
        return
    if request.url.path in CSRF_EXEMPT_PATHS:
        return
    cookie_csrf = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    header_csrf = ""
    for hdr_name in CSRF_HEADER_NAMES:
        val = (request.headers.get(hdr_name) or "").strip()
        if val:
            header_csrf = val
            break
    if not cookie_csrf or not header_csrf or not secrets.compare_digest(cookie_csrf, header_csrf):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Protection CSRF : jeton X-CSRF-Token manquant ou invalide.",
        )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    raw_token: str | None = None
    used_cookie_auth = False

    if credentials is not None and credentials.credentials:
        raw_token = credentials.credentials
        # Si le client envoie explicitement un en-tête X-CSRF-Token invalide avec un cookie CSRF actif, on le vérifie aussi
        if (
            request.method.upper() in MUTATING_HTTP_METHODS
            and request.url.path not in CSRF_EXEMPT_PATHS
            and any(request.headers.get(h) is not None for h in CSRF_HEADER_NAMES)
        ):
            _verify_csrf_for_cookie_session(request)
    else:
        cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
        if cookie_token:
            raw_token = cookie_token
            used_cookie_auth = True

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise.",
        )

    if used_cookie_auth:
        _verify_csrf_for_cookie_session(request)

    try:
        payload = decode_access_token(raw_token)
        user_id: str | None = payload.get("sub")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton JWT invalide ou expiré.",
        ) from exc

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable.",
        )
    return user


@router.post("/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserRegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    existing = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cet e-mail est déjà utilisé.",
        )

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        preferred_style=payload.preferred_style.value,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=user.id, extra_claims={"email": user.email})
    csrf_token = secrets.token_urlsafe(32)
    _set_auth_and_csrf_cookies(response, token, csrf_token)
    return AuthTokenResponse(
        access_token=token,
        csrf_token=csrf_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=AuthTokenResponse)
async def login_user(
    payload: UserLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects.",
        )
    token = create_access_token(subject=user.id, extra_claims={"email": user.email})
    csrf_token = secrets.token_urlsafe(32)
    _set_auth_and_csrf_cookies(response, token, csrf_token)
    return AuthTokenResponse(
        access_token=token,
        csrf_token=csrf_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
async def logout_user(response: Response) -> dict[str, str]:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", samesite="lax")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/", samesite="lax")
    return {
        "status": "logged_out",
        "message": "Vous êtes déconnecté. Le jeton de session et le jeton CSRF ont été supprimés.",
    }


@router.get("/csrf", response_model=CsrfTokenResponse)
async def get_csrf_token(
    request: Request,
    response: Response,
) -> CsrfTokenResponse:
    existing_csrf = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    csrf_token = existing_csrf or secrets.token_urlsafe(32)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        samesite="lax",
        secure=False,
        path="/",
        max_age=int(get_settings().ACCESS_TOKEN_EXPIRE_MINUTES) * 60,
    )
    return CsrfTokenResponse(csrf_token=csrf_token)


@router.get("/me", response_model=UserResponse)
async def read_current_user(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    if not request.cookies.get(CSRF_COOKIE_NAME):
        csrf_token = secrets.token_urlsafe(32)
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=csrf_token,
            httponly=False,
            samesite="lax",
            secure=False,
            path="/",
            max_age=int(get_settings().ACCESS_TOKEN_EXPIRE_MINUTES) * 60,
        )
    return UserResponse.model_validate(current_user)


@router.patch("/travel-style", response_model=UserResponse)
async def update_travel_style(
    payload: TravelStyleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    current_user.preferred_style = payload.preferred_style.value
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)

