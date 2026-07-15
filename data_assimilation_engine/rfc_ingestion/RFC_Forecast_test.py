import unittest
import copy
from datetime import datetime, timedelta
from PI_XML import PI_XML
from RFC_Forecast import RFC_Forecast
from RFC_Sites import RFC_Sites

class RFC_Forecast_test(unittest.TestCase):
        def run_rfc_test(self, pixmlfile, sitefile ):
             rfcsites = RFC_Sites( sitefile )
             pixml = PI_XML( pixmlfile, rfcsites )

             allids = pixml.getAllStationIDs()
             print(allids)
             for s in pixml.getFlowTimeseries():
                 s.print()
                 print("=========================================")


             for id in allids:
                print( "============== " + id + " ===============" )
                ts = pixml.getObservedAndForecastForID( id )
#                if ts[0] is None or ts[1] is None:
#                  print( "Missing observed or forecast: " + id + " : " +
#                                  rfcsites.getRFCBySite( id ) )
#                  break
                ts[0].print()
                ts[1].print()
                obvhourly = copy.deepcopy( ts[0] )
                fsthourly = copy.deepcopy( ts[1] )
                obvhourly.linearInterpolate( timedelta( hours = 1 ))
                fsthourly.linearInterpolate( timedelta( hours = 1 ))
                obvhourly.persistForward( obvhourly.getTimePeriod()[1] + \
                                         timedelta( days = 2 ) )
                obvhourly.persistBackward( obvhourly.getTimePeriod()[0] - \
                                         timedelta( days = 2 ) )
                fsthourly.persistForward( fsthourly.getTimePeriod()[1] + \
                                         timedelta( days = 2 ) )
                fsthourly.persistBackward( fsthourly.getTimePeriod()[0] - \
                                         timedelta( days = 2 ) )
                print( "============== " + "hourly: " + id + " ===============" )

                print( "============== " + "combined: " + id + " ===============" )
                combined = \
                   pixml.combineObvFstAndApplyPresistenceLinearInterpolation( ts )
                combined.print()
             allcombined = \
                pixml.getReserviorObservedForecastCombinedWithT0()

             print( "============== all combined: ===============" )
             for c in allcombined:
                print( "============== all combined: " + c.get5CharStationID() + " ===============" )
                c.print()

             self.assertTrue(True)

        def test_NCRFC( self ):
             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/ncrfc/201911181200_NCRFC_Reservoir_Export.xml"
             self.run_rfc_test( pixmlfile, sitefile )
             self.assertTrue(True)

        def test_NERFC( self ):
             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/nerfc/NERFC_Reservoir_Export.xml"

             self.run_rfc_test( pixmlfile, sitefile )

             self.assertTrue(True)

        def test_WGRFC( self ):
             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/wgrfc/WGRFC_11.27.2019.16.00.xml"

             self.run_rfc_test( pixmlfile, sitefile )

             self.assertTrue(True)

        def test_MARFC( self ):
             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/marfc/2019112712_MARFC_Reservoir_Export.xml"

             self.run_rfc_test( pixmlfile, sitefile )
             self.assertTrue(True)

        def test_OHRFC( self ):
             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             for pixmlfile in [ \
                 "./testdata/ohrfc/201911271319_OHRFC_Reservoir_Export_SAGU.xml",
                 "./testdata/ohrfc/201911271327_OHRFC_Reservoir_Export_SAGL.xml",
             "./testdata/ohrfc/201911271331_OHRFC_Reservoir_Export_SMNU.xml",
             "./testdata/ohrfc/201911271332_OHRFC_Reservoir_Export_SBVR.xml",
             "./testdata/ohrfc/201911271332_OHRFC_Reservoir_Export_SMNL.xml" ]:
                self.run_rfc_test( pixmlfile, sitefile )

        def test_ABRFC( self ):

             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/abrfc/2019112712_ABRFC_RES_NWM_pixml_export.xml"

             self.run_rfc_test( pixmlfile, sitefile )

        def test_LMRFC( self ):

             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/lmrfc/201911290111_LMRFC_Reservoir_export.xml"

             self.run_rfc_test( pixmlfile, sitefile )

        def test_SERFC( self ):

             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/serfc/201911290600_SERFC_Reservoir_Export.xml"

             self.run_rfc_test( pixmlfile, sitefile )

        def test_CBRFC( self ):

             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/cbrfc/201911281800_CBRFC_Reservoir_Export.xml"

             self.run_rfc_test( pixmlfile, sitefile )

        def test_CNRFC( self ):

             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/cnrfc/201911290600_CNRFC_Reservoir_Export_for_NWM.xml"

             self.run_rfc_test( pixmlfile, sitefile )
        def test_NWRFC( self ):

             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/nwrfc/NWRFC_11.29.2019.2100.xml"

             self.run_rfc_test( pixmlfile, sitefile )

        def test_MBRFC( self ):

             sitefile = "./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
             pixmlfile = "./testdata/mbrfc/201911111541_MBRFC_Reservoir_Export.xml"

             self.run_rfc_test( pixmlfile, sitefile )

if __name__ == '__main__':
        unittest.main()
