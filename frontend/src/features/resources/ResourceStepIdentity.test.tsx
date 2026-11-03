import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { ResourceOperationView } from "./ResourceOperationView";
vi.mock("../../api/client", () => ({api:vi.fn()}));
afterEach(cleanup);
test("each step labels its own host name IP and execution user", () => {
  render(<ResourceOperationView label="创建缓存组" canManage={false} onChange={()=>{}} operation={{
    id:"op",action:"cache.create",state:"failed",machine_name:"127",target_user:"bob",
    result:{steps:[
      {machine_name:"126",machine_address:"172.30.14.126",target_user:"alice",returncode:0},
      {machine_name:"127",machine_address:"172.30.14.127",target_user:"bob",returncode:1},
      {returncode:1}
    ]}}} />);
  const steps=document.querySelectorAll(".resource-step");
  expect(within(steps[0] as HTMLElement).getByText("执行机器：126（172.30.14.126）")).toBeVisible();
  expect(within(steps[0] as HTMLElement).getByText("执行用户：alice")).toBeVisible();
  expect(within(steps[1] as HTMLElement).getByText("执行机器：127（172.30.14.127）")).toBeVisible();
  expect(within(steps[1] as HTMLElement).getByText("执行用户：bob")).toBeVisible();
  expect(within(steps[2] as HTMLElement).getByText("执行机器：未记录（IP 未记录）")).toBeVisible();
  expect(screen.getByText("执行用户：未记录")).toBeVisible();
});
