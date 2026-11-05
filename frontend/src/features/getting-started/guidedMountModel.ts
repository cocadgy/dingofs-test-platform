import type { ResourceMachine, Parameters } from '../resources/types';
import type { CacheOptions } from '../cache-profiles/types';
export type MountRow = {
  machineId: string; user: string; count: number; mountPath: string; subdir: string;
  cacheGroup: string; binaryDirectory: string; options: CacheOptions; logDirectory: string;
  profileId: string; profileRevision: number; rdma: boolean; rdmaDevice: string; rdmaPort: number;
};
export type MountDraft = { clusterId: string; fsName: string; source: 'default' | 'tag' | 'path'; tag: string; digest: string; rows: MountRow[] };
export const blankMountDraft = (): MountDraft => ({ clusterId: '', fsName: '', source: 'default', tag: '', digest: '', rows: [] });
export const newMountRow = (machine: ResourceMachine): MountRow => ({ machineId: machine.id, user: machine.ssh_user,
  count: 1, mountPath: '', subdir: '/', cacheGroup: '', binaryDirectory: '', options: {}, logDirectory: '',
  profileId: '', profileRevision: 0, rdma: false, rdmaDevice: '', rdmaPort: 1 });
export const mountPaths = (row: MountRow) => Array.from({ length: Number.isInteger(row.count) && row.count > 0 && row.count <= 1000 ? row.count : 0 },
  (_, i) => row.mountPath.replace(/\/$/, '') + (row.count > 1 ? '-' + String(i + 1).padStart(3, '0') : ''));
export function cloneMountSettings(source: MountRow, target: MountRow): MountRow {
  const options = { ...source.options };
  for (const key of ['cache_dir', 'log_dir', 'vfs_dummy_server_port', 'cache_rdma_device', 'cache_rdma_port_num']) delete options[key];
  return { ...target, options, subdir: source.subdir, cacheGroup: source.cacheGroup, rdma: source.rdma,
    profileId: '', profileRevision: 0, rdmaDevice: '', rdmaPort: 1 };
}
export function buildMountClients(draft: MountDraft): Parameters[] {
  if (!draft.fsName || draft.fsName.includes('DELETE')) throw new Error('请选择有效的文件系统');
  if (!draft.rows.length) throw new Error('请至少选择一台机器');
  if (draft.source === 'tag' && (!draft.tag || !/^sha256:[a-f0-9]{64}$/.test(draft.digest))) throw new Error('请从列表选择 TAG');
  const seen = new Set<string>();
  let total = 0;
  return draft.rows.map(row => {
    if (!row.user.trim() || !row.mountPath.startsWith('/') || row.mountPath === '/' || !row.subdir.startsWith('/')) throw new Error('请填写执行用户和有效的绝对路径');
    if (!Number.isInteger(row.count) || row.count < 1 || (total += row.count) > 1000) throw new Error('每批客户端总数量须为 1～1000');
    if (draft.source === 'path' && !row.binaryDirectory.startsWith('/')) throw new Error('请填写各机器的程序目录');
    if (row.rdma && !row.rdmaDevice) throw new Error('请选择 RDMA 设备');
    for (const path of mountPaths(row)) {
      const key = row.machineId + ':' + path;
      if (seen.has(key)) throw new Error('同一机器的挂载路径不能重复');
      seen.add(key);
    }
    return { machine_id: row.machineId, target_user: row.user.trim(), count: row.count, mount_path: row.mountPath,
      subdir: row.subdir, cache_group: row.cacheGroup, mount_options: row.options,
      log_directory: row.logDirectory,
      mount_profile_id: row.profileId, mount_profile_revision: row.profileRevision,
      binary_source: draft.source, binary_tag: draft.source === 'tag' ? draft.tag : '',
      binary_digest: draft.source === 'tag' ? draft.digest : '', binary_directory: draft.source === 'path' ? row.binaryDirectory : '',
      use_rdma: row.rdma, rdma_device: row.rdmaDevice, rdma_port: row.rdmaPort };
  });
}
