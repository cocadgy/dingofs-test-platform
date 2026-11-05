import { expect, test } from 'vitest';
import { filesystemOptions } from './filesystemOptions';
import type { ResourceOperation } from './types';

test('newest filesystems come first using creation time, not names or update time', () => {
  const operation = { result: { steps: [{ data: { result: { fs_infos: [
    { fs_name: 'a-old', create_time_s: 100, last_update_time_ns: 999999999999 },
    { fs_name: 'z-new', create_time_s: '300' },
    { fs_name: 'b-middle', create_time_s: 200 },
    { fs_name: 'a-unknown' },
    { fs_name: 'b-invalid', create_time_s: 'invalid' },
    { fs_name: 'DELETE-newest', create_time_s: 400 },
    { fs_name: 'a-middle', create_time_s: '200' },
  ] } } }] } } as unknown as ResourceOperation;
  expect(filesystemOptions(operation, 'newest').map(f => f.name)).toEqual([
    'z-new', 'a-middle', 'b-middle', 'a-old', 'a-unknown', 'b-invalid',
  ]);
  expect(filesystemOptions(operation).map(f => f.name)).toEqual([
    'a-middle', 'a-old', 'a-unknown', 'b-invalid', 'b-middle', 'z-new',
  ]);
});
