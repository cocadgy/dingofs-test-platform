"""Standalone adapter embedded in the task's custom .mdtest script."""
import html
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys


def parse_output(text):
    tables=[]
    task_count=None
    for line in text.splitlines():
        match=re.search(r'^\s*(\d+)\s+tasks?[, ]',line,re.I)
        if match:task_count=int(match[1])
        header=re.search(r'SUMMARY\s+(rate|time).*?\(of\s+(\d+)\s+iterations?\)',line,re.I)
        if header:
            tables.append(dict(unit='ops/s' if header[1].lower()=='rate' else 's',rounds=int(header[2]),tasks=task_count,rows=[]))
            continue
        match=re.fullmatch(r'\s*((?:File|Directory|Tree)\s+[\w ]+?)\s*:?\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s*',line)
        if tables and match:
            values=[float(match[i]) for i in range(2,6)]
            if not all(math.isfinite(v) and v>=0 for v in values):raise ValueError('mdtest 报告含无效指标')
            tables[-1]['rows'].append(dict(operation=match[1],max=values[0],min=values[1],mean=values[2],stddev=values[3]))
    return tables


def summarize(tables, spec, rc):
    complete=rc==0 and bool(tables) and all(t['rounds']==spec['rounds'] and t['rows'] for t in tables)
    metrics={}
    # Never average measurements from distinct task counts together.
    for unit in ('ops/s','s'):
        subset=[t for t in tables if t['unit']==unit]
        if len(subset)!=1:continue
        for row in subset[0]['rows']:
            phases={'creation':'-C','stat':'-T','read':'-E','removal':'-r','rename':'-U'}
            selected={k for k in ('-C','-T','-E','-r','-U') if spec.get('mdtest_options',{}).get(k)}
            phase=phases.get(row['operation'].split()[-1])
            if selected and phase not in selected:continue
            if row['max']==0 and unit=='ops/s':continue
            key=row['operation'].lower().replace(' ','_')
            key={'file_creation':'create','file_stat':'stat','file_removal':'remove'}.get(key,key)
            metrics[key+('_ops_s' if unit=='ops/s' else '_seconds')]={'mean':row['mean'],'samples':spec['rounds']}
    return dict(format='mdtest-custom-v1',parameters=spec,status='passed' if complete else 'failed',
                error='' if complete else f'mdtest 退出码 {rc}，或原生报告不完整；请查看 mdtest.log',tables=tables,
                statistics=dict(complete=complete,requested_rounds=spec['rounds'],successful_rounds=spec['rounds'] if complete else 0,metrics=metrics))


def execute(argv,spec):
    report_dir=Path('/output/mdtest-custom');report_dir.mkdir(parents=True,exist_ok=True)
    (report_dir/'mdtest.command').write_text(shlex.join(argv)+'\n')
    print('$ '+shlex.join(argv),flush=True)
    with (report_dir/'mdtest.log').open('w') as log:
        process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',bufsize=1)
        for line in process.stdout:
            log.write(line);log.flush();print(line,end='',flush=True)
        rc=process.wait()
    try:report=summarize(parse_output((report_dir/'mdtest.log').read_text()),spec,rc)
    except ValueError as exc:
        report=summarize([],spec,rc or 1);report['error']=str(exc)
    (report_dir/'summary.json').write_text(json.dumps(report,ensure_ascii=False,allow_nan=False))
    body='<h1>mdtest 自定义测试</h1><pre>'+html.escape(shlex.join(argv))+'</pre>'
    for table in report['tables']:
        body+=f'<h2>MPI {table["tasks"] or spec["concurrency"]} · {table["unit"]} · {table["rounds"]} 轮</h2><table><tr><th>操作</th><th>最大</th><th>最小</th><th>平均</th><th>标准差</th></tr>'
        for row in table['rows']:
            body+='<tr>'+''.join('<td>'+html.escape(str(row[k]))+'</td>' for k in ('operation','max','min','mean','stddev'))+'</tr>'
        body+='</table>'
    (report_dir/'index.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:16px system-ui;margin:40px}table{border-collapse:collapse}td,th{padding:12px;border:1px solid #ddd}pre{white-space:pre-wrap}</style>'+body)
    sys.exit(0 if report['status']=='passed' else rc or 1)
