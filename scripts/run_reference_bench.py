"""Measure matched prediction work and DPI dispatch separately from RTL runtime."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.address_model import Descriptor,addresses
from scripts.reference_tools import call,compiler,build_shared,vivado,xsim_bridge
from scripts.run_tests import find_questa


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim',choices=['xsim','questa'],default='xsim');args=parser.parse_args()
    out=ROOT/'build/cpp_reference/microbenchmark'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True)
    names=['reference/tma_reference.hpp','reference/tma_reference.cpp','reference/tma_dpi.cpp','reference/reference_cli.cpp',
           'scripts/run_reference_bench.py','scripts/reference_tools.py','tb/dpi/tb_tma_reference_bench.sv',
           'tb/uvm/tma_dpi_pkg.sv','tb/uvm/tma_mutation_pkg.sv','model/address_model.py',
           'tb/uvm/tma_uvm_pkg.sv','tb/uvm/tma_uvm_agent.svh','tb/uvm/tma_uvm_scoreboard.svh',
           'tb/uvm/tma_uvm_sequences.svh','tb/uvm/tma_uvm_coverage.svh','tb/uvm/tma_uvm_if.sv']
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    native_sources=[ROOT/'reference/tma_reference.cpp',ROOT/'reference/tma_dpi.cpp']
    dll=build_shared(native_sources,out,'tma_bench_'+args.sim)
    executable=out/'reference_cli.exe'
    call([compiler(),'-std=c++17','-O2','-Wall','-Wextra','-Werror',*native_sources,ROOT/'reference/reference_cli.cpp','-o',executable],out,'cli_build.log')
    native_text,_=call([executable,'prediction'],out,'native_prediction.log')
    native=[json.loads(line) for line in native_text.splitlines() if line.startswith('{')]
    assert len(native)==5
    python=[];memory=[(i*73^0xa55a)&65535 for i in range(4096)]
    for side in (1,8,16,32,64):
        desc=Descriptor(0,0,side,side,side*2,2,2,side*2)
        def predict():return [(s,d,memory[s//2]) for s,d,_ in addresses(desc)]
        for _ in range(3):predict()
        samples=[]
        for _ in range(7):
            start=time.perf_counter_ns()
            for _ in range(100):predicted=predict()
            samples.append((time.perf_counter_ns()-start)/100)
        assert len(predicted)==side*side
        python.append({'side':side,'ns_per_descriptor':samples})
    tool=vivado() if args.sim=='xsim' else find_questa()
    sv=[ROOT/'tb/uvm/tma_uvm_if.sv',ROOT/'tb/uvm/tma_uvm_pkg.sv',ROOT/'tb/uvm/tma_mutation_pkg.sv',
        ROOT/'tb/uvm/tma_dpi_pkg.sv',ROOT/'tb/dpi/tb_tma_reference_bench.sv']
    if args.sim=='xsim':
        xsim_bridge(dll,native_sources,out,dll.stem)
        call([tool/'xvlog.bat','-sv','-L','uvm','-i',tool.parent/'data/system_verilog/uvm_1.2','-i',ROOT/'tb/uvm',*sv],out,'compile.log')
        call([tool/'xelab.bat','-L','uvm','work.tb_tma_reference_bench','-s','reference_bench','--timescale','1ns/1ps',
              '-sv_root',out,'-sv_lib',dll.stem],out,'elaborate.log')
        (out/'run.tcl').write_text('run all\nquit\n')
        transcript,wall=call([tool/'xsim.bat','reference_bench','-tclbatch','run.tcl','-onerror','quit'],out,'simulation.log')
    else:
        uvm=tool.parent/'verilog_src/uvm-1.2/src'
        for name in ('work','uvm12'):call([tool/'vlib.exe',name],out,name+'.log')
        call([tool/'vlog.exe','-sv','-work','uvm12','+incdir+'+str(uvm),uvm/'uvm_pkg.sv'],out,'uvm_compile.log')
        call([tool/'vlog.exe','-sv','-L','uvm12','+incdir+'+str(uvm),'+incdir+'+str(ROOT/'tb/uvm'),*sv],out,'compile.log')
        transcript,wall=call([tool/'vsim.exe','-c','-onfinish','exit','-L','uvm12','-sv_lib',tool.parent/'uvm-1.2/win64/uvm_dpi',
                             '-sv_lib',dll.with_suffix(''),'work.tb_tma_reference_bench','-do','run -all; quit -code 0'],out,'simulation.log')
    if '[TMA_REFERENCE_BENCH_PASS]' not in transcript or any(not re.search(rf'UVM_{s}\s*:\s*0\b',transcript) for s in ('WARNING','ERROR','FATAL')):
        raise RuntimeError('Model-computation UVM benchmark did not pass')
    rows=[]
    for line in re.findall(r'^#?\s*TMA_PREDICT_BENCH (.+)$',transcript,re.M):
        rows.append({k:int(v) for k,v in (token.split('=') for token in line.split())})
    overhead=[]
    for line in re.findall(r'^#?\s*TMA_DPI_OVERHEAD (.+)$',transcript,re.M):
        overhead.append({k:int(v) for k,v in (token.split('=') for token in line.split())})
    assert len(rows)==35 and len(overhead)==7
    summaries=[]
    for n,side in enumerate((1,8,16,32,64)):
        subset=[r for r in rows if r['side']==side]
        assert len(subset)==7 and {r['repetition'] for r in subset}==set(range(7))
        values={'python':python[n]['ns_per_descriptor'],'cpp_native':native[n]['ns_per_descriptor'],
                'cpp_dpi':[r['dpi_ns']/r['loops'] for r in subset],'sv_scoreboard':[r['sv_ns']/r['loops'] for r in subset]}
        summaries.append({'side':side,'elements':side*side,'backends':{k:{'samples_ns':v,'median_ns':statistics.median(v),
                         'min_ns':min(v),'max_ns':max(v),'elements_per_second':side*side*1e9/statistics.median(v)} for k,v in values.items()}})
    result={'status':'pass','simulator':args.sim,'timestamp_utc':datetime.now(timezone.utc).isoformat(),
            'sha256':hashes,'scope':'Prediction-only microbenchmark in native UVM; no RTL cycles simulated',
            'contract':'Complete ordered (source,destination,data) tables for identical known-valid 1..64 square transposes. Initialization and result readback outside timing. SV uses unchanged tma_scoreboard.predict; Python composes preserved addresses oracle with source-memory lookup. C++ standalone and DPI use the same mathematical predictor. 100 iterations, 3 warmups, 7 repeats. No full destination copy in this benchmark.',
            'predictions':summaries,'dpi_dispatch':overhead,'native_noop_log':'native_prediction.log',
            'uvm_simulator_wall_seconds':wall,'source_files_unchanged':hashes=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}}
    if not result['source_files_unchanged']:raise RuntimeError('Sources changed during benchmark')
    (out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('REFERENCE_MICROBENCH_PASS',out,flush=True)


if __name__=='__main__':main()
