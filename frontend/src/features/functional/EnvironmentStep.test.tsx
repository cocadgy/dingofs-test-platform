import {expect,test,vi} from 'vitest';
import {render,screen} from '@testing-library/react';
import {EnvironmentStep} from './EnvironmentStep';
import {PreflightStep} from './PreflightStep';
import type {Profile} from './types';

test('summary shows producer directory and binary arrays with labels and unknown values', () => {
  const profile = {id:'env',name:'fixture',source_kind:'predefined',enabled:true,validation:'valid',
    display:{descriptor:{env_name:'fixture',source_manifest:{},digest:'a',mds_addresses:[],targets:[],
      client_count:null,cache_count:0,storage_type:null,modules:{},issues:[],
      programs:{dingo:'/opt/dingo',mds_client:null,client_binaries:['/bin/client-a','[REDACTED]'],
        cache_binaries:['/bin/cache'],chaos_tool:''},
      directories:{mounts:['/mnt/a','/mnt/b'],client_cache:['/cache'],client_logs:[],remote_cache:['/remote']}}}
  } as unknown as Profile;
  render(<EnvironmentStep metadata={{enabled:true,clusters:[]}} profiles={[profile]} clusterId="" environmentId="env"
    onCluster={vi.fn()} onEnvironment={vi.fn()} onRefresh={vi.fn()}/>);
  for (const text of ['Dingo：/opt/dingo','MDS 客户端：未知','客户端二进制：/bin/client-a、[REDACTED]',
    '缓存二进制：/bin/cache','挂载目录：/mnt/a、/mnt/b','客户端缓存目录：/cache','客户端日志目录：未知','远端缓存目录：/remote']) {
    expect(screen.getByText(text)).toBeInTheDocument();
  }
});

test('preflight explains queue wait and deferred checks', () => {
  render(<PreflightStep configuration={{kind:'existing-environments',version:2,cluster_id:'c',default_environment_id:'e',
    module_plans:[],name:'test',retries:0,timeout_minutes:60}} profiles={[]} metadata={{enabled:true,clusters:[]}}
    compatibility={null} busy={false} onCheck={vi.fn()} onInstall={vi.fn()} onStart={vi.fn()}
    preflight={{can_start:true,token:'test',expires_at:null,checks:[{code:'resource_wait',ok:true,
      reason:'等待正在运行的功能测试释放资源；启动前重新预检'}],required_confirmations:[],impacts:[]}}/>);
  expect(screen.getByText(/等待正在运行的功能测试释放资源/)).toBeInTheDocument();
});
