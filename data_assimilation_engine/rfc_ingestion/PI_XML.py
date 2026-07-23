###############################################################################
#  Module name: PI_XML
#                                                                             #
#  Author     : Zhengtao Cui (Zhengtao.Cui@noaa.gov)                          #
#                                                                             #
#  Initial version date:                                                      #
#                                                                             #
#  Last modification date:  07/02/2019                                         #
#                                                                             #
#  Description: manage data in a RFC FEWS PI xml file                       #
#                                                                             #
###############################################################################

import os, sys, time, csv, re
import logging
from string import *
from collections import OrderedDict
from datetime import datetime, timedelta
import dateutil.parser
import math
import pytz
#import iso8601
import xml.etree.ElementTree as etree
import copy
from RFC_Forecast import RFC_Forecast 
from RFC_Sites import RFC_Sites
class PI_XML:
        """
           Store one RFC forecast data
        """

        @property
        def timeZone(self):
                return self._timeZone

        @timeZone.setter
        def timeZone(self, t):
                self._timeZone = t

        @property
        def series(self):
                return self._series

        @series.setter
        def series(self, s):
                self._series = s

        @property
        def rfcsites(self):
                return self._rfcsites

        @rfcsites.setter
        def rfcsites(self, r):
                self._rfcsites = r

        def __init__(self, pixmlfilename, sites ):
           """
              Initialize the RFC_Forecast object with a given
              filename
           """
           self.source = pixmlfilename
           self.series = []
           self.rfcsites = sites

           self.loadPIxml( pixmlfilename )

        def loadPIxml( self, pixmlfilename ):
           try:
                fstwml = etree.parse( pixmlfilename )
                root= fstwml.getroot()
                self.timeZone = root.find( '{http://www.wldelft.nl/fews/PI}timeZone' ).text
                for series in \
                        root.iter('{http://www.wldelft.nl/fews/PI}series'):
                  self.series.append( series ) 
#                for series in self.series:
#                        print(series.tag, series.attrib )
#                print ( 'timeZone = ', self.timeZone )

           except Exception as e:
               raise RuntimeError( "WARNING: parsing PI XML error: " + str( e )\
                               + ": " + pixmlfilename + " skipping ..." )

        def toRFCForecast(self):

#            print("to rfcforecast")
            rfc_series = []
            for s in self.series:
#              print(s.tag, s.attrib )
              rfc_series.append( RFC_Forecast( s, self.rfcsites ))

            return rfc_series

        def getFlowTimeseries( self ):
            return list( filter( lambda s: s.parameterId in \
                                    [ "RQOT", "QINE", "SQIN" ] and \
                                    s.rfcname is not None and \
                                     not s.isEmpty(), self.toRFCForecast() ) )

        def getAllStationIDs( self ):
            return set( map( lambda s: s.get5CharStationID(), \
                            self.getFlowTimeseries() ) )


        def getObservedAndForecastForID( self, id ):
            fst = next( ( s for s in self.getFlowTimeseries() \
                            if s.isForecast() and \
                            s.get5CharStationID() == id ), None )
            obv = next( ( s for s in self.getFlowTimeseries() \
                            if s.isObserved() and \
                            s.get5CharStationID() == id ), None )
            #
            # Some RFCs already combined observed and forecast series
            #
            if fst is not None and obv is None:
               #
               # Split the forecast series into observed and forecast
               #
               obv = copy.deepcopy( fst )
               T0 = fst.getT0()
               dt = timedelta( seconds = obv.getTimeStepInSeconds() )
               t = obv.getTimePeriod()[1]
               while t >=T0:
                   if obv.timeValueQuality:
                     obv.timeValueQuality.popitem()
                   t = t - dt

               obv.resetTimePeriod()
               obv.qualifierId = "observed"

               t = fst.getTimePeriod()[0]
               while t < T0:
                   fst.timeValueQuality.popitem(last=False)
                   t = t + dt
               fst.resetTimePeriod()

            return( fst, obv )

        #Some RFCs such as NE have observed and forecast in separate
        #time series
        def getReserviorForecastWithT0(self):
            series = self.toRFCForecast()
            observed = []
            forecast = []
            parameterset = set( ["RQOT", "QINE", "SQIN" ] )
            for s in series:
              if s.parameterId in parameterset and not s.isEmpty(): 
                 if s.isObserved():
                    observed.append( s )
                 else:
                    if s.isForecast():
                       forecast.append( s )
                    else:
                       #
                       # CNRFC doesn't have the <forecastDate> tag
                       #
                       if s.rfcname == "CNRFC":
                          forecast.append( s )
#                       # NCRFC observed doesn't have the qualifierId tag
#                       if s.rfcname == "NCRFC":
#                          observed.append( s )

                       

            if observed:
              for o in observed:
                for s in forecast:
                  if o.stationID == s.stationID:
                     if s.startDate == s.getT0():
#                        #NERFC
#                        if s.stationID == "SWRN6" or  \
#                            s.stationID == "STDM1" or  \
#                            s.stationID == "RKWM1":
#
#                           s.timeValueQuality.update( {s.startDate :\
#                             o.timeValueQuality[ next(reversed(   \
#                                       o.timeValueQuality.keys() ) ) ] } )
#
#                        else:
                          if s.startDate in o.timeValueQuality.keys():
                              if not math.isclose( \
                                  o.timeValueQuality[ s.startDate ][ 0 ],
                                  float( o.missVal ), abs_tol=0.0001 ):

                                  s.timeValueQuality.update( {s.startDate :\
                                      o.timeValueQuality.get( s.startDate, \
                                                  (float( s.missVal ), 0) ) } )

                     elif s.startDate < s.getT0():
                          tvq = OrderedDict()
                          for k in s.timeValueQuality:
                             if k >= s.getT0(): 
                               tvq[ k ] = s.timeValueQuality[ k ]
                          s.timeValueQuality=tvq 
                          if s.timeValueQuality.has_key( s.getT0() ): 
                            s.timeValueQuality.update( {s.getT0(): \
                              o.timeValueQuality.get( s.getT0()) } )
                            s.timeValueQuality.move_to_end( s.getT0(), \
                                          last=False )

                          s.startDate = s.getT0()

                          s.fstPeriod =  \
                                  list( s.timeValueQuality.keys() )[0], \
                                  list( s.timeValueQuality.keys() )[-1]
                     else:
                          t = s.startDate - timedelta( \
                                      seconds = s.getTimeStepInSeconds())
                          while t > s.getT0():
                              s.timeValueQuality.update({t : \
                                          ( float( s.missVal ), 0 ) } )
                              s.timeValueQuality.move_to_end( t, \
                                          last=False )
                              t = t - timedelta( \
                                      seconds = s.getTimeStepInSeconds())

                          s.timeValueQuality.update({t: \
                                      o.timeValueQuality.get( t, \
                                                (float( s.missVal) , 0)) } )
                          s.timeValueQuality.move_to_end( t, \
                                          last=False )
                          s.startDate = s.getT0()

                          s.fstPeriod =  \
                                  list( s.timeValueQuality.keys() )[0], \
                                  list( s.timeValueQuality.keys() )[-1]
                     break
              forcast_without_observed = []
              for s in forecast:
                found = False
                for o in observed:
                  if o.stationID == s.stationID:
                     found = True
                     break
                if not found:
                  forcast_without_observed.append( s )

              for f in forcast_without_observed:
                  if f.startDate < f.getT0():
                     tvq = OrderedDict()
                     for k in f.timeValueQuality:
                         if k >= f.getT0(): 
                            tvq[ k ] = f.timeValueQuality[ k ]
                     f.timeValueQuality=tvq 
                  else:
                     t = f.startDate - timedelta( \
                                      seconds = f.getTimeStepInSeconds())
                     while t >= f.getT0():
                         f.timeValueQuality.update({t : \
                                          ( float( f.missVal ), 0 ) } )
                         f.timeValueQuality.move_to_end( t, \
                                          last=False )
                         t = t - timedelta( \
                                      seconds = f.getTimeStepInSeconds())

#                  print( "getReserviorForecastWithT0:" + f.stationID)                   
                  f.startDate = f.getT0()
                  f.fstPeriod =  list( f.timeValueQuality.keys() )[0], \
                                 list( f.timeValueQuality.keys() )[-1]

            else:
                for f in forecast:
                  if f.startDate < f.getT0():
                     tvq = OrderedDict()
                     for k in f.timeValueQuality:
                         if k >= f.getT0(): 
                            tvq[ k ] = f.timeValueQuality[ k ]
                     f.timeValueQuality=tvq 
                  else:
                     t = f.startDate - timedelta( \
                                      seconds = f.getTimeStepInSeconds())
                     while t >= f.getT0():
                         f.timeValueQuality.update({t : \
                                          ( float( f.missVal ), 0 ) } )
                         f.timeValueQuality.move_to_end( t, \
                                          last=False )
                         t = t - timedelta( \
                                      seconds = f.getTimeStepInSeconds())

#                  print( "getReserviorForecastWithT0:" + f.stationID)                   
                  f.startDate = f.getT0()
                  f.fstPeriod =  list( f.timeValueQuality.keys() )[0], \
                                 list( f.timeValueQuality.keys() )[-1]
            return forecast

        def getRFCName( self ):
            YYYYMMDDHH = '[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[1-2][0-9]|3[0-1])(2[0-3]|[01][0-9])'
            YYYYMMDD = '[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[1-2][0-9]|3[0-1])'
            YYYYMMDDHHMMSS = YYYYMMDDHH + '(0[0-9]|[1-5][0-9]){2}'
            CBRFCPattern = '^(.*/)?CBRFC_Reservoirs_' + YYYYMMDDHH + '.xml'
            NERFCPattern = '^(.*/)?NERFC_Reservoir_Export.xml'
            LMRFCPattern = '^(.*/)?LMRFC_RESERVOIR_FORECAST\.' + YYYYMMDD

            ABRFCPattern = '^(.*/)?' + YYYYMMDDHH + '_RES_NWM_pixml_export.' + YYYYMMDDHHMMSS
            NWRFCPattern = '^(.*/)?' + YYYYMMDDHH + '_QINE_NWM_Res_export.' + YYYYMMDDHHMMSS
            MBRFCPattern = '^(.*/)?' + YYYYMMDDHHMMSS + '_RQOT_Forecast_.+_xml_' + YYYYMMDDHH
            RFCName = None
            result = re.match(CBRFCPattern, self.source)
            if result:
              RFCName = 'CBRFC'
            else:
              result = re.match(NERFCPattern, self.source)
              if result:
                 RFCName = 'NERFC'
              else:
                 result = re.match(ABRFCPattern, self.source)
                 if result:
                   RFCName = 'ABRFC'
                 else:
                   result = re.match(NWRFCPattern, self.source)
                   if result:
                     RFCName = 'NWRFC'
                   else:
                     result = re.match(LMRFCPattern, self.source)
                     if result:
                       RFCName = 'LMRFC'
                     else:
                       result = re.match(MBRFCPattern, self.source)
                       if result:
                         RFCName = 'MBRFC'
                       
            return RFCName


        def allStations( self ):
              stations = set()
              series = self.toRFCForecast()
              for s in series:
                 stations.add( s.get5CharStationID() )
              return stations

        def getRFCNameBySitelist( self, gages ):
             sta = self.allStations()
             for rfc in gages.RFC:
                rfcgages = gages.getSitesByRFC( rfc )
                if not sta.isdisjoint( set( rfcgages ) ):
                      return rfc

        #
        # Apply the persistence and linear interplation algorithm
        #
        # For observed, persist both forward and backward up to 24 hours,
        # linear interpolate between observed values. However, the maximum gap 
        # between interplation is 48 hours. That is if the gap between is 
        # more than 48 hours, fill the gap with -999 (missing) values.
        #
        # For forecast, persist only in the forward direction up to 24 hours.
        # Linear interpolate between values. If the gap is more than 48 hours,
        # fill with missing values. 
        #
        # see email thread "rfc obs" Nov 13, 2019
        #
        def combineObvFstAndApplyPresistenceLinearInterpolation( self, \
                        obvfst):
             obv = copy.deepcopy( obvfst[1] )
             fst = copy.deepcopy( obvfst[0] )
             obv.linearInterpolate(timedelta( hours = 1 ) )
             fst.interForwardPersist(timedelta( hours = 1 ) )
             combined = copy.deepcopy( obv )
             obvperiod = obv.getTimePeriod()
             fstperiod = fst.getTimePeriod()
             if obvperiod[1] >= fstperiod[ 0 ]:
                for k, v in fst.timeValueQuality.items():
                  if k not in combined.timeValueQuality:
                    combined.timeValueQuality[ k ] = v
             elif obvperiod[1] + timedelta( days = 1 ) < fstperiod[ 0 ]:
                combined.persistForward( obvperiod[1] + timedelta( days = 1 ) )
                t = obvperiod[1] + timedelta( days = 1 )
                while t < fstperiod[ 0 ]:
                    combined.timeValueQuality[ t ] = \
                                    ( float( combined.missVal ), 0.0, True )
                    t = t + \
                       timedelta( seconds = combined.getTimeStepInSeconds() )
                for k, v in fst.timeValueQuality.items():
                    combined.timeValueQuality[ k ] = v
             else:
                combined.persistForward( fstperiod[ 0 ] )
                for k, v in fst.timeValueQuality.items():
                    combined.timeValueQuality[ k ] = v

             combined.resetTimePeriod()
             combined.qualifierId = fst.qualifierId
             combined.forecastDate = fst.forecastDate

             combined_period = combined.getTimePeriod()
             T0 = combined.getT0()

             if T0 - timedelta( days = 2 ) < combined_period[0]:
                combined.persistBackward( T0 - timedelta( days = 2 ),\
                                           timedelta( days = 1 ) )

             if T0 + timedelta( days = 10 ) > combined_period[ 1 ]:
                combined.persistForward( T0 + timedelta( days = 10, 
                              seconds = combined.getTimeStepInSeconds() ) )

             return combined

        #
        # See the comment below for the presist and interpolate algorithms
        #
        def linearInterpolateObservedPresisForecastAndCombine( self, o, f):

              f.interForwardPersist( timedelta( hours = 1 ) )
              fstperiod = f.getTimePeriod()
              o.linearInterpolate( timedelta( hours = 1 ) )
              obvperiod = o.getTimePeriod()
              #
              # If the observation period and the forecast  period
              # overlap.
              if obvperiod[1] >= fstperiod[ 0 ]:
                      t = fstperiod[ 0 ] - \
                                timedelta( seconds = f.getTimeStepInSeconds() )
                      while t >= obvperiod[ 0 ]:
                          f.timeValueQuality.update( {t: \
                                                   o.timeValueQuality[ t ] } )
                          f.timeValueQuality.move_to_end( t, last=False )
                          t = t - timedelta( \
                                            seconds = f.getTimeStepInSeconds() )
              #
              # If the last observation is less than 2 days from the 
              # T0 value.
              elif obvperiod[1] + timedelta( days = 2 ) >= fstperiod[ 0 ]:
                       t0 = f.getT0()
                       #interpolate between t0 and obvperiod[1]
                       if t0 == fstperiod[0]:
                          t1 = obvperiod[ 1 ]
                          t = t0 - timedelta( hours = 1 ) 
                          while t > t1:
                              f.timeValueQuality.update( {t: \
                                 (  ( f.timeValueQuality[ t0 ][0] -  \
                                        o.timeValueQuality[ t1 ][ 0 ] ) *\
                                  ( ( t - t1 ).total_seconds() / \
                                    ( t0 - t1 ).total_seconds() ) + \
                                    o.timeValueQuality[ t1 ][ 0 ] , 
                                   ( f.timeValueQuality[ t0 ][1] -  \
                                        o.timeValueQuality[ t1 ][ 1 ] ) *\
                                  ( ( t - t1 ).total_seconds() / \
                                    ( t0 - t1 ).total_seconds() ) + \
                                    o.timeValueQuality[ t1 ][ 1 ] , 
                                    True ) } )
                              f.timeValueQuality.move_to_end( t, last=False )
                              t = t - timedelta( hours = 1 )
                          t = t1
                          while t >= obvperiod[0]:
                            f.timeValueQuality.update( {t: \
                                                   o.timeValueQuality[ t ] } )
                            f.timeValueQuality.move_to_end( t, last=False )
                            t = t - timedelta( hours = 1 ) 

                       #persist obvperiod[1] up to 1 day
                       else: #t0 < fstperiod[0] or t0 > fstperiod[0]:
                          t1 = obvperiod[ 1 ]
                          t = fstperiod[0] - timedelta( hours = 1 ) 
                          while t > t1 + timedelta( days = 1 ):
                              f.timeValueQuality.update( {t: \
                                        ( float( f.missVal ), 0.0, True ) } )
                              f.timeValueQuality.move_to_end( t, \
                                                                   last=False )
                              t = t - timedelta( hours = 1 )
                          while t > t1:
                            f.timeValueQuality.update( {t: \
                                                 o.timeValueQuality[ t1 ] } )
                            f.timeValueQuality.move_to_end( t, last=False )
                            t = t - timedelta( hours = 1 ) 
                          while t >= obvperiod[0]:
                            f.timeValueQuality.update( {t: \
                                                   o.timeValueQuality[ t ] } )
                            f.timeValueQuality.move_to_end( t, last=False )
                            t = t - timedelta( hours = 1 ) 

              #
              # If the last observation is more than 2 days from the 
              # T0 value.
              else: #persist obvperiod[1] up to 1 day
                     t1 = obvperiod[ 1 ]
                     t = fstperiod[0] - timedelta( hours = 1 ) 
                     while t > t1 + timedelta( days = 1 ):
                           f.timeValueQuality.update( {t: \
                                        ( float( f.missVal ), 0.0, True ) } )
                           f.timeValueQuality.move_to_end( t, \
                                                                   last=False )
                           t = t - timedelta( hours = 1 )
                     while t > t1:
                           f.timeValueQuality.update( {t: \
                                                 o.timeValueQuality[ t1 ] } )
                           f.timeValueQuality.move_to_end( t, last=False )
                           t = t - timedelta( hours = 1 ) 
                     while t >= obvperiod[0]:
                           f.timeValueQuality.update( {t: \
                                                   o.timeValueQuality[ t ] } )
                           f.timeValueQuality.move_to_end( t, last=False )
                           t = t - timedelta( hours = 1 ) 


#      1) No interpolation for forecast values.
#      2) Interpolate observed values if the gap is less or equal to 48
#         hours. Otherwise, fill the gap with missing values such as -999.
#      3) Persist forecast values if there is a gap between the values.
#          The maximum gap is 10 days (this is also the total length of our
#          forecast values).
#      4) When it is necessary, persist observed values backward and
#         forward for up to 1 day at the first and last values respectively.  
#      5) Persist the last forecast value to 10 days from T0.
#      4*) I think any observed value could be persisted forward/backward up 
#         to 1 day. For example, if there are observations at T-6 through T-1 
#         and nothing before, then the value at T-6 could be persisted 
#         backwards to T-30.
#      5) If there is a T0 value and nothing beyond that, then the T0 value is
#         persisted through day 10. If the last available forecast value is at
#         T36, then that value is persisted through day 10.
#      6) If no observation (including T0 value) is provided, fill the 
#         observation including T0 with missing value (-999).
#      7) When RFC provides observations longer than 2 days before T0 , 
#         keep the values. That means the time silce will have observation
#         longer than 2 dyas
#      8) If RFC provides forecast longer than 10 days, keep the values even
#         the time slices will have forecast values longer than 10 days from
#         T0.
#
#      NOTE: * Later it is changed to persisted backward up to 2 days, in this
#              example, the value at T-6 could persisted backwards to T-54.

        def getReserviorObservedForecastCombinedWithT0(self):

             series = self.toRFCForecast()
             obs = []
             fst = []
             #
             # get only then non-empty timeseries
             #
             for s in series:
               if s.parameterId in [ "RQOT", "QINE", "SQIN" ] and \
                               s.rfcname is not None and not s.isEmpty():
           #    if s.parameterId in [ "RQOT", "QINE", "SQIN" ]:
                 if s.isForecast():
                      fst.append( s )
                 else:
                      obs.append( s )
                   

             for f in fst:
                obv = None
                t0 = f.getT0()

           #
           # APRFC linear interpolate 6 hourly data to hourly data
           # Here is the Google Doc about the APRFC forecast data
           # https://docs.google.com/document/d/1vMvBvi-aBbXkq6goYBGjentlUxt4HhxHfygGs01l9xE/edit
           #
           # Section:
           #
           # Data Preprocessing on APRFC pixml files for the GDL release
           #  1) Check with APRFC and ensure:
           #       They follow one of the naming conventions provided to them by Zhengtao (WGRFC_02.24.2021.06.00.xml or 202102230102_LMRFC_Reservoir_export.xml) (confirmed)
           #        They send data in a regular time resolution (6-hourly) (confirmed)
           #        They are fine with us utilizing linear interpolation for in-between values of a time series to convert 6-hr data to hourly data (confirmed)
           #  2) Implement a zero-value filling for expansion of time series to 12-day, instead of persisting on the last value in the time series. 
           #
           #  Email from john.mattern@noaa.gov on 4/13/2021
           #  Summary:
           #  1) Interpolate 6 hourly data to hourly 
           #  2) Extend forecast data to 10 days from T0 with 0s
           #  3) If there is no observed, fill observed period, T0 - 2 days to 
           #       T0, with 0s,
           #  4) If there is observed, but shorter than 2 days, then extend 
           #      backward with 0s.
           #
           # Email thread with subject "Glacial lake damming/outflow for NWM V3.0" 
           #  on June 15, 2021. 
           # After discussions with Dave Streubel, David Mattern, Brain Cosgrove, 
           #  and Mehdei Rezaeianzadeh, we will interpolate the values between
           # zero and the first non-zero values, and between the last non-zero
           # and zero. That is if the first value provided is non-zero, we 
           # interpolate from the preceding zero (valid at an earlier 6 hour time)
           # to the first (non-zero) value you provide in the timeseries.  Likewise,
           # we apply linear interpolation for the timestep after the last value.
           #
                if f.rfcname == 'APRFC':
                     f.addLeadingAndTrailingZeros()
                     f.linearInterpolate(  timedelta( hours = 1 ) )
                     f.persistBackward( t0 - timedelta( days=2 ), \
                                      timedelta( days = 2 ), 0.0 )
                     f.persistForward( t0 + timedelta( days=10 ), 0.0 )

                else:
                  for o in obs:
                   if o.stationID == f.stationID:
                     obv = o
                     break
                  #
                  #For RFCs have separate observation and forecast sections
                  #
                  if obv and not obv.isEmpty():

                     self.linearInterpolateObservedPresisForecastAndCombine(  \
                                                                     obv, f )
                  #
                  #For RFCs have combined observation and forecast into one
                  #  section.
                  #
                  else:
                     f.linearInterpolateAndInterForwardPersist(\
                                                  timedelta( hours = 1 ) )

                  f.persistBackward( t0 - timedelta( days=2 ), \
                                      timedelta( days = 2 ) )
                  f.persistForward( t0 + timedelta( days=10 ) )

                f.resetTimePeriod()

             #
             # get the time series even it is empty
             #
             fst.clear()
             for s in series:
               if s.parameterId in [ "RQOT", "QINE", "SQIN" ]:
                 if s.isForecast():
                      fst.append( s )
             return fst
                  

