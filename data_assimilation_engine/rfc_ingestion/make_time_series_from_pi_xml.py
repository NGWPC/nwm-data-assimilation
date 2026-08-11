#! /usr/bin/env python
###############################################################################
#  File name: make_time_slice_from_pi_xml.py                                 #
#                                                                             #
#  Author     : Zhengtao Cui (Zhengtao.Cui@noaa.gov)                          #
#                                                                             #
#  Initial version date:                                                      #
#                                                                             #
#  Last modification date:  5/30/2019                                         #
#                                                                             #
#  Description: The driver to create NetCDF time slice files from Army Crops  #
#               of Engineers real-time observations                           #
#                                                                             #
###############################################################################

import os, sys, time, urllib, getopt, re
import logging
import glob
from string import *
import xml.etree.ElementTree as etree
from datetime import datetime, timedelta
from PI_XML import PI_XML
from RFC_Forecast import RFC_Forecast
from RFCTimeSeries import RFCTimeSeries
from RFCHelper import RFCHelper
from RFC_Sites import RFC_Sites
from data_assimilation_engine.EmptyDirOrFileException import EmptyDirOrFileException
#import Tracer

"""
   The driver to parse downloaded ACE XML observations and 
   create time slices and write to NetCDF files
   Author: Zhengtao Cui (Zhengtao.Cui@noaa.gov)
   Date: May 30, 2019
"""
def main(argv):
   """
     function to get input arguments
   """
   inputdir = ''
   try:
           opts, args = getopt.getopt(argv,"hi:o:s:",["idir=", "odir=", \
                                                      "sites="])
   except getopt.GetoptError:
      print('make_time_slice_from_pi_xml.py -i <inputdir> -o <outputdir> -s <rfcsitefile>')
      sys.exit(2)
   for opt, arg in opts:
      if opt == '-h':
         print( \
           'make_time_slice_from_pi_xml.py -i <inputdir> -o <outputdir> -s <rfcsitefile>')
         sys.exit()
      elif opt in ('-i', "--idir"):
         inputdir = arg
         if not os.path.exists( inputdir ):
                 raise RuntimeError( 'FATAL Error: inputdir ' + \
                                 inputdir + ' does not exist!' )
      elif opt in ('-o', "--odir" ):
         outputdir = arg
         if not os.path.exists( outputdir ):
                 raise RuntimeError( 'FATAL Error: outputdir ' + \
                                 outputdir + ' does not exist!' )
  
      elif opt in ('-s', "--rfcsitefile" ):
         sitefile = arg
         if not os.path.exists( sitefile ):
                 raise RuntimeError( 'FATAL Error: sitefile ' + \
                                 sitefile + ' does not exist!' )
  
   return (inputdir, outputdir, sitefile)




t0 = time.time()

logging.basicConfig(format=\
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',\
                level=logging.INFO)
logger = logging.getLogger(__name__)
formatter = logging.Formatter(\
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#logger.setFormatter(formatter)
logger.info( "System Path: " + str( sys.path ) )

if __name__ == "__main__":
   try:
      odir = main(sys.argv[1:])
   except Exception as e:
      logger.error("Failed to get program options.", exc_info=True)

indir = odir[0]
outdir = odir[1]
rfcsitefile = odir[2]
logger.info( 'Input dir is "' + indir + '"')
logger.info( 'Output dir is "' + outdir + '"')
logger.info( 'RFC site file is "' + rfcsitefile + '"')

#
# Load ACE observed XML discharge data
#

try:
   fcsts = []

   stationsNotInListFile = { 'ABRFC': set(), \
                             'SERFC': set(), \
                             'LMRFC': set(), \
                             'MARFC': set(), \
                             'NERFC': set(), \
                             'WGRFC': set(), \
                             'MBRFC': set(), \
                             'CNRFC': set(), \
                             'NWRFC': set(), \
                             'NCRFC': set(), \
                             'CBRFC': set(), \
                             'OHRFC': set(), \
                             'APRFC': set(), \
                             'UNKNOWN': set() }

   if not os.path.isdir( indir ):
#           raise SystemExit( "FATAL ERROR: " + indir + \
           raise RuntimeError( "FATAL ERROR: " + indir + \
                                   " is not a directory or does not exist. ")

   YYYYMMDDHH = '[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[1-2][0-9]|3[0-1])(2[0-3]|[01][0-9])'
   YYYYMMDDHHMMSS = YYYYMMDDHH + '(0[0-9]|[1-5][0-9]){2}'
   ABRFCPattern = '^(.*/)?' + YYYYMMDDHH + '_RES_NWM_pixml_export.' + YYYYMMDDHHMMSS
   NWRFCPattern = '^(.*/)?' + YYYYMMDDHH + '_QINE_NWM_Res_export.' + YYYYMMDDHHMMSS
   rfcsites = RFC_Sites( rfcsitefile )

   thirtyMinAgo = datetime.now() - timedelta(minutes=30)
#   for file in os.listdir( indir ): 
   for file in sorted( glob.glob( indir + '/*' ),  key=os.path.getmtime ): 
#     mtime=datetime.fromtimestamp(\
#                     os.stat(os.path.join( indir,  file)).st_mtime)
#        m1 = re.match( ABRFCPattern, file )
#        m2 = re.match( NWRFCPattern, file )
#        if file.endswith( ".xml" ) or m1 or m2:
#     if mtime > thirtyMinAgo:
     logger.info( 'Reading ' + file + ' ... ' )
     try:
           pixml = PI_XML( file, rfcsites ) 
#           rfc_series = pixml.getReserviorForecastWithT0()
           t1 = time.time()
           rfc_series = pixml.getReserviorObservedForecastCombinedWithT0()
           logger.info( "Processing PI XML file done: " + \
                "{0:.1f}".format( (time.time() - t1) ) + \
                 " seconds" )
           for s in rfc_series:
              if rfcsites.siteExist( s.get5CharStationID() ):
                    if not s.isEmpty():
                        fcsts.append( s )
                        rfcsites.addComment( s.get5CharStationID(), \
                                        "OK")
                    else:
                        rfcsites.addComment( s.get5CharStationID(), \
                                        "Empty")
              else:
                    rfcname = re.search( "[A-Z][A-Z]RFC",  file).group() if \
                          re.search( "[A-Z][A-Z]RFC",  file) else "UNKNOWN"
                    if not s.isEmpty():
                        stationsNotInListFile[ rfcname ].add( \
                                          s.get5CharStationID() )
                          
                    else:
                        stationsNotInListFile[ rfcname ].add( \
                                          s.get5CharStationID() + "*" )

     except Exception as e:
                logger.warn( repr( e ), exc_info=True )
                continue

   if not fcsts:
           raise EmptyDirOrFileException( "Input directory " + indir + \
                           " has no PI XML files or no forecast data"
              " in PI XML files!" )
#              raise SystemExit(0)
   for s, r, c in zip( rfcsites.gauge, rfcsites.RFC, rfcsites.comments ):
       logger.info( 'Site info: ' +  s + "  " + r + "  " + c )
   logger.info( 'Sits not in the site file:' )
   for k, v in stationsNotInListFile.items():
       if v:
          for e in v:
            logger.info( '     ' + e + (':  ' if len(e) == 6 else ' :  ') + k )

   logger.info( 'Note: \'*\' - flow values are missing.' )

except EmptyDirOrFileException as e:
   logger.warning( str(e), exc_info=True)
   sys.exit(0)
except Exception as e:
   logger.error("Failed to load PI XML files:" + str(e), exc_info=True)
   sys.exit(3)

try:
   helper = RFCHelper( fcsts  )

   logger.info( 'Earliest time in PI XML: ' + \
                helper.timePeriodForAll()[0].isoformat() )
   logger.info( 'Latest time in PI XML: ' +  \
                helper.timePeriodForAll()[1].isoformat() )

   #
   # Create time slices from loaded observations
   #
   # Set time resolution to 60 minutes
   # and
   # Write time slices to NetCDF files
   #
   timeslices = helper.makeAllTimeSeries( outdir, 'RFCTimeSeries.ncdf' )
except Exception as e:
   logger.error("Failed to make time series:" + str(e), exc_info=True)
   logger.error("Input dir = " + indir, exc_info=True)
   sys.exit(3)

logger.info( "Total number of timeseries: " + str( timeslices ) )
logger.info( "Program finished in: " + \
                "{0:.1f}".format( (time.time() - t0) / 60.0 ) + \
                 " minutes" )

