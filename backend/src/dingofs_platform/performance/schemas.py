"""Validated subset of the dtt single-client benchmark contract."""
import re
import json
import math
from itertools import product
from pathlib import PurePosixPath
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator, PrivateAttr


def byte_size(value: str) -> int:
    match=re.fullmatch(r'([1-9][0-9]*)([KMGTPE]?)(?:i?B)?',value,re.I)
    if not match:raise ValueError('大小格式应为 4KiB、256MiB 或 1GiB')
    result=int(match[1])*1024**(('KMGTPE'.index(match[2].upper())+1) if match[2] else 0)
    if result>1024**5:raise ValueError('数据量不能超过1PiB')
    return result


class TestSpec(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tool: Literal['fio','elbencho','mdtest']
    direct: bool=True
    concurrency: int=Field(default=4,ge=1,le=1024)
    file_size: str | None=None
    file_count: int | None=Field(default=None,ge=1,le=10000000)
    total_size: str | None=None
    block_size: str | None=None
    rw: Literal['read','write','randread','randwrite','rw','randrw']='write'
    rounds: int=Field(default=1,ge=1,le=100)
    iodepth: int=Field(default=1,ge=1,le=1024)
    read_percent: int | None=Field(default=None,ge=0,le=100)

    mdtest_options: dict = Field(default_factory=dict)
    layout: Literal['unique','shared']='unique'

    @model_validator(mode='after')
    def validate_plan(self):
        if self.tool == 'mdtest':
            self.file_count = self.file_count or 10000
            from .mdtest import validate_options
            validate_options(self.mdtest_options)
            if not (self.mdtest_options.get('-n') or self.mdtest_options.get('-I')) and self.file_count % self.concurrency:
                raise ValueError('文件总数必须能被 MPI 进程数整除')
            self.mdtest_options=dict(sorted(self.mdtest_options.items()))
            opts=self.mdtest_options
            if opts.get('-l',0)>self.concurrency or opts.get('-f',1)>self.concurrency or (opts.get('-l',0) and opts.get('-f',1)>opts['-l']):
                raise ValueError('mdtest 任务数扫描范围不能超过 MPI 进程数，起点不能超过终点')
            items=opts.get('-n',self.file_count//self.concurrency)
            if opts.get('-I'):
                depth=opts.get('-z',0);branch=opts.get('-b',1)
                directories=branch**depth if opts.get('-L') else sum(branch**i for i in range(depth+1))
                items=opts['-I']*directories
            total=0 if opts.get('-D') else items*self.concurrency*opts.get('-w',0)
            if total>1024**5:raise ValueError('mdtest 写入数据量不能超过 1PiB')
            self.file_size = self.block_size = '0'
            self.total_size=str(total)
            self.direct = False
            self.iodepth = 1
            self.read_percent = None
            return self
        size=byte_size(self.file_size) if self.file_size else None
        total=byte_size(self.total_size) if self.total_size else None
        count=self.file_count
        if total:
            if size and count and total!=size*count:raise ValueError('总大小必须等于文件大小乘以文件数量')
            if size:
                if total%size:raise ValueError('总大小必须能整除文件大小')
                count=total//size
            else:
                count=count or self.concurrency
                if total%count:raise ValueError('总大小必须能整除文件数量')
                size=total//count
        else:
            count=count or self.concurrency
            size=size or 256*1024**2
            total=count*size
        if not 1<=count<=10000000 or total>1024**5:raise ValueError('文件数或数据量超出支持范围')
        if count<self.concurrency:raise ValueError('文件数量不能小于并发度')
        block=byte_size(self.block_size) if self.block_size else min(1024**2,size & -size)
        if block>size or size%block:raise ValueError('块大小必须不大于文件大小并能整除文件大小')
        if self.direct and (size%4096 or block%4096):raise ValueError('Direct I/O要求文件和块大小按4KiB对齐')
        if self.tool=='elbencho' and self.rw.startswith('rand') and total%(block*self.concurrency):
            raise ValueError('elbencho随机模式总量必须能整除块大小乘以并发度')
        if self.read_percent is not None and self.rw not in ('rw','randrw'):
            raise ValueError('读比例仅用于混合读写')
        self.file_size,self.file_count,self.total_size,self.block_size=str(size),count,str(total),str(block)
        return self


class ParameterMatrix(BaseModel):
    """Scalar values remain supported; lists define independent candidate axes."""
    model_config=ConfigDict(extra='forbid')
    tool: Literal['fio','elbencho','mdtest']
    direct: bool | list[bool]=True
    concurrency: int | list[int]=4
    file_size: str | list[str] | None=None
    file_count: int | list[int] | None=None
    total_size: str | list[str] | None=None
    block_size: str | list[str] | None=None
    rw: Literal['read','write','randread','randwrite','rw','randrw'] | list[Literal['read','write','randread','randwrite','rw','randrw']]='write'
    rounds: int | list[int]=1
    iodepth: int | list[int]=1
    read_percent: int | list[int] | None=None

    mdtest_options: dict = Field(default_factory=dict)
    layout: Literal['unique','shared'] | list[Literal['unique','shared']]='unique'

    @field_validator('mdtest_options')
    @classmethod
    def option_values(cls, options):
        from .mdtest import BY_FLAG
        for key,value in options.items():
            if key not in BY_FLAG:raise ValueError('不支持的 mdtest 参数：'+key)
            values=value if isinstance(value,list) else [value]
            if not values or any(type(v) not in (str,int,bool) for v in values):raise ValueError('mdtest 参数需为非空的数字、布尔值或字符串候选值')
        return options

    def axes(self):
        axes={key:list(dict.fromkeys(value)) if isinstance(value,list) else [value]
              for key,value in self.model_dump().items() if key not in ('tool','mdtest_options')}
        if self.tool == 'mdtest':
            axes = {key: axes[key] for key in ('concurrency','file_count','rounds','layout')}
        else:
            axes.pop('layout')
        if self.tool=='mdtest':
            axes.update({'md:'+key:list(dict.fromkeys(value)) if isinstance(value,list) else [value] for key,value in self.mdtest_options.items()})
        if any(not values for values in axes.values()):raise ValueError('每个参数至少选择一个值')
        return axes

    def candidate_count(self):
        axes=self.axes()
        if self.tool == 'mdtest':return math.prod(len(values) for values in axes.values())
        modes=axes.pop('rw'); ratios=axes.pop('read_percent')
        return math.prod(len(values) for values in axes.values())*sum(len(ratios) if mode in ('rw','randrw') else 1 for mode in modes)

    def expand(self):
        axes=self.axes();ratios=axes.pop('read_percent',[None])
        seen=set()
        for values in product(*axes.values()):
            parameters=dict(zip(axes,values));parameters['tool']=self.tool
            if self.tool=='mdtest':
                parameters['mdtest_options']={key[3:]:parameters.pop(key) for key in list(parameters) if key.startswith('md:')}
            for ratio in ratios if parameters.get('rw') in ('rw','randrw') else [None]:
                parameters['read_percent']=ratio
                try:spec=TestSpec(**parameters)
                except ValueError as exc:
                    raise ValueError(f'{self.tool} 参数组合 {parameters} 无效：{exc}') from exc
                key=json.dumps(spec.model_dump(),sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    yield spec


class RunInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=120)
    machine_id: str=Field(min_length=1,max_length=36)
    target_kind: Literal['directory','mount']='directory'
    target_path: str=Field(min_length=2,max_length=1024)
    tests: list[ParameterMatrix]=Field(min_length=1,max_length=3)
    cleanup_data: bool=False
    timeout_minutes: int=Field(default=120,ge=1,le=1440)

    @field_validator('target_path')
    @classmethod
    def path(cls,value):
        p=PurePosixPath(value)
        if not p.is_absolute() or '..' in p.parts or value=='/' or any(c in value for c in '\n\r\x00:\\[],'):
            raise ValueError('请填写有效的绝对目录路径')
        if p.parts[1] in ('dev','proc','sys'):raise ValueError('不支持裸设备或系统虚拟目录')
        return str(p)

    _scenarios: list[dict]=PrivateAttr(default_factory=list)

    @property
    def scenarios(self):
        return self._scenarios

    @model_validator(mode='after')
    def unique_tools(self):
        if len({t.tool for t in self.tests})!=len(self.tests):raise ValueError('每种工具只能选择一次')
        if sum(t.candidate_count() for t in self.tests)>256:raise ValueError('每个任务最多256个候选参数组合，请减少参数值或拆分任务')
        specs=[spec for matrix in self.tests for spec in matrix.expand()]
        self._scenarios=[{'id':f'scene-{index:03d}-{spec.tool}','tool':spec.tool,'parameters':spec.model_dump()} for index,spec in enumerate(specs,1)]
        return self
