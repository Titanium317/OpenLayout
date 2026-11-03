# OpenLayout stage 4 — routing + post-route optimization
# (Innovus routeDesign + optDesign -postRoute analogue: global route,
# GRT-based parasitics, repair_design/repair_timing, incremental reroute,
# detailed route, final STA + DRC report).
# Defaults follow the settings proven DRC-clean on bp_fe (adjustment 0.3,
# signal metal2-metal9, droute_end_iter 8).

if {![info exists data_dir]}    { set data_dir "." }
if {![info exists tech_dir]}   { set tech_dir ${data_dir} }
if {![info exists proj_name]}   { set proj_name "design" }
if {![info exists sdc_file]}    { set sdc_file ${data_dir}/constraint.sdc }
if {![info exists save_dir]}    { set save_dir ./saves_db }
if {![info exists report_dir]}  { set report_dir ./reports }
if {![info exists image_dir]}   { set image_dir ./images }
if {![info exists tag]}         { set tag route }
if {![info exists in_odb]}      { set in_odb ${save_dir}/03_cts.odb }
if {![info exists out_odb]}     { set out_odb ${save_dir}/04_route.odb }
if {![info exists num_threads]} { set num_threads 8 }
# --- tunables ---
if {![info exists layer_adjustment]}       { set layer_adjustment 0.3 }
if {![info exists sig_min_layer]}          { set sig_min_layer metal2 }
if {![info exists sig_max_layer]}          { set sig_max_layer metal9 }
if {![info exists clk_min_layer]}          { set clk_min_layer metal3 }
if {![info exists clk_max_layer]}          { set clk_max_layer metal7 }
if {![info exists congestion_iterations]}  { set congestion_iterations 30 }
if {![info exists droute_end_iter]}        { set droute_end_iter 8 }
if {![info exists post_grt_repair_design]} { set post_grt_repair_design 1 }
if {![info exists post_grt_repair_setup]}  { set post_grt_repair_setup 1 }
if {![info exists post_grt_repair_hold]}   { set post_grt_repair_hold 1 }
if {![info exists hold_margin]}            { set hold_margin 0.05 }
if {![info exists stdcell_lib]}            { set stdcell_lib ${tech_dir}/lib/NangateOpenCellLibrary_typical.lib }
if {![info exists rc_signal_layer]}        { set rc_signal_layer metal3 }
if {![info exists rc_clock_layer]}         { set rc_clock_layer metal5 }
if {![info exists extra_libs]}              { set extra_libs {} }
file mkdir $save_dir $report_dir $image_dir

define_corners tt
read_liberty -corner tt ${stdcell_lib}
foreach _l [glob -nocomplain ${data_dir}/lib/*.lib] {
    if {$_l eq $stdcell_lib} continue
    read_liberty -corner tt $_l
}
foreach _extra_lib $extra_libs {
    if {[file exists $_extra_lib]} { read_liberty -corner tt $_extra_lib }
}
read_db ${in_odb}
read_sdc ${sdc_file}
catch {set_wire_rc -signal -layer $rc_signal_layer}
catch {set_wire_rc -clock -layer $rc_clock_layer}
set_thread_count $num_threads
set_propagated_clock [all_clocks]

set_global_routing_layer_adjustment ${sig_min_layer}-${sig_max_layer} $layer_adjustment
set_routing_layers -signal ${sig_min_layer}-${sig_max_layer} \
                   -clock  ${clk_min_layer}-${clk_max_layer}

utl::report "Global routing"
if {[catch {global_route -guide_file ${report_dir}/${tag}.guide \
             -congestion_iterations $congestion_iterations -verbose} _grt_err]} {
    puts "OL_WARN global route completed with congestion: $_grt_err"
}
catch {estimate_parasitics -global_routing} _est_err
utl::report "GLOBAL_ROUTE_DONE"

# ---- post-GRT optimization (parasitics now realistic) ----
if {$post_grt_repair_design} {
    utl::report "Repair design"
    repair_design
}
if {$post_grt_repair_setup} {
    utl::report "Repair setup"
    repair_timing -setup -max_buffer_percent 20 -max_utilization 90
}
if {$post_grt_repair_hold} {
    utl::report "Repair hold"
    repair_timing -hold -hold_margin $hold_margin
}
if {$post_grt_repair_design || $post_grt_repair_setup || $post_grt_repair_hold} {
    utl::report "Detailed placement (legalize repair cells)"
    detailed_placement
    utl::report "Global routing (after repair)"
    if {[catch {global_route -guide_file ${report_dir}/${tag}.guide \
                 -congestion_iterations $congestion_iterations -verbose} _grt2_err]} {
        puts "OL_WARN post-repair global route completed with congestion: $_grt2_err"
    }
    catch {estimate_parasitics -global_routing} _est2_err
}

utl::report "Detailed routing (droute_end_iter ${droute_end_iter})"
if {[catch {detailed_route -output_drc      ${report_dir}/${tag}.drc.rpt \
               -output_maze     ${report_dir}/${tag}.maze.log \
               -droute_end_iter $droute_end_iter \
               -verbose 1} _drt_err]} {
    puts "OL_WARN detailed route incomplete; preserving partial routed DB: $_drt_err"
}
if {[catch {estimate_parasitics -global_routing} _est3_err]} {
    puts "OL_WARN final global-routing parasitics unavailable: $_est3_err"
}

report_clock_skew > ${report_dir}/${tag}.clock_skew.rpt
report_checks -path_delay max -group_count 10 > ${report_dir}/${tag}.setup.rpt
report_checks -path_delay min -group_count 10 > ${report_dir}/${tag}.hold.rpt
report_worst_slack -max
report_worst_slack -min
report_tns
report_design_area
# (no report_wire_length here: this build requires -net and prints an ERROR
# line even under catch; detailed_route already logs the total wire length)

write_db ${out_odb}
write_def ${save_dir}/${tag}.routed.def
puts "OL_STAGE_DONE route"
