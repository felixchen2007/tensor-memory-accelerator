package require ::quartus::jtag
package require ::quartus::insystem_source_probe
set hardware [get_hardware_names]
puts "HARDWARE=$hardware"
set cable ""
foreach entry $hardware {
    if {[string match {*USB-Blaster*USB-0*} $entry]} {set cable $entry;break}
}
if {$cable eq ""} {error "Expected USB-Blaster cable is absent"}
set devices [get_device_names -hardware_name $cable]
puts "DEVICES=$devices"
if {[llength $devices]!=1} {error "Expected exactly one FPGA in the chain"}
set device [lindex $devices 0]
if {![string match {*10M50*} $device]} {error "Expected the DE10-Lite 10M50 FPGA"}
set probes [get_insystem_source_probe_instance_info -hardware_name $cable -device_name $device]
puts "PROBES=$probes"
set trace_present 0
foreach probe $probes {
    if {[lindex $probe 0]==1 && [lindex $probe 2]==256} {set trace_present 1}
}
start_insystem_source_probe -hardware_name $cable -device_name $device
for {set sample 0} {$sample<3} {incr sample} {
    puts "TMA_PROBE_HEX=[read_probe_data -instance_index 0 -value_in_hex]"
    if {$trace_present} {puts "TMA_READ_TRACE_HEX=[read_probe_data -instance_index 1 -value_in_hex]"}
    after 100
}
end_insystem_source_probe
