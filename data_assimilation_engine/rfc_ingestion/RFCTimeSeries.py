###############################################################################
#  Module name: RFCTimeSeries                                                 #
#                                                                             #
#  Author     : Zhengtao Cui (Zhengtao.Cui@noaa.gov)                          #
#                                                                             #
#  Initial version date:                                                      #
#                                                                             #
#  Last modification date:  7/10/2019                                         #
#                                                                             #
#  Description: manage a RFC time series file that contains forecast stream    #
#               flow data a given time stamp                                  #
#                                                                             #
###############################################################################
import os, sys, time, math
from string import *
from datetime import datetime, timedelta
import calendar
#import xml.utils.iso8601
#from netCDF4 import Dataset
import netCDF4 
import numpy as np
import random

class RFCTimeSeries:
        """
           Description: Store one RFC time series data
           Author: Zhengtao Cui (Zhengtao.Cui@noaa.gov)
           Date: July. 10, 2019
           Date modified: 
        """

        stationIdStrLen = 5
        stationIdLong_name = "RFC station identifer of length 5"
        timeStrLen = 19
        timeUnit = "UTC"
        timeLong_name = "YYYY-MM-DD_HH:mm:ss UTC"
        qualifierStrLen = 15
        dischargeUnit = "m^3/s"
        dischargeLong_name = "Obsverved and forecasted discharges. There are 48 hours of observed values before issue time (T0), that is the start time is T0 - 48 hours. Values after T0 (including T0) are forecasts that genenrally extend to 10 days, that is T0 + 240 hours. The total length of dischargs is 12 days in general except in cases where forecasts or observations that are longer than 10 days or 2 days respectively are available."
        syntheticsUnit = "-"
        syntheticsLong_name = "Whether the discharge value is synthetic or orginal, 1 - synthetic, 0 - original"
        dischargeQualityUnit = "-"
        dischargeQualaityLong_name = \
                        "Discharge quality 0 to 100 to be scaled by 100."

#        offsetTimeUnit = "seconds since T0"
#        offsetTimeLong_name = "Offset time from T0"

        totalCountsUnit = "-"
        totalCountsLong_name = "Total count of all observation and forecast values"

        observedCountsUnit = "-"
        observedCountsLong_name = "Total observed values before T0."

        forecastCountsUnit = "-"
        forecastCountsLong_name = "Total forecasted values including and after T0."

        timeStepsUnit = "seconds"
        timeStepsLong_name = "Frequency/temporal resolution of forecast values"

        queryTimeUnit = "seconds since 1970-01-01 00:00:00 local TZ"
        queryTimeLong_name = "Query time at RFC"

        @property
        def issueTimeStamps(self):
              return self._issueTimeStamps
        @issueTimeStamps.setter
        def issueTimeStamps(self, its):
              self._issueTimeStamps = its 

        @property
        def startTimeStamp(self):
              return self._startTimeStamp
        @startTimeStamp.setter
        def startTimeStamp(self, sts):
              self._startTimeStamp = sts 

        def __init__(self, staID, time_stamp, resolution, starttime, \
                      dis, quality, synthetics, timestep, querytime, missVal ):
           """
              Initialize a RFC TimeSeries object
              Input: time_stamp - a time stamp
                     resolution - time resolution of the time series
                       station_time_value - Tuple of (station, time, flow, 
                                          quality)
           """
           self.issueTimeStamps = time_stamp
           self.seriesTimeResolution = resolution
           self.stationID = staID
           self.startTimeStamp = starttime
           self.discharges = dis
           self.discharge_qualities = quality
           self.synthetics = synthetics
           self.timeSteps = timestep
           self.querytime = querytime
           self.missingValue = missVal

        def isEmpty( self ):
            """
               Test if the time series is empty
               Return: boolean
            """
            return not self.discharges

        def print_station_offsettime_value( self ):
                """
                   Print the time series data
                """
                print( "Series: start time: " +  \
                                self.startTimeStamp.isoformat() )
                print( self.issueTimeStamps )
                print( self.discharges )
                print( self.stationID )
                print( self.querytime )
                for issuetime, dis in \
                                zip( self.issueTimeStamps,\
                                                    self.discharges):
                     print( "    issue time: " + issuetime.isoformat() + \
                            " " +  self.stationID )
                     for v in dis:
                           print( "             ", v )

        def get_total_counts(self):
                counts = []
                for dis in self.discharges:
                        counts.append( len( dis ) )

                return counts

        def get_observed_counts(self):
                counts = []
                for t, s in zip( self.issueTimeStamps, self.timeSteps):
                     counts.append( \
                  ( t - self.startTimeStamp ).total_seconds() / s )

                return counts

        def get_forecast_counts(self):
                counts = []
                obvcounts = self.get_observed_counts()
                for oc, dis in zip(obvcounts, self.discharges):
                        counts.append( len( dis ) - oc )

                return counts
        def getStationID( self ):
              """
                 Get all station ids of the time series
                 Return: list of station ids
              """
              station =  list( self.stationID )
              if len(station) < self.stationIdStrLen:
                  for i in range( len(station), self.stationIdStrLen ):
                    station.insert(0, ' ' )
              elif len(station) > self.stationIdStrLen:
                  station = station[0:self.stationIdStrLen - 1] 
               
              return station 

        def getDischargeValues( self ):
              """
                 Get all stream flow values of the time series
                 Return: list of flow values
              """
              return  self.discharges

#        def getOffsetTimeInSeconds( self ):
#              """
#                 Get all observation times of the time series
#                 Return: list of observation times
#              """
#              return int( self.offsettime.total_seconds() )

        def getSeriesNCFileName( self, suffix='RFCTimeSeries.ncdf' ):
            """
              Get NetCDF file for this time series
              Return: A NetCDF filename
            """
            filename =  \
             self.issueTimeStamps[-1].strftime( "%Y-%m-%d_%H." ) + \
              str( int( self.seriesTimeResolution.days * 24 * 60 + \
                  self.seriesTimeResolution.seconds // 60 ) ).zfill(2) + \
                "min." + self.stationID + "." + suffix
            return filename 

        def getDischargeQualities( self ):
              """
                Get discharge quality for this time series
                Return: A list of discharge quality
              """
              return self.discharge_qualities 
            

        def toNetCDF( self, outputdir = './', suffix='RFCTimeSeries.ncdf' ):
            """
              Write the time series to a NetCDF file
              Input: outputdir - the directory where to write the NetCDF 
            """
            nc_fid = netCDF4.Dataset(  \
                      outputdir + '/' + self.getSeriesNCFileName( suffix ), \
                              'w', format='NETCDF4' )
            nc_fid.createDimension( 'stationIdStrLen', self.stationIdStrLen ) 
            nc_fid.createDimension( 'timeStrLen', self.timeStrLen ) 
            nc_fid.createDimension( 'forecastInd', None ) 
            nc_fid.createDimension( 'nseries', len( self.discharges ) ) 
            nc_fid.createDimension( 'zero', 0 ) 


            stationId = nc_fid.createVariable( 'stationId', 'S1',\
                                 ('stationIdStrLen',) )

            stationId.setncatts( {'long_name' :    \
                                     self.stationIdLong_name, \
                                  'units' : '-'} )

            issuetime = nc_fid.createVariable( 'issueTimeUTC', 'S1', \
                            ('nseries', 'timeStrLen', ) )

            issuetime.setncatts( {'long_name' : self.timeLong_name, \
                                 'unts' : self.timeUnit } )

            discharges = nc_fid.createVariable( 'discharges', 'f4',\
                                  ('nseries', 'forecastInd', ) )

            discharges.setncatts( {'long_name' : \
                                       self.dischargeLong_name, \
                                  'units' : self.dischargeUnit} )

#            offsettime = nc_fid.createVariable( 'offsetTime', 'i4', ('zero'))
#            offsettime.setncatts( {'long_name' : self.offsetTimeLong_name, \
#                                  'units' : self.offsetTimeUnit} )
            synthetics = nc_fid.createVariable( 'synthetic_values', 'i1',\
                                  ('nseries', 'forecastInd', ) )

            synthetics.setncatts( {'long_name' : \
                                       self.syntheticsLong_name, \
                                  'units' : self.syntheticsUnit} )

            totalcounts = nc_fid.createVariable( 'totalCounts', 'i2',\
                            ('nseries',))

            totalcounts.setncatts( {'long_name' : \
                                    self.totalCountsLong_name, \
                                  'units' : self.totalCountsUnit} )

            obvcounts = nc_fid.createVariable( 'observedCounts', 'i2',\
                            ('nseries',))

            obvcounts.setncatts( {'long_name' : \
                                    self.observedCountsLong_name, \
                                  'units' : self.observedCountsUnit} )

            fstcounts = nc_fid.createVariable( 'forecastCounts', 'i2',\
                            ('nseries',))

            fstcounts.setncatts( {'long_name' : \
                                    self.forecastCountsLong_name, \
                                  'units' : self.forecastCountsUnit} )

            timeSteps = nc_fid.createVariable( 'timeSteps', 'i4',\
                            ('nseries',))

            timeSteps.setncatts( {'long_name' : \
                                    self.timeStepsLong_name, \
                                  'units' : self.timeStepsUnit} )

            discharge_qualities = \
                      nc_fid.createVariable( 'discharge_qualities', 'i2',\
                      ('nseries',))

            discharge_qualities.setncatts( {'long_name' : \
                                       self.dischargeQualaityLong_name, \
                                  'units' : self.dischargeQualityUnit,  \
                        'multfactor' : '0.01' } )

            queryTime = nc_fid.createVariable( 'queryTime', 'i8',\
                            ('nseries',))

            queryTime.setncatts( { 'units' :  \
                   'seconds since 1970-01-01 00:00:00 local TZ'       \
                        } )
         
            nc_fid.setncatts( { 'fileUpdateTimeUTC':  \
                     datetime.utcnow().strftime( "%Y-%m-%d_%H:%M:00" ), \
             'sliceStartTimeUTC' : \
                     self.startTimeStamp.strftime( "%Y-%m-%d_%H:%M:00" ),\
             'sliceTimeResolutionMinutes' :  \
                str( int( self.seriesTimeResolution.days * 24 * 60 + \
                  self.seriesTimeResolution.seconds // 60 ) ).zfill(2), \
             'missingValue' : self.missingValue, \
             'newest_forecast' : str( len( self.discharges ) - 1 ), \
             'NWM_version_number' : 'v2.1' } ) 
                              
            discharges[:,:] = np.asarray( self.discharges )
            synthetics[:,:] = np.asarray( self.synthetics )
#            issuetime = netCDF4.stringtochar( [ ''.join('2019-08-18_00:00:00' ) ] )
#            chars = '1234567890aabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
            timestrings = []
            timestrings = np.empty((len(self.issueTimeStamps),),\
                                                 'S'+repr(self.timeStrLen))
            for n in range(len(self.issueTimeStamps)):
                    timestrings[ n ] = \
                       self.issueTimeStamps[n].strftime( "%Y-%m-%d_%H:%M:00" ) 
            issuetime[:,:] = netCDF4.stringtochar( timestrings )
#            issuetime = netCDF4.stringtochar( \
#               [ ''.join( t.strftime( "%Y-%m-%d_%H:%M:00" )  \
#                                for t in self.issueTimeStamps ] ) ] )

            queryTime[:] = self.querytime
            totalcounts[:] = self.get_total_counts()
            obvcounts[:] = self.get_observed_counts()
            fstcounts[:] = self.get_forecast_counts()

#            offsettime[:] = self.getOffsetTimeInSeconds()
            timeSteps[:] = self.timeSteps

            stationId[:] = self.getStationID()

            discharge_qualities[:] = self.discharge_qualities

            nc_fid.close()

        @classmethod
        def fromNetCDF( self, ncfilename ):
            """
              Read the time series from a NetCDF file
              Input: ncfilename - the NetCDF filename
            """
            nc_fid = netCDF4.Dataset(  ncfilename, 'r' )
            startTimeStamp = datetime.strptime( \
                     nc_fid.getncattr( 'sliceStartTimeUTC' ), \
                                      "%Y-%m-%d_%H:%M:00" )

            time_resol = timedelta( minutes = \
                     int( nc_fid.getncattr( 'sliceTimeResolutionMinutes' ) ) )

            missVal = nc_fid.getncattr( 'missingValue' )

            newest_series = nc_fid.getncattr( 'newest_forecast' )

            station = netCDF4.chartostring( \
                         nc_fid.variables[ 'stationId'][ : ] )

            discharges = nc_fid.variables[ 'discharges'][ :, : ].tolist()
            synthetics = nc_fid.variables[ 'synthetic_values'][ :, : ].tolist()

            #queryTime = int( nc_fid.variables[ 'queryTime'][0] )
            queryTime = [ int( x ) for x in \
                            nc_fid.variables[ 'queryTime'][:] ]
#            queryTime = nc_fid.variables[ 'queryTime'][:].tolist()

            qualities = [ int( x ) for x in \
                            nc_fid.variables[ 'discharge_qualities'][:] ] 

            timeSteps = [ int( x ) for x in \
                            nc_fid.variables[ 'timeSteps' ][:] ] 
 #           offsettime = nc_fid.variables[ 'offsetTime' ][0]
 #           print( "offsetitme:", int( offsettime))

            issueTimes = [ datetime.strptime( t, "%Y-%m-%d_%H:%M:00") \
                            for t in netCDF4.chartostring ( \
                            nc_fid.variables[ 'issueTimeUTC' ][:] ) ]

            nc_fid.close()

#            d = timedelta( seconds = int( offsettime ) )
#            print(d)
#
            return self( str( station ), issueTimes, time_resol, \
                            startTimeStamp ,\
                            discharges,\
                         qualities, synthetics, timeSteps, queryTime, missVal )

        def mergeOld( self, oldTimeSeries ):
              """
              Merge data in an existing NetCDF time series file with this one
              Input: oldTimeSeries - the NetCDF filename of the existing time
                                    series
              """

              return False
              if self.startTimeStamp != oldTimeSeries.startTimeStamp or \
                 self.seriesTimeResolution != oldTimeSeries.seriesTimeResolution \
                 or self.stationID != oldTimeSeries.stationID or \
                 self.missingValue != oldTimeSeries.missingValue:
                  #raise RuntimeError( "FATAL ERROR: the two time series "\
                  #    " have different time stamps, temporal resolutions, "\
                  #    "or station IDs, not merging ..." )
                  print ( "The two time series "\
                      " have different start time, temporal resolutions, "\
                      "or station IDs, not merging ..." )
                  return False
              else:
                  extraIssueTimes = []
                  for n in range( len(self.issueTimeStamps ) ):
                    for m in range( len( oldTimeSeries.issueTimeStamps ) ):
                       if self.issueTimeStamps[n] == \
                                       oldTimeSeries.issueTimeStamps[ m ]:
                          self.discharges[ n ] =  oldTimeSeries.discharges[ m ]
                          self.synthetics[ n ] =  oldTimeSeries.synthetics[ m ]
                          break

                  for m in range( len( oldTimeSeries.issueTimeStamps ) ):
                    found = False
                    for n in range( len(self.issueTimeStamps ) ):
                       if self.issueTimeStamps[n] == \
                                       oldTimeSeries.issueTimeStamps[ m ]:
                           found = True
                           break
                    if not found:
                        extraIssueTimes.append( m ) 

                  if extraIssueTimes:
                      for i in extraIssueTimes:

                         if len( self.discharges[ -1 ] ) == \
                               len( oldTimeSeries.discharges[ i ]  ):
                            pass
                         elif len( self.discharges[ -1 ] ) <  \
                               len( oldTimeSeries.discharges[ i ]  ):
                            for d in self.discharges:  
                               for j in range( len(self.discharges[ -1 ] ),\
                                       len( oldTimeSeries.discharges[ i ] ) ):
                                  d.append( self.missingValue ) 
                            for s in self.synthetics:  
                               for j in range( len(self.synthetics[ -1 ] ),\
                                       len( oldTimeSeries.synthetics[ i ] ) ):
                                  s.append( 1 ) 

                         else:
                            for j in range( \
                                       len(oldTimeSeries.discharges[ i ] ),\
                                       len( self.discharges[ -1 ] ) ):
                               oldTimeSeries.discharges[ i ].append( \
                                                       self.missingValue ) 
                               oldTimeSeries.synthetics[ i ].append( 1 ) 

                         self.discharges.append( oldTimeSeries.discharges[ i ] )
                         self.synthetics.append( oldTimeSeries.synthetics[ i ] )
                         self.issueTimeStamps.append( \
                                         oldTimeSeries.issueTimeStamps[ i ] )
                         self.timeSteps.append( oldTimeSeries.timeSteps[ i ] )
                         self.discharge_qualities.append( \
                                        oldTimeSeries.discharge_qualities[ i ] )
                         self.querytime.append( oldTimeSeries.querytime[ i ] )
                  return True


        def compare( self, otherTimeSeries ):

                if self.stationID != otherTimeSeries.stationID:
                        return False

                if self.seriesTimeResolution != \
                                otherTimeSeries.seriesTimeResolution:
                        return False

                if self.startTimeStamp != otherTimeSeries.startTimeStamp:
                        return False

                if len(self.discharges) != len( otherTimeSeries.discharges):
                        return False

                if len(self.synthetics) != len( otherTimeSeries.synthetics):
                        return False

                if self.issueTimeStamps != otherTimeSeries.issueTimeStamps:
                        return False

                if self.timeSteps != otherTimeSeries.timeSteps:
                        return False

                if self.missingValue != otherTimeSeries.missingValue:
                        return False

                if self.discharge_qualities != \
                                otherTimeSeries.discharge_qualities:
                        return False

                for x, y in zip( self.discharges, otherTimeSeries.discharges): 
                  if len(x) != len(y):
                      return False
                  for a, b in zip( x, y):
                      if not math.isclose( a, b, abs_tol=0.001 ):
#                          print("value diff", a, b)
                          return False

                for x, y in zip( self.synthetics, otherTimeSeries.synthetics): 
                  if len(x) != len(y):
                      return False
                  for a, b in zip( x, y):
                      if a != b:
#                          print("synthetics diff", a, b)
                          return False

                return True
