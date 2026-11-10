import { cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { GuidedMountFlow } from './GuidedMountFlow';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); sessionStorage.clear(); vi.resetAllMocks(); });
test('mount guide starts with cluster selection and cannot advance without filesystem', async () => {
  vi.mocked(api).mockImplementation(async (path) => path.startsWith('/clusters/overview') ? { items: [], total: 0 } as never : {} as never);
  render(<GuidedMountFlow admin userId="u" route="#/start/mount" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  expect(screen.getByRole('heading', { name: '挂载文件系统' })).toBeTruthy();
  expect((screen.getByRole('button', { name: '下一步' }) as HTMLButtonElement).disabled).toBe(true);
  await waitFor(() => expect(api).toHaveBeenCalled());
});
test('draft remains scoped to the current user', async () => {
  sessionStorage.setItem('guided-mount-draft-other', JSON.stringify({ clusterId: 'secret', rows: [] }));
  vi.mocked(api).mockResolvedValue({ items: [], total: 0 } as never);
  render(<GuidedMountFlow admin userId="u" route="#/start/mount" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  expect((screen.getByLabelText('目标集群') as HTMLSelectElement).value).toBe('');
  await waitFor(() => expect(sessionStorage.getItem('guided-mount-draft-u')).not.toBeNull());
});

test('returning from nested storage restores the filesystem details and draft', async () => {
  const cluster = { id: 'c', external_name: 'training', machine_name: 'machine', machine_address: '10.0.0.1', os_user: 'test', binding_state: 'verified', archived: false, revision: 1 };
  vi.mocked(api).mockImplementation(async path => {
    if (path.startsWith('/clusters/overview')) return { items: [cluster], total: 1 } as never;
    if (path === '/storage-profiles') return [] as never;
    if (path === '/clusters/c/resources') return { catalog: [], machines: [], resources: [], operations: [] } as never;
    throw new Error('unexpected API request ' + path);
  });
  const onNavigate = vi.fn();
  const props = { admin: true, userId: 'u', onNavigate, onDirty: vi.fn() };
  const view = render(<GuidedMountFlow {...props} route="#/start/mount/filesystem" />);
  fireEvent.change(await screen.findByLabelText('目标集群'), { target: { value: 'c' } });
  await waitFor(() => expect(screen.getByRole('button', { name: '下一步' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '下一步' }));
  fireEvent.change(screen.getByLabelText('文件系统名称'), { target: { value: 'nested-fs' } });
  fireEvent.change(screen.getByLabelText('时间后缀'), { target: { value: 'seconds' } });
  fireEvent.change(screen.getByLabelText('分区类型'), { target: { value: 'monolithic' } });
  fireEvent.click(screen.getByRole('button', { name: '添加存储配置' }));
  expect(onNavigate).toHaveBeenLastCalledWith('#/start/mount/filesystem/storage');
  expect(JSON.parse(sessionStorage.getItem('guided-filesystem-draft') || '{}')).toMatchObject({ clusterId: 'c', fsName: 'nested-fs', suffix: 'seconds', partition: 'monolithic' });
  view.rerender(<GuidedMountFlow {...props} route="#/start/mount/filesystem/storage" />);
  fireEvent.click(screen.getByRole('button', { name: '返回创建文件系统' }));
  expect(onNavigate).toHaveBeenLastCalledWith('#/start/mount/filesystem');
  view.rerender(<GuidedMountFlow {...props} route="#/start/mount/filesystem" />);
  expect(await screen.findByLabelText('文件系统名称')).toHaveValue('nested-fs');
  expect(screen.getByText('步骤 2 / 3')).toBeInTheDocument();
  expect(screen.getByLabelText('时间后缀')).toHaveValue('seconds');
  expect(screen.getByLabelText('分区类型')).toHaveValue('monolithic');
});

test('four-step guide submits checked clients and only retries the failed operation', async () => {
  const submitted: Record<string, unknown>[] = [];
  const onDirty = vi.fn();
  const machine = { id: 'm', name: 'machine', address: '10.0.0.1', ssh_user: 'test', can_manage: true, rdma: [] };
  const cluster = { id: 'c', external_name: 'training', machine_name: 'machine', machine_address: '10.0.0.1', os_user: 'test', binding_state: 'verified', archived: false, revision: 1 };
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path.startsWith('/clusters/overview')) return { items: [cluster], total: 1 } as never;
    if (path.endsWith('/resources')) return { catalog: [], resources: [], operations: [], machines: [machine], mount_profiles: [], mount_parameter_catalog: { fields: [] } } as never;
    if (method === 'POST') {
      const p = body as { action: string; parameters: Record<string, unknown> };
      submitted.push(p);
      if (p.action === 'fs.list') return { id: 'fs', action: p.action, state: 'succeeded', result: { steps: [{ data: { result: { fs_infos: [{ fs_name: 'train' }, { fs_name: 'old_DELETE_1' }] } } }] } } as never;
      if (p.action === 'cache.list') return { id: 'cache', action: p.action, state: 'succeeded', result: { steps: [{ data: { groups: { result: { group_names: [] } }, members: { result: { members: [] } } } }] } } as never;
      return { id: p.action === 'mount.plan' ? 'plan' : 'mount', action: p.action, state: p.action === 'mount.create' && !p.parameters.retry_operation_id ? 'failed' : 'succeeded' } as never;
    }
    throw new Error('unexpected API request ' + path);
  });
  render(<GuidedMountFlow admin userId="u" route="#/start/mount" onNavigate={vi.fn()} onDirty={onDirty} />);
  await screen.findByRole('option', { name: /training/ });
  fireEvent.change(screen.getByLabelText('目标集群'), { target: { value: 'c' } });
  await screen.findByRole('option', { name: 'train' });
  expect(screen.queryByRole('option', { name: 'old_DELETE_1' })).toBeNull();
  fireEvent.change(screen.getByLabelText('文件系统'), { target: { value: 'train' } });
  fireEvent.click(screen.getByRole('button', { name: '下一步' }));
  fireEvent.click(screen.getByRole('button', { name: '下一步' }));
  await waitFor(() => expect((screen.getByRole('checkbox', { name: /machine/ }) as HTMLInputElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('checkbox', { name: /machine/ }));
  fireEvent.change(screen.getByLabelText('挂载路径'), { target: { value: '/mnt/train' } });
  fireEvent.change(screen.getByLabelText('客户端数量'), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: '下一步' }));
  fireEvent.click(screen.getByRole('button', { name: '检查并挂载' }));
  await screen.findByRole('button', { name: '重试未成功客户端' });
  expect(onDirty).toHaveBeenLastCalledWith(true);
  expect(submitted.find(p => p.action === 'mount.plan')?.parameters).toMatchObject({ fs_name: 'train', clients: [{ machine_id: 'm', count: 2, mount_path: '/mnt/train' }] });
  expect(submitted.find(p => p.action === 'mount.create')?.parameters).toEqual({ plan_id: 'plan' });
  fireEvent.click(screen.getByRole('button', { name: '重试未成功客户端' }));
  await screen.findByRole('heading', { name: '挂载完成' });
  await waitFor(() => expect(onDirty).toHaveBeenLastCalledWith(false));
  expect(submitted.at(-1)?.parameters).toEqual({ retry_operation_id: 'mount' });
  fireEvent.click(screen.getByRole('button', { name: '返回配置' }));
  await waitFor(() => expect(onDirty).toHaveBeenLastCalledWith(true));
});
