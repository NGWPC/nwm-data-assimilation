import unittest
from datetime import datetime, timedelta
from PI_XML import PI_XML
from RFC_Sites import RFC_Sites

class PI_XML_test(unittest.TestCase):
        def test(self):
                self.assertTrue(True)

        def testInit(self):
            pixml = PI_XML('./NERFC_Reservoir_Export.xml') 
            self.assertEqual('NERFC', pixml.getRFCName())
            self.assertEqual(pixml.timeZone, '0.0')

        def test_toRFCForecast(self):
            pixml = PI_XML('./NERFC_Reservoir_Export.xml') 

            print("test_toRFCForecast", pixml.source)

#            for s in pixml.series:
#                print(s.tag)

            rfc_series = pixml.toRFCForecast()

            for s in rfc_series:
                    print( s.stationID )
                    print( s.missVal )
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                           if abs(float( v[0] ) - float( s.missVal )) > 0.0001:
                                print(k, v)
           
            self.assertEqual( len( rfc_series ), 5 ) 
            self.assertEqual( rfc_series[ 0 ].stationID, 'INRN6' )
            self.assertEqual( rfc_series[ 1 ].stationID, 'SWRN6' )
            self.assertEqual( rfc_series[ 2 ].stationID, 'INRN6' )
            self.assertEqual( rfc_series[ 3 ].stationID, 'SWRN6' )
            self.assertEqual( rfc_series[ 4 ].stationID, 'INDN6HUD' )

        def test_2nd_RFC(self):
            pixml = PI_XML('./2019052412_QINE_NWM_Res_export.20190702202800')
            self.assertEqual('NWRFC', pixml.getRFCName())
            self.assertEqual( len( pixml.series ), 2 )

        def test_2nd_RFC_toRFCForecast(self):
            print( 'test_2nd_RFC_toRFCForecast:')
            pixml = PI_XML('./2019052812_QINE_NWM_Res_export.20190702202832')
            rfc_series = pixml.toRFCForecast()
            self.assertEqual( len( rfc_series ), len(pixml.series) ) 
            self.assertAlmostEqual( rfc_series[0].getTimeValueAt( \
                            datetime( 2019, 5, 28, 12, 0, 0) )[1][0], \
                            1.59751 )
           
        def test_2nd_RFC_QPF(self):
            print( 'test_2nd_RFC_QPF:')
            pixml = PI_XML('./2019052812_QPF_chps_pixml_export.20190702202832')
            rfc_series = pixml.toRFCForecast()
            self.assertEqual( len( rfc_series ), len(pixml.series) ) 
            self.assertAlmostEqual( rfc_series[3].getTimeValueAt( \
                            datetime( 2019, 6, 1, 0, 0, 0) )[1][0], \
                            0.011811 )


        def test_ABRFC(self):
            pixml = PI_XML('./2019052112_RES_NWM_pixml_export.20190705164143')
            self.assertEqual('ABRFC', pixml.getRFCName())
            self.assertEqual( len( pixml.series ), 108 )


        def test_ABRFC_toRFCForecast(self):
            print( 'test_ABRFC_toRFCForecast:')
            pixml = PI_XML('./2019052112_RES_NWM_pixml_export.20190705164143')
            rfc_series = pixml.toRFCForecast()

            for s in rfc_series:
                    print( s.stationID )
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                                print(k, v)

            self.assertEqual( len( rfc_series ), len(pixml.series) ) 
            self.assertEqual( rfc_series[8].stationID, 'CHNK1' )
            self.assertAlmostEqual( rfc_series[8].getTimeValueAt( \
                            datetime( 2019, 5, 19, 6, 0, 0) )[1][0], \
                            1534.9979 )
        def test_CBRFC(self):
            pixml = PI_XML('./CBRFC_Reservoirs_2019070612.xml')
            self.assertEqual('CBRFC', pixml.getRFCName())
            self.assertEqual( len( pixml.series ), 2 )

        def test_CBRFC_toRFCForecast(self):
            print( 'test_CBRFC_toRFCForecast:')
            pixml = PI_XML('./CBRFC_Reservoirs_2019070712.xml')
            rfc_series = pixml.toRFCForecast()

            for s in rfc_series:
                    print( s.stationID )
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                                print(k, v)

            self.assertEqual( len( rfc_series ), len(pixml.series) ) 
            self.assertEqual( rfc_series[1].stationID, 'GRZU1OSF' )
            self.assertAlmostEqual( rfc_series[1].getTimeValueAt( \
                            datetime( 2019, 7, 16, 17, 0, 0) )[1][0], \
                            1487.9976 )

        def test_LMRFC(self):
            pixml = PI_XML('./LMRFC_RESERVOIR_FORECAST.20190819')
            self.assertEqual('LMRFC', pixml.getRFCName())
            self.assertEqual( len( pixml.series ), 180 )
            print( "LMRFC length: ",  len( pixml.series ) )

        def test_LMRFC_toRFCForecast(self):
            print( 'test_LMRFC_toRFCForecast:')
            pixml = PI_XML('./LMRFC_RESERVOIR_FORECAST.20190819')
            rfc_series = pixml.toRFCForecast()
            sites = RFC_Sites( './RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv')
            lmsites = sites.getSitesByRFC( 'LMRFC' )

            for lms in lmsites:
              print( lms + ':')
              for s in rfc_series:
                if s.stationID[:5] == lms:
                  if len(s.timeValueQuality) > 0:
                          print( '           found: ', s.stationID[:5], "OK", s.getTimePeriod()[0].strftime("%m/%d/%Y %H:%M") + ' - ' + s.getTimePeriod()[1].strftime("%m/%d/%Y %H:%M") )
                  else:
                       print( '           found: ', s.stationID[:5], "missing data" )
#                    if len(s.timeValueQuality) > 0:
#                        for k, v in s.timeValueQuality.items():
#                                print(k, v)
#               else:
#                    print( 'not found: ', s.stationID )
           
        def test_MBRFC_Hourly(self):
            pixml = PI_XML('./20190819182258_RQOT_Forecast_1hr_missings_xml_2019080512')
            sites = RFC_Sites( './RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv')
            self.assertEqual('MBRFC', pixml.getRFCNameBySitelist(sites))
            self.assertEqual( len( pixml.series ), 1 )
            print( "MBRFC length: ",  len( pixml.series ) )

        def test_MBRFC_Hourly_toRFCForecast(self):
            print( 'test_MBRFC_Hourly_toRFCForecast:')
            pixml = PI_XML('./20190819182258_RQOT_Forecast_1hr_missings_xml_2019080512')
            rfc_series = pixml.toRFCForecast()

            for s in rfc_series:
                    print( s.stationID )
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                                print('     ', k, v)
                    print( 'missVal = ', s.missVal )

        def test_MBRFC_6Hourly(self):
            pixml = PI_XML('./20190819182258_RQOT_Forecast_6hr_missings_xml_2019080512')
            self.assertEqual('MBRFC', pixml.getRFCName())
            self.assertEqual( len( pixml.series ), 1 )
            print( "MBRFC 6 hourly length: ",  len( pixml.series ) )

        def test_MBRFC_6Hourly_toRFCForecast(self):
            print( 'test_MBRFC_6Hourly_toRFCForecast:')
            pixml = PI_XML('./20190819182258_RQOT_Forecast_6hr_missings_xml_2019080512')
            rfc_series = pixml.toRFCForecast()

            for s in rfc_series:
                    print( s.stationID )
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                                print('     6 hourly: ',  k, v)
                    print( '6 hourly missVal = ', s.missVal )

        def test_MBRFC(self):
            pixml = PI_XML('./MBRFC_RQOT_Forecast.xml')
#            self.assertEqual('MBRFC', pixml.getRFCName())
            self.assertEqual( len( pixml.series ), 19 )
            print( "MBRFC length: ",  len( pixml.series ) )

        def test_MBRFC_toRFCForecast(self):
            print( 'test_MBRFC_toRFCForecast:')
            pixml = PI_XML('./MBRFC_RQOT_Forecast.xml')
            rfc_series = pixml.toRFCForecast()

            for s in rfc_series:
                    print( s.stationID )
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                           if abs( v[0] - float( s.missVal ) ) > 0.0001:
                                print('     : ',  k, v)
                    print( 'missVal = ', s.missVal )

        def test_MBRFC_Monday_toRFCForecast(self):
            print( 'test_MBRFC_Monday_toRFCForecast:')
            pixml = PI_XML('./MBRFC_RQOT_Forecast_Monday.xml')
            sites = RFC_Sites( './RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv')
            lmsites = sites.getSitesByRFC( 'MBRFC' )
            rfc_series = pixml.toRFCForecast()
            self.assertEqual( len( pixml.series ), 19 )

            self.assertAlmostEqual( rfc_series[1].getTimeValueAt( \
                            datetime( 2019, 8, 30, 13, 0, 0) )[1][0], \
                            2635.29 )
            for lms in lmsites:
               for s in rfc_series:
                if s.stationID[:5] == lms:
                  if len(s.timeValueQuality) > 0:
                       print( '           found: ', s.stationID[:5], "OK", s.getTimePeriod()[0].strftime("%m/%d/%Y %H:%M") + ' - ' + s.getTimePeriod()[1].strftime("%m/%d/%Y %H:%M") )
                  else:
                       print( '           found: ', s.stationID[:5], "missing data" )

            for s in rfc_series:
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                           if abs( v[0] - float( s.missVal ) ) > 0.0001:
                                print('     : ',  k, v)

        def test_NERFC_toRFCForecast(self):
            print( 'test_NERFC_toRFCForecast:')
            pixml = PI_XML('./20190822_12z_NERFC_Reservoir_Export.xml')
            sites = RFC_Sites( './RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv')
            lmsites = sites.getSitesByRFC( 'NERFC' )
            rfc_series = pixml.toRFCForecast()
            print( len( rfc_series ) )
            self.assertEqual( len( rfc_series ), 18 )
            self.assertAlmostEqual( rfc_series[1].getTimeValueAt( \
                            datetime( 2019, 8, 23, 18, 0, 0) )[1][0], \
                            300.0332 )
            for lms in lmsites:
               for s in rfc_series:
                if s.stationID[:5] == lms:
                  if len(s.timeValueQuality) > 0:
                       print( '           found: ', s.stationID[:5], "OK", s.getTimePeriod()[0].strftime("%m/%d/%Y %H:%M") + ' - ' + s.getTimePeriod()[1].strftime("%m/%d/%Y %H:%M") )
                  else:
                       print( '           found: ', s.stationID[:5], "missing data" )

            for s in rfc_series:
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                           if abs( v[0] - float( s.missVal ) ) > 0.0001:
                                print('     : ',  k, v)

        def test_NERFC_1_toRFCForecast(self):
            print( 'test_NERFC_1_toRFCForecast:')
            pixml = PI_XML('./20190820_12z_NERFC_Reservoir_Export.xml')
            sites = RFC_Sites( './RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv')
            lmsites = sites.getSitesByRFC( 'NERFC' )
            rfc_series = pixml.toRFCForecast()
            print( len( rfc_series ) )
#            self.assertEqual( len( rfc_series ), 18 )
#            self.assertAlmostEqual( rfc_series[1].getTimeValueAt( \
#                            datetime( 2019, 8, 23, 18, 0, 0) )[1][0], \
#                            300.0332 )
            for lms in lmsites:
               for s in rfc_series:
                if s.stationID[:5] == lms:
                  if len(s.timeValueQuality) > 0:
                       print( '           found: ', s.stationID[:5], "OK", s.getTimePeriod()[0].strftime("%m/%d/%Y %H:%M") + ' - ' + s.getTimePeriod()[1].strftime("%m/%d/%Y %H:%M") )
                  else:
                       print( '           found: ', s.stationID[:5], "missing data" )

            for s in rfc_series:
                    if len(s.timeValueQuality) > 0:
                        for k, v in s.timeValueQuality.items():
                           if abs( v[0] - float( s.missVal ) ) > 0.0001:
                                print('     : ',  k, v)
        def test_MARFC_toRFCForecast(self):
            print( 'test_MARFC_toRFCForecast:')
            sites = RFC_Sites( './RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv')
            for stn in ["BCHP1BEC", "JCKV2JCK", "DWNN6DEL", "CNNN6DEL" ]:
              pixml = PI_XML('./20190824_' + stn + '.xml')
              rfc_series = pixml.toRFCForecast()
              print( stn + ":" )
              self.assertEqual( len( rfc_series ), 1 )
              self.assertEqual('MARFC', pixml.getRFCNameBySitelist(sites))
              for s in rfc_series:
                  print("   " + s.stationID[:5], "OK", s.getTimePeriod()[0].strftime("%m/%d/%Y %H:%M") + ' - ' + s.getTimePeriod()[1].strftime("%m/%d/%Y %H:%M") )
                  if len(s.timeValueQuality) > 0:
                      for k, v in s.timeValueQuality.items():
                          if abs( v[0] - float( s.missVal ) ) > 0.0001:
                                print('     : ',  k, v)


if __name__ == '__main__':
        unittest.main()
