from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import TravelStyle


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2, max_length=150)
    preferred_style: TravelStyle = TravelStyle.STANDARD


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TravelStyleUpdateRequest(BaseModel):
    preferred_style: TravelStyle


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    preferred_style: str
    created_at: datetime


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
