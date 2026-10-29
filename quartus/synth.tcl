# Standalone analysis and synthesis, not a fitted or board-programmable project.
package require ::quartus::project
package require ::quartus::flow

set project_root [file normalize [file join [file dirname [info script]] ..]]
set top_name tma_addr_gen
if {[llength $argv] > 0} { set top_name [lindex $argv 0] }
if {$top_name ni {tma_addr_gen tma_copy_engine tma_copy_engine_pipelined tma_scratchpad tma_scratchpad_endpoint tma_local_copy_system tma_local_copy_pipelined tma_scratchpad_swizzled tma_local_copy_swizzled}} {
    error "Unsupported top level: $top_name"
}
set build_dir [file join $project_root build quartus]
if {$top_name eq "tma_copy_engine"} { set build_dir [file join $build_dir copy_engine] }
if {$top_name eq "tma_scratchpad"} { set build_dir [file join $build_dir scratchpad] }
if {$top_name eq "tma_scratchpad_endpoint"} { set build_dir [file join $build_dir scratchpad_endpoint] }
if {$top_name eq "tma_local_copy_system"} { set build_dir [file join $build_dir local_copy] }
if {$top_name eq "tma_copy_engine_pipelined"} { set build_dir [file join $build_dir pipeline] }
if {$top_name eq "tma_local_copy_pipelined"} { set build_dir [file join $build_dir local_copy_pipelined] }
if {$top_name eq "tma_scratchpad_swizzled"} { set build_dir [file join $build_dir scratchpad_swizzled] }
if {$top_name eq "tma_local_copy_swizzled"} { set build_dir [file join $build_dir local_copy_swizzled] }
file mkdir $build_dir
cd $build_dir

project_new $top_name -overwrite
set_global_assignment -name FAMILY "MAX 10"
set_global_assignment -name DEVICE 10M50DAF484C7G
set entity_name $top_name
if {$top_name in {tma_local_copy_pipelined tma_local_copy_swizzled}} { set entity_name tma_local_copy_system }
if {$top_name eq "tma_scratchpad_swizzled"} { set entity_name tma_scratchpad }
set_global_assignment -name TOP_LEVEL_ENTITY $entity_name
if {$top_name in {tma_local_copy_pipelined tma_local_copy_swizzled}} { set_parameter -name PIPELINED 1 }
if {$top_name in {tma_scratchpad_swizzled tma_local_copy_swizzled}} {
    set_parameter -name SWIZZLE 1
    set_parameter -name SWIZZLE_SHIFT 5
}
set_global_assignment -name SYSTEMVERILOG_FILE [file join $project_root rtl tma_addr_gen.sv]
if {$entity_name in {tma_copy_engine tma_local_copy_system}} {
    set_global_assignment -name SYSTEMVERILOG_FILE [file join $project_root rtl tma_copy_engine.sv]
}
if {$entity_name in {tma_copy_engine_pipelined tma_local_copy_system}} {
    set_global_assignment -name SYSTEMVERILOG_FILE [file join $project_root rtl tma_copy_engine_pipelined.sv]
}
if {$entity_name eq "tma_local_copy_system"} {
    set_global_assignment -name SYSTEMVERILOG_FILE [file join $project_root rtl tma_copy_engine_select.sv]
}
if {$entity_name in {tma_scratchpad tma_scratchpad_endpoint tma_local_copy_system}} {
    foreach rtl_file {tma_ram_bank.sv tma_scratchpad.sv} {
        set_global_assignment -name SYSTEMVERILOG_FILE [file join $project_root rtl $rtl_file]
    }
}
if {$entity_name in {tma_scratchpad_endpoint tma_local_copy_system}} {
    set_global_assignment -name SYSTEMVERILOG_FILE [file join $project_root rtl tma_scratchpad_endpoint.sv]
}
if {$entity_name eq "tma_local_copy_system"} {
    set_global_assignment -name SYSTEMVERILOG_FILE [file join $project_root rtl tma_local_copy_system.sv]
}
set_global_assignment -name SDC_FILE [file join $project_root quartus tma_addr_gen.sdc]
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files
set_global_assignment -name NUM_PARALLEL_PROCESSORS 2
export_assignments
if {[catch {execute_module -tool map} result]} {
    post_message -type error $result
    project_close
    exit 1
}
project_close
