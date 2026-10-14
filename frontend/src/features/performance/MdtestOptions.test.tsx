import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe,it,expect } from "vitest";
import { MdtestOptions } from "./MdtestOptions";
import { defaults,matrixParameters,estimatedCount } from "./matrix";
function Form(){const [v,set]=useState("{}");return <><MdtestOptions value={v} onChange={set} catalog={[
 {flag:"-D",label:"仅目录",kind:"bool",group:"测试阶段",default:false},
 {flag:"-F",label:"仅文件",kind:"bool",group:"测试阶段",default:true},
 {flag:"-w",label:"写入字节",kind:"int",group:"测试阶段",default:0,bytes:true},
]}/><output>{v}</output></>}
describe("mdtest custom",()=>{
 it("目录测试关闭文件专用模式",()=>{render(<Form/>);fireEvent.click(screen.getByRole("checkbox",{name:"-D 仅目录"}));expect(screen.getByRole("status").textContent).toContain('"-F":false');});
 it("传递多选的原生参数并计算组合",()=>{const form={...defaults("mdtest"),concurrency:"1,2",mdtest_options_json:JSON.stringify({"-w":[0,4096],"-C":true})};expect(estimatedCount(form,"files")).toBe(4);expect(matrixParameters(form,"files").mdtest_options).toEqual({"-w":[0,4096],"-C":true});});
});
