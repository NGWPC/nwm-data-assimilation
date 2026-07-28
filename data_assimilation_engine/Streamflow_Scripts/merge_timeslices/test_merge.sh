#!/bin/bash

./merge_timeslices.py --help

can_path=/d7/jamesmcc/canadian_data_merge/canadian_data
usa_path=/d7/jamesmcc/canadian_data_merge/us_data
merge_path=/d7/jamesmcc/canadian_data_merge/merge_result
can_slices=($can_path/2019-02-12_00*)
usa_slices=($usa_path/2019-02-12_00*)
out_slices=(`for i in ${usa_slices[*]}; do echo $merge_path$(basename $i); done`)

# Normal usage. 
rm -f ${out_slices[*]}
ls ${out_slices[*]} | wc -l

for ii in `seq 0 $((${#can_slices[@]}-1))`; do
    ./merge_timeslices.py \
         --in_file_new ${can_slices[ii]} \
         --in_file_copy_addto ${usa_slices[ii]} \
         --out_file ${out_slices[ii]}
done

ls ${out_slices[*]}
rm -f ${out_slices[*]}
ls ${out_slices[*]} | wc -l

# Test abnormal operation: trying to merge slices with different times.
# This one failes with a value error on internal file times. 
./merge_timeslices.py \
    --in_file_new ${can_slices[0]} \
    --in_file_copy_addto ${usa_slices[1]} \
    --out_file ${out_slices[1]}

echo $?

# This one succeeds.
./merge_timeslices.py \
    --in_file_new ${can_slices[1]} \
    --in_file_copy_addto ${usa_slices[1]} \
    --out_file ${out_slices[1]}

echo $?

# This one fails with IO error because the file from the
# previous merge is trying to be overwritten.
./merge_timeslices.py \
    --in_file_new ${can_slices[1]} \
    --in_file_copy_addto ${usa_slices[1]} \
    --out_file ${out_slices[1]}

echo $?
# The return code is different here than in the interactive example.

# Clean up.
rm -f ${out_slices[*]}
