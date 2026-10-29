"""Native UVM with selectable independent SV, C++ or dual scoreboards.

Canonical RTL/testbench sources are never rewritten. A generated top selects
factory overrides; isolated mutant copies reuse the existing fault catalog.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.reference_tools import call,build_shared,compiler,vivado,xsim_bridge
from scripts.run_tests import find_questa
from scripts.run_uvm_tests import RTL_SOURCES,UVM_SOURCES,PROFILES
from scripts.mutation_catalog import MUTATIONS
from scripts.run_mutation_tests import ERROR_STOP,classify

ADDED=['reference/tma_reference.hpp','reference/tma_reference.cpp','reference/tma_dpi.cpp',
       'tb/uvm/tma_dpi_pkg.sv','tb/uvm/tma_mutation_pkg.sv','scripts/run_dpi_uvm_tests.py',
       'scripts/reference_tools.py','scripts/mutation_catalog.py','scripts/run_mutation_tests.py']


def cpp_mutation(m):
    protocol={'TMA_READ_STABILITY','TMA_WRITE_STABILITY','TMA_RESPONSE_STABILITY',
              'TMA_READ_RESPONSE_STABILITY','TMA_WRITE_RESPONSE_STABILITY'}
    names=[]
    for name in m.checker_ids:
        names.append(name if name in protocol else 'TMA_CPP_'+('PENDING' if name=='TMA_INCOMPLETE' else name.removeprefix('TMA_')))
    return replace(m,checker_ids=tuple(names))


def run(args):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=ROOT/'build/cpp_reference/uvm'/stamp;out.mkdir(parents=True)
    pointer=ROOT/'build/cpp_reference/current_uvm.json';pointer.unlink(missing_ok=True)
    names=list(dict.fromkeys(RTL_SOURCES+UVM_SOURCES+['tb/tma_sdram_model.sv']+ADDED))
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    result={'status':'incomplete','timestamp_utc':datetime.now(timezone.utc).isoformat(),'simulator':args.sim,
            'checker':args.checker,'uvm_version':'1.2','mode':'sv-constrained-random-and-covergroups' if args.full else 'seeded-procedural',
            'sv_constrained_randomization_executed':False,'sv_covergroups_executed':False,
            'sha256':hashes,'runs':[],'mutations':[],'scope':'Native UVM simulation; no FPGA access'}
    def save():(out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    save()
    try:
        compiler_version,_=call([compiler(),'--version'],out,'compiler.log');result['compiler']=compiler_version
        native_sources=[ROOT/'reference/tma_reference.cpp',ROOT/'reference/tma_dpi.cpp']
        dll=build_shared(native_sources,out,'tma_reference_'+args.sim)
        result['library_sha256']=hashlib.sha256(dll.read_bytes()).hexdigest()
        base=(ROOT/'tb/uvm/tb_tma_uvm.sv').read_text()
        assert base.count('run_test("tma_uvm_test");')==1
        base=base.replace('import tma_uvm_pkg::*;','import tma_uvm_pkg::*;\n    import tma_dpi_pkg::*;')
        base=base.replace('run_test("tma_uvm_test");','run_test("tma_dpi_test");')
        top=out/'tb_tma_dpi_top.sv';top.write_text(base.replace('endmodule',ERROR_STOP+'endmodule'))
        result['generated_top_sha256']=hashlib.sha256(top.read_bytes()).hexdigest()
        tool=find_questa() if args.sim=='questa' else vivado()
        if tool is None:raise RuntimeError('Selected simulator not found')
        suffix='.exe' if args.sim=='questa' else '.bat'
        result['simulator_version']=call([tool/('vsim.exe' if args.sim=='questa' else 'xvlog.bat'),'--version' if args.sim=='xsim' else '-version'],out,'version.log')[0]
        if args.sim=='questa':
            if args.full:raise RuntimeError('Installed Questa Starter does not license --full; use XSim')
            uvm=tool.parent/'verilog_src/uvm-1.2/src'
            for library in ('work','uvm12'):call([tool/'vlib.exe',library],out,library+'.log')
            call([tool/'vlog.exe','-sv','-work','uvm12','+incdir+'+str(uvm),uvm/'uvm_pkg.sv'],out,'uvm_compile.log')
        else:
            uvm=tool.parent/'data/system_verilog/uvm_1.2'
            archive=xsim_bridge(dll,native_sources,out,dll.stem)
            result['bridge_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
        (out/'run.do').write_text('onerror {quit -code 1}\nrun -all\nquit -code 0\n')
        (out/'run.tcl').write_text('run all\nquit\n')

        def compile_case(folder,mutation=None,profile='p1_b4_s0',xor_mask=0):
            sources=[ROOT/n for n in RTL_SOURCES]
            if mutation:
                patched=folder/Path(mutation.source).name
                patched.write_bytes(mutation.apply((ROOT/mutation.source).read_bytes()))
                sources[RTL_SOURCES.index(mutation.source)]=patched
            sources += [ROOT/'tb/tma_sdram_model.sv',ROOT/'tb/uvm/tma_uvm_if.sv',ROOT/'tb/uvm/tma_uvm_pkg.sv',
                        ROOT/'tb/uvm/tma_mutation_pkg.sv',ROOT/'tb/uvm/tma_dpi_pkg.sv',top]
            if args.sim=='questa':
                cmd=[tool/'vlog.exe','-sv','-L','uvm12','+incdir+'+str(uvm),'+incdir+'+str(ROOT/'tb/uvm'),*sources]
                call(cmd,out,str(folder.relative_to(out)/'compile.log'))
            else:
                cmd=[tool/'xvlog.bat','-sv','-L','uvm','-i',uvm,'-i',ROOT/'tb/uvm']
                if args.full:cmd+=['-d','TMA_UVM_FULL']
                cmd+=sources
                call(cmd,out,str(folder.relative_to(out)/'compile.log'))
                p,b,s=PROFILES[profile]
                options=['-L','uvm','work.tb_tma_uvm','-s','tma_dpi_snapshot','--timescale','1ns/1ps',
                      '-generic_top',f'PIPELINED={p}','-generic_top',f'READ_BURST_WORDS={b}','-generic_top',f'SWIZZLE={s}',
                      '-generic_top',f'READ_XOR_MASK={xor_mask}','-sv_root',out,'-sv_lib',dll.stem]
                argfile=folder/'elaboration.args'
                argfile.write_text('\n'.join('"'+str(a).replace('\\','/')+'"' for a in options)+'\n')
                call([tool/'xelab.bat','-f',argfile],out,str(folder.relative_to(out)/'elaborate.log'))

        def simulate(folder,profile,seed,mode,probes=False,random_cases=12,corrupt=False):
            p,b,s=PROFILES[profile]
            plus=[f'TMA_CHECKER={mode}',f'TMA_STIMULUS_SEED={seed}',f'TMA_RANDOM_CASES={random_cases}',
                  f'TMA_MUTATION_PROBES={int(probes)}','UVM_VERBOSITY=UVM_LOW','UVM_MAX_QUIT_COUNT=0,YES']
            if corrupt:plus+=['TMA_SKIP_SOURCE_READ=1']
            if args.sim=='questa':
                cmd=[tool/'vsim.exe','-c','-onfinish','exit','-L','uvm12','-sv_lib',tool.parent/'uvm-1.2/win64/uvm_dpi',
                     '-sv_lib',dll.with_suffix(''),'-sv_seed',str(seed),'work.tb_tma_uvm',f'-gPIPELINED={p}',f'-gREAD_BURST_WORDS={b}',f'-gSWIZZLE={s}',f'-gREAD_XOR_MASK={int(corrupt)}']
                cmd+=['+'+a for a in plus]+['-do','do run.do']
            else:
                options=['-tclbatch','run.tcl','-onerror','quit','-sv_seed',str(seed),'-log',str(folder/'simulation.log')]
                if args.full:options+=['-cov_db_dir',str(folder/'coverage'),'-cov_db_name','tma_dpi_snapshot']
                for value in plus:options+=['-testplusarg',value]
                argfile=folder/'simulation.args'
                argfile.write_text('\n'.join('"'+str(a).replace('\\','/')+'"' for a in options)+'\n')
                cmd=[tool/'xsim.bat','tma_dpi_snapshot','-f',argfile]
            return call(cmd,out,str(folder.relative_to(out)/'console.log'))

        def positive(folder,profile,seed,mode,probes=False,random_cases=12):
            transcript,wall=simulate(folder,profile,seed,mode,probes,random_cases)
            marker=re.search(r'\[TMA_UVM_PASS\] ([^\r\n]+)',transcript)
            if not marker or re.search(r'(?m)^\s*(?:#\s*)?(?:ERROR:|FATAL:|\*\* (?:Error|Fatal):)',transcript):
                raise RuntimeError('Nominal failed: '+str(folder)+'\n'+transcript[-5000:])
            if any(not re.search(rf'UVM_{k}\s*:\s*0\b',transcript) for k in ('WARNING','ERROR','FATAL')):
                raise RuntimeError('Nominal UVM severity count is not zero')
            fields={k:int(v) for k,v in (p.split('=',1) for p in marker[1].split())}
            if fields['descriptors']!=34+random_cases or (fields['pipelined'],fields['burst_words'],fields['swizzle'])!=PROFILES[profile]:
                raise RuntimeError('Nominal configuration/count mismatch')
            metrics={}
            match=re.search(r'\[TMA_CPP_METRICS\] ([^\r\n]+)',transcript)
            if match:metrics={k:int(v) for k,v in (p.split('=',1) for p in match[1].split())}
            peak=re.search(r'\[TMA_PROCESS_METRICS\] process_peak_bytes=(\d+)',transcript)
            cover=re.search(r'\[TMA_COVERGROUP\] functional_coverage=([0-9.]+)',transcript)
            if args.full and cover is None:raise RuntimeError('Full mode lacks executed covergroup report')
            record={'profile':profile,'seed':seed,'checker':mode,'scope':'cold-start RTL run, simulator launch included, compilation excluded',
                    'wall_seconds':wall,'summary':fields,'cpp_metrics':metrics,'process_peak_bytes':int(peak[1]) if peak else None,
                    'functional_covergroup_percent':float(cover[1]) if cover else None,
                    'log':(folder/'console.log').relative_to(ROOT).as_posix()}
            result['runs'].append(record);save()
            print(f'DPI_UVM_PASS {args.sim} {mode} {profile} seed={seed} descriptors={fields["descriptors"]} wall={wall:.3f}s',flush=True)
            return record

        profiles=args.profile or list(PROFILES)
        seeds=args.seed or [20261029]
        for profile in profiles:
            folder=out/('compile_'+profile);folder.mkdir();compile_case(folder,profile=profile)
            for seed in seeds:
                for repeat in range(args.repeat):
                    for mode in (['sv','cpp','dual'] if args.compare else [args.checker]):
                        mode_folder=out/f'{profile}_{seed}_{repeat}_{mode}';mode_folder.mkdir()
                        positive(mode_folder,profile,seed,mode,random_cases=args.random_cases)
        fault=out/'data_fault_control';fault.mkdir();compile_case(fault,xor_mask=1)
        text,wall=simulate(fault,'p1_b4_s0',seeds[0],args.checker,corrupt=True)
        first='TMA_READ_DATA' if args.checker=='sv' else 'TMA_CPP_READ_DATA'
        if '['+first+']' not in text or '[TMA_UVM_PASS]' in text or re.search(r'(?mi)^\s*(?:#\s*)?(?:ERROR:|FATAL:|\*\* (?:Error|Fatal):)',text):
            raise RuntimeError('DPI data-corruption control failed its checker contract')
        if args.checker=='dual' and '[TMA_READ_DATA]' not in text:
            raise RuntimeError('Dual corruption control must exercise both independent scoreboards')
        result['corruption_control']={'status':'detected','first_checker':first,'both_scoreboards':args.checker=='dual',
                                      'log':(fault/'console.log').relative_to(ROOT).as_posix(),'wall_seconds':wall}
        save();print('DPI_CORRUPTION_DETECTED',args.checker,first,flush=True)
        if args.mutations:
            if args.checker!='cpp':raise RuntimeError('Mutation acceptance requires --checker cpp, to avoid SV scoreboard masking')
            profile='p1_b4_s0';before=out/'mutation_nominal_before';before.mkdir();compile_case(before,profile=profile)
            positive(before,profile,seeds[0],'cpp',True,0)
            for mutation in MUTATIONS:
                folder=out/mutation.name;folder.mkdir();compile_case(folder,mutation,profile)
                transcript,wall=simulate(folder,profile,seeds[0],'cpp',True,0)
                m=cpp_mutation(mutation)
                if args.sim=='xsim':
                    transcript=re.sub(r'(?m)^Fatal:\s*','** Fatal: ',transcript)
                    if re.search(r'(?m)^\s*(?:ERROR:|FATAL:)',transcript):
                        raise RuntimeError('XSim runtime failure is not a detected mutation: '+mutation.name)
                verdict=classify(transcript,m,0)
                record={**asdict(m),**m.identity((ROOT/m.source).read_bytes()),**verdict,'wall_seconds':wall,
                        'log':(folder/'console.log').relative_to(ROOT).as_posix()}
                result['mutations'].append(record);save()
                print('DPI_MUTATION_'+verdict['outcome'].upper(),mutation.name,verdict.get('checker'),flush=True)
                if verdict['outcome']!='detected':raise RuntimeError('Mutation missed designated checker: '+mutation.name)
            after=out/'mutation_nominal_after';after.mkdir();compile_case(after,profile=profile)
            positive(after,profile,seeds[0],'cpp',True,0)
        result['source_files_unchanged']=hashes=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
        if not result['source_files_unchanged']:raise RuntimeError('Sources changed during DPI acceptance')
        result.update(status='pass',completed_utc=datetime.now(timezone.utc).isoformat(),
                      sv_constrained_randomization_executed=bool(args.full and args.random_cases),sv_covergroups_executed=bool(args.full))
        if args.compare:
            result['runtime_comparison']=[]
            for profile in profiles:
                for seed in seeds:
                    records=[r for r in result['runs'] if r['profile']==profile and r['seed']==seed]
                    if any(r['summary']!=records[0]['summary'] for r in records):raise RuntimeError('Runtime benchmark workloads differ')
                    modes={}
                    for mode in ('sv','cpp','dual'):
                        samples=[r['wall_seconds'] for r in records if r['checker']==mode]
                        modes[mode]={'wall_samples_seconds':samples,'median_seconds':statistics.median(samples),
                                     'min_seconds':min(samples),'max_seconds':max(samples),
                                     'checked_elements_per_second':records[0]['summary']['write_checks']/statistics.median(samples),
                                     'process_peak_bytes':[r['process_peak_bytes'] for r in records if r['checker']==mode]}
                    result['runtime_comparison'].append({'profile':profile,'seed':seed,'backends':modes,
                        'sv_over_cpp_wall_ratio':modes['sv']['median_seconds']/modes['cpp']['median_seconds'],
                        'note':'Simulator launch included; compilation and memory-image preparation outside wall samples; modes interleaved each repetition; identical public-interface stimulus and checked-element counts.'})
        save();pointer.write_text(json.dumps({'record':(out/'results.json').relative_to(ROOT).as_posix()})+'\n')
        print('DPI_UVM_SUITE_PASS',out,flush=True)
        return result
    except Exception as error:
        result.update(status='error',diagnostic=str(error));save();raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sim',choices=['questa','xsim'],default='xsim')
    p.add_argument('--checker',choices=['sv','cpp','dual'],default='dual')
    p.add_argument('--profile',choices=PROFILES,action='append')
    p.add_argument('--seed',type=int,action='append')
    p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--random-cases',type=int,default=12)
    p.add_argument('--full',action='store_true')
    p.add_argument('--mutations',action='store_true')
    p.add_argument('--compare',action='store_true',help='Interleave sv/cpp/dual modes for matched runtime samples')
    args=p.parse_args()
    if not 1<=args.repeat<=20 or not 0<=args.random_cases<=1000:p.error('repeat 1..20; random cases 0..1000')
    run(args)


if __name__=='__main__':main()
