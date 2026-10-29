"""Build/test the C++17 oracle against the preserved Python oracle, then benchmark.

The shared vector files are an independent file-based fallback when DPI is
unavailable. Complete traces and destination images must agree before timing.
"""
from dataclasses import astuple
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.address_model import Descriptor
from model.copy_model import copy_tensor
from model.bank_layout import BankLayout
from scripts.generate_copy_vectors import generate_copy_vectors, WORDS
from scripts.reference_tools import call, compiler, build_shared

SOURCES=['reference/tma_reference.hpp','reference/tma_reference.cpp','reference/tma_dpi.cpp',
         'reference/reference_cli.cpp','model/address_model.py','model/copy_model.py','model/bank_layout.py',
         'scripts/run_cpp_reference.py','scripts/reference_tools.py','scripts/generate_copy_vectors.py']


def cases(output):
    expected=[];inputs=[]
    for seed in (20261029,57,991):
        folder=output/f'python_{seed}'
        manifest=generate_copy_vectors(folder,seed,100)
        with (folder/'copy_vectors.txt').open() as stream:
            for case in manifest['cases']:
                h=[int(n,16) for n in stream.readline().split()]
                triples=[[int(n,16) for n in stream.readline().split()] for _ in range(WORDS)]
                reads=[int(stream.readline(),16) for _ in range(h[13])]
                writes=[[int(n,16) for n in stream.readline().split()] for _ in range(h[14])]
                expected.append({'status':h[11],'completed':h[12],'reads':reads,'writes':writes,
                                 'destination':[t[2] for t in triples]})
                inputs.append((h[:8],[t[0] for t in triples],[t[1] for t in triples],h[10] if h[9]==1 else -1,h[10] if h[9]==2 else -1))
    # Scaling checks use the identical arrays/transpose shape timed below.
    for side in (1,8,16,32,64,128):
        words=max(4096,side*side)
        source=[(i*73^0xa55a)&65535 for i in range(words)]
        initial=[(i^0xca71)&65535 for i in range(words)]
        desc=Descriptor(0,0,side,side,side*2,2,2,side*2)
        r=copy_tensor(desc,source,initial)
        expected.append({'status':int(r.error_code),'completed':r.completed_elements,'reads':r.reads,
                         'writes':[list(v) for v in r.writes],'destination':r.destination})
        inputs.append((list(astuple(desc)),source,initial,-1,-1))
    file=output/'common_vectors.txt'
    with file.open('w',encoding='ascii') as stream:
        stream.write(str(len(inputs))+'\n')
        for d,source,destination,rf,wf in inputs:
            stream.write(' '.join(map(str,[*d,len(source),len(destination),rf,wf]))+'\n')
            stream.write(' '.join(map(str,source))+'\n'+' '.join(map(str,destination))+'\n')
    return file,expected


def api_checks(dll):
    runtime=os.add_dll_directory(str(compiler().parent)) if os.name=='nt' else None
    lib=ctypes.CDLL(str(dll));lib._runtime_directory=runtime
    p=ctypes.c_void_p;u=ctypes.c_uint32
    lib.tma_ref_create.argtypes=[u,u];lib.tma_ref_create.restype=p
    lib.tma_ref_destroy.argtypes=[p];lib.tma_ref_destroy.restype=None
    lib.tma_ref_error.argtypes=[p];lib.tma_ref_error.restype=ctypes.c_char_p
    lib.tma_ref_reset.argtypes=[p];lib.tma_ref_reset.restype=u
    lib.tma_ref_seed.argtypes=[p,u,u,u];lib.tma_ref_seed.restype=u
    lib.tma_ref_read.argtypes=[p,u,u,ctypes.POINTER(u)];lib.tma_ref_read.restype=u
    lib.tma_ref_begin.argtypes=[p]+[u]*8;lib.tma_ref_begin.restype=u
    lib.tma_ref_event.argtypes=[p]+[u]*6;lib.tma_ref_event.restype=u
    lib.tma_ref_metric.argtypes=[p,u];lib.tma_ref_metric.restype=ctypes.c_uint64
    lib.tma_ref_peak_bytes.restype=ctypes.c_uint64
    assert lib.tma_ref_create(3,128) is None and lib.tma_ref_error(None)
    assert lib.tma_ref_reset(None)==1
    for iteration in range(100):
        handle=lib.tma_ref_create(128,128)
        assert handle
        try:
            value=u()
            assert lib.tma_ref_read(handle,0,0,ctypes.byref(value))==2
            assert lib.tma_ref_seed(handle,0,0,iteration)==0
            assert lib.tma_ref_begin(handle,0,0,1,1,2,2,2,2)==0
            for kind,addr,data,error,count,code in ((0,0,0,0,0,0),(1,0,iteration,0,0,0),
                    (2,0,iteration,0,0,0),(3,0,0,0,0,0),(4,0,0,0,1,0),(5,0,0,0,0,0)):
                assert lib.tma_ref_event(handle,kind,addr,data,error,count,code)==0
            assert lib.tma_ref_read(handle,1,0,ctypes.byref(value))==0 and value.value==iteration
            assert lib.tma_ref_reset(handle)==0
            assert lib.tma_ref_read(handle,1,0,ctypes.byref(value))==2
        finally:lib.tma_ref_destroy(handle)
    return lib


def process_peak_bytes():
    if os.name=='nt':
        class Counters(ctypes.Structure):
            _fields_=[('cb',ctypes.c_uint32),('faults',ctypes.c_uint32)]+[(name,ctypes.c_size_t) for name in
                ('peak','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
        value=Counters();value.cb=ctypes.sizeof(value)
        kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
        function=ctypes.windll.psapi.GetProcessMemoryInfo
        function.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_uint32]
        if not function(kernel.GetCurrentProcess(),ctypes.byref(value),value.cb):raise RuntimeError('Process memory measurement failed')
        return value.peak
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024


def python_bench():
    records=[]
    for side in (1,8,16,32,64,128):
        words=max(4096,side*side);loops=max(2,min(100,100000//(side*side)))
        source=[(i*73^0xa55a)&65535 for i in range(words)];initial=[(i^0xca71)&65535 for i in range(words)]
        d=Descriptor(0,0,side,side,side*2,2,2,side*2)
        for _ in range(3):copy_tensor(d,source,initial)
        samples=[]
        for _ in range(7):
            start=time.perf_counter_ns()
            for _ in range(loops):copy_tensor(d,source,initial)
            samples.append((time.perf_counter_ns()-start)/loops)
        tracemalloc.start();copy_tensor(d,source,initial);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        records.append({'side':side,'elements':side*side,'loops':loops,'ns_per_descriptor':samples,
                        'python_traced_peak_bytes':peak,'process_peak_bytes':process_peak_bytes()})
    return records


def main():
    out=ROOT/'build/cpp_reference/standalone'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True)
    pointer=ROOT/'build/cpp_reference/current_standalone.json';pointer.unlink(missing_ok=True)
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES}
    executable=out/('reference_cli.exe' if sys.platform=='win32' else 'reference_cli')
    source=[ROOT/'reference'/n for n in ('tma_reference.cpp','tma_dpi.cpp','reference_cli.cpp')]
    call([compiler(),'-std=c++17','-O2','-Wall','-Wextra','-Werror',*source,'-o',executable],out,'build.log')
    unit,_=call([executable,'selftest'],out,'selftest.log');assert 'CPP_SELFTEST_PASS cases=21' in unit
    file,expected=cases(out)
    call([executable,'vectors',file,out/'cpp_results.jsonl'],out,'vectors.log')
    actual=[json.loads(line) for line in (out/'cpp_results.jsonl').read_text().splitlines()]
    if len(actual)!=len(expected):raise RuntimeError('C++ omitted common vectors')
    for index,(a,b) in enumerate(zip(actual,expected)):
        if a!=b:raise RuntimeError(f'C++/Python disagreement case={index}, fields={[k for k in b if a.get(k)!=b[k]]}; investigate specification')
    bank_text,_=call([executable,'banks'],out,'banks.log')
    mappings=[int(n) for n in bank_text.split()]
    assert mappings==[BankLayout(swizzle=bool(s)).decode(w)[0] for s in (0,1) for w in range(4096)]
    dll=build_shared(source[:2],out)
    api_checks(dll)
    native,native_wall=call([executable,'benchmark'],out,'cpp_benchmark.jsonl')
    cpp=[json.loads(line) for line in native.splitlines()]
    # Fresh process: retained cross-check corpora must not inflate Python's
    # memory peak or allocator state in a model-only benchmark.
    _,python_wall=call([sys.executable,ROOT/'scripts/run_cpp_reference.py','--python-benchmark-worker',out/'python_benchmark.json'],out,'python_benchmark.log')
    python=json.loads((out/'python_benchmark.json').read_text())
    comparison=[]
    for p,c in zip(python,cpp):
        assert (p['side'],p['loops'])==(c['side'],c['loops'])
        def summary(record):
            samples=record['ns_per_descriptor']
            return {**record,'median_ns':statistics.median(samples),'min_ns':min(samples),'max_ns':max(samples),
                    'elements_per_second':record['elements']*1e9/statistics.median(samples)}
        p,c=summary(p),summary(c)
        comparison.append({'side':p['side'],'python':p,'cpp':c,'pure_model_ratio':p['median_ns']/c['median_ns']})
    assert hashes=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES}
    version,_=call([compiler(),'--version'],out,'compiler_version.log')
    result={'status':'pass','scope':'standalone models and C API; no RTL/UVM execution',
            'timestamp_utc':datetime.now(timezone.utc).isoformat(),'compiler':version,'python':platform.python_version(),
            'flags':['-std=c++17','-O2','-Wall','-Wextra','-Werror'],'sha256':hashes,
            'cpp_directed_tests':21,'python_cpp_cases':len(expected),'bank_mappings':len(mappings),'c_api_lifecycles':100,
            'seeds':[20261029,57,991],'common_vectors_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
            'benchmark':comparison,'cpp_benchmark_process_wall_seconds':native_wall,
            'python_benchmark_process_wall_seconds':python_wall,
            'benchmark_contract':'Both public copy APIs validate memory values, materialize complete read/write traces and a complete destination copy. Each backend runs in its own fresh benchmark process without retained cross-validation corpora. Input initialization, compilation and process launch excluded from pure computation samples. Seven repetitions after three warmups. >4096-word endpoints are synthetic reference-model scaling, not RTL capacity. Process peak working set includes runtime and is cumulative across ascending sizes; Python traced allocation is a separate metric.'}
    (out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    pointer.write_text(json.dumps({'record':(out/'results.json').relative_to(ROOT).as_posix()})+'\n')
    print(f'CPP_REFERENCE_PASS tests=21 cross_cases={len(expected)} bank_mappings={len(mappings)} api_lifecycles=100',flush=True)
    for r in comparison:print(f"MODEL_BENCH side={r['side']} python_us={r['python']['median_ns']/1000:.2f} cpp_us={r['cpp']['median_ns']/1000:.2f} ratio={r['pure_model_ratio']:.2f}",flush=True)


if __name__=='__main__':
    if not __debug__:raise RuntimeError('Verification checks require Python without -O')
    if len(sys.argv)==3 and sys.argv[1]=='--python-benchmark-worker':
        Path(sys.argv[2]).write_text(json.dumps(python_bench(),indent=2)+'\n')
    else:main()
