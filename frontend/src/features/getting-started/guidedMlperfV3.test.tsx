import { describe, it, expect } from 'vitest';
import { defaultGuidedPerformanceForm, buildGuidedPerformancePayload, guidedPerformanceTotals, validateGuidedPerformance } from './guidedPerformanceModel';

describe('guided MLPerf 3.0', () => {
  it('preserves the selected checkpoint model without a custom size override', () => {
    const form = {...defaultGuidedPerformanceForm(), tools:['mlperf'] as ('mlperf')[], machineId:'m',targetPath:'/data',
      mlperfScenario:'checkpointing' as const,checkpointModel:'llama3-8b' as const,concurrency:8};
    expect(buildGuidedPerformancePayload(form).tests[0]).toMatchObject({mlperf_model:'llama3-8b'});
    expect(buildGuidedPerformancePayload(form).tests[0].checkpoint_size).toBeUndefined();
  });
  it('builds a checkpoint read payload with explicit preparation semantics', () => {
    const form = {...defaultGuidedPerformanceForm(), tools: ['mlperf'] as const,
      machineId:'m', targetPath:'/data', mlperfScenario:'checkpointing' as const,
      checkpointMode:'read' as const, checkpointCount:2, dataset:16, datasetUnit:'MiB' as const};
    const input = {...form, tools:[...form.tools]};
    expect(validateGuidedPerformance(input)).toBe('');
    expect(buildGuidedPerformancePayload(input).tests[0]).toMatchObject({mlperf_scenario:'checkpointing',
      mlperf_model:'custom', checkpoint_mode:'read', checkpoint_count:2, checkpoint_size:String(16*1024**2)});
    expect(guidedPerformanceTotals(input).mlperfDatasetBytes).toBe(32*1024**2);
  });
  it('uses duration and capacity for KV cache without training parameters', () => {
    const form = {...defaultGuidedPerformanceForm(), tools:['mlperf'] as ('mlperf')[],
      machineId:'m', targetPath:'/data', mlperfScenario:'kvcache' as const, kvModel:'tiny-1b', duration:5};
    expect(validateGuidedPerformance(form)).toBe('');
    const spec = buildGuidedPerformancePayload(form).tests[0];
    expect(spec).toMatchObject({mlperf_scenario:'kvcache', runtime_seconds:5, mlperf_model:'tiny-1b'});
    expect(spec).not.toHaveProperty('mlperf_epochs');
    expect(guidedPerformanceTotals(form).measuredSeconds).toBe(5);
  });
});
