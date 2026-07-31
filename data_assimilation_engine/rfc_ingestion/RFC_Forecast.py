###############################################################################
#  Module name: RFC_Intestion
#                                                                             #
#  Author     : Zhengtao Cui (Zhengtao.Cui@noaa.gov)                          #
#                                                                             #
#  Initial version date:                                                      #
#                                                                             #
#  Last modification date:  08/06/2019                                         #
#                                                                             #
#  Description: manage data in a RFC FEWS PI xml file                       #
#                                                                             #
###############################################################################

import os, sys, time, csv, re
sys.path.append( os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))\
                + '/Streamflow_Scripts/usgs_download/analysis/')
import logging
import math
from string import *
from collections import OrderedDict
from datetime import datetime, timedelta
import dateutil.parser
import pytz
#import iso8601
import xml.etree.ElementTree as etree
#import Tracer
from Observation import Observation
from RFC_Sites import RFC_Sites

class RFC_Forecast(Observation):
        """
           Store one RFC forecast data
        """
        @property
        def type(self):
                return self._type

        @type.setter
        def type(self, t):
                self._type = t

        @property
        def parameterId(self):
                return self._parameterId

        @parameterId.setter
        def parameterId(self, p):
                self._parameterId = p

        @property
        def qualifierId(self):
                return self._qualifierId

        @qualifierId.setter
        def qualifierId(self, q):
                self._qualifierId = q

        @property
        def timeStep(self):
                return self._timeStep

        @timeStep.setter
        def timeStep(self, t):
                self._timeStep = t

        @property
        def forecastDate(self):
                return self._forecastDate

        @forecastDate.setter
        def forecastDate(self,f):
                self._forecastDate = f

        @property
        def creationDateTime(self):
                return self._creationDateTime

        @creationDateTime.setter
        def creationDateTime(self, c):
                self._creationDateTime = c

        @property
        def missVal(self):
                return self._missVal

        @missVal.setter
        def missVal(self, m):
                self._missVal = m

        @property
        def lat(self):
                return self._lat

        @lat.setter
        def lat(self, l):
                self._lat = l

        @property
        def lon(self):
                return self._lon

        @lon.setter
        def lon(self, l):
                self._lon = l

        @property
        def x(self):
                return self._x

        @x.setter
        def x(self, l):
                self._x = l

        @property
        def y(self):
                return self._y

        @y.setter
        def y(self, l):
                self._y = l

        @property
        def z(self):
                return self._z

        @z.setter
        def z(self, l):
                self._z = l

        @property
        def timeValueQuality(self):
                return self._timeValueQuality

        @timeValueQuality.setter
        def timeValueQuality(self, v):
                self._timeValueQuality = v

        @property
        def fstPeriod(self):
            return self._obvPeriod

        @fstPeriod.setter
        def fstPeriod(self, p):
            self._obvPeriod = p

        @property
        def rfcname(self):
                return self._rfcname

        @rfcname.setter
        def rfcname(self, r):
                self._rfcname = r

        def __init__(self, pixmlseries, stations ):
           """
              Initialize the RFC_Forecast object with a given
              pixml series
           """
           self.source = pixmlseries
           header = pixmlseries.find('{http://www.wldelft.nl/fews/PI}header')
           self.type = header.find('{http://www.wldelft.nl/fews/PI}type').text
           self.stationID = header.find('{http://www.wldelft.nl/fews/PI}locationId').text
           self.stationName = header.find('{http://www.wldelft.nl/fews/PI}stationName').text
           self.parameterId = header.find('{http://www.wldelft.nl/fews/PI}parameterId').text
           if header.find('{http://www.wldelft.nl/fews/PI}qualifierId') \
                           is not None:

              self.qualifierId = header.find('{http://www.wldelft.nl/fews/PI}qualifierId').text
           else:
              self.qualifierId = None

           timeStepUnit = \
                   header.find('{http://www.wldelft.nl/fews/PI}timeStep').\
                   attrib[ 'unit' ]
           timeStepMultiplier = \
                   header.find('{http://www.wldelft.nl/fews/PI}timeStep').\
                   attrib[ 'multiplier' ]
           self.timeStep = (timeStepUnit, timeStepMultiplier)

           if header.find('{http://www.wldelft.nl/fews/PI}startDate') \
                           is not None:
              self.startDate = datetime.strptime( \
                   header.find('{http://www.wldelft.nl/fews/PI}startDate').\
                   attrib['date'] + ' ' + \
                   header.find('{http://www.wldelft.nl/fews/PI}startDate').\
                   attrib['time'], '%Y-%m-%d %H:%M:%S')
           else:
              self.startDate = None

           if header.find('{http://www.wldelft.nl/fews/PI}forecastDate') \
                           is not None:
              self.forecastDate = datetime.strptime( \
                   header.find('{http://www.wldelft.nl/fews/PI}forecastDate').\
                   attrib['date'] + ' ' + \
                   header.find('{http://www.wldelft.nl/fews/PI}forecastDate').\
                   attrib['time'], '%Y-%m-%d %H:%M:%S')
           else:
              self.forecastDate = None
#              if self.startDate is not None:
#                self.forecastDate = self.startDate
#              else:
#                self.forecastDate = None

           if header.find('{http://www.wldelft.nl/fews/PI}creationDate') \
                           is not None:
              self.creationDateTime = datetime.strptime( \
                   header.find('{http://www.wldelft.nl/fews/PI}creationDate').\
                   text + ' ' + \
                   header.find('{http://www.wldelft.nl/fews/PI}creationTime').\
                   text, '%Y-%m-%d %H:%M:%S')
           else:
              self.creationDateTime = None

           self.missVal = \
                   header.find('{http://www.wldelft.nl/fews/PI}missVal').text

           if math.isnan( float( self.missVal ) ):
                   self.missVal = '-999'

           if header.find('{http://www.wldelft.nl/fews/PI}lat') is not None:
              self.lat = float( \
                   header.find('{http://www.wldelft.nl/fews/PI}lat').text )
           if header.find('{http://www.wldelft.nl/fews/PI}lon') is not None:
              self.lon = float( \
                   header.find('{http://www.wldelft.nl/fews/PI}lon').text )

           if header.find('{http://www.wldelft.nl/fews/PI}x') is not None:
              self.x = float( \
                   header.find('{http://www.wldelft.nl/fews/PI}x').text )

           if header.find('{http://www.wldelft.nl/fews/PI}y') is not None:
              self.y = float( \
                   header.find('{http://www.wldelft.nl/fews/PI}y').text )

           if header.find('{http://www.wldelft.nl/fews/PI}z') is not None:
              self.z = float( \
                   header.find('{http://www.wldelft.nl/fews/PI}z').text )

           self.unit = \
                   header.find('{http://www.wldelft.nl/fews/PI}units').text

           self.timeValueQuality = OrderedDict()

           for event in pixmlseries.iter( \
                           '{http://www.wldelft.nl/fews/PI}event'):
              value = float( event.attrib[ 'value' ] )
              if math.isnan( value ):
                      value = -999.0

              # set negative values to missing values
              if not math.isclose( value, float( self.missVal ),\
                              abs_tol=0.0001 ) and value < 0:
                 value = float( self.missVal )

              #NERFC
#              if self.stationID == "RKWM1ME":
#                 value = -999

              self.timeValueQuality[ datetime.strptime( \
                      event.attrib['date'] + ' ' + event.attrib['time'],  \
                      '%Y-%m-%d %H:%M:%S' ) ] = ( \
                      value, \
                      float( event.attrib[ 'flag' ] ), False )

           if len( self.timeValueQuality ) > 0:
              self.fstPeriod =  list( self.timeValueQuality.keys() )[0], \
                             list( self.timeValueQuality.keys() )[-1]
              if self.startDate != self.fstPeriod[0]:
                      self.startDate = self.fstPeriod[0]

           self.rfcname = stations.getRFCBySite( self.get5CharStationID() )
#           #
#           #Set time step for WGRFC
#           #
#           if self.rfcname == "WGRFC":
#              self.timeStep = (timeStepUnit, "3600")

#           #NERFC
#           if self.stationID == "SWRN6" or self.stationID == "SACN6":
#                if self.isForecast():
#                    self.timeStep = (timeStepUnit, "86400")
#           if self.stationID == "SWRN6":
#                if self.isForecast():
#                   self.startDate = self.fstPeriod[0]
#                   self.forecastDate = self.startDate - timedelta( days = 1 )
           #
           # CNRFC assumes T0 = startDate + 48 hours
           #
           if self.rfcname == "CNRFC": 
               self.forecastDate = self.startDate + timedelta( hours = 48 )

           if self.rfcname == "NCRFC" and self.forecastDate is not None:
               if self.startDate - self.forecastDate > timedelta( hours = 12 ):
                  self.forecastDate = self.startDate

        def getTimeStepInSeconds(self):
                if self.timeStep[0] == "second":
                  return int( self.timeStep[1] )
                elif self.timeStep[0] == "minute":
                  return int( self.timeStep[1] ) * 60
                elif self.timeStep[0] == "hour":
                  return int( self.timeStep[1] ) * 3600
                else:
                  return None


        def setTimeStepInSeconds(self, dtInSec):
               self.timeStep = ( "second", f"{dtInSec}")

        def getTimePeriod(self):
                return self.fstPeriod

        def resetTimePeriod( self ):
              if self.isEmpty():
                   self.fstPeriod = None
                   self.startDate = None
                   return

              self.fstPeriod =  list( self.timeValueQuality.keys() )[0], \
                             list( self.timeValueQuality.keys() )[-1]
              self.startDate = self.fstPeriod[0]


        def getStartTime( self ):
                return self.fstPeriod[0]

        def getT0(self):
                if self.isForecast():
                      #
                      #  MBRFC has synoptic time, round down to 0, 6, 12 and 18
                      #
#                     if self.rfcname == "MBRFC":
#                        hr = self.forecastDate.hour // 6 * 6 
#                        return self.forecastDate.replace(hour=hr) 
#                     else:
                        return self.forecastDate
                elif self.isObserved():
                        return None
                elif self.startDate is not None:
                        return self.startDate
                elif not isEmpty():
                        return self.fstPeriod[0]
                else:
                        return None

        def getSyntheticValues( self ):
              syntheticValues = []
              for k, v in self.timeValueQuality.items():
                syntheticValues.append( v[ 2 ] ) 
              return syntheticValues

        def getStationTimeValueInCMSQuality(self):
              parameterset = set( ["RQOT", "QINE", "SQIN" ] )
              if self.parameterId in parameterset:
                  values = [] 
                  for k, v in self.timeValueQuality.items():
                    if self.unit == 'CFS':
                      values.append( v[0]  * 0.028316846592 if \
                      abs( v[0] - float( self.missVal ) ) > 0.0001 else \
                                      v[0] )
                    elif self.unit == 'KCFS':
                      values.append( v[0]  * 28.316846592 if \
                      abs( v[0] - float( self.missVal ) ) > 0.0001 else \
                                      v[0] )
                    elif self.unit == 'CMS':
                      values.append( v[0] )
                    else:
                      raise RuntimeError( 'FATAL Error: RFC_Forecast: ' + \
                                  ' unknown unit: ' + self.unit )

                  offset = self.getOffsetTime()
                  return (self.stationID, offset, values, 100)
              else:
                  return None

        def getValuesInCMS(self):
              parameterset = set( ["RQOT", "QINE", "SQIN" ] )
              values = [] 
              if self.parameterId in parameterset:
                  for k, v in self.timeValueQuality.items():
                    if self.unit == 'CFS':
                      values.append( v[0]  * 0.028316846592 if \
                        abs( v[0] - float( self.missVal ) ) > 0.0001 else \
                                      v[0] )
                    elif self.unit == 'KCFS':
                      values.append( v[0]  * 28.316846592 if \
                        abs( v[0] - float( self.missVal ) ) > 0.0001 else \
                                      v[0] )
                    elif self.unit == 'CMS':
                      values.append( v[0] )
                    else:
                      raise RuntimeError( 'FATAL Error: RFC_Forecast: ' + \
                                  ' unknown unit: ' + self.unit )
              return values

        def getQueryTime(self):
               querytime = None
               if self.creationDateTime is not None:
                    querytime =  int( time.mktime( \
                                    self.creationDateTime.timetuple() ) )
               elif self.forecastDate is not None:
                    querytime = int( time.mktime( \
                                    self.forecastDate.timetuple() ) )
               else:
                    querytime = int( time.mktime( datetime.now().timetuple() ) )

               return querytime

        def getOffsetTime(self):
                return self.fstPeriod[0] - self.getT0()

        def isEmpty(self):
            if len( self.timeValueQuality ) <= 0:
               return True
            else:
               for v in self.getValuesInCMS():
                   if not math.isclose( v, float( self.missVal ),\
                                                      abs_tol=0.0001 ):
                       return False
               return True


        def get5CharStationID(self):
                if len( self.stationID ) > 5:
                   return self.stationID[:5]
                else:
                   return self.stationID

        def getQuality(self):
                return 100

        def isObserved(self):
                if self.qualifierId is not None and \
                                self.qualifierId == "observed": 
                        return True
                elif self.qualifierId is not None and \
                                self.qualifierId == "forecast": 
                        return False
                else:
                        return False
                     
        def isForecast(self):
                if self.qualifierId is not None and \
                                self.qualifierId == "forecast": 
                        return True
                elif self.qualifierId is not None and \
                                self.qualifierId == "observed": 
                        return False
                elif self.forecastDate is not None:
                        return True
                else:
                        return False
                     
        def print(self):
            print( "Station: " + self.get5CharStationID() )
            print( "isForecast:  ", "True" if self.isForecast() else "False" )
            print( "isObserved:  ", "True" if self.isObserved() else "False" )
            print( "Parameter:  " + self.parameterId )
            print( "Period:  (" + self.getTimePeriod()[0].strftime( \
                            "%m/%d/%Y %H:%M:%S" ) + ", " + \
                                  self.getTimePeriod()[1].strftime( \
                                       "%m/%d/%Y %H:%M:%S" ) + ")" )
            if self.isForecast():
               print( "T0:  " + self.getT0().strftime( "%m/%d/%Y %H:%M:%S" ) )
            print( "Time step:  " + self.timeStep[1] + " " + self.timeStep[0] )
            print( "Missing Value:  " + self.missVal )
            print( "Time              Value(org.)              Quality"  )
            for k, v in self.timeValueQuality.items():
                 print(k.strftime( "%m/%d/%Y %H:%M"), v[0], v[1], v[2] )


        def getPreviousValueTime( self, t ):
            previousTime = None                 
            for k, v in self.timeValueQuality.items():
                if k <= t: 
                   if not math.isclose( v[ 0 ], \
                                     float( self.missVal ),\
                                   abs_tol=0.0001 ):
                      previousTime = k
                else:
                   break

            return previousTime
             
        def getNextValueTime( self, t ):
            nextTime = None                 
            for k, v in self.timeValueQuality.items():
                if k >= t:
                   if not math.isclose( v[ 0 ], \
                                     float( self.missVal ),\
                                   abs_tol=0.0001 ):
                      nextTime = k
                      break
            return nextTime

        def removeMissVals(self):
            keyMissVal = []
            for k in self.timeValueQuality.keys():
               v = self.timeValueQuality[ k ]
               if math.isclose( v[ 0 ], float( self.missVal ),\
                                                  abs_tol=0.0001 ):
                      keyMissVal.append( k )

            if keyMissVal:
                for k in keyMissVal:
                    self.timeValueQuality.pop( k ) 

            self.resetTimePeriod()

        def addLeadingAndTrailingZeros(self):
            #
            # Add trailing and leading zeros when the event raw data 
            # doesn't begin or end with a zero value.
            # This function can only be used for a forecast timeseries
            # because T0 is not available for observed timeseries
            #
            t0 = self.getT0()
            dt = timedelta( seconds = self.getTimeStepInSeconds() )
            if self.fstPeriod[0] > t0 - timedelta( hours = 48 ):
                 flag = self.timeValueQuality[ self.fstPeriod[0] ][1]
                 self.timeValueQuality.update( {self.fstPeriod[0] - dt: ( \
                            0.0, flag, False ) } )

                 self.timeValueQuality.move_to_end( self.fstPeriod[0] - dt, \
                                                                  last=False )

            if self.fstPeriod[1] < t0 + timedelta( hours = 240 ):
                 flag = self.timeValueQuality[ self.fstPeriod[1] ][1]
                 self.timeValueQuality.update( {self.fstPeriod[1] + dt: ( \
                            0.0, flag, False ) } )

                 self.timeValueQuality.move_to_end( self.fstPeriod[1] + dt, \
                                                                  last=True )

            self.resetTimePeriod()

        def linearInterpolate(self, dt):
            #
            # remove missing values
            #
            self.removeMissVals()
            if self.isEmpty():
               return self.timeValueQuality

            t = list( self.timeValueQuality.keys() )[ 0 ]
            last = list( self.timeValueQuality.keys() )[ -1 ]

            tvq = OrderedDict()
            while t <= last:
                 if t in self.timeValueQuality:
                   tvq[ t ] = self.timeValueQuality[ t ]
                 else:
                   t1 = self.getPreviousValueTime( t ) 
                   t2 = self.getNextValueTime( t )
                   
                   if ( t2  - t1 ).total_seconds() > 48 * 3600:

                      tvq[ t ] = ( float( self.missVal ), 0.0,   False )

                   else:

                      tvq[t] = ( ( self.timeValueQuality[t2][0] - \
                                      self.timeValueQuality[t1][0] ) * \
                         ( ( t - t1 ).total_seconds() / \
                         ( t2 - t1 ).total_seconds() )  + \
                         self.timeValueQuality[t1][0] ,
                         ( self.timeValueQuality[t2][1] - \
                                         self.timeValueQuality[t1][1] ) * \
                         ( ( t - t1 ).total_seconds() / \
                         ( t2 - t1 ).total_seconds() )  + \
                         self.timeValueQuality[t1][1], \
                         True )

                 t = t + dt

            if self.getTimeStepInSeconds() > int( dt.total_seconds() ):
               self.setTimeStepInSeconds(int( dt.total_seconds() ) )

            self.fstPeriod =  list( tvq.keys() )[0], list( tvq.keys() )[-1]
            self.startDate = self.fstPeriod[0]
            self.timeValueQuality = tvq
            return tvq
                  
        def interForwardPersist(self, dt):
            #
            # remove missing values
            #
            self.removeMissVals()

            t = list( self.timeValueQuality.keys() )[ 0 ]
            last = list( self.timeValueQuality.keys() )[ -1 ]

            tvq = OrderedDict()
            while t <= last:
                 if t in self.timeValueQuality:
                   tvq[ t ] = self.timeValueQuality[ t ]
                 else:
                   t1 = self.getPreviousValueTime( t ) 
                   
                   if ( t  - t1 ).total_seconds() > 10 * 24 * 3600:
                      tvq[ t ] = ( float( self.missVal ), 0.0,   False )
                   else:
                      tvq[t] = ( self.timeValueQuality[t1][0], \
                                 self.timeValueQuality[t1][1], \
                                 True )

                 t = t + dt

            if self.getTimeStepInSeconds() != int( dt.total_seconds() ):
               self.setTimeStepInSeconds(int( dt.total_seconds() ) )

            self.fstPeriod =  list( tvq.keys() )[0], list( tvq.keys() )[-1]
            self.startDate = self.fstPeriod[0]
            self.timeValueQuality = tvq
            return tvq

        def linearInterpolateAndInterForwardPersist(self, dt):
            #
            # remove missing values
            #
            self.removeMissVals()
            if self.isEmpty():
               return self.timeValueQuality

            t = list( self.timeValueQuality.keys() )[ 0 ]
            last = list( self.timeValueQuality.keys() )[ -1 ]

            t0 = self.getT0()

            tvq = OrderedDict()

            while t < t0:
                 if t in self.timeValueQuality:
                   tvq[ t ] = self.timeValueQuality[ t ]
                 else:
                   t1 = self.getPreviousValueTime( t ) 
                   t2 = self.getNextValueTime( t )
                   
                   #
                   # For LMRFC files that have missing values starting before
                   # T0, that is t2 is None, next value for t is missing or
                   # T0 > last.
                   #
                   if not t1 or not t2:
                      tvq[ t ] = ( float( self.missVal ), 0.0,   True )

                   else: 
                      if ( t2  - t1 ).total_seconds() > 48 * 3600:

                           tvq[ t ] = ( float( self.missVal ), 0.0,   True )

                      else:

                           tvq[t] = ( ( self.timeValueQuality[t2][0] - \
                                           self.timeValueQuality[t1][0] ) * \
                                    ( ( t - t1 ).total_seconds() / \
                                     ( t2 - t1 ).total_seconds() )  + \
                                      self.timeValueQuality[t1][0] ,
                                      ( self.timeValueQuality[t2][1] - \
                                         self.timeValueQuality[t1][1] ) * \
                                     ( ( t - t1 ).total_seconds() / \
                                       ( t2 - t1 ).total_seconds() )  + \
                                          self.timeValueQuality[t1][1], \
                                     True )

                 t = t + dt

            t = t0
            while t <= last:
                 if t in self.timeValueQuality:
                   tvq[ t ] = self.timeValueQuality[ t ]
                 else:
                   t1 = self.getPreviousValueTime( t ) 

                   if t1:
                     if ( t  - t1 ).total_seconds() > 10 * 24 * 3600:
                        tvq[ t ] = ( float( self.missVal ), 0.0,   True )
                     else: 
                        tvq[t] = ( self.timeValueQuality[t1][0], \
                                 self.timeValueQuality[t1][1], \
                                 True )
                   #
                   # If the previous value doesn't exist or 
                   # observed values (including T0) are not provided
                   #
                   else:
                        tvq[ t ] = ( float( self.missVal ), 0.0,   True )

                 t = t + dt

            if self.getTimeStepInSeconds() != int( dt.total_seconds() ):
               self.setTimeStepInSeconds(int( dt.total_seconds() ) )

            self.fstPeriod =  list( tvq.keys() )[0], list( tvq.keys() )[-1]
            self.startDate = self.fstPeriod[0]
            self.timeValueQuality = tvq
            return tvq

        def persistBackward(self, t, maxt, v = None ):

            if self.isEmpty():
              return self.timeValueQuality

            start = list( self.timeValueQuality.keys() )[ 0 ]
            dt = timedelta( seconds = self.getTimeStepInSeconds() )

#            while \
#               math.isclose( self.timeValueQuality[ start ][ 0 ], \
#                     float( self.missVal ), abs_tol=0.0001 ):
#               start = start + dt

            if t >= start:
              return None

            firstvalue = self.timeValueQuality[ start ]

            t1 = t
            it = start - dt
            if start - t  > maxt:
                t1 = start - maxt 

            while t1 <= it: 

                 self.timeValueQuality.update({it: ( \
                            firstvalue[0] if not isinstance(v, float) else v, \
                                                 firstvalue[1], True ) } )
                 self.timeValueQuality.move_to_end( it, last=False )

                 it = it - dt

            if start - t  > maxt:
               it = t1 - dt

               while t <= it: 

                 self.timeValueQuality.update({it: (  \
                   float( self.missVal ) if not isinstance(v, float) else v,  \
                                                    0.0,   True ) } )
                 self.timeValueQuality.move_to_end( it, last=False )

                 it = it - dt

            self.resetTimePeriod()

            return self.timeValueQuality

        def persistForward(self, t, v = None ):

            if self.isEmpty():
              return self.timeValueQuality

            end = list( self.timeValueQuality.keys() )[ -1 ]

            if t <= end:
              return self.timeValueQuality

            dt = timedelta( seconds = self.getTimeStepInSeconds() )

            while \
               math.isclose( self.timeValueQuality[ end ][ 0 ], \
                         float( self.missVal ), abs_tol=0.0001 ):
               end = end - dt

            vlast = self.timeValueQuality[ end ]

            end = end + dt

            while end <= t: 
                 self.timeValueQuality[end] = ( \
                                 vlast[0] if not isinstance(v, float) else v,\
                                                vlast[1], True )
                 end = end + dt

            self.resetTimePeriod()
            return self.timeValueQuality
