
#set limits (don't change unless you're running local):
#if running remote, increasing threads will potentially cause your code to submission to get bounced
#due to a process watchdog.
set_param general.maxThreads 16
#Define target part and create output directory

# The ??? uses this chip:
# ??? refers to the fact that it is a ???
# ??? refers to its package it is in
# ??? to the "speed grade" of the chip

# set partNum xc7a200t-fbg484-1
set partNum xc7k325t-ffg900-2
set outputDir obj_wyf
file mkdir $outputDir
set files [glob -nocomplain "$outputDir/*"]
# if {[llength $files] != 0} {
#     # clear folder contents
#     puts "deleting contents of $outputDir"
#     file delete -force {*}[glob -directory $outputDir *];
# } else {
#     puts "$outputDir is empty"
# }

# read in all system verilog files:
set sources_sv [ concat \
    [ glob ./hdl/*.sv ]
]
read_verilog -sv $sources_sv

# read in all (if any) verilog files:
set sources_v [ concat \
    [ glob -nocomplain ./hdl/clk_wiz_100mhz.v ]
]
if {[llength $sources_v] > 0 } {
    read_verilog $sources_v
}

# read in constraint files:
read_xdc ./xdc/genesys2.xdc

# read in all (if any) hex memory files:
set sources_mem [ glob -nocomplain ./data/*.mem ]
if {[llength $sources_mem] > 0} {
    read_mem $sources_mem
}

# set the part number so Vivado knows how to build (each FPGA is different)
set_part $partNum

# Read in and synthesize all IP (first used in week 04!)
set sources_ip [ glob -nocomplain -directory ./ip -tails * ]
puts $sources_ip
foreach ip_source $sources_ip {
    if {[file isdirectory ./ip/$ip_source]} {
	read_ip ./ip/$ip_source/$ip_source.xci
    }
}
generate_target all [get_ips]
synth_ip [get_ips]

#Run Synthesis
synth_design -top top_level -part $partNum -verbose
#write_checkpoint -force $outputDir/post_synth.dcp
report_timing_summary -file $outputDir/post_synth_timing_summary.rpt
report_utilization -file $outputDir/post_synth_util.rpt -hierarchical -hierarchical_depth 16
report_timing -file $outputDir/post_synth_timing.rpt

#run optimization
opt_design
place_design
report_clock_utilization -file $outputDir/clock_util.rpt

#get timing violations and run optimizations if needed
if {[get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] < 0} {
 puts "Found setup timing violations => running physical optimization"
 phys_opt_design
}
#write_checkpoint -force $outputDir/post_place.dcp
report_utilization -file $outputDir/post_place_util.rpt
report_timing_summary -file $outputDir/post_place_timing_summary.rpt
report_timing -file $outputDir/post_place_timing.rpt
#Route design and generate bitstream
route_design -directive Explore
#write_checkpoint -force $outputDir/post_route.dcp
report_route_status -file $outputDir/post_route_status.rpt
report_timing_summary -file $outputDir/post_route_timing_summary.rpt
report_timing -file $outputDir/post_route_timing.rpt
report_power -file $outputDir/post_route_power.rpt
report_drc -file $outputDir/post_imp_drc.rpt
#set_property SEVERITY {Warning} [get_drc_checks NSTD-1]
#write_verilog -force $outputDir/cpu_impl_netlist.v -mode timesim -sdf_anno true
write_bitstream -force $outputDir/final.bit
