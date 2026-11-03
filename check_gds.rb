layout = RBA::Layout::new
layout.read(ENV["CHECK_GDS"])
puts "cells=#{layout.cells.size} dbu=#{layout.dbu}"
