from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceRow(BaseModel):
    id: str
    role: str
    host: str
    running_instances: int
    expected_instances: int
    container_id: str | None
    status_text: str
    state: str
    ports: list[str]
    log_dir: str | None
    data_dir: str | None
    raft_dir: str | None


class ClusterSnapshot(BaseModel):
    cluster_name: str
    cluster_kind: str
    mds_addresses: list[str]
    tikv_addresses: list[str]
    services: list[ServiceRow]
    role_counts: dict[str, int]
    node_count: int
    service_count: int
    running_instances: int
    expected_instances: int
    state: str
    parser_version: int = 1


class DiscoverInput(Strict):
    machine_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    machine_revision: int = Field(ge=1, strict=True)
    target_user: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")


class RevisionInput(Strict):
    base_revision: int = Field(ge=1, strict=True)


class AuthInput(Strict):
    challenge: str = Field(min_length=32, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=4096)


class ImportInput(Strict):
    names: list[str] = Field(min_length=1, max_length=1000)


class RebindInput(RevisionInput):
    discovery_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    name: str = Field(min_length=1, max_length=120)


class EditInput(RevisionInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class OperationView(BaseModel):
    parameters: dict | None = None
    id: str
    kind: str
    state: str
    machine_id: str
    machine_name: str
    ssh_user: str
    target_user: str
    cluster_id: str | None
    error_code: str | None
    message: str | None
    result: dict | None
    auth_account: str | None
    challenge: str | None
    expires_at: str


from datetime import datetime


class ClusterSummary(BaseModel):
    creator_id: str | None = None
    id: str
    name: str
    external_name: str
    machine_name: str
    machine_address: str
    os_user: str
    archived: bool
    binding_state: str
    cluster_kind: str | None
    state: str
    node_count: int | None
    service_count: int | None
    running_instances: int | None
    expected_instances: int | None
    status_success_at: datetime | None
    status_attempt_state: str
    revision: int


class ClusterList(BaseModel):
    items: list[ClusterSummary]
    total: int


class ClusterDetailView(BaseModel):
    creator_id: str | None = None
    node_links: dict[str, str] = Field(default_factory=dict)
    node_match_states: dict[str, Literal["matched", "missing", "ambiguous"]] = Field(
        default_factory=dict
    )
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    external_name: str
    machine_name: str
    machine_address: str
    management_machine_id: str
    ssh_user: str
    os_user: str
    archived: bool
    binding_state: str
    revision: int
    status_snapshot: ClusterSnapshot | None
    status_success_at: datetime | None
    status_attempt_at: datetime | None
    status_attempt_state: str
    status_error_code: str | None
    status_output: dict | None
    config_dir: str
    execution_home: str | None
    resolved_dingo_path: str | None


class ImportedCluster(BaseModel):
    id: str
    name: str


class BindingCandidate(ImportedCluster):
    config_dir: str
    archived: bool
    revision: int


class BindingChoice(BaseModel):
    name: str
    candidates: list[BindingCandidate]


class ImportResult(BaseModel):
    created: list[ImportedCluster]
    existing: list[ImportedCluster]
    needs_confirmation: list[BindingChoice]


class ControlInput(RevisionInput):
    action: Literal["start", "stop", "restart"]
    scope: Literal["all", "service", "role"]
    target: str | None = Field(default=None, max_length=120)
    confirmed: bool = Field(strict=True)
