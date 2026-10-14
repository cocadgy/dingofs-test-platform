"""Standalone remote supervisor. Operates only inside this task's directories."""
import html
import math
import statistics
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time


def atomic(path,value):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False))
    tmp.replace(path)


def stop_process(process, runtime, data_dir, output_dir):
    # docker run forwards TERM; also stop only containers mounted to this job.
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
    if runtime:
        found=subprocess.run([runtime,'ps','-q'],capture_output=True,text=True,timeout=15)
        for cid in found.stdout.split():
            info=subprocess.run([runtime,'inspect',cid],capture_output=True,text=True,timeout=15)
            if info.returncode:continue
            item=json.loads(info.stdout)[0]
            paths={m.get('Source') for m in item.get('Mounts',[])}
            if str(data_dir) in paths and str(output_dir) in paths:
                stopped=subprocess.run([runtime,'stop','-t','10',cid],capture_output=True,text=True,timeout=20)
                if stopped.returncode:raise RuntimeError('无法确认本任务容器已停止：'+cid)
    try:process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL)
        process.wait(timeout=5)


def relay_mdtest_log(output, log, offset):
    path=output/'mdtest-custom/mdtest.log'
    if path.is_file():
        with path.open('rb') as stream:
            stream.seek(offset)
            chunk=stream.read(65536)
            log.write(chunk)
            return offset+len(chunk)
    return offset


def summary_paths(output, tool):
    if tool=='mdtest' and (output/'mdtest-custom/summary.json').exists():return [output/'mdtest-custom/summary.json']
    pattern = 'ai-storage-*/summary.json' if tool == 'mdtest' else 'performance-'+tool+'-*/summary.json'
    return list(output.glob(pattern))


def mdtest_summary(raw, expected=None):
    if raw.get('format')=='mdtest-custom-v1':
        if expected and raw.get('parameters')!=expected:raise ValueError('mdtest 报告参数与请求不一致')
        return raw
    plan = raw.get('plan') or {}
    rounds = plan.get('repeats')
    if plan.get('tool') != 'mdtest' or type(rounds) is not int or not 1 <= rounds <= 100:
        raise ValueError('mdtest 报告计划无效')
    if expected and any(plan.get(key) != expected[field] for key, field in
                        [('repeats','rounds'),('workers','concurrency'),('file_count','file_count'),('layout','layout')]):
        raise ValueError('mdtest 报告参数与请求不一致')
    phases = ('create','stat','remove')
    results = {phase:{} for phase in phases}
    invalid = False
    for row in raw.get('results', []):
        phase, number, rate = row.get('phase'), row.get('round'), row.get('operations_per_second')
        if phase not in results or not row.get('success'):
            continue
        if type(number) is not int or not 1 <= number <= rounds or number in results[phase]:
            invalid = True
            continue
        if type(rate) not in (int,float) or not math.isfinite(rate) or rate <= 0:
            invalid = True
            continue
        results[phase][number] = rate
    complete_rounds = set.intersection(*(set(rows) for rows in results.values()))
    complete = not invalid and len(complete_rounds) == rounds and raw.get('status') == 'PASS'
    metrics = {phase+'_ops_s':{'mean':statistics.mean(values.values()) if values else None,
                             'samples':len(values)} for phase,values in results.items()}
    return {'status':'passed' if complete else 'failed',
            'error':raw.get('error') or ('' if complete else 'mdtest 阶段或轮次未完整完成'),
            'statistics':{'complete':complete,'requested_rounds':rounds,
                          'successful_rounds':len(complete_rounds),'metrics':metrics}}


def mdtest_html(report):
    rows = ''.join('<tr><td>'+html.escape(key)+'</td><td>'+str(value.get('mean'))+
                   '</td><td>'+str(value.get('samples'))+'</td></tr>'
                   for key,value in report['statistics']['metrics'].items())
    return ('<!doctype html><meta charset="utf-8"><title>mdtest 报告</title>'
            '<style>body{font:16px system-ui;max-width:960px;margin:40px auto;color:#243047}table{border-collapse:collapse;width:100%}td,th{padding:14px;border-bottom:1px solid #ddd;text-align:left}</style>'
            '<h1>mdtest 元数据性能报告</h1><p>'+html.escape(report['status'])+' · '+
            html.escape(str(report.get('error') or ''))+'</p><p>各阶段有效轮次均值，ops_s 为 ops/s，seconds 为秒。详细数据见 summary.json。</p>'
            '<table><tr><th>操作</th><th>平均值</th><th>有效轮次</th></tr>'+rows+'</table>')


def report_files(output,tool,budget=16*1024*1024,expected=None):
    paths=summary_paths(output,tool)
    if len(paths)!=1:return None,{}
    if paths[0].stat().st_size>4*1024*1024:raise ValueError('报告摘要超过4MiB，请查看远端文件')
    report=json.loads(paths[0].read_text())
    if not isinstance(report,dict):raise ValueError('报告摘要格式错误')
    if tool == 'mdtest':report=mdtest_summary(report,expected)
    # Keep live metadata compact; full round data remains in the JSON artifact.
    statistics=report.get('statistics') or {}
    metrics=statistics.get('metrics') or {}
    report={'status':report.get('status'),'error':str(report.get('error') or '')[:2000],
            'statistics':{key:statistics.get(key) for key in ('complete','requested_rounds','successful_rounds')}}
    report['statistics']['metrics']={key:{field:metrics.get(key,{}).get(field) for field in ('mean','samples')} for key in (tuple(metrics) if tool == 'mdtest' else ('bandwidth_mib_s','iops','latency_mean_us'))}
    artifacts={}
    total=0
    for path in sorted(paths[0].parent.iterdir(),key=lambda p:(p.name not in ('summary.json','index.html'),p.name)):
        if path.is_symlink() or not path.is_file():continue
        if path.suffix not in ('.html','.json','.log','.command','.fio'):continue
        size=path.stat().st_size
        if size>4*1024*1024 or total+size>16*1024*1024:continue
        content=path.read_text(errors='replace')
        wire_size=len(json.dumps(content,ensure_ascii=False).encode())
        if wire_size>budget:continue
        artifacts[path.name]=content
        budget-=wire_size
        total+=size
    if tool == 'mdtest' and 'index.html' not in artifacts:
        page=mdtest_html(report)
        if len(json.dumps(page,ensure_ascii=False).encode()) <= budget:artifacts['index.html']=page
    return report,artifacts


def prepare_target(path, kind):
    target=Path(path).resolve()
    if target==Path('/') or target.parts[1] in ('dev','proc','sys'):
        raise RuntimeError('测试目标必须是普通目录，不能是裸设备')
    if kind=='mount' and not os.path.ismount(target):
        raise RuntimeError('目标目录尚未挂载，已阻止测试落到本地磁盘')
    if not target.exists():
        try:
            target.mkdir(parents=True,exist_ok=True)
            print('已创建测试目录：'+str(target),flush=True)
        except PermissionError:
            # Only grant ownership of the new target, never its parents or contents.
            commands=[
                ['sudo','-n','mkdir','-p','--',str(target)],
                ['sudo','-n','chown',str(os.getuid())+':'+str(os.getgid()),'--',str(target)],
                ['sudo','-n','chmod','u+rwx','--',str(target)],
            ]
            for argv in commands:
                print('$ '+shlex.join(argv),flush=True)
                result=subprocess.run(argv,capture_output=True,text=True,timeout=30,stdin=subprocess.DEVNULL)
                if result.returncode:
                    raise RuntimeError('创建测试目录或授权失败：'+shlex.join(argv)+'：'+(result.stderr or result.stdout).strip())
    if not target.is_dir():
        raise RuntimeError('测试目标不是目录：'+str(target))
    if not os.access(target,os.W_OK|os.X_OK):
        raise RuntimeError('SSH用户没有目标目录写入权限：'+str(target))
    return target


def resolve_dtt():
    managed=Path.home()/'.local/share/dingofs-platform/tools/dtt/current/dtt'
    found=shutil.which('dtt')
    candidates=[managed]
    if found:candidates.append(Path(found).absolute())
    candidates.append(Path.home()/'.local/bin/dtt')
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate,os.X_OK):
            print('使用 dtt：'+str(candidate),flush=True)
            return candidate
    raise RuntimeError('未找到可执行 dtt：已检查平台托管目录、SSH用户 PATH 和 ~/.local/bin/dtt；请安装 dtt 或在机器详情部署测试工具')


def cleanup_task_data(directory, identity, timeout):
    # Validate identity in the deleting process; rmtree never follows child symlinks.
    code="""import os,shutil,stat,sys
path=sys.argv[1]
s=os.lstat(path)
if not stat.S_ISDIR(s.st_mode) or (s.st_dev,s.st_ino)!=(int(sys.argv[2]),int(sys.argv[3])):
    raise RuntimeError('测试数据目录身份已变化，拒绝清理')
if not shutil.rmtree.avoids_symlink_attacks:
    raise RuntimeError('当前系统不支持安全目录清理')
shutil.rmtree(path)
"""
    print('清理本任务数据目录：'+str(directory),flush=True)
    result=subprocess.run([sys.executable,'-c',code,str(directory),str(identity[0]),str(identity[1])],
                          capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=max(1,timeout))
    if result.returncode:raise RuntimeError('测试数据清理失败：'+(result.stderr or result.stdout).strip())
    print('本任务数据已清理；报告和日志已保留',flush=True)


def execute(root):
    request=json.loads((root/'request.json').read_text())
    state={'state':'running','phase':'检查工具和目标目录','progress':0,'reports':{},'error':'','pid':os.getpid()}
    started=time.monotonic()
    timeout=request['timeout_seconds']
    def save():
        state['elapsed_seconds']=round(time.monotonic()-started,2)
        state['scene_results']={key:{k:v for k,v in report.items() if k!='artifacts'} for key,report in state['reports'].items()}
        atomic(root/'state.json',{k:v for k,v in state.items() if k!='reports'})
    tests=request['tests']
    matrix=any(t.get('id','').startswith('scene-') for t in tests)
    for test in tests:
        scene=test.get('id',test['spec']['tool'])
        state['reports'][scene]={'tool':test['spec']['tool'],'parameters':test['spec'],'state':'pending','artifacts':{}}
    def save_reports():
        atomic(root/'reports.json',state['reports'])
    process=None
    scene=None
    artifact_budget=32*1024*1024
    runtime=shutil.which('docker') or shutil.which('podman')
    data_dir=output=None
    try:
        save()
        target=prepare_target(request['target_path'],request['target_kind'])
        required=sum(int(t['spec']['total_size']) for t in request['tests'])
        if shutil.disk_usage(target).free<required+16*1024*1024:raise RuntimeError('目标可用空间不足以保留所有工具的数据集')
        dtt=resolve_dtt()
        request['dtt_path']=str(dtt)
        atomic(root/'resolved.json',request)
        task_data=target/('platform-performance-'+request['id'])
        task_data.mkdir(exist_ok=False)
        created=task_data.stat()
        identity=(created.st_dev,created.st_ino)
        tests=request['tests']
        for index,test in enumerate(tests):
            if (root/'cancel').exists():
                state.update(state='cancelled',phase='已取消');break
            if time.monotonic()-started>=timeout:raise TimeoutError('性能测试超过设置的总超时')
            spec=test['spec'];tool=spec['tool']
            scene=test.get('id',tool)
            label=f'场景 {index+1}/{len(tests)} · {tool}'
            state['reports'][scene]['state']='running'
            if request['target_kind']=='mount' and not os.path.ismount(target):
                raise RuntimeError('挂载点已卸载，停止后续测试')
            data_dir=task_data/scene
            output=root/'output'/scene
            data_dir.mkdir(exist_ok=False)
            output.mkdir(parents=True,exist_ok=True)
            argv=[str(dtt)]+test['args']
            argv=[str(data_dir) if x=='__DATA__' else str(output) if x=='__OUTPUT__' else x for x in argv]
            env=os.environ.copy()
            if tool=='mdtest':
                custom=root/'custom'/scene;custom.mkdir(parents=True,exist_ok=True)
                (custom/'platform.mdtest').write_text(test['custom_script'])
                argv=[str(custom) if x=='__CUSTOM__' else x for x in argv]
                print('自定义 mdtest 场景：'+str(custom/'platform.mdtest')+'\n'+test['custom_script'].splitlines()[1],flush=True)
            state['reports'][scene].update(command=shlex.join(argv),remote_path=str(output))
            print(label+'\n$ '+shlex.join(argv),flush=True)
            state.update(phase=label+' · 执行测试',current_tool=tool,progress=int(100*index/len(tests)),data_dir=str(data_dir),output_dir=str(output))
            save()
            with (root/'console.log').open('ab',buffering=0) as log:
                process=subprocess.Popen(argv,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
                interrupted=False
                log_offset=0
                while process.poll() is None:
                    if request['target_kind']=='mount' and not os.path.ismount(target):
                        raise RuntimeError('运行期间挂载点已卸载，停止测试')
                    if tool=='mdtest':log_offset=relay_mdtest_log(output,log,log_offset)
                    cancelled=(root/'cancel').exists()
                    timed_out=time.monotonic()-started>=timeout
                    if cancelled or timed_out:
                        stop_process(process,runtime,data_dir,output)
                        state.update(state='cancelled' if cancelled else 'failed',phase='已取消' if cancelled else '超时',error='' if cancelled else '性能测试超过设置的总超时')
                        interrupted=True
                        break
                    try:
                        reports=summary_paths(output,tool)
                        if reports:
                            current=json.loads(reports[0].read_text())
                            done=(mdtest_summary(current)['statistics']['successful_rounds'] if tool == 'mdtest' else len(current.get('rounds',[])))
                            state['phase']=label+f' · 已完成 {done}/{spec["rounds"]} 轮'
                            state['progress']=min(99,int(100*(index+done/spec['rounds'])/len(tests)))
                    except (ValueError,OSError):pass
                    save()
                    time.sleep(.5)
                if tool=='mdtest':
                    while True:
                        next_offset=relay_mdtest_log(output,log,log_offset)
                        if next_offset==log_offset:break
                        log_offset=next_offset
            report_error=''
            try:report,artifacts=report_files(output,tool,artifact_budget,expected=spec)
            except (ValueError,OSError) as exc:
                report,artifacts=None,{}
                report_error='报告读取失败：'+str(exc)
            artifact_budget-=sum(len(json.dumps(value,ensure_ascii=False).encode()) for value in artifacts.values())
            rc=process.returncode
            process=None
            failed=bool(rc or not report or report.get('status')!='passed' or not report.get('statistics',{}).get('complete'))
            reason=report_error or (report or {}).get('error') or ('未生成完整有效报告' if not rc else 'dtt退出码 '+str(rc))
            state['reports'][scene].update(summary=report,artifacts=artifacts,
                state=state['state'] if interrupted else 'failed' if failed else 'success',
                error=state['error'] if interrupted else reason if failed else '')
            save_reports()
            if interrupted:break
            if failed:
                print('FAILED '+label+'：'+reason,flush=True)
                if not matrix:raise RuntimeError(tool+'：'+reason)
            state['progress']=int(100*(index+1)/len(tests))
            save()
        else:
            failures=sum(r['state']=='failed' for r in state['reports'].values())
            state.update(state='failed' if failures else 'success',phase='全部场景执行完成',progress=100,
                         error=f'{len(tests)} 个场景中 {failures} 个失败，请查看场景结果' if failures else '')
            if not failures and request.get('cleanup_data',False):
                state.update(state='running',phase='测试通过，正在清理本任务数据',progress=99)
                save()
                if (root/'cancel').exists():
                    state.update(state='cancelled',phase='已取消，保留测试数据')
                else:
                    if time.monotonic()-started>=timeout:raise TimeoutError('清理前已超过任务总超时，保留测试数据')
                    if request['target_kind']=='mount' and not os.path.ismount(target):
                        raise RuntimeError('挂载点已卸载，拒绝清理数据')
                    cleanup_task_data(task_data,identity,timeout-(time.monotonic()-started))
                    state.update(state='success',phase='全部场景通过，测试数据已清理',progress=100)
    except BaseException as exc:
        state.update(state='failed',phase='执行失败',error=str(exc))
        print('ERROR: '+str(exc),flush=True)
        if process is not None and data_dir is not None:
            try:stop_process(process,runtime,data_dir,output)
            except Exception as cleanup:
                state.update(state='unknown',error=str(exc)+'；停止确认失败：'+str(cleanup))
    finally:
        for result in state['reports'].values():
            if result['state']=='pending':result.update(state='skipped',error='任务已结束，此场景未执行')
            elif result['state']=='running':result.update(state=state['state'],error=state['error'])
        save_reports()
        save()


if __name__=='__main__':
    root=Path(sys.argv[1])
    with (root/'runner.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:sys.exit(0)
        if (root/'state.json').exists():
            previous=json.loads((root/'state.json').read_text())
            if previous.get('state') not in ('queued',):sys.exit(0)
        execute(root)
