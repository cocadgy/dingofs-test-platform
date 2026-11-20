import {render, screen, cleanup} from '@testing-library/react';
import {test, expect, afterEach} from 'vitest';
import {ReportCards} from './ReportCards';
import {ScenarioParameters} from './ScenarioParameters';
afterEach(cleanup);
test('checkpoint report shows read bandwidth instead of training throughput', () => {
  const spec = {tool:'mlperf',mlperf_scenario:'checkpointing',mlperf_model:'custom',checkpoint_mode:'read',checkpoint_count:2,total_size:'33554432',concurrency:1,rounds:1} as any;
  render(<><ScenarioParameters spec={spec}/><ReportCards run={{id:'r',reports:{mlperf:{parameters:spec,tool:'mlperf',files:[],summary:{status:'passed',statistics:{metrics:{read_gib_per_second:{mean:1.5},read_seconds:{mean:.1}}}}}},snapshot:{scenarios:[]}} as any}/></>);
  expect(screen.getByText('读取带宽')).toBeVisible();
  expect(screen.queryByText('平均训练吞吐')).toBeNull();
  expect(screen.getByText(/先准备数据/)).toBeVisible();
});
test('KV capacity is not displayed as dataset or actual IO', () => {
  const spec = {tool:'mlperf',mlperf_scenario:'kvcache',runtime_seconds:5,total_size:'268435456'};
  render(<ReportCards run={{id:'r',reports:{mlperf:{parameters:spec,tool:'mlperf',files:[],summary:{status:'passed',statistics:{metrics:{}}}}},snapshot:{scenarios:[]}} as any}/>);
  expect(screen.getByText(/缓存层容量：256 MiB/)).toBeVisible();
  expect(screen.queryByText(/每工具数据集/)).toBeNull();
  expect(screen.queryByText(/每轮实际 I\/O/)).toBeNull();
});
