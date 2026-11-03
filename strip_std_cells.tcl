read_db /data/taiyuzhou/net2GDS/final_test_dataset/tasks/final_test_relaxed_netlist_nangate45_bp_fe_20261020/work/results/nangate45/bp_fe/base/2_floorplan.odb
set b [ord::get_db_block]
set n 0
foreach i [$b getInsts] {
  if {![[$i getMaster] isBlock]} { odb::dbInst_destroy $i; incr n }
}
puts "removed_std_cells=$n"
write_def /data/taiyuzhou/OpenLayout/Benchmark/CurrentNet2GDS/bp_fe/def/macro_floorplan.def
