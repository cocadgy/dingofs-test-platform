from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from typing import Literal

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
