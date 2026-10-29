package require ::quartus::project
package require ::quartus::sta
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
cd $build_dir
project_open tma_de10_lite
create_timing_netlist -model slow
read_sdc
update_timing_netlist
report_timing -setup -npaths 20 -detail full_path -file [file join $build_dir board_setup.rpt]
report_timing -hold -npaths 20 -detail full_path -file [file join $build_dir board_hold.rpt]
report_ucp -file [file join $build_dir board_unconstrained.rpt]
delete_timing_netlist
project_close
