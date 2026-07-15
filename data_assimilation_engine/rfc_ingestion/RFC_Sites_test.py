import unittest
from RFC_Sites import RFC_Sites 

class RFC_Sites_test(unittest.TestCase):
        def test(self):
                self.assertTrue(True)

        def testInit(self):
                sites = RFC_Sites('./RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv' )
                self.assertEqual( len(sites.gauge), 380 )  	
                self.assertEqual( len(sites.gaugedFlowline), 380 )  	
                self.assertEqual( len(sites.NHDWaterbodyComID), 380 )  	
                self.assertEqual( len(sites.lakeLink), 380 )  	
                self.assertEqual( len(sites.SiteName), 380 )  	

if __name__ == '__main__':
        unittest.main()
