"""Local C++/simulator tools. Build and log each simulator library separately."""
from pathlib import Path
import os
import shutil
import subprocess
import time
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def compiler():
    candidate = os.environ.get('TMA_CXX') or shutil.which('g++')
    if not candidate:
        raise RuntimeError('Set TMA_CXX to a C++17 g++ compiler')
    return Path(candidate)


def vivado():
    candidates = [Path(os.environ['VIVADO_BIN'])] if os.environ.get('VIVADO_BIN') else []
    for location in ('D:/AMDDesignTools', 'C:/AMDDesignTools', 'C:/Xilinx/Vivado', 'D:/Xilinx/Vivado'):
        base = Path(location)
        if base.is_dir():
            candidates += sorted(base.glob('*/Vivado/bin'), reverse=True)
            candidates += sorted(base.glob('*/bin'), reverse=True)
    return next((p for p in candidates if (p/'xsim.bat').is_file()), None)


def call(command, output, name, timeout=300):
    start = time.perf_counter()
    env=os.environ.copy()
    # Generated XSim executables need Vivado's SJLJ runtime, not an unrelated
    # libstdc++-6.dll earlier on the user's compiler PATH.
    if 'AMDDesignTools' in str(command[0]):
        root=vivado()
        if root:
            native=root.parent/'tps/mingw/6.2.0/win64.o/nt/bin'
            env['PATH']=str(native)+os.pathsep+env.get('PATH','')
    run = subprocess.run([str(v) for v in command], cwd=output, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         errors='replace', timeout=timeout,env=env)
    (output/name).write_text(run.stdout, encoding='utf-8')
    if run.returncode:
        raise RuntimeError(f'{name}: exit {run.returncode}\n{run.stdout[-5000:]}')
    return run.stdout, time.perf_counter()-start


def build_shared(sources, output, name='tma_reference'):
    suffix = '.dll' if os.name == 'nt' else '.so'
    binary = output/(name+suffix)
    command = [compiler(), '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared']
    command += ['-static-libgcc', '-static-libstdc++'] if os.name == 'nt' else ['-fPIC']
    command += [*sources, '-o', binary]
    call(command, output, name+'_build.log')
    return binary


def xsim_bridge(dll, sources, output, name):
    """XSim Windows links a GCC6 static archive; keep C++17 behind plain C ABI.

    No STL object, exception or allocation crosses this native C bridge. The
    same DLL owns each model handle from construction through destruction.
    """
    tool=vivado()
    native=tool.parent/'tps/mingw/6.2.0/win64.o/nt/bin'
    definitions=[]
    for source in sources:
        definitions+=re.findall(r'^TMA_API\s+([^\n]+?)\s+(tma_\w+)\((.*?)\)\s+noexcept',
                                Path(source).read_text(),re.M|re.S)
    if not definitions:raise RuntimeError('No C ABI definitions for XSim bridge')
    body=['#include <windows.h>\n#include <cstdio>\n#include <cstdlib>\n',
          'static FARPROC resolve(const char* name) {\n',
          'static HMODULE library=LoadLibraryA('+json.dumps(str(dll))+');\n',
          'FARPROC function=library ? GetProcAddress(library,name):nullptr;\n',
          'if(!function){std::fprintf(stderr,"TMA_DPI_LOAD_ERROR %s code=%lu\\n",name,GetLastError());std::abort();}\n',
          'return function;}\n']
    for ret,fn,params in definitions:
        params=' '.join(params.split())
        names=[re.search(r'(\w+)\s*$',p).group(1) for p in params.split(',') if p.strip()]
        body.append(f'extern "C" {ret} {fn}({params}) {{ using F={ret}(*)({params}); '
                    f'static F function=reinterpret_cast<F>(resolve("{fn}")); return function({",".join(names)}); }}\n')
    bridge=output/(name+'_bridge.cpp');bridge.write_text(''.join(body),encoding='utf-8')
    obj=output/(name+'_bridge.o');archive=output/(name+'.a')
    call([native/'g++.exe','-std=c++11','-O2','-c',bridge,'-o',obj],output,name+'_bridge_compile.log')
    call([native/'ar.exe','rcs',archive,obj],output,name+'_bridge_archive.log')
    return archive
