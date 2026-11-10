from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from typing import Literal
from pathlib import PurePosixPath
from .contracts import Digest, MODULE_ORDER

class WizardInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    machine_id:str
    storage_profile_id:str
    settings:dict
    fs_mode:Literal["auto","existing"]="auto"
    existing_fs_name:str|None=None
    save_as_environment:bool=False

    @model_validator(mode="after")
    def verify_fs(self):
        if self.fs_mode=="existing" and (not self.existing_fs_name or not self.existing_fs_name.strip()):
            raise ValueError("请选择已有文件系统")
        return self

class RunInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    cluster_id:str
    env_name:str|None=Field(default=None,pattern=r'^env_[A-Za-z0-9_\-]{1,100}$')
    environment_profile_id:str|None=None
    environment_profile_revision:int|None=Field(default=None,ge=1)
    selected:dict[str,list[str]]
    catalog_digest:str=Field(min_length=64,max_length=64)
    retries:int=Field(default=0,ge=0,le=5)
    timeout_minutes:int=Field(default=120,ge=1,le=1440)
    binaries:dict[str,str]=Field(default_factory=dict)
    wizard:WizardInput|None=None
    draft_id:str|None=None
    draft_revision:int|None=None

    @model_validator(mode='after')
    def choose_environment(self):
        if sum(bool(x) for x in (self.env_name,self.environment_profile_id,self.wizard))!=1:
            raise ValueError('请选择一个测试环境或完成向导配置')
        if self.environment_profile_id and self.environment_profile_revision is None:
            raise ValueError('需要测试环境版本')
        return self

    @field_validator('binaries')
    @classmethod
    def binary_paths(cls,value):
        from pathlib import PurePosixPath
        for key,path in value.items():
            if key not in ('dingo-client','dingo-cache','dingo-mds-client') or not isinstance(path,str) or not path.startswith('/') or '..' in PurePosixPath(path).parts or any(c in path for c in '\n\r\x00') or len(path)>512:
                raise ValueError('二进制必须是目标机器上的绝对路径')
        return value


class ModuleSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    module: str
    environment_profile_id: str = Field(min_length=1, max_length=120)
    environment_profile_revision: int = Field(ge=1)
    cases: list[str] = Field(min_length=1)

    @field_validator('module')
    @classmethod
    def supported_module(cls, value):
        if value not in MODULE_ORDER:
            raise ValueError('模块尚未开放')
        return value

    @field_validator('cases')
    @classmethod
    def safe_cases(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('用例重复')
        for path in value:
            rel = PurePosixPath(path)
            if (not path or rel.is_absolute() or '..' in rel.parts or rel.as_posix() != path
                    or '\\' in path or any(ord(c) < 32 for c in path) or not path.endswith('.yaml')):
                raise ValueError('用例必须是模块内相对 YAML 路径')
        return sorted(value)


class RunSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    name: str = Field(min_length=1, max_length=120)
    cluster_id: str = Field(min_length=1)
    module_plans: list[ModuleSelection] = Field(min_length=1, max_length=12)
    catalog_digest: Digest
    retries: int = Field(default=0, ge=0, le=5)
    timeout_minutes: int = Field(default=1440, ge=1, le=1440)

    @field_validator('module_plans')
    @classmethod
    def ordered_unique_modules(cls, value):
        if len({plan.module for plan in value}) != len(value):
            raise ValueError('模块重复')
        return sorted(value, key=lambda plan: MODULE_ORDER.index(plan.module))


class RunInputV2(RunSpec):
    version: Literal[2]
    idempotency_key: str = Field(min_length=1, max_length=128)
    preflight_token: str = Field(min_length=1, max_length=512, repr=False)
    confirmed_impacts: list[Digest] = Field(default_factory=list)
    draft_id: str | None = None
    draft_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def paired_draft(self):
        if (self.draft_id is None) != (self.draft_revision is None):
            raise ValueError('需要草稿标识和版本')
        return self
