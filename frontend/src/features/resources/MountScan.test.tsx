import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MountScan } from "./MountScan";
import type { ResourceSnapshot, ResourceOperation } from "./types";

afterEach(cleanup);
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
