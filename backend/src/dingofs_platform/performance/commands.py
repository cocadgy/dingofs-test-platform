from .schemas import TestSpec


def argv_for(spec: TestSpec, target: str, output: str, dtt: str) -> list[str]:
    if spec.tool == 'mlperf':
        if spec.mlperf_scenario != 'training':
            args = [dtt, '-t', 'mlperf', '-s', 'benchmark', '-m', target, '-o', output,
                    '--mlperf-scenario', spec.mlperf_scenario, '--mlperf-model', spec.mlperf_model,
                    '--concurrency', str(spec.concurrency), '--rounds', str(spec.rounds)]
            if spec.mlperf_scenario == 'checkpointing':
                args += ['--checkpoint-mode', spec.checkpoint_mode, '--checkpoint-count', str(spec.checkpoint_count)]
                if spec.checkpoint_size is not None:
                    args += ['--checkpoint-size', spec.checkpoint_size]
            else:
                args += ['--runtime-seconds', str(spec.runtime_seconds), '--total-size', spec.total_size,
                         '--gpu-memory-gib', str(spec.gpu_memory_gib), '--cpu-memory-gib', str(spec.cpu_memory_gib)]
            return args
        return [dtt, '-t', 'mlperf', '-s', 'benchmark', '-m', target, '-o', output,
                '--mlperf-model', spec.mlperf_model, '--mlperf-epochs', str(spec.mlperf_epochs),
                '--mlperf-accelerators', str(spec.mlperf_accelerators), '--concurrency', str(spec.concurrency),
                '--file-count', str(spec.file_count), '--rounds', str(spec.rounds)]
    if spec.tool == 'mdtest':
        return [dtt,'-t','mdtest','-s','custom','-m',target,'-o',output,'-n',str(spec.concurrency),'--custom-dir','__CUSTOM__']
    args=[dtt,'-t',spec.tool,'-s','benchmark','-m',target,'-o',output,
          '--direct',str(int(spec.direct)),'--concurrency',str(spec.concurrency),
          '--file-size',spec.file_size,'--file-count',str(spec.file_count),
          '--block-size',spec.block_size,'--rw',spec.rw,'--rounds',str(spec.rounds),
          '--iodepth',str(spec.iodepth)]
    if spec.read_percent is not None:args+=['--read-percent',str(spec.read_percent)]
    if spec.runtime_seconds is not None:args+=['--runtime-seconds',str(spec.runtime_seconds)]
    return args
