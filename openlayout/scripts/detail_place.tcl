# OpenLayout stage 2 — detailed placement (PDN + global place + resize +
# detailed place). Adapted from skills_Nangate45/2.detail_place, parameterized
# for the Optimizer agent (place_density, halo_um, pdn_pitch, ...).

if {![info exists data_dir]}    { set data_dir "." }
if {![info exists tech_dir]}   { set tech_dir ${data_dir} }
if {![info exists proj_name]}   { set proj_name "design" }
if {![info exists sdc_file]}    { set sdc_file ${data_dir}/constraint.sdc }
if {![info exists save_dir]}    { set save_dir ./saves_db }
if {![info exists report_dir]}  { set report_dir ./reports }
if {![info exists image_dir]}   { set image_dir ./images }
if {![info exists tag]}         { set tag detail_place }
if {![info exists in_odb]}      { set in_odb ${save_dir}/01_macro_placed.odb }
if {![info exists out_odb]}     { set out_odb ${save_dir}/02_detail_place.odb }
if {![info exists num_threads]} { set num_threads 8 }
# --- tunables ---
if {![info exists place_density]}      { set place_density 0.0 }
if {![info exists halo_um]}            { set halo_um 5.0 }
if {![info exists pdn_pitch]}          { set pdn_pitch 30.0 }
if {![info exists routability_driven]} { set routability_driven 1 }
if {![info exists timing_driven]}      { set timing_driven 1 }
if {![info exists run_resizer]}        { set run_resizer 1 }
if {![info exists platform]}           { set platform nangate45 }
if {![info exists stdcell_lib]}        { set stdcell_lib ${tech_dir}/lib/NangateOpenCellLibrary_typical.lib }
if {![info exists rc_signal_layer]}    { set rc_signal_layer metal3 }
if {![info exists rc_clock_layer]}     { set rc_clock_layer metal5 }
if {![info exists place_pin_h]}        { set place_pin_h metal3 }
if {![info exists place_pin_v]}        { set place_pin_v metal2 }
if {![info exists skip_pdn]}            { set skip_pdn 0 }
if {![info exists extra_libs]}          { set extra_libs {} }
file mkdir $save_dir $report_dir $image_dir

# Fresh process: re-establish liberty/SDC after read_db.
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

# Lock macros (pdngen requires FIXED macros).
set _nfix 0
foreach _inst [[ord::get_db_block] getInsts] {
    if {[[$_inst getMaster] isBlock]} { $_inst setPlacementStatus "FIRM"; incr _nfix }
}
utl::report "Fixed $_nfix macros (FIRM) before PDN"

# Keep the imported floorplan rows intact. The frozen checkpoint already
# contains placed macro geometry; cut_rows can leave hundreds of partially
# occupied rows and makes pdngen report false remaining channels.
# Placement-blockage halo around every macro (honored by GPL and DPL).
set _hblk [ord::get_db_block]
set _h [expr {int(0.0 * [$_hblk getDbUnitsPerMicron])}]
set _nhalo 0
foreach _inst [$_hblk getInsts] {
    if {![[$_inst getMaster] isBlock]} { continue }
    set _bb [$_inst getBBox]
    odb::dbBlockage_create $_hblk \
        [expr {[$_bb xMin] - $_h}] [expr {[$_bb yMin] - $_h}] \
        [expr {[$_bb xMax] + $_h}] [expr {[$_bb yMax] + $_h}]
    incr _nhalo
}
utl::report "Added ${halo_um}um placement halo around $_nhalo macros"

##########################################################################
# Global connections + PDN (Nangate45 core-only stripes).  The other
# platforms are allowed to run without a platform-specific PDN recipe; this
# keeps the placement/route/GDS pipeline observable while reporting IR as
# unavailable rather than aborting the design.
if {!$skip_pdn} {
##########################################################################
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {VDD} -power
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {VSS} -ground
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {VDDARRAY} -power
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {VDDARRAY!} -power
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {VDD!} -power
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {VSS!} -ground
global_connect

set_voltage_domain -name {CORE} -power {VDD} -ground {VSS}

# Nangate45 platform grid. The validated ORFS policy uses M1 followpins
# feeding M4 and M7; the previous M8/M9 ring recipe left narrow macro
# channels without a same-net upper strap (PDN-0179).
define_pdn_grid -name {core_grid} -voltage_domains {CORE} -pins {metal7}
add_pdn_stripe -grid {core_grid} -layer {metal1} -width 0.17 \
    -pitch 2.4 -offset 0 -followpins
add_pdn_stripe -grid {core_grid} -layer {metal4} -width 0.48 \
    -pitch $pdn_pitch -offset 0
add_pdn_stripe -grid {core_grid} -layer {metal7} -width 1.40 \
    -pitch $pdn_pitch -offset 0
add_pdn_ring -grid {core_grid} -layer {metal7 metal8} \
    -widths {0.40 0.40} -spacings {0.40 0.40} \
    -core_offsets {0.10 0.10} -add_connect
add_pdn_connect -grid {core_grid} -layers {metal1 metal4}
add_pdn_connect -grid {core_grid} -layers {metal4 metal7}

# ----- Macro power grid: connect macro power pins (metal4 strips on the
# fakerams) up into the core grid so IR analysis (psm) sees a connected net.
if {$_nfix > 0} {
    define_pdn_grid -macro -default -name {macro_grid} \
        -voltage_domains {CORE} -halo "0.0 0.0"
    # Cross-hatch straps (m5 H + m6 V) at tight pitch so every macro power
    # pin strip is crossed regardless of macro orientation/size — a single
    # m5 layer at pitch 20 missed a rotated 64x7 fakeram's ~31um pins.
    add_pdn_stripe -grid {macro_grid} -layer {metal5} -width 0.93 \
        -pitch 10.0 -spacing 2.0 -offset 2.0 -snap_to_grid
    add_pdn_stripe -grid {macro_grid} -layer {metal6} -width 0.93 \
        -pitch 10.0 -spacing 2.0 -offset 2.0 -snap_to_grid
    add_pdn_connect -grid {macro_grid} -layers {metal4 metal5}
    add_pdn_connect -grid {macro_grid} -layers {metal4 metal6}
    add_pdn_connect -grid {macro_grid} -layers {metal5 metal6}
    add_pdn_connect -grid {macro_grid} -layers {metal6 metal7}
}
}

if {!$skip_pdn} {
  if {[catch {pdngen} _pdn_err]} {
    puts "OL_WARN PDN failed; continuing without repaired PDN: $_pdn_err"
  }
}

##########################################################################
# Protect clock-root nets (CTS-0114 otherwise), then place
##########################################################################
if {[llength [all_clocks]] == 0} { catch { read_sdc ${sdc_file} } }
proc clock_root_nets {} {
    set nets {}
    foreach clk [all_clocks] {
        set srcnames {}
        catch { foreach src [get_property $clk sources] { lappend srcnames [get_full_name $src] } }
        foreach pn $srcnames {
            set n [get_nets -quiet -of_objects [get_pins -quiet $pn]]
            if {$n eq ""} { set n [get_nets -quiet $pn] }
            foreach net $n { lappend nets [get_full_name $net] }
        }
    }
    return [lsort -unique $nets]
}
set CLK_NETS [clock_root_nets]
if {[llength $CLK_NETS]} {
    catch { set_dont_touch [get_nets $CLK_NETS] }
    puts "DONT_TOUCH clk nets: $CLK_NETS"
}

utl::report "Remove buffers"
remove_buffers
utl::report "Repair design (pre-place)"
repair_design

# A netlist-driven floorplan has no DEF pin section.  Place top-level pins
# before global placement so GPL does not abort on unplaced ports.
catch { place_pins -hor_layers $place_pin_h -ver_layers $place_pin_v }

# density: 0.0 => auto (uniform density + margin)
set _gp_args {}
if {$place_density > 0.0} { lappend _gp_args -density $place_density }
if {$timing_driven}       { lappend _gp_args -timing_driven }

utl::report "Global Placement (1)"
global_placement {*}$_gp_args

utl::report "Estimate parasitics"
estimate_parasitics -placement
if {$run_resizer} {
    utl::report "Repair design"
    repair_design
    set REPAIR_BOUNDS "-max_buffer_percent 20 -max_utilization 90 -max_passes 50"
    utl::report "Repair setup"
    repair_timing -setup {*}$REPAIR_BOUNDS
}

utl::report "Global Placement (2)"
set _gp2_args $_gp_args
if {$routability_driven} {
    lappend _gp2_args -routability_driven -routability_check_overflow 0.30
}
global_placement {*}$_gp2_args

utl::report "Detailed placement"
detailed_placement
optimize_mirroring
estimate_parasitics -placement

utl::report "Check placement"
if {[catch {check_placement -verbose -report_file_name ${report_dir}/${tag}.place_check.rpt} _place_err]} {
    puts "OL_WARN placement check reported non-legal rows: $_place_err"
}

report_worst_slack -max
report_worst_slack -min
report_tns
report_design_area

write_db ${out_odb}
puts "OL_STAGE_DONE detail_place"
