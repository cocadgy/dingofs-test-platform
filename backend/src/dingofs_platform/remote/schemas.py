from datetime import datetime
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    device: int = Field(ge=0)
    inode: int = Field(ge=0)
    offset: int = Field(ge=0, le=2**63 - 1)


class RemoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["files", "search", "read", "download", "log-follow", "terminal"]
    cluster_id: str | None = Field(default=None, max_length=36)
    service_id: str | None = Field(default=None, max_length=160)
    machine_id: str | None = Field(default=None, max_length=36)
    file_id: str | None = Field(default=None, max_length=80)
    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    case_sensitive: bool = False
    scan_mode: Literal["prefix", "full"] = "prefix"
    per_file_mb: int = Field(default=1, ge=1, le=64)
    max_files: int = Field(default=200, ge=1, le=1000)
    max_total_mb: int = Field(default=16, ge=0, le=1024)
    max_hits: int = Field(default=200, ge=0, le=500)
    lines: Literal[100, 500, 1000] = 500
    cursor: Cursor | None = None
    cols: int = Field(default=100, ge=1, le=500)
    rows: int = Field(default=30, ge=1, le=500)
    confirmed: bool = Field(default=False, strict=True)


class RemoteAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge: str = Field(min_length=20, max_length=128)
    password: Annotated[
        str, StringConstraints(min_length=1, max_length=4096, strip_whitespace=False)
    ] = Field(repr=False)


class RemoteView(BaseModel):
    id: str
    kind: str
    state: str
    machine_id: str
    machine_name: str
    address: str
    ssh_port: int
    ssh_user: str
    target_user: str
    cluster_id: str | None
    service_id: str | None
    log_dir: str | None
    expires_at: datetime
    challenge: str | None = None
    auth_account: str | None = None
    error_code: str | None = None
    message: str | None = None
    result: dict | None = None
