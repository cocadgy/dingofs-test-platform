import { render, screen, within, fireEvent } from "@testing-library/react";
import { test, expect } from "vitest";
import { ToolComparisonReports } from "./ToolComparisonReports";
import { Run } from "./types";
test("each parameter table includes all tool combinations with independent metrics and failures", () => {
  const spec = {
    tool: "fio",
    rw: "write",
    direct: true,
    concurrency: 1,
    iodepth: 1,
    block_size: "4096",
    file_size: "1048576",
    file_count: 1,
    total_size: "1048576",
    rounds: 2,
    read_percent: 50,
  };
  const run = {
    id: "job",
    state: "failed",
    snapshot: {
      scenarios: [
        { id: "a", tool: "fio", parameters: spec },
        {
          id: "b",
          tool: "fio",
          parameters: { ...spec, concurrency: 8, rw: "rw", read_percent: 70 },
        },
        {
          id: "c",
          tool: "elbencho",
          parameters: { ...spec, tool: "elbencho" },
        },
      ],
    },
    reports: {
      a: {
        state: "success",
        files: ["index.html"],
        summary: {
          statistics: {
            successful_rounds: 2,
            requested_rounds: 2,
            metrics: { bandwidth_mib_s: { mean: 12.3 } },
          },
        },
      },
      b: { state: "failed", error: "磁盘空间不足", files: [] },
    },
  } as unknown as Run;
  render(<ToolComparisonReports run={run} />);
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("group", { name: "文件总数量柱状图" })).toBeNull();
  expect(screen.queryByRole("group", { name: "总文件大小柱状图" })).toBeNull();
  expect(screen.queryByRole("group", { name: "测量轮次柱状图" })).toBeNull();
  const concurrency = screen.getByRole("group", { name: "并发度柱状图" });
  expect(
    concurrency.querySelectorAll(".performance-chart-value-group"),
  ).toHaveLength(2);
  const direct = screen.getByRole("group", { name: "Direct I/O柱状图" });
  expect(
    direct.querySelectorAll(".performance-chart-value-group"),
  ).toHaveLength(2);
  expect(direct.querySelectorAll(".performance-chart-column")).toHaveLength(2);
  const charts = screen.getAllByRole("group", { name: /柱状图$/ });
  expect(charts).toHaveLength(7);
  for (const chart of charts) {
    expect(within(chart).getAllByRole("button")).toHaveLength(2);
    expect(
      within(chart).getByRole("button", { name: /12.3 MiB/ }),
    ).toBeInTheDocument();
    expect(
      within(chart).getByRole("button", { name: /无有效数据/ }),
    ).toBeInTheDocument();
  }
  fireEvent.click(within(charts[0]).getByRole("button", { name: /12.3 MiB/ }));
  expect(screen.getByRole("link", { name: "原始报告" })).toHaveAttribute(
    "href",
    "#/performance/job/reports/a",
  );
  fireEvent.click(screen.getByRole("button", { name: "平均 IOPS（IO/s）" }));
  expect(
    within(charts[0]).getAllByRole("button", { name: /无有效数据/ }),
  ).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "elbencho 汇总报告" }));
  expect(screen.getAllByRole("group", { name: /柱状图$/ })).toHaveLength(6);
  expect(screen.queryByRole("link", { name: "原始报告" })).toBeNull();
});

test("mdtest comparison uses metadata rates without bandwidth or direct IO charts",()=>{
  const parameters={tool:"mdtest",concurrency:1,file_count:100,rounds:2,layout:"unique"};
  const run={id:"m",state:"success",snapshot:{scenarios:[{id:"a",tool:"mdtest",parameters}]},
    reports:{a:{state:"success",files:[],summary:{statistics:{metrics:{create_ops_s:{mean:200,samples:2}}}}}}} as unknown as Run;
  render(<ToolComparisonReports run={run}/>);
  expect(screen.getByRole("button",{name:"平均创建速率（ops/s）"})).toBeVisible();
  expect(screen.queryByRole("button",{name:"平均带宽（MiB/s）"})).toBeNull();
  expect(screen.queryByRole("group",{name:"Direct I/O柱状图"})).toBeNull();
  expect(screen.getByRole("group",{name:"MPI 进程数柱状图"})).toBeVisible();
});

test("MLPerf comparison uses training metrics and training dimensions", () => {
  const parameters = {tool:"mlperf", mlperf_model:"resnet50", mlperf_epochs:2, mlperf_accelerators:4,
    concurrency:4, file_count:8, file_size:"143439748", total_size:"1147517984", rounds:1,
    read_percent:null};
  const run={id:"train",state:"success",snapshot:{scenarios:[
    {id:"train-a",tool:"mlperf",parameters},
    {id:"train-b",tool:"mlperf",parameters:{...parameters,mlperf_model:"unet3d",mlperf_epochs:3,mlperf_accelerators:8}},
  ]},reports:{
    "train-a":{state:"success",files:[],summary:{statistics:{metrics:{samples_per_second:{mean:125.5,samples:1},accelerator_utilization_percent:{mean:81.2,samples:1}}}}},
    "train-b":{state:"success",files:[],summary:{statistics:{metrics:{samples_per_second:{mean:91,samples:1},accelerator_utilization_percent:{mean:70,samples:1}}}}},
  }} as unknown as Run;
  render(<ToolComparisonReports run={run}/>);
  expect(screen.getByRole("button",{name:"平均训练吞吐（samples/s）"})).toBeVisible();
  expect(screen.getByRole("button",{name:"平均加速器利用率（%）"})).toBeVisible();
  expect(screen.queryByRole("button",{name:"平均带宽（MiB/s）"})).toBeNull();
  expect(screen.getByRole("group",{name:"训练模型柱状图"})).toBeVisible();
  expect(screen.getByRole("group",{name:"每轮训练 epochs柱状图"})).toBeVisible();
  expect(screen.getByRole("group",{name:"模拟 H100 加速器数柱状图"})).toBeVisible();
  expect(screen.queryByRole("group",{name:"Direct I/O柱状图"})).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"平均加速器利用率（%）"}));
  expect(within(screen.getByRole("group",{name:"训练模型柱状图"})).getByRole("button",{name:/81.2 %/})).toBeVisible();
});
