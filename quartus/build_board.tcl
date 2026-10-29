# Full compile, including fitter and timing. Does NOT program the board.
package require ::quartus::project
package require ::quartus::flow
set root [file normalize [file join [file dirname [info script]] ..]]
set pipeline 1
if {[llength $quartus(args)]>0} {set pipeline [lindex $quartus(args) 0]}
if {$pipeline ni {0 1}} {error "PIPELINED must be 0 or 1"}
set read_burst 1
if {[llength $quartus(args)]>1} {set read_burst [lindex $quartus(args) 1]}
if {$read_burst ni {1 4}} {error "READ_BURST_WORDS must be 1 or 4"}
set suffix [expr {$pipeline ? "" : "_serialized"}]
if {$read_burst==4} {append suffix "_burst4"}
set build_dir [file join $root build quartus de10_lite$suffix]
file mkdir $build_dir
cd $build_dir
project_new tma_de10_lite -overwrite
set_global_assignment -name FAMILY "MAX 10"
set_global_assignment -name DEVICE 10M50DAF484C7G
set_global_assignment -name TOP_LEVEL_ENTITY tma_de10_lite
set_parameter -name PIPELINED $pipeline
set_parameter -name READ_BURST_WORDS $read_burst
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files
set_global_assignment -name NUM_PARALLEL_PROCESSORS 2
set_global_assignment -name RESERVE_ALL_UNUSED_PINS "AS INPUT TRI-STATED"
foreach name {tma_addr_gen tma_copy_engine tma_copy_engine_pipelined tma_copy_engine_select
    tma_ram_bank tma_scratchpad tma_scratchpad_endpoint tma_sdram_controller
    tma_sdram_copy_system tma_sdram_selftest tma_board_clocks tma_de10_lite} {
    set_global_assignment -name SYSTEMVERILOG_FILE [file join $root rtl $name.sv]
}
set_global_assignment -name SDC_FILE [file join $root quartus de10_lite.sdc]
source [file join $root quartus de10_lite_pins.tcl]
export_assignments
if {[catch {execute_flow -compile} result]} {
    post_message -type error $result
    project_close
    exit 1
}
project_close
