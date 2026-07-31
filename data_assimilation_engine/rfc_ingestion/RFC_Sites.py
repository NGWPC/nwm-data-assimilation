###############################################################################
#  Module name: RFC_Sites
#                                                                             #
#  Author     : Zhengtao Cui (Zhengtao.Cui@noaa.gov)                          #
#                                                                             #
#  Initial version date:                                                      #
#                                                                             #
#  Last modification date:  08/19/2019                                         #
#                                                                             #
#  Description: manage the RFC sites in CSV format                       #
#                                                                             #
###############################################################################

import csv

class RFC_Sites:
        """
           Store RFC site information 
        """        
        def __init__(self, csvSitefile ):
           """
              Initialize the RFC_Sites object with a given
              filename
           """
           self.source = csvSitefile

           self.gauge = []
           self.gaugedFlowline = []
           self.NHDWaterbodyComID = []
           self.lakeLink = []
           self.SiteName = []
           self.RFC = []
           self.comments = []
           with open( csvSitefile, mode='r') as csvsite_file: 
                   csvsite_reader = csv.DictReader( csvsite_file )
                   line_count = 0
                   for row in csvsite_reader:
                       if line_count == 0:
                              print('Column names are ' + ", ".join(row))
                              line_count += 1
                       self.gauge.append( row["gage"] )                   
                       self.gaugedFlowline.append( row["gagedFlowline"] )
                       self.NHDWaterbodyComID.append( row["NHDWaterbodyComID"] )
                       self.lakeLink.append( row["lakeLink"] ) 
                       self.SiteName.append( row["SiteName"] )
                       self.RFC.append( row["RFC"] )
                       self.comments.append( "Not present!" ) 
                       line_count += 1

                   print('Processed ' + str( line_count ) + ' lines.')


        @property
        def source(self):
            return self._source

        @source.setter
        def source(self, s):
            self._source = s

        @property
        def gauge(self):
            return self._gauge

        @gauge.setter
        def gauge(self, g):
            self._gauge=g

        @property
        def gaugedFlowline(self):
            return self._gaugedFlowline

        @gaugedFlowline.setter
        def gaugedFlowline(self, g):
            self._gaugedFlowline=g

        @property
        def NHDWaterbodyComID(self):
            return self._NHDWaterbodyComID

        @NHDWaterbodyComID.setter
        def NHDWaterbodyComID(self, n):
            self._NHDWaterbodyComID=n

        @property
        def lakeLink(self):
            return self._lakeLink

        @lakeLink.setter
        def lakeLink(self, l):
            self._lakeLink=l

        @property
        def SiteName(self):
            return self._SiteName

        @SiteName.setter
        def SiteName(self, s):
            self._SiteName=s

        @property
        def RFC(self):
            return self._RFC

        @RFC.setter
        def RFC(self, r):
            self._RFC=r

        @property
        def comments(self):
            return self._comments

        @comments.setter
        def comments(self, c):
            self._comments=c

        def siteExist(self, s):
            return s in self.gauge

        def addComment( self, sta, message ):
              try:
                   ind = self.gauge.index( sta )
                   self._comments[ ind ] = message
              except ValueError as e:  
                   raise RuntimeError( e )

        def getSitesByRFC( self, rfcname ):
                sites = []
                for s, rfc in zip(self.gauge, self.RFC):
                    if rfc == rfcname:
                       sites.append( s )
                return sites

        def getRFCBySite( self, sta ):
            for s, rfc in zip(self.gauge, self.RFC):
                if s == sta:
                  return rfc
            return None
