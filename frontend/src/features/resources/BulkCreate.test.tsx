import {fireEvent,render,screen} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import {ResourceFields} from './ResourceFields';
test.each(['cache.create','mount.create'])('%s exposes bounded batch quantity and explains generated targets', action=>{
  const change=vi.fn();
  render(<ResourceFields action={{action,label:'创建',section:action==='cache.create'?'cache':'mount',mutating:true,fields:[{key:'count',label:'数量',type:'number',default:1}]}}
    values={{count:1,mount_path:'/mnt/client'}} machines={[]} resources={[]} disabled={false} onChange={change}/>);
  const count=screen.getByRole('spinbutton');
  expect(count).toHaveValue(1);expect(count).toHaveAttribute('min','1');expect(count).not.toHaveAttribute('max');
  fireEvent.change(count,{target:{value:'100'}});expect(change).toHaveBeenCalledWith('count',100);
  expect(screen.getByText(/中途失败保留已完成实例/)).toBeInTheDocument();
  if(action==='mount.create') expect(screen.getByText(/\/mnt\/client-001/)).toBeInTheDocument();
});
