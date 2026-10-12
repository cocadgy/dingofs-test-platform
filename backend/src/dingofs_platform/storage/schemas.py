from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


STORAGE_FIELDS = {
    "s3": ("s3_ak", "s3_sk", "s3_endpoint", "s3_bucketname"),
    "rados": (
        "rados_username", "rados_key", "rados_mon", "rados_poolname", "rados_clustername",
    ),
}
SECRET_FIELDS = {"s3_ak", "s3_sk", "rados_key"}


class StorageProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    storage_type: Literal["s3", "rados"]
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    parameters: dict[str, str]

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("invalid name")
        return value


class StorageProfileUpdate(StorageProfileInput):
    revision: int = Field(ge=1)


class StorageProfileView(BaseModel):
    id: str
    name: str
    storage_type: Literal["s3", "rados"]
    description: str
    enabled: bool
    revision: int
    creator_id: str
    can_manage: bool
    parameters: dict[str, str]
    has_secrets: bool
    created_at: datetime
    updated_at: datetime
