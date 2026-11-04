import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MountScan } from "./MountScan";
import type { ResourceSnapshot, ResourceOperation, ResourceAction } from "./types";

afterEach(cleanup);

test("selects residual mounts in one batch and excludes already unmounted rows", () => {
  const execute = vi.fn();
  const action: ResourceAction = {action:"mount.unmount",label:"卸载",section:"mount",mutating:true,fields:[]};
  const op: ResourceOperation = {...result,state:"succeeded",result:{steps:[{
    machine_id:"m1",machine_name:"129",machine_address:"172.30.14.129",data:{mounts:["42","43","44"].map(id => ({
      mount_id:id,mount_path:`/mnt/${id}`,fs_name:"demo",pid:null,client_user:null,
      mds_addresses:[],cluster_match:"unknown",reason:"已退出",cleanup_allowed:true,
    }))},
  }]}};
  const done:ResourceOperation={id:"done",cluster_id:"c1",action:"mount.unmount",state:"succeeded",
    payload:{scan_operation_id:"scan",machine_id:"m1",mount_id:"42"}};
  const {rerender} = render(<MountScan clusterId="c1" snapshot={{...snapshot,catalog:[...snapshot.catalog,action]}}
    operations={[done,op]} execute={execute} disabled={false} />);
  expect(screen.getByRole("button",{name:"批量卸载残留挂载"})).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox",{name:"全选可卸载的残留挂载"}));
  expect(screen.getByText("已选择 2 项")).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"批量卸载残留挂载"}));
  expect(execute).toHaveBeenCalledWith(expect.objectContaining({action:"mount.unmount"}),
    {scan_operation_id:"scan",targets:[{machine_id:"m1",mount_id:"43"},{machine_id:"m1",mount_id:"44"}]});
  const partial:ResourceOperation = {id:"batch",cluster_id:"c1",action:"mount.unmount",state:"failed",
    payload:{scan_operation_id:"scan",targets:[{machine_id:"m1",mount_id:"43"},{machine_id:"m1",mount_id:"44"}]},
    result:{steps:[{machine_id:"m1",mount_id:"43",failed:false},{machine_id:"m1",mount_id:"44",failed:true}]}};
  rerender(<MountScan clusterId="c1" snapshot={{...snapshot,catalog:[...snapshot.catalog,action]}}
    operations={[partial,done,op]} execute={execute} disabled={false} />);
  expect(screen.getByRole("checkbox",{name:"选择 129 /mnt/43"})).toBeDisabled();
  expect(screen.getByRole("checkbox",{name:"选择 129 /mnt/44"})).toBeEnabled();
  expect(screen.getByText("已选择 1 项")).toBeVisible();
  rerender(<MountScan clusterId="c1" snapshot={{...snapshot,catalog:[...snapshot.catalog,action]}}
    operations={[{...op,id:"new-scan"},partial,done]} execute={execute} disabled={false} />);
  expect(screen.getByText("已选择 0 项")).toBeVisible();
});

test("offers residual unmount by saved scan identity, not a caller supplied path", () => {
  const execute = vi.fn();
  const action: ResourceAction = {action:"mount.unmount",label:"卸载文件系统",section:"mount",mutating:true,fields:[]};
  const op: ResourceOperation = {...result, state:"succeeded", result:{steps:[{
    machine_id:"m1", machine_name:"129", machine_address:"172.30.14.129", data:{mounts:[{
      mount_id:"42",mount_path:"/mnt/dead",fs_name:"demo",pid:null,client_user:null,
      mds_addresses:[],cluster_match:"unknown",reason:"客户端已退出",cleanup_allowed:true,
    }]},
  }]}};
  render(<MountScan clusterId="c1" snapshot={{...snapshot,catalog:[...snapshot.catalog,action]}}
    operations={[op]} execute={execute} disabled={false} />);
  fireEvent.click(screen.getByRole("button",{name:"卸载残留挂载"}));
  expect(execute).toHaveBeenCalledWith(expect.objectContaining({label:expect.stringContaining("/mnt/dead")}),
    {scan_operation_id:"scan",machine_id:"m1",mount_id:"42"});
});
const snapshot: ResourceSnapshot = {
  catalog: [{action:"mount.scan", label:"扫描已有挂载", section:"mount", mutating:false, fields:[]}],
  resources:[], operations:[], machines:[
    {id:"m1",name:"129",address:"172.30.14.129",ssh_user:"jenkins",can_manage:true,has_ssh_password:true},
    {id:"m2",name:"127",address:"172.30.14.127",ssh_user:"jenkins",can_manage:true,has_ssh_password:true},
    {id:"m3",name:"禁止",address:"other",ssh_user:"test",can_manage:false,has_ssh_password:true},
  ],
};
const result: ResourceOperation = {id:"scan",cluster_id:"c1",action:"mount.scan",state:"failed",result:{steps:[
  {machine_name:"129",machine_address:"172.30.14.129",target_user:"root",data:{scanned_at:"2026-11-04T01:02:03Z",mounts:[
    {mount_id:"42",mount_path:"/mnt/demo",fs_name:"demo",pid:123,client_user:"jenkins",mds_addresses:["172.30.14.129:16900"],cluster_match:"current",reason:"MDS 地址集合一致",saved_resource_id:null},
  ]}},
  {machine_name:"127",machine_address:"172.30.14.127",target_user:"root",failed:true,message:"connect_failed"},
]}};

test("selects multiple machines and submits a read-only scan", () => {
  const execute=vi.fn();
  render(<MountScan clusterId="c1" snapshot={snapshot} operations={[]} execute={execute} disabled={false} />);
  const button=screen.getByRole("button",{name:"扫描已有挂载"});
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/129（172.30.14.129）/));
  fireEvent.click(screen.getByLabelText(/127（172.30.14.127）/));
  fireEvent.click(button);
  expect(execute).toHaveBeenCalledWith(snapshot.catalog[0],{machine_ids:["m1","m2"]});
  expect(screen.queryByLabelText(/禁止/)).not.toBeInTheDocument();
});

test("shows identity, results and machine failures without offering lifecycle actions", () => {
  render(<MountScan clusterId="c1" snapshot={snapshot} operations={[result]} execute={vi.fn()} disabled={false} />);
  expect(screen.getByText("/mnt/demo")).toBeVisible();
  expect(screen.getByText("当前集群")).toBeVisible();
  expect(screen.getAllByText(/扫描用户：root/)).toHaveLength(2);
  expect(screen.getByText("connect_failed")).toBeVisible();
  expect(screen.getByText("未保存（请查看归属原因）")).toBeVisible();
  expect(screen.queryByRole("button",{name:/卸载|纳管|重挂载/})).not.toBeInTheDocument();
});

test("does not display a different cluster's result", () => {
  render(<MountScan clusterId="c2" snapshot={snapshot} operations={[result]} execute={vi.fn()} disabled={false} />);
  expect(screen.queryByText("/mnt/demo")).not.toBeInTheDocument();
});

test("empty successful scan differs from failed scan and readonly disables submission", () => {
  const op:ResourceOperation={...result,state:"succeeded",result:{steps:[{data:{mounts:[],scanned_at:"now"}}]}};
  render(<MountScan clusterId="c1" snapshot={snapshot} operations={[op]} execute={vi.fn()} disabled />);
  expect(screen.getByText(/未发现 DingoFS 挂载/)).toBeVisible();
  expect(screen.getByRole("button",{name:"扫描已有挂载"})).toBeDisabled();
});
