import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", value):
        raise ValueError("有效邮箱为必填项")
    local, domain = value.rsplit("@", 1)
    return local + "@" + domain.lower()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewUser(Strict):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str
    password: str = Field(min_length=6, max_length=1024)
    role: Literal["admin", "member"] = "member"
    _email = field_validator("email")(normalize_email)


class UserRevision(Strict):
    base_revision: int = Field(ge=1, strict=True)


class UserStatus(UserRevision):
    disabled: bool = Field(strict=True)


class ProfileUpdate(Strict):
    current_password: str = Field(min_length=1, max_length=1024)
    email: str | None = None
    new_password: str | None = Field(default=None, min_length=6, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        if value is None:
            raise ValueError("邮箱不能为空")
        return normalize_email(value)

    @model_validator(mode="after")
    def has_update(self):
        if self.email is None and self.new_password is None:
            raise ValueError("需要邮箱或新密码")
        return self


class UserView(BaseModel):
    id: str
    username: str
    email: str | None
    role: str
    disabled: bool
    revision: int
    model_config = ConfigDict(from_attributes=True)


class UserList(BaseModel):
    items: list[UserView]
    total: int
