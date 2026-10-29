"""Execute a minimal native-UVM C++17 DPI probe in both installed simulators."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.reference_tools import call, build_shared, compiler, vivado, xsim_bridge
from scripts.run_tests import find_questa


def main():
    base=ROOT/'build/cpp_reference/dpi_smoke'
    base.mkdir(parents=True,exist_ok=True)
    result={'status':'incomplete','timestamp_utc':datetime.now(timezone.utc).isoformat(),'profiles':{},
            'sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
                      ('tb/dpi/tma_dpi_smoke.cpp','tb/dpi/tb_tma_dpi_smoke.sv','scripts/run_dpi_smoke.py','scripts/reference_tools.py')}}
    (base/'results.json').unlink(missing_ok=True)
    for simulator in ('questa','xsim'):
        out=base/simulator;out.mkdir(exist_ok=True)
        dll=build_shared([ROOT/'tb/dpi/tma_dpi_smoke.cpp'],out,'tma_probe_'+simulator)
        if simulator=='questa':
            tool=find_questa();uvm=tool.parent/'verilog_src/uvm-1.2/src'
            if not (out/'work').exists(): call([tool/'vlib.exe','work'],out,'library.log')
            if not (out/'uvm12').exists():call([tool/'vlib.exe','uvm12'],out,'uvm_library.log')
            call([tool/'vlog.exe','-sv','-work','uvm12','+incdir+'+str(uvm),uvm/'uvm_pkg.sv'],out,'uvm_compile.log')
            call([tool/'vlog.exe','-sv','-L','uvm12','+incdir+'+str(uvm),ROOT/'tb/dpi/tb_tma_dpi_smoke.sv'],out,'compile.log')
            text,wall=call([tool/'vsim.exe','-c','-onfinish','exit','-L','uvm12','-sv_lib',tool.parent/'uvm-1.2/win64/uvm_dpi',
                           '-sv_lib',dll.with_suffix(''),'work.tb_tma_dpi_smoke','-do','run -all; quit -code 0'],out,'simulation.log')
        else:
            tool=vivado()
            if tool is None:raise RuntimeError('XSim not found')
            xsim_bridge(dll,[ROOT/'tb/dpi/tma_dpi_smoke.cpp'],out,dll.stem)
            call([tool/'xvlog.bat','-sv','-L','uvm','-i',tool.parent/'data/system_verilog/uvm_1.2',ROOT/'tb/dpi/tb_tma_dpi_smoke.sv'],out,'compile.log')
            call([tool/'xelab.bat','-L','uvm','work.tb_tma_dpi_smoke','-s','dpi_probe','--timescale','1ns/1ps','-sv_root',out,'-sv_lib',dll.stem],out,'elaborate.log')
            (out/'run.tcl').write_text('run all\nquit\n')
            text,wall=call([tool/'xsim.bat','dpi_probe','-tclbatch','run.tcl','-onerror','quit'],out,'simulation.log')
        if '[TMA_DPI_SMOKE_PASS]' not in text or 'UVM_FATAL :    0' not in text:
            raise RuntimeError(f'{simulator} did not pass native UVM DPI ABI probe: {text[-4000:]}')
        result['profiles'][simulator]={'status':'pass','wall_seconds':wall,'library_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),
                                       'compiler':str(compiler()),'scope':'C++17 32/64-bit unsigned scalars and output argument; native UVM 1.2'}
        print('DPI_SMOKE_PASS',simulator,flush=True)
    result['status']='pass'
    (base/'results.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
