import { expect, test } from "vitest";
import { blankCacheDraft, newCacheRow, cacheMembers, cloneCacheSettings, loadMachineTemplate, migrateCacheDraft } from "./guidedCacheModel";
import type { CacheProfile } from "../cache-profiles/types";
const machine = { id:"a", name:"A", address:"10.0.0.1", ssh_user:"alice", can_manage:true, rdma:[{device:"mlx5_0",port:1}] };
const target = { ...machine, id:"b", name:"B", address:"10.0.0.2", ssh_user:"bob", rdma:[] };
const template = { id:"p", name:"模板", enabled:true, description:"", creator_id:"u", source_version:"test", can_manage:true, updated_at:"", revision:2, parameters:{shards:"8", cache_expire_s:"300", cache_size_mb:"2048", group_weight:"70"} } as CacheProfile;
test("template detach keeps current values and other machines remain independent", () => {
  const initial = newCacheRow(machine);
  const loaded = loadMachineTemplate(initial, template);
  const edited = {...loaded, options:{...loaded.options, shards:"9"}};
  const detached = loadMachineTemplate(edited);
  expect(detached.options).toEqual(edited.options);
  expect(detached.profileId).toBe("");
  expect(detached.capacity).toBe(2048);
  expect(initial.options).not.toEqual(edited.options);
});
test("new machines copy cache settings but not identity/user/program path or invalid RDMA", () => {
  const first = {...newCacheRow(machine), directory:"/cache", capacity:4096, weight:60, binaryDirectory:"/alice/bin",
    options:{shards:"3"}, rdma:true, rdmaDevice:"mlx5_0",rdmaPort:1};
  const second = cloneCacheSettings(first, newCacheRow(target), target);
  expect(second).toMatchObject({machineId:"b",user:"bob",listenIp:"10.0.0.2",binaryDirectory:"",capacity:4096,weight:60,directory:"/cache",rdma:true,rdmaDevice:""});
  first.options.shards="7";
  expect(second.options?.shards).toBe("3");
});
test("per-machine options and binary paths survive node expansion", () => {
  const first = {...newCacheRow(machine),directory:"/cache",binaryDirectory:"/a/bin",count:2,options:{shards:"2"}};
  const second = {...newCacheRow(target),directory:"/cache",binaryDirectory:"/b/bin",options:{shards:"8"}};
  const rows = cacheMembers({...blankCacheDraft(), source:"path",rows:[first,second]});
  expect(rows.map(r=>r.cache_options)).toEqual([{shards:"2"},{shards:"2"},{shards:"8"}]);
  expect(rows.map(r=>r.binary_directory)).toEqual(["/a/bin","/a/bin","/b/bin"]);
});
test("legacy global template and path migrate only once", () => {
  const legacy = {...blankCacheDraft(),profileId:"p",source:"path" as const,binaryDirectory:"/old/bin",rows:[{...newCacheRow(machine),directory:"/cache"}]};
  const migrated = migrateCacheDraft(legacy,[template]);
  expect(migrated.rows[0]).toMatchObject({options:{shards:"8"},binaryDirectory:"/old/bin",profileId:"p",profileRevision:2});
  const changed = {...migrated,rows:[{...migrated.rows[0],options:{shards:"12"}}]};
  expect(migrateCacheDraft(changed,[template]).rows[0].options).toEqual({shards:"12"});
});

test("template node identity cannot leak into per-machine parameter expansion", () => {
  const row = loadMachineTemplate({...newCacheRow(machine),directory:"/cache"}, {...template,parameters:{...template.parameters,id:"fixed-id"}});
  expect(cacheMembers({...blankCacheDraft(),rows:[{...row,count:2}]}).map(r=>r.cache_options)).toEqual([
    expect.not.objectContaining({id:"fixed-id"}), expect.not.objectContaining({id:"fixed-id"})
  ]);
});
