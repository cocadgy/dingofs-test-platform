"""Secret-free JSON contracts shared with the functional runner."""
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]

# Filtered MODULE_EXECUTORS insertion order in integration-test/run_tests.py.
MODULE_ORDER = ('quota', 'client', 'cache_node', 'fault', 'mount_subdir',
                'basic_file_operation', 'trash', 'dirstat', 'mds_manage',
                'hot_upgrade', 'warmup', 'xattr')


class Target(BaseModel):
    model_config = ConfigDict(extra='ignore', frozen=True)
    role: str
    host: str
    user: str
    mutates: bool


class ModuleCapability(BaseModel):
    model_config = ConfigDict(extra='ignore', frozen=True)
    available: bool
    reasons: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    impacts: list[str] = Field(default_factory=list)
    fixed_resources: list[str] = Field(default_factory=list)


class EnvironmentDescriptor(BaseModel):
    # Raw resolver settings, passwords and storage credentials are never copied.
    model_config = ConfigDict(extra='ignore', frozen=True)
    env_name: str
    source_manifest: dict[str, Digest]
    digest: Digest
    mds_addresses: list[str]
    targets: list[Target]
    client_count: int | None = Field(default=None, ge=0)
    cache_count: int | None = Field(default=None, ge=0)
    storage_type: str | None = None
    programs: dict[str, Any] = Field(default_factory=dict)
    directories: dict[str, Any] = Field(default_factory=dict)
    modules: dict[str, ModuleCapability] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def reject_nested_credentials(self):
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    lowered = key.lower().replace('-', '_')
                    if (any(part in lowered for part in ('password', 'secret', 'credential', 'private_key'))
                            or lowered in ('s3_ak', 's3_sk', 'rados_key', 'access_key', 'token')):
                        raise ValueError('credential fields are forbidden in environment descriptors')
                    visit(item)
            elif isinstance(value, list):
                for item in value: visit(item)
        visit(self.model_dump())
        return self
