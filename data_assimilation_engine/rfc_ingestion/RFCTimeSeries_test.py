import unittest
import time, os
import numpy as np
from datetime import datetime, timedelta
from RFCTimeSeries import RFCTimeSeries
from PI_XML import PI_XML
from RFC_Forecast import RFC_Forecast

class RFCTimeSeries_test(unittest.TestCase):
        def test(self):
                self.assertTrue(True)

        def testInit(self):
            timestamp = datetime(2019, 5, 19, 12, 0, 0)
            starttime = datetime(2019, 5, 19, 12, 0, 0)
            timeresolution = timedelta( minutes = 180 )
            stations = [ "CHNK1", "CNGK1" ]
            discharges = [ [ 1218.9941, 1218.9941, 1217.003, 1228.0027, \
                            1221.9971, 1221.9971 ],  \
                            [ 15936.987, 16065.989, 16035.982, 15959.986, \
                            15950.99, 15937.987, 15858.99, \
                            1218.9941, 1217.003, 1228.0027, \
                            1221.9971, 1221.9971 ] ]
            quality = [ 100, 50 ]

            timesteps = [ 21600, 21600 ]

            querytime = [ int( time.mktime( \
                            datetime( 2019, 5, 26, 7, 12, 45).timetuple()) ), \
                          int( time.mktime( \
                            datetime( 2019, 5, 26, 7, 12, 45).timetuple()) ) ]  

            for ( sta, dis, qual, dt, queryt) in \
                zip( stations, discharges, quality, timesteps,\
                     querytime ):

                print( sta,  qual, dt, queryt)
                timeseries = RFCTimeSeries( sta, [ timestamp ], timeresolution, \
                                starttime, \
                            [ dis ], [ qual ], [ dt ], [ queryt ], '-999.0' )

                timeseries.toNetCDF()

        def test_fromNetCDF(self):

                timeseries = RFCTimeSeries.fromNetCDF( "./2019-05-19_12.180min.CHNK1.RFCTimeSeries.ncdf" )
                print( "from Netcdf:" )
                timeseries.print_station_offsettime_value()
                self.assertEqual( timeseries.startTimeStamp, \
                                datetime(2019, 5, 19, 12, 0, 0) )

                self.assertAlmostEqual( \
                                timeseries.getDischargeValues()[0][3], \
                                 1228.003, 3 ) 

        def test_compare_equal(self):
                timeseries = RFCTimeSeries.fromNetCDF( "./2019-05-19_12.180min.CHNK1.RFCTimeSeries.ncdf" )
                timeseries1 = RFCTimeSeries.fromNetCDF( "./2019-05-19_12.180min.CHNK1.RFCTimeSeries.ncdf.bak" )

                self.assertTrue( timeseries.compare( timeseries1 ) )

        def test_compare_nonequal(self):
            timeseries = RFCTimeSeries.fromNetCDF( "./2019-05-19_12.180min.CHNK1.RFCTimeSeries.ncdf" )

            timestamp = datetime(2019, 5, 19, 12, 0, 0)
            starttime = datetime(2019, 5, 19, 12, 0, 0)
            timeresolution = timedelta( minutes = 180 )
            station = "CHNK1"
            discharges = [ [ 1218.9941, 1218.9941, 1217.003, 1228.0027, \
                            1221.9971, 1221.9981 ] ]
            quality = [ 100]

            timesteps = [ 21600 ]

            querytime = [ int( time.mktime( \
                            datetime( 2019, 5, 26, 7, 12, 45).timetuple()) ) ]

            timeseries1 = RFCTimeSeries( station, [ timestamp ], timeresolution, \
                                starttime, discharges, quality, \
                                timesteps, querytime, '-999.0' )


            self.assertFalse( timeseries.compare( timeseries1 ) )

        def test_mergeOld(self):

            timestamp = datetime(2019, 5, 19, 12, 0, 0)
            starttime = datetime(2019, 5, 19, 12, 0, 0)
            timeresolution = timedelta( minutes = 180 )
            station = "CHNK1"
            newdischarges = [ [ 1218.9941, 1218.9941, 1217.003, 1228.0027, \
                            1221.9971, 1221.9981 ] ]
            quality = [ 100]

            timesteps = [ 21600 ]

            querytime = [ int( time.mktime( \
                            datetime( 2019, 5, 26, 7, 12, 45).timetuple()) ) ]

            tsnew = RFCTimeSeries( station, [ timestamp ], timeresolution, \
                                starttime, newdischarges, quality, \
                                timesteps, querytime, '-999.0' )

            olddischarges = [ [ 1218.9941, 1218.9941, 1217.003, 1228.0027, \
                            1223.9971, 1221.9981 ] ]

            tsold = RFCTimeSeries( station, [ timestamp ], timeresolution, \
                                starttime, olddischarges, quality, \
                                timesteps, querytime, '-999.0' )

            tsnew.mergeOld( tsold )

            tsnew.toNetCDF( suffix='RFCTimeSeries.ncdf.merged' )

            self.assertTrue( os.path.exists(\
            './2019-05-19_12.180min.CHNK1.RFCTimeSeries.ncdf.merged' ) )

#        def test_NERFC_to_Timeseries(self):
#            pixml = PI_XML('./NERFC_Reservoir_Export.xml') 
#            rfc_series = pixml.toRFCForecast()
#
#            timeresolution = timedelta( minutes = 180 )
#            
#            for s in rfc_series:
#               print( "ParameterID = ", s.parameterId )
#               print( "stationID = ", s.stationID )
#               print( "size = ", len(s.timeValueQuality))
#               if s.parameterId == 'RQOT':
#                    print( "qualifierID = ", s.qualifierId )
#                    print( "timeStep = ", s.timeStep )
#                    print( "forecastDate = ", s.forecastDate )
#                    print( "unit = ", s.unit )
#                    print( "period = ", s.fstPeriod )
#                    if s.creationDateTime is not None:
#                        querytime = time.mktime( s.creationDateTime.timetuple() )
#                    elif s.forecastDate is not None:
#                        querytime = time.mktime( s.forecastDate.timetuple() )
#                    else:
#                        querytime = time.mktime( datetime.now().timetuple() )
#
#                    values = []
#
#                    for k, v in s.timeValueQuality.items():
#                            print("{0} ===> {1}".format( k, v ) )
#                            if s.unit == 'CFS':
#                                values.append( v[0] * 0.028316846592 )   
#                            else:
#                                values.append( v[0] )
#
#                    timeseries = RFCTimeSeries( s.get5CharStationID(),\
#                                     s.getT0(), \
#                                     timeresolution, \
#                                      timedelta( seconds = 0 ),\
#                                      values,\
#                                      100,\
#                                      s.getTimeStepInSeconds(),\
#                                      querytime, '-999.0')
#
#
#                    timeseries.toNetCDF()



if __name__ == '__main__':
    unittest.main()

