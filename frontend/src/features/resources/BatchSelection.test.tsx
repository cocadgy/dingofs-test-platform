import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { BatchActions, useBatchSelection } from "./BatchSelection";
afterEach(cleanup);
function Harness({ids=["a","b"],busy=false,onAction=vi.fn()}: {ids?:string[];busy?:boolean;onAction?:ReturnType<typeof vi.fn>}) {
  const selection=useBatchSelection(ids,busy);
  return <><button onClick={()=>selection.toggle(ids)}>全选当前结果</button>
    <BatchActions picked={selection.picked} choices={[{key:"stop",label:"批量停止",eligible:id=>id==="a"}]}
      disabled={busy} onAction={onAction} onClear={selection.clear}/>
    {ids.map(id=><input key={id} type="checkbox" aria-label={id} checked={selection.checked([id])} onChange={()=>selection.toggle([id])}/>)}
  </>;
}
test("only selected eligible rows are submitted; deleted rows drop out",()=>{
  const execute=vi.fn();const view=render(<Harness onAction={execute}/>);
  fireEvent.click(screen.getByLabelText("a"));
  fireEvent.click(screen.getByRole("button",{name:"批量停止"}));
  expect(execute).toHaveBeenCalledWith("stop",["a"]);
  fireEvent.click(screen.getByLabelText("b"));
  expect(screen.getByRole("button",{name:"批量停止"})).toBeDisabled();
  view.rerender(<Harness ids={["b"]} onAction={execute}/>);
  expect(screen.getByText("已选择 1 项")).toBeVisible();
});
test("select all toggles current rows and starting execution clears selection",()=>{
  const view=render(<Harness/>);
  fireEvent.click(screen.getByText("全选当前结果"));
  expect(screen.getByText("已选择 2 项")).toBeVisible();
  fireEvent.click(screen.getByText("全选当前结果"));
  expect(screen.getByText("已选择 0 项")).toBeVisible();
  fireEvent.click(screen.getByLabelText("a"));
  view.rerender(<Harness busy/>);
  expect(screen.getByText("已选择 0 项")).toBeVisible();
});

import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
import type { Execute } from "./useResourceWorkspace";

test("client list sends one batch request with selected resource IDs",()=>{
  const execute=vi.fn<Execute>(async()=>{});
  render(<ResourceSectionForm section={sections[2]} group="挂载操作" onGroupChange={vi.fn()}
    snapshot={{catalog:[{action:"mount.unmount",label:"卸载文件系统",section:"mount",mutating:true,fields:[]}],
      machines:[],operations:[],resources:["a","b"].map(id=>({id,kind:"mount" as const,name:"/mnt/"+id,state:"mounted",created_at:"",data:{mount_path:"/mnt/"+id}}))}}
    disabled={false} execute={execute}/>);
  fireEvent.click(screen.getByLabelText("选择资源 /mnt/b"));
  fireEvent.click(screen.getByRole("button",{name:"批量卸载"}));
  expect(execute).toHaveBeenCalledTimes(1);
  expect(execute.mock.calls[0][0].action).toBe("mount.unmount");
  expect(execute.mock.calls[0][1]).toEqual({resource_ids:["b"]});
});
