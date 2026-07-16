###############################################################################
#  Module name: RFCHelper
#                                                                             #
#  Author     : Zhengtao Cui (Zhengtao.Cui@noaa.gov)                          #
#                                                                             #
#  Initial version date:  7/31/2019                                           #
#                                                                             #
#  Last modification date:  
#                                                                             #
#  Description: Abstract the RFC forecast  to time series
#                                                                             #
###############################################################################

import os, logging
from string import *
from datetime import datetime, timedelta
import dateutil.parser
from shutil import copyfile
#import pytz
#import iso8601
#import Tracer
#from abc import ABCMeta, abstractmethod, abstractproperty
from RFCTimeSeries import RFCTimeSeries


class RFCHelper:
        "Store all RFC data"
        def __init__(self, rfcdata ):
           """
              Initialize the RFCHelper object for a given
             RFC forecasts 

              Input: list of forecast object
           """
           self.logger = logging.getLogger(__name__)
           self.rfcForecasts = rfcdata

           if not self.rfcForecasts:
              raise RuntimeError( "FATAL ERROR: rfcForecasts has no data")

           self.index = -1

           self.timePeriod = ( self.rfcForecasts[0].fstPeriod[0], \
                               self.rfcForecasts[0].fstPeriod[0] )
           for fst in self.rfcForecasts:
               #print( "RFCHelper inti:" + fst.stationID, fst.fstPeriod, fst.getT0() )          
               if self.timePeriod[0] > fst.fstPeriod[ 0 ]:
                   self.timePeriod = ( fst.fstPeriod[ 0 ], \
                                       self.timePeriod[1] )

               if self.timePeriod[1] < fst.fstPeriod[ 0 ]:
                   self.timePeriod = ( self.timePeriod[ 0 ],\
                                      fst.fstPeriod[ 0 ] )

        def __iter__(self ):
            """
               The iterator
            """
            return self

        def __next__( self ):
           """
               The next RFC_Forecast object
           """
           if self.index == len( self.rfcForecasts ) - 1:
              self.index = -1
              raise StopIteration
           self.index = self.index + 1
           return self.rfcForecasts[ self.index ]

        def timePeriodForAll( self ):
                """
                  Get the earlist and latest time for all observations

                  Return: Tuple of start time and end time
                """
                return self.timePeriod

        def makeTimeSeries( self ):
            """
               Create time series from forecast data 

               Return: list of time series objects
            """
            timeseries = []
            for fst in self:
              if not fst.isEmpty():
                    timestamp = fst.getT0()
                    synthetics = list(map(int, fst.getSyntheticValues() ) )
                    timeSeries = RFCTimeSeries( fst.get5CharStationID(), \
                                    [ timestamp ], \
                           timedelta( seconds = fst.getTimeStepInSeconds()), \
                                    fst.getStartTime(), \
                                    [ fst.getValuesInCMS() ], \
                                    [ fst.getQuality() ], \
                                    [ synthetics ], \
                                    [ fst.getTimeStepInSeconds() ],\
                                    [ fst.getQueryTime() ], \
                                    fst.missVal)
                    timeseries.append(timeSeries)
           
            return timeseries

        def makeAllTimeSeries( self, outdir, suffix='RFCTimeSeries.ncdf' ):
            """
               Create the time series NetCDF files for all USGS observations

               Input: outdir - the output directory
                      suffix - suffix of the filename                

               Return: Total number of time series files created
            """

            # the time resultions must divide 60 minutes with no remainder                  
            series = self.makeTimeSeries()
            count = 0    
            if series:
               for s in series:
#                  s.print_station_offsettime_value()
                  self.logger.info( "Making time series:  " + \
                             outdir + '/' + s.getSeriesNCFileName( suffix ) )
                  seriesfilename = outdir + '/' +s.getSeriesNCFileName( suffix ) 
                  if os.path.isfile( seriesfilename ):
                      oldseries = RFCTimeSeries.fromNetCDF( seriesfilename )
                      if s.compare( oldseries ):
                          self.logger.info( s.getSeriesNCFileName( suffix )+ \
                                        " has no change!" )
                      else:
                          self.logger.info( s.getSeriesNCFileName( suffix ) + \
                                                             " updated!" )
#                         copyfile( seriesfilename, seriesfilename + '.bak' )
                          ismerged = s.mergeOld( oldseries )
                          if not ismerged:
                              self.logger.info( "RFCHelper :" + \
                                      s.getSeriesNCFileName( suffix )+ " is not merged" ) 

                          s.toNetCDF( outdir, suffix )
                          count = count + 1
                  else:
#                      s.print_station_offsettime_value()
                      s.toNetCDF( outdir, suffix )
                      self.logger.info( s.getSeriesNCFileName( suffix )+\
                                                            " created!" )
                      count = count + 1

            else:
               self.logger.info( "Skip making time series for " + \
                                    startTime.isoformat() + ' - no data' )

            return count
