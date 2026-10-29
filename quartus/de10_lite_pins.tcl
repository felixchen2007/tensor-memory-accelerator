# Terasic DE10-Lite user manual, downloaded from resource page on 2026-10-27.
# PDF footer October 17, 2022: Tables 3-2, 3-5, 3-12 (printed pp24,27,38).
# See docs/sdram.md for the source URL and physical-board validation gate.
set_location_assignment PIN_P11 -to MAX10_CLK1_50
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to MAX10_CLK1_50
foreach signal {DRAM_ADDR DRAM_BA DRAM_DQ LEDR} pins {
    {U17 W19 V18 U18 U19 T18 T19 R18 P18 P19 T20 P20 R20}
    {T21 T22}
    {Y21 Y20 AA22 AA21 Y22 W22 W20 V21 P21 J22 H21 H22 G22 G20 G19 F22}
    {A8 A9 A10 B10 D13 C13 E14 D14 A11 B11}
} {
    set index 0
    foreach pin $pins {
        set port [format {%s[%d]} $signal $index]
        set_location_assignment PIN_$pin -to $port
        set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to $port
        if {$signal eq "LEDR"} {
            set_instance_assignment -name CURRENT_STRENGTH_NEW "4MA" -to $port
        } else {
            set_instance_assignment -name CURRENT_STRENGTH_NEW "8MA" -to $port
        }
        incr index
    }
}
foreach {signal pin} {
    DRAM_LDQM V22 DRAM_UDQM J21 DRAM_RAS_N U22 DRAM_CAS_N U21
    DRAM_CKE N22 DRAM_CLK L14 DRAM_WE_N V20 DRAM_CS_N U20
} {
    set_location_assignment PIN_$pin -to $signal
    set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to $signal
    set_instance_assignment -name CURRENT_STRENGTH_NEW "8MA" -to $signal
}
# Diagnostic: force the continuously clocked DQ capture into the logic array,
# so the next hardware run independently checks the IOE input-register path.
set_instance_assignment -name FAST_INPUT_REGISTER OFF -to {DRAM_DQ[*]}
foreach signal {DRAM_ADDR[*] DRAM_BA[*] DRAM_RAS_N DRAM_CAS_N DRAM_WE_N DRAM_LDQM DRAM_UDQM DRAM_DQ[*]} {
    set_instance_assignment -name FAST_OUTPUT_REGISTER ON -to $signal
}
set_instance_assignment -name FAST_OUTPUT_ENABLE_REGISTER ON -to {DRAM_DQ[*]}
