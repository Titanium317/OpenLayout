# OpenLayout stage 0 — init/floorplan.
# Loads libs/LEFs/netlist and the PREDEFINED floorplan DEF, sets layer RC,
# prints design facts (macro count, cells, core area, clocks) and writes the
# pristine floorplan checkpoint. Adapted from skills_Nangate45/0.init.

if {![info exists data_dir]}     { set data_dir "." }
if {![info exists tech_dir]}     { set tech_dir ${data_dir} }
if {![info exists proj_name]}    { set proj_name "design" }
if {![info exists top_design]}   { set top_design $proj_name }
if {![info exists netlist_file]} { set netlist_file ${data_dir}/${proj_name}.v }
if {![info exists sdc_file]}     { set sdc_file ${data_dir}/constraint.sdc }
if {![info exists fp_def]}       { set fp_def ${data_dir}/def/1_1_u60_floorplan.def }
if {![info exists save_dir]}     { set save_dir ./saves_db }
if {![info exists report_dir]}   { set report_dir ./reports }
if {![info exists image_dir]}    { set image_dir ./images }
if {![info exists tag]}          { set tag floorplan }
if {![info exists out_odb]}      { set out_odb ${save_dir}/00_floorplan.odb }
if {![info exists platform]}     { set platform nangate45 }
if {![info exists stdcell_lib]}  { set stdcell_lib ${tech_dir}/lib/NangateOpenCellLibrary_typical.lib }
if {![info exists tech_lef]}     { set tech_lef ${tech_dir}/lef/NangateOpenCellLibrary.tech.lef }
if {![info exists cell_lef]}     { set cell_lef ${tech_dir}/lef/NangateOpenCellLibrary.macro.mod.lef }
if {![info exists extra_cell_lefs]} { set extra_cell_lefs {} }
if {![info exists extra_libs]}     { set extra_libs {} }
if {![info exists site_name]}    { set site_name FreePDK45_38x28_10R_NP_162NW_34O }
if {![info exists rc_signal_layer]} { set rc_signal_layer metal3 }
if {![info exists rc_clock_layer]}  { set rc_clock_layer metal5 }
file mkdir $save_dir $report_dir $image_dir

# PDK (std cells + tech LEF) from tech_dir; design macros from data_dir.
set pdk_cells_lib ${tech_dir}/lib
set pdk_cells_lef ${tech_dir}/lef
set design_lib    ${data_dir}/lib
set design_lef    ${data_dir}/lef

define_corners tt
puts "Init standard cells"
read_liberty -corner tt ${stdcell_lib}

puts "Init tech-lef"
read_lef ${tech_lef}
puts "Init cell-lef"
read_lef ${cell_lef}
foreach _extra_lef $extra_cell_lefs {
    if {[file exists $_extra_lef]} { read_lef $_extra_lef }
}

# Every non-stdcell LEF/LIB in the circuit's dirs (fakeram + custom macros).
puts "Init macro lef"
foreach _lef [lsort [glob -nocomplain ${design_lef}/*.lef]] {
    if {$_lef eq $tech_lef || $_lef eq $cell_lef} { continue }
    if {$platform ne "nangate45" && ([string match "*tech.lef" $_lef] ||
        [string match "*.tlef" $_lef] || [string match "*stdcell*" $_lef] ||
        [string match "*_sc.lef" $_lef] || [string match "*_merged.lef" $_lef])} { continue }
    puts "  read_lef $_lef"
    read_lef $_lef
}
puts "Init macro liberty"
foreach _lib [lsort [glob -nocomplain ${design_lib}/*.lib]] {
    if {$_lib eq $stdcell_lib} { continue }
    if {$platform ne "nangate45" && ([string match "*stdcell*" $_lib] ||
        [string match "*fd_sc*" $_lib] || [string match "*mcu*" $_lib])} { continue }
    puts "  read_liberty $_lib"
    read_liberty -corner tt $_lib
}
foreach _extra_lib $extra_libs {
    if {[file exists $_extra_lib]} { read_liberty -corner tt $_extra_lib }
}

read_verilog ${netlist_file}
link_design ${top_design}
if {$fp_def ne "" && [file exists $fp_def]} {
  read_def $fp_def
} else {
  if {$platform eq "nangate45" && $proj_name eq "bp_fe" && [file exists [file join $data_dir def macro_coords.tcl]]} {
    # Match the frozen macro envelope while trimming the unusable top sliver
    # above the highest macro (it otherwise creates three PDN-0178 channels).
    initialize_floorplan -die_area {0 0 658.68 658.68} \
        -core_area {2.28 2.80 656.26 654.00} \
        -site $site_name
  } else {
    # Per-design sizing is essential for the batch: a fixed bp_fe core makes
    # small designs appear artificially under-utilized.
    initialize_floorplan -utilization 50 -aspect_ratio 1.0 -core_space 2.28 \
        -site $site_name
  }
}
make_tracks

# Optional macro seed for a netlist-driven floorplan.  This preserves the
# known-good macro locations from the user's frozen checkpoint while keeping
# all standard-cell instances unplaced, so PDN sees clean rows.
set _macro_seed [file join $data_dir def macro_coords.tcl]
if {[file exists $_macro_seed]} {
  source $_macro_seed
  set _blk [ord::get_db_block]
  set _dbu [[ord::get_db_tech] getDbUnitsPerMicron]
  foreach _e $imported_macro_coords {
    lassign $_e _name _x _y _or
    set _i [$_blk findInst $_name]
    if {$_i eq "NULL" || $_i eq ""} { set _i [$_blk findInst [string map {/ \\/} $_name]] }
    if {$_i ne "NULL" && $_i ne ""} {
      array set _omap {N R0 S R180 E R90 W R270 FN MX FS MY FE MYR90 FW MXR90}
      if {[info exists _omap($_or)]} { set _or $_omap($_or) }
      $_i setOrient $_or
      $_i setLocation [expr {int($_x * $_dbu)}] [expr {int($_y * $_dbu)}]
      $_i setPlacementStatus FIRM
    }
  }
}
read_sdc ${sdc_file}

# Nangate45 RC (liberty units fF,kOhm). Other platforms carry RC in their
# technology LEF/ORFS setup; only set explicit values for the reference PDK.
if {$platform eq "nangate45"} {
  set_layer_rc -layer metal1 -resistance 5.4286e-03 -capacitance 7.41819E-02
  set_layer_rc -layer metal2 -resistance 3.5714e-03 -capacitance 6.74606E-02
  set_layer_rc -layer metal3 -resistance 3.5714e-03 -capacitance 8.88758E-02
  set_layer_rc -layer metal4 -resistance 1.5000e-03 -capacitance 1.07121E-01
  set_layer_rc -layer metal5 -resistance 1.5000e-03 -capacitance 1.08964E-01
  set_layer_rc -layer metal6 -resistance 1.5000e-03 -capacitance 1.02044E-01
  set_layer_rc -layer metal7 -resistance 1.8750e-04 -capacitance 1.10436E-01
  set_layer_rc -layer metal8 -resistance 1.8750e-04 -capacitance 9.69714E-02
}
if {[catch {set_wire_rc -signal -layer $rc_signal_layer}]} {}
if {[catch {set_wire_rc -clock -layer $rc_clock_layer}]} {}

# ---- design facts (parsed by the flow into the design context) ----
set _blk [ord::get_db_block]
set _nmacro 0
set _ninst 0
foreach _i [$_blk getInsts] {
    incr _ninst
    if {[[$_i getMaster] isBlock]} { incr _nmacro }
}
set _dbu  [[ord::get_db_tech] getDbUnitsPerMicron]
set _core [$_blk getCoreArea]
set _cw [expr {([$_core xMax]-[$_core xMin])/double($_dbu)}]
set _ch [expr {([$_core yMax]-[$_core yMin])/double($_dbu)}]
puts "OL_FACT num_instances $_ninst"
puts "OL_FACT num_macros $_nmacro"
puts "OL_FACT core_width_um [format %.2f $_cw]"
puts "OL_FACT core_height_um [format %.2f $_ch]"
puts "OL_FACT core_bbox_um [format %.3f [expr {[$_core xMin]/double($_dbu)}]] [format %.3f [expr {[$_core yMin]/double($_dbu)}]] [format %.3f [expr {[$_core xMax]/double($_dbu)}]] [format %.3f [expr {[$_core yMax]/double($_dbu)}]]"
# macro sizes (unoriented master W H) for the Python macro legalizer
foreach _i [$_blk getInsts] {
    set _m [$_i getMaster]
    if {[$_m isBlock]} {
        puts "OL_MACRO [$_i getName] [format %.3f [expr {[$_m getWidth]/double($_dbu)}]] [format %.3f [expr {[$_m getHeight]/double($_dbu)}]]"
    }
}
foreach _clk [all_clocks] {
    puts "OL_FACT clock [get_name $_clk] period_ns [get_property $_clk period]"
}
report_design_area

write_db ${out_odb}
write_def ${save_dir}/00_floorplan.def
puts "OL_STAGE_DONE floorplan"
