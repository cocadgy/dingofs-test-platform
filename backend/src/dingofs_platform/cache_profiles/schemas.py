from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .catalog import validate_options

class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    enabled: bool = True
    parameters: dict[str, str] = Field(default_factory=dict)

    @field_validator('name')
    @classmethod
    def name_valid(cls, v):
        v = v.strip()
        if not v or any((ord(c) < 32 for c in v)):
            raise ValueError('名称无效')
        return v

    @field_validator('parameters')
    @classmethod
    def options_valid(cls, v):
        return validate_options(v)

class ProfileUpdate(ProfileInput):
    revision: int = Field(ge=1)

class ProfileView(ProfileInput):
    id: str
    revision: int
    creator_id: str
    can_manage: bool
    source_version: str
    created_at: datetime
    updated_at: datetime
