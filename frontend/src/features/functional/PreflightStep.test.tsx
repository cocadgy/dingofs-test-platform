import {render, screen} from '@testing-library/react';
import {expect, test, vi} from 'vitest';
import {PreflightStep} from './PreflightStep';

test('shows skipped checks and attributes failures to environment and module', () => {
  render(<PreflightStep
    configuration={{kind:'existing-environments',version:2,cluster_id:'c',default_environment_id:'',module_plans:[],name:'test',retries:0,timeout_minutes:10}}
    profiles={[]} metadata={{enabled:true,clusters:[]}} compatibility={null} busy={false}
    onCheck={vi.fn()} onInstall={vi.fn()} onStart={vi.fn()}
    preflight={{can_start:false,token:null,expires_at:null,required_confirmations:[],impacts:[],checks:[
      {code:'pidfd',ok:true,status:'skipped',env_name:'env_no_cache',modules:['basic_file_operation'],reason:'无缓存进程'},
      {code:'directories',ok:false,env_name:'env_quota',modules:['quota'],host:'172.30.14.126',user:'jenkins',reason:'目录不存在：/cache/data'},
    ]} as any} />);
  expect(screen.getByText(/跳过.*pidfd/)).toBeVisible();
  expect(screen.getByText(/env_no_cache/)).toBeVisible();
  expect(screen.getByText(/env_quota/)).toHaveTextContent('/cache/data');
  expect(screen.getByRole('button',{name:'开始测试'})).toBeDisabled();
});
