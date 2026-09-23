import posixpath, re
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator, StringConstraints


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssetInput(Strict):
    name: str = Field(min_length=1, max_length=120)


class MachineInput(AssetInput):
    address: str = Field(min_length=1, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    credential_ref: str = Field(default="", max_length=160)
    ssh_password: (
        Annotated[str, StringConstraints(strip_whitespace=False, max_length=4096)]
        | None
    ) = None
    clear_ssh_password: bool = Field(default=False, strict=True)
    physical_id: str | None = Field(default=None, max_length=160)
    tags: list[str] = Field(default_factory=list, max_length=32)
    maintenance: bool = False

    @field_validator("address")
    @classmethod
    def address_valid(cls, v):
        if not re.fullmatch(r"[A-Za-z0-9_.:\-]+", v):
            raise ValueError("invalid hostname or IP")
        return v.lower().rstrip(".")


class ClusterInput(AssetInput):
    management_machine_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    os_user: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    dingo_path: str = Field(max_length=512)
    config_dir: str = Field(max_length=512)
    credential_ref: str = Field(default="", max_length=160)
    external_name: str = Field(min_length=1, max_length=120)
    machine_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("dingo_path", "config_dir")
    @classmethod
    def absolute(cls, v):
        if not v.startswith("/") or "\x00" in v or "\n" in v:
            raise ValueError("absolute path required")
        return posixpath.normpath(v)


class EnvironmentInput(AssetInput):
    cluster_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    machine_ids: list[str] = Field(default_factory=list, max_length=1000)
    enabled: bool = True
