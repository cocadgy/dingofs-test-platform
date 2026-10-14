"""mdtest option contract, based on the bundled mdtest 4.1.0+dev -h.

All argv are constructed as tokens. Paths remain relative to the owned task
folder; -i and MPI size are represented by the existing matrix controls.
"""
import json
import shlex
from pathlib import Path, PurePosixPath


def option(flag, label, group, kind='bool', default=False, **kwargs):
    return dict(flag=flag,label=label,group=group,kind=kind,default=default,**kwargs)


OPTIONS = [
    option('-C','仅执行创建（可与其他阶段组合）','测试阶段'),
    option('-T','执行 stat 查询','测试阶段'),
    option('-E','执行读取','测试阶段'),
    option('-r','执行删除','测试阶段'),
    option('-U','增加目录重命名阶段','测试阶段'),
    option('-F','仅测试文件','测试阶段',default=True),
    option('-D','仅测试目录','测试阶段'),
    option('-n','每进程文件/目录数量（覆盖文件总数量）','目录与规模','int',0,min=1),
    option('-I','每目录条目数（替代 -n）','目录与规模','int',0,min=1),
    option('-z','目录树深度','目录与规模','int',0,min=0,max=64),
    option('-b','目录树分支数','目录与规模','int',1,min=1),
    option('-L','仅在叶子目录创建文件','目录与规模'),
    option('-d','任务目录下的相对路径，多路径用 @ 分隔','目录与规模','path','.'),
    option('-S','共享文件访问（仅文件）','目录与规模'),
    option('-c','由进程 0 统一创建','目录与规模'),
    option('-t','计入独立工作目录的开销','目录与规模'),
    option('-w','每文件写入字节数','文件读写','int',0,min=0,bytes=True),
    option('-e','每文件读取字节数','文件读写','int',0,min=0,bytes=True),
    option('-k','使用 mknod 创建文件','文件读写'),
    option('-R','随机 stat 顺序','文件读写'),
    option('--random-seed','随机种子','文件读写','int',0,min=0),
    option('-X','读取时校验数据（--verify-read）','文件读写'),
    option('--verify-write','写入后读回校验','文件读写'),
    option('-y','每文件写入后 sync','文件读写'),
    option('-Y','每阶段后调用系统 sync（计入时间）','文件读写'),
    option('-G','缓冲区数据偏移；-1 表示随机','文件读写','int',-1,min=-1),
    option('--dataPacketType','数据模式','文件读写','choice','t',choices=['offset','incompressible','timestamp','random','o','i','t','r']),
    option('-B','阶段之间不使用 barrier（0/1）','运行控制','choice','0',choices=['0','1']),
    option('-f','任务数扫描起点','运行控制','int',1,min=1),
    option('-l','任务数扫描终点；0 为 MPI 进程数','运行控制','int',0,min=0),
    option('-s','任务数扫描步长','运行控制','int',1,min=1),
    option('-N','操作进程偏移步长；0 为本地','运行控制','int',0,min=0),
    option('-p','每轮开始前等待秒数','运行控制','int',0,min=0),
    option('-W','创建文件的 stonewall 秒数','运行控制','int',0,min=0),
    option('-x','stonewall 状态文件（任务内相对路径）','运行控制','path','stonewall.status'),
    option('-P','同时打印速率和耗时','报告与调试'),
    option('-Z','仅打印耗时而非速率','报告与调试'),
    option('-V','详细输出级别','报告与调试','int',0,min=0),
    option('-v','追加详细输出次数（重复 -v）','报告与调试','int',0,min=0,max=10),
    option('--print-all-procs','所有进程打印摘要','报告与调试'),
    option('--warningAsErrors','将警告视为错误','报告与调试'),
    option('--showRankStatistics','显示每个 rank 的统计','报告与调试'),
    option('--saveRankPerformanceDetails','rank 性能 CSV（任务内相对路径）','报告与调试','path','rank.csv'),
    option('--savePerOpDataCSV','每操作 CSV 文件前缀（任务内相对路径）','报告与调试','path','operation'),
    option('--run-cmd-before-phase','阶段前执行命令（不计时；在测试容器中执行）','高级命令','text',''),
    option('--run-cmd-after-phase','阶段后执行命令（计时；在测试容器中执行）','高级命令','text',''),
    option('-a','I/O API（当前 mdtest 支持 POSIX、DUMMY）','I/O 模块','choice','POSIX',choices=['POSIX','DUMMY']),
    option('--posix.odirect','POSIX Direct I/O（读写大小需要对齐）','I/O 模块'),
    option('--posix.rangelocks','POSIX 范围锁','I/O 模块'),
    option('--dummy.delay-only-rank0','DUMMY 仅 rank 0 延时','I/O 模块'),
    *[option('--dummy.delay-'+x,'DUMMY '+x+' 延时（微秒）','I/O 模块','int',0,min=0) for x in ('create','close','sync','xfer')],
    *[option('--mpiio.'+x,'MPIIO '+x+'（当前 API 未启用，仅保留原生选项）','其他模块') for x in ('showHints','preallocate','useStridedDatatype','useFileView')],
    option('--mpiio.hintsFileName','MPIIO hints 文件（任务内相对路径）','其他模块','path','hints'),
    option('--mmap.madv_dont_need','MMAP MADV_DONTNEED（当前 API 未启用）','其他模块'),
    option('--mmap.madv_pattern','MMAP madvise 模式（当前 API 未启用）','其他模块'),
]
BY_FLAG={x['flag']:x for x in OPTIONS}


def validate_options(values):
    for flag,value in values.items():
        if flag not in BY_FLAG:raise ValueError('不支持的 mdtest 参数：'+flag)
        meta=BY_FLAG[flag];kind=meta['kind']
        if kind=='bool' and type(value) is not bool:raise ValueError(flag+' 必须为布尔值')
        if kind=='int' and (type(value) is not int or not meta.get('min',0)<=value<=meta.get('max',2**63-1)):
            raise ValueError(flag+' 数值超出范围')
        if kind in ('choice','path','text'):
            if not isinstance(value,str) or '\x00' in value or '\n' in value or '\r' in value or len(value)>4096:
                raise ValueError(flag+' 字符串无效')
            if kind=='choice' and value not in meta['choices']:raise ValueError(flag+' 选项无效')
            if kind=='path':
                for item in value.split('@') if flag=='-d' else [value]:
                    p=PurePosixPath(item)
                    if not item or p.is_absolute() or '..' in p.parts:raise ValueError(flag+' 必须是任务目录内的相对路径')
    if values.get('-D') and values.get('-F',True):raise ValueError('-D 与 -F 不可同时启用；目录测试请关闭仅测试文件')
    if values.get('-I') and values.get('-n'):raise ValueError('-I 与 -n 不能同时设置')


def command_for(spec):
    options=dict(spec.mdtest_options)
    options.setdefault('-F',not options.get('-D',False))
    if not options.get('-n') and not options.get('-I'):options['-n']=spec.file_count//spec.concurrency
    options.setdefault('-d','.')
    args=['mpirun','--allow-run-as-root','--host',f'localhost:{spec.concurrency}',
          '-np',str(spec.concurrency),'mdtest','-i',str(spec.rounds)]
    if spec.layout=='unique':args+=['-u']
    for flag,value in options.items():
        if flag=='-v':args+=['-v']*value
        elif isinstance(value,bool):
            if value:args.append(flag)
        else:args.extend([flag,str(value)])
    return args


def custom_script(spec):
    # Quoted Python data, not shell interpolation of user values.
    source=Path(__file__).with_name('mdtest_runtime.py').read_text()
    args=command_for(spec)
    return '#!/usr/bin/env bash\n# '+shlex.join(args)+'\npython3 -u - <<\'PLATFORM_MDTEST_PY\'\n'+source+'\nexecute('+repr(args)+','+repr(spec.model_dump())+')\nPLATFORM_MDTEST_PY\n'
