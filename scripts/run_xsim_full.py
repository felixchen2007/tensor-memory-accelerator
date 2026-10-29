"""Launch the existing XSim UVM runner through a Windows short-path alias.

Vivado 2025.2's Tcl launch path splits absolute coverage directories containing
spaces even when native option files quote them. This adapter changes only the
checkout's filesystem spelling, not stimulus, checks or verification sources.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_dpi_uvm_tests as runner


def main():
    if '--sim' in sys.argv and sys.argv[sys.argv.index('--sim')+1]!='xsim':
        raise RuntimeError('This launcher is specifically for XSim')
    alias=ROOT
    if os.name=='nt' and ' ' in str(ROOT):
        getshort=ctypes.windll.kernel32.GetShortPathNameW
        getshort.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32]
        buffer=ctypes.create_unicode_buffer(32768)
        if not getshort(str(ROOT),buffer,len(buffer)) or ' ' in buffer.value:
            raise RuntimeError('No space-free Windows alias is available; use a checkout path without spaces for XSim coverage')
        alias=Path(buffer.value)
        if not os.path.samefile(alias,ROOT):raise RuntimeError('Windows alias resolved to a different checkout')
    runner.ROOT=alias
    runner.main()
    pointer=json.loads((ROOT/'build/cpp_reference/current_uvm.json').read_text())
    record=ROOT/pointer['record']
    result=json.loads(record.read_text())
    result['launch_adapter']={'source':'scripts/run_xsim_full.py',
        'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'same_checkout_verified':True,'short_path_alias_used':alias!=ROOT,
        'scope':'Filesystem path alias only; original runner, stimulus, model and checkers unchanged'}
    record.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
