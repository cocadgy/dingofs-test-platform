from .schemas import TestSpec


def argv_for(spec: TestSpec, target: str, output: str, dtt: str) -> list[str]:
    if spec.tool == 'mdtest':
        return [dtt,'-t','mdtest','-s','custom','-m',target,'-o',output,'-n',str(spec.concurrency),'--custom-dir','__CUSTOM__']
    args=[dtt,'-t',spec.tool,'-s','benchmark','-m',target,'-o',output,
          '--direct',str(int(spec.direct)),'--concurrency',str(spec.concurrency),
          '--file-size',spec.file_size,'--file-count',str(spec.file_count),
          '--block-size',spec.block_size,'--rw',spec.rw,'--rounds',str(spec.rounds),
          '--iodepth',str(spec.iodepth)]
    if spec.read_percent is not None:args+=['--read-percent',str(spec.read_percent)]
    return args
