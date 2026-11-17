import {beforeEach,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../../api/client';
import {FunctionalWizard} from './FunctionalWizard';
vi.mock('../../api/client',()=>({api:vi.fn()}));
const options={digest:'a'.repeat(64),modules:{basic_file_operation:[{path:'smoke/a.yaml',name:'A'}]},clusters:[{id:'c1',name:'集群1',machine:'node',mds_addresses:['1.1.1.1:6900']}],machines:[{id:'m1',name:'机器1',address:'1.1.1.1',ssh_user:'jenkins'}],environments:[]};
beforeEach(()=>{vi.mocked(api).mockReset();vi.mocked(api).mockImplementation(async(path,method)=>{
 if(path==='/storage-profiles')return [{id:'s1',name:'测试存储',enabled:true}];
 if(path==='/functional/drafts'&&method==='POST')return {id:'d1',revision:1,name:'功能测试',step:1,configuration:{},state:'draft'};
 if(path==='/functional/drafts/d1'&&method==='PUT')return {id:'d1',revision:2,name:'功能测试',step:1,configuration:{cluster_id:'c1'},state:'draft'};
 if(path==='/machines/m1/tool-jobs')return [];
 return {};
});});
test('wizard advances by steps and saves a resumable draft without submitting a run',async()=>{
 render(<FunctionalWizard options={options} onBack={()=>{}} onStarted={()=>{}}/>);
 expect(screen.getByRole('heading',{name:'选择集群'})).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'下一步'}));
 expect(screen.getByRole('heading',{name:'执行机器'})).toBeVisible();
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(c=>c[0]==='/functional/drafts'&&c[1]==='POST')).toBe(true));
 expect(vi.mocked(api).mock.calls.some(c=>c[0]==='/functional/runs'&&c[1]==='POST')).toBe(false);
});

test('selects an installed dtt, completes the six steps, and submits exact wizard settings',async()=>{
 let revision=0;
 vi.mocked(api).mockImplementation(async(path,method,body)=>{
  if(path==='/storage-profiles')return [{id:'s1',name:'测试存储',enabled:true}];
  if(path==='/functional/drafts'&&method==='POST')return {id:'d1',revision:++revision,name:'draft',step:(body as any).step,configuration:(body as any).configuration,state:'draft'};
  if(path==='/functional/drafts/d1'&&method==='PUT')return {id:'d1',revision:++revision,name:'draft',step:(body as any).step,configuration:(body as any).configuration,state:'draft'};
  if(path==='/machines/m1/tool-jobs')return {id:'j1',state:'success',phase:'完成',result:{items:[{tool:'dtt',status:'ready'}]}};
  if(path==='/functional/runs'&&method==='POST')return {id:'run1'};
  return {};
 });
 const started=vi.fn();render(<FunctionalWizard options={options} onBack={()=>{}} onStarted={started}/>);
 fireEvent.click(screen.getByRole('button',{name:'下一步'}));
 await screen.findByRole('heading',{name:'执行机器'});
 fireEvent.change(screen.getByRole('combobox',{name:'测试机'}),{target:{value:'m1'}});
 fireEvent.click(screen.getByRole('button',{name:'检查 SSH 与 dtt'}));
 await waitFor(()=>expect(screen.getByText(/dtt：ready/)).toBeVisible());
 fireEvent.click(screen.getByRole('button',{name:'下一步'}));
 await screen.findByRole('heading',{name:'二进制与目录'});
 fireEvent.click(screen.getByRole('button',{name:'下一步'}));
 await screen.findByRole('heading',{name:'客户端与缓存参数'});
 fireEvent.click(screen.getByRole('button',{name:'下一步'}));
 await screen.findByRole('heading',{name:'文件系统'});
 fireEvent.change(screen.getByRole('combobox',{name:'存储配置'}),{target:{value:'s1'}});
 fireEvent.click(screen.getByRole('button',{name:'下一步'}));
 await screen.findByRole('heading',{name:'确认并启动'});
 fireEvent.click(screen.getByRole('checkbox',{name:'选择 basic_file_operation 全部用例'}));
 fireEvent.click(screen.getByRole('button',{name:'开始测试'}));
 await waitFor(()=>expect(started).toHaveBeenCalledWith('run1'));
 const call=vi.mocked(api).mock.calls.find(c=>c[0]==='/functional/runs'&&c[1]==='POST');
 expect(call?.[2]).toMatchObject({cluster_id:'c1',wizard:{machine_id:'m1',storage_profile_id:'s1',fs_mode:'auto'},selected:{basic_file_operation:['smoke/a.yaml']},draft_id:'d1'});
});
