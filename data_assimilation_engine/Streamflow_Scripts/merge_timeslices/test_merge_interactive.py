from merge_timeslices.merge_timeslices import merge_timeslices

import datetime
import pathlib
import xarray

can_path = pathlib.Path('/d7/jamesmcc/canadian_data_merge/canadian_data/')
usa_path = pathlib.Path('/d7/jamesmcc/canadian_data_merge/us_data/')
merge_path = pathlib.Path('/d7/jamesmcc/canadian_data_merge/merge_result/')
can_slices = sorted(can_path.glob('2019-02-12_00*'))
usa_slices = sorted(usa_path.glob('2019-02-12_00*'))
out_slices = [merge_path / slice.name for slice in usa_slices]

# -------------------------------------------------------
# Test normal operation.

# remove output files, if they exist.
[slice.unlink() for slice in out_slices if slice.exists()]

for can, usa, out in zip(can_slices, usa_slices, out_slices):
    merge_timeslices(
        in_file_new=str(can),
        in_file_copy_addto=str(usa),
        out_file=str(out),
        verbose=True
    )

# Check equality in the appends. 
for ff in range(len(out_slices)):

    usa_check = xarray.open_dataset(usa_slices[ff])
    can_check = xarray.open_dataset(can_slices[ff])
    out_check = xarray.open_dataset(out_slices[ff])

    assert \
        len(out_check['stationIdInd']) == len(can_check['stationIdInd']) + len(usa_check['stationIdInd'])

    can_start = len(usa_check['stationIdInd'])
    can_end = len(usa_check['stationIdInd']) + len(can_check['stationIdInd']) + 1

    tol_delta = datetime.timedelta(seconds=.1)

    for var in out_check.variables.iterkeys():
        print '' 
        print var
        assert all(usa_check[var] == out_check[var][0:can_start])
        assert all(can_check[var] == out_check[var][can_start:can_end])


# remove the output_files now that we are done.    
[slice.unlink() for slice in out_slices if slice.exists()]

# -------------------------------------------------------
# Test abnormal operation: trying to merge slices with different times.
# This one failes with a value error on internal file times. 
try: 
    result = merge_timeslices(
        in_file_new=str(can_slices[0]),
        in_file_copy_addto=str(usa_slices[1]),
        out_file=str(out_slices[1]),
        verbose=False
    )
except IOError:
    result = 2
except ValueError:
    result = 1

assert result == 1    

# This one succeeds.
try: 
    result = merge_timeslices(
        in_file_new=str(can_slices[1]),
        in_file_copy_addto=str(usa_slices[1]),
        out_file=str(out_slices[1]),
        verbose=False
    )
except IOError:
    result = 2
except ValueError:
    result = 1

assert result == 0

# This one fails with IO error because the file from the
# previous merge is trying to be overwritten.
try: 
    result = merge_timeslices(
        in_file_new=str(can_slices[1]),
        in_file_copy_addto=str(usa_slices[1]),
        out_file=str(out_slices[1]),
        verbose=False
    )
except IOError:
    result = 2
except ValueError:
    result = 1

assert result == 2

# Clean up
[slice.unlink() for slice in out_slices if slice.exists()]
