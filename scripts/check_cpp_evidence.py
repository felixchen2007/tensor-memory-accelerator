"""Offline validation of published C++/DPI evidence; does not run a simulator."""
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_dpi_uvm_tests import cpp_mutation
from scripts.mutation_catalog import MUTATIONS
from scripts.run_mutation_tests import classify


def require(condition,message):
    if not condition:raise ValueError(message)


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def sources(record):
    for name,digest in record['sha256'].items():
        require(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,'Tested source differs: '+name)


def validate():
    folder=ROOT/'evidence/cpp_reference/2026-10-29'
    index=read(folder/'index.json')
    def local(relative):
        path=(folder/relative).resolve()
        require(path.is_relative_to(folder.resolve()),'Evidence path escaped its directory')
        return path
    def record(name):
        r=read(local(index['records'][name]));sources(r);return r
    def log(original):
        require(original in index['logs'],'Missing exported log '+original)
        return local(index['logs'][original]).read_text(encoding='utf-8')
    def clean_report(text):
        require(not re.search(r'(?mi)^\s*(?:#\s*)?(?:ERROR:|FATAL:|\*\* (?:Error|Fatal):)',text),'Simulator failure in nominal log')
        for severity in ('WARNING','ERROR','FATAL'):
            require(re.search(rf'UVM_{severity}\s*:\s*0\b',text),'Missing/nonzero nominal severity '+severity)
    def uvm(name,partial=False):
        r=record(name)
        require(r['status']==('incomplete' if partial else 'pass'),'Unaccepted UVM record '+name)
        if not partial:require(r['source_files_unchanged'] is True,'Sources changed during '+name)
        for run in r['runs']:
            text=log(run['log']);clean_report(text)
            marker=re.search(r'\[TMA_UVM_PASS\] ([^\r\n]+)',text)
            require(marker is not None,'No native UVM pass marker')
            summary={k:int(v) for k,v in (t.split('=',1) for t in marker[1].split())}
            require(summary==run['summary'],'UVM summary differs from transcript')
            require(summary['descriptors'] in (34,46),'Unexpected tested descriptor count')
            require(run['process_peak_bytes']>0,'Missing process working-set measurement')
            if run['checker']!='sv':
                marker=re.search(r'\[TMA_CPP_METRICS\] ([^\r\n]+)',text)
                require(marker is not None,'No C++ execution metrics')
                metrics={k:int(v) for k,v in (t.split('=',1) for t in marker[1].split())}
                require(metrics==run['cpp_metrics'] and metrics['calls']>0,'C++ path not executed')
            if r['sv_covergroups_executed']:
                coverage=re.search(r'\[TMA_COVERGROUP\] functional_coverage=([0-9.]+)',text)
                require(coverage and float(coverage[1])==run['functional_covergroup_percent'],'Covergroup report mismatch')
        if not partial:
            control=r['corruption_control'];text=log(control['log'])
            require(control['status']=='detected' and '['+control['first_checker']+']' in text
                    and '[TMA_UVM_PASS]' not in text,'Corruption checker did not fire')
            require(not re.search(r'(?mi)^\s*(?:#\s*)?(?:ERROR:|FATAL:|\*\* (?:Error|Fatal):)',text),'Corruption run has tool failure')
            if control['both_scoreboards']:
                require('[TMA_CPP_READ_DATA]' in text and '[TMA_READ_DATA]' in text,'Dual control must diagnose both paths')
        return r

    first=uvm('matrix_interrupted',True);last=uvm('matrix_completion')
    profiles={f'p{p}_b{b}_s{s}' for p in (0,1) for b in (1,4) for s in (0,1)}
    all_runs=first['runs']+last['runs']
    require(len(first['runs'])==6 and len(last['runs'])==2,'Interrupted matrix recovery counts differ')
    require({r['profile'] for r in all_runs}==profiles and len(all_runs)==8,'DPI matrix incomplete')
    require(first['sha256']==last['sha256'],'Recovered matrix used different sources')
    require(all(r['checker']=='dual' and r['summary']['descriptors']==46 for r in all_runs),'DPI matrix is not dual/46')
    require(index['matrix_recovery']['partial_record_status_preserved'] is True,'Interrupted run status must remain historical')
    mutation=uvm('cpp_mutations')
    require(mutation['checker']=='cpp' and len(mutation['mutations'])==len(MUTATIONS),'C++ mutation matrix missing')
    counts={'cpp_scoreboard':0,'uvm_protocol':0,'sdram_pin_model':0}
    for original in MUTATIONS:
        target=cpp_mutation(original)
        entry=next(v for v in mutation['mutations'] if v['name']==original.name)
        require(entry['source_sha256']==target.identity((ROOT/target.source).read_bytes())['source_sha256']
                and entry['mutated_sha256']==target.identity((ROOT/target.source).read_bytes())['mutated_sha256'],'Mutation source identity differs')
        text=re.sub(r'(?m)^Fatal:\s*','** Fatal: ',log(entry['log']))
        verdict=classify(text,target,0)
        require(verdict['outcome']=='detected' and all(entry[k]==v for k,v in verdict.items()),'C++ mutation diagnosis mismatch: '+original.name)
        key='cpp_scoreboard' if verdict['checker'].startswith('TMA_CPP_') else ('sdram_pin_model' if verdict['checker']=='SDRAM_PIN_MODEL' else 'uvm_protocol')
        counts[key]+=1
    full=uvm('full_features')
    require(full['sv_constrained_randomization_executed'] is True and full['sv_covergroups_executed'] is True,'Full features were not executed')
    require({r['seed'] for r in full['runs']}=={20261029,57,991} and len(full['runs'])==3,'Full-mode seed set differs')
    require(all(r['functional_covergroup_percent']==100 for r in full['runs']),'Recorded descriptor covergroup differs')
    adapter=full['launch_adapter']
    require(adapter['same_checkout_verified'] and hashlib.sha256((ROOT/adapter['source']).read_bytes()).hexdigest()==adapter['sha256'],'Coverage launcher identity mismatch')
    questa=uvm('questa_dpi');require(questa['simulator']=='questa' and questa['checker']=='dual','Missing Questa DPI run')
    runtime=uvm('runtime_benchmark')
    require(len(runtime['runtime_comparison'])==1 and len(runtime['runs'])==9,'Require three interleaved repetitions per checker')
    table=runtime['runtime_comparison'][0]
    for mode in ('sv','cpp','dual'):
        values=[r['wall_seconds'] for r in runtime['runs'] if r['checker']==mode]
        require(len(values)==3 and values==table['backends'][mode]['wall_samples_seconds'],'Runtime samples differ')
        require(statistics.median(values)==table['backends'][mode]['median_seconds'],'Runtime median differs')
    require(table['sv_over_cpp_wall_ratio']==table['backends']['sv']['median_seconds']/table['backends']['cpp']['median_seconds'],'Runtime ratio differs')
    standalone=record('standalone')
    require(standalone['status']=='pass' and (standalone['cpp_directed_tests'],standalone['python_cpp_cases'],standalone['bank_mappings'],standalone['c_api_lifecycles'])==(21,387,8192,100),'Standalone C++ acceptance counts differ')
    require('CPP_SELFTEST_PASS cases=21' in log(index['standalone_unit_log']),'Native self-test marker absent')
    digests=read(local(index['cross_model_digests']))
    require(len(digests)==387 and {r['case'] for r in digests}==set(range(387))
            and all(r['cpp_sha256']==r['python_sha256'] for r in digests),'Cross-model case digests disagree')
    for comparison in standalone['benchmark']:
        for backend in ('python','cpp'):
            stats=comparison[backend];values=stats['ns_per_descriptor']
            require(len(values)==7 and statistics.median(values)==stats['median_ns']
                    and min(values)==stats['min_ns'] and max(values)==stats['max_ns'],'Copy-model benchmark summary differs')
            require(stats['process_peak_bytes']>0,'Missing isolated process peak')
        require(comparison['pure_model_ratio']==comparison['python']['median_ns']/comparison['cpp']['median_ns'],'Copy-model ratio differs')
    micro=record('microbenchmark')
    require(micro['status']=='pass' and micro['source_files_unchanged'] and len(micro['predictions'])==5 and len(micro['dpi_dispatch'])==7,'Microbenchmark incomplete')
    clean_report(log(index['microbenchmark_log']))
    for item in micro['predictions']:
        require(set(item['backends'])=={'python','cpp_native','cpp_dpi','sv_scoreboard'},'Missing prediction backend')
        for backend in item['backends'].values():
            require(len(backend['samples_ns'])==7 and statistics.median(backend['samples_ns'])==backend['median_ns'],'Prediction timing summary differs')
    smoke=record('dpi_smoke')
    require(smoke['status']=='pass' and set(smoke['profiles'])=={'questa','xsim'},'DPI ABI proof incomplete')
    for path in index['smoke_logs']:
        text=log(path);clean_report(text);require('[TMA_DPI_SMOKE_PASS]' in text,'Missing DPI ABI marker')
    baseline=record('original_questa')
    require(baseline['status']=='pass' and set(baseline['profiles'])==profiles|{'data_fault_control'},'Original Questa regression incomplete')
    for name in profiles:
        source='build/uvm/starter/'+name+'_console.log'
        text=log(source);clean_report(text)
        marker=re.search(r'\[TMA_UVM_PASS\] ([^\r\n]+)',text)
        require(marker is not None,'Original Questa pass marker missing')
        actual={k:int(v) for k,v in (p.split('=',1) for p in marker[1].split())}
        require(actual==baseline['profiles'][name],'Original Questa summary mismatch')
    control=log('build/uvm/starter/data_fault_control_console.log')
    require('[TMA_READ_DATA]' in control and '[TMA_UVM_PASS]' not in control
            and '** Fatal:' not in control and '** Error:' not in control
            and re.search(r'UVM_ERROR\s*:\s*1\b',control),'Original corruption control is not a clean checker diagnosis')
    python_baseline=record('original_python')
    require(python_baseline['status']=='pass' and len(python_baseline['records'])==6,'Pre-change Python baseline missing')
    return {'matrix_descriptors':sum(r['summary']['descriptors'] for r in all_runs),'mutations':counts,
            'full_mode_descriptors':sum(r['summary']['descriptors'] for r in full['runs']),
            'runtime_ratio':table['sv_over_cpp_wall_ratio']}


if __name__=='__main__':
    try:print('CPP_EVIDENCE_CHECK_PASS '+json.dumps(validate()))
    except (ValueError,OSError,KeyError,StopIteration) as error:raise SystemExit('CPP_EVIDENCE_CHECK_FAILED: '+str(error))
