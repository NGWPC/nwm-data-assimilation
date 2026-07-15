#!/usr/bin/sh

YYYYMMDD=`date -u +%Y%m%d`
#LDIR="/dfprod/dbnet/user/can_streamgauge"
LDIR="$DBNROOT/user/can_streamgauge"

for varnum in 5 46 47; do
  local_tmpname="station_list_tmp_var${varnum}.txt"
  local_filename="stations_all_var${varnum}.txt"
  curl -s -o ${LDIR}/${local_tmpname} "https://wateroffice.ec.gc.ca/services/recent_real_time_data/csv/inline?parameters[]=${varnum}"
  cat ${LDIR}/${local_tmpname} | grep ${varnum} | awk -F "," '{print $1}' > ${LDIR}/${local_filename}
done
echo 'Pull complete'

cat ${LDIR}/stations_all_var*.txt | sort -u > stations_all.txt

echo 'Station extraction complete'

rm -v ${LDIR}/station_list_tmp_var*.txt
rm -v ${LDIR}/stations_all_var*.txt
