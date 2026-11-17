from pydantic import BaseModel, ConfigDict, Field

class ProfileInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=120)
    cluster_id:str
    machine_id:str
    storage_profile_id:str|None=None
    settings:dict=Field(default_factory=dict)
    enabled:bool=True

class ProfileUpdate(ProfileInput):
    revision:int=Field(ge=1)
