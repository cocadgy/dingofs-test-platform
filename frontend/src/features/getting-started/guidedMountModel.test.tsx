import { expect, test } from 'vitest';
import { blankMountDraft, newMountRow, cloneMountSettings, buildMountClients, mountPaths } from './guidedMountModel';
const machine = { id: 'm1', name: 'one', address: '10.0.0.1', ssh_user: 'test', can_manage: true };
test('client paths and defaults match server expansion', () => {
  const row = { ...newMountRow(machine), mountPath: '/mnt/train', count: 2 };
  expect(row.subdir).toBe('/');
  expect(mountPaths(row)).toEqual(['/mnt/train-001', '/mnt/train-002']);
  const draft = { ...blankMountDraft(), clusterId: 'c', fsName: 'train', rows: [row] };
  expect(buildMountClients(draft)[0]).toMatchObject({ machine_id: 'm1', target_user: 'test', count: 2, mount_path: '/mnt/train', subdir: '/' });
});
test('new machine inherits options but not identity paths or RDMA device', () => {
  const source = { ...newMountRow(machine), mountPath: '/mnt/old', binaryDirectory: '/opt/old', options: { cache_dir: '/mnt/cache', log_level: 'INFO' }, rdma: true, rdmaDevice: 'mlx5_0' };
  const target = newMountRow({ ...machine, id: 'm2', ssh_user: 'other' });
  const copied = cloneMountSettings(source, target);
  expect(copied).toMatchObject({ machineId: 'm2', user: 'other', mountPath: '', binaryDirectory: '', rdmaDevice: '' });
  expect(copied.options).toEqual({ log_level: 'INFO' });
});
test('reject duplicate targets and invalid TAG source', () => {
  const row = { ...newMountRow(machine), mountPath: '/mnt/train' };
  expect(() => buildMountClients({ ...blankMountDraft(), fsName: 'train', rows: [row, row] })).toThrow(/重复/);
  expect(() => buildMountClients({ ...blankMountDraft(), fsName: 'train', source: 'tag', rows: [row] })).toThrow(/TAG/);
});
