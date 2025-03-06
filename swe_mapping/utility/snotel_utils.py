import re
import fsspec
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

class SnotelDataLoader:
    @staticmethod
    def list_snotel_filenames():
        """
        List SNOTEL CSV files available in the S3 bucket.
        
        Returns
        -------
        list
            List of filenames (strings) of SNOTEL CSV files in the S3 bucket
        """
        fs = fsspec.filesystem('s3')
        path = 'ngwpc-forcing/snotel_csv/'
        objects = fs.ls(path)

        filenames = [obj.split('/')[-1] for obj in objects if '/' in obj]
        
        # Filter out empty strings
        snotel_filenames = [f for f in filenames if f]

        return snotel_filenames

    @staticmethod
    def parse_snotel_filenames(filenames):
        """
        Parse latitude and longitude from SNOTEL filenames and create a GeoDataFrame.
        
        Parameters
        ----------
        filenames : list
            List of SNOTEL filenames to parse
        
        Returns
        -------
        geopandas.GeoDataFrame
            GeoDataFrame with columns for station_id, latitude, longitude, filename,
            and geometry (Point objects)
        """
        data = []
        
        for filename in filenames:
            # Skip if not a CSV file
            if not filename.endswith('.csv'):
                continue
                
            # Use regex to extract information from the filename
            match = re.search(r'(\d+)_LAT_([\d.-]+)_LON_([\d.-]+)\.csv', filename)
            
            if match:
                station_id = match.group(1)
                latitude = float(match.group(2))
                longitude = float(match.group(3))
                
                data.append({
                    'station_id': station_id,
                    'latitude': latitude,
                    'longitude': longitude,
                    'filename': filename,
                    'geometry': Point(longitude, latitude)  # Create Point geometry (x=lon, y=lat)
                })
        
        # Convert to GeoDataFrame for spatial operations
        stations_gdf = gpd.GeoDataFrame(data, geometry='geometry')
        
        # Assuming WGS 84 (EPSG:4326) for the coordinates
        stations_gdf.crs = "EPSG:4326"
        
        return stations_gdf
    
    @staticmethod
    def load_snotel_data(stations_in_basin, date):
        """
        Load SNOTEL SWE data for stations within the basin for a specific date.
        
        Parameters
        ----------
        stations_in_basin : geopandas.GeoDataFrame
            GeoDataFrame of SNOTEL stations that are within the basin
        date : str
            Date string in format 'YYYY-MM-DD'
        
        Returns
        -------
        pandas.DataFrame
            DataFrame with station information and SWE values for the specified date
        """
        if stations_in_basin.empty:
            return pd.DataFrame()
        
        # Initialize a list to store data
        snotel_data_list = []
        
        # S3 filesystem
        fs = fsspec.filesystem('s3')
        
        # Process each station in the basin
        for _, station in stations_in_basin.iterrows():
            filename = station['filename']
            s3_path = f"s3://ngwpc-forcing/snotel_csv/{filename}"
            
            try:
                # Open and read the CSV file
                with fs.open(s3_path, 'r') as file:
                    df = pd.read_csv(file)
                    # Convert the target date to datetime
                    target_date = pd.to_datetime(date)
                    
                    # Filter for rows where the date matches our target date
                    df['date'] = pd.to_datetime(df['date'])
                    df_filtered = df[df['date'].dt.date == target_date.date()]
                    
                    if not df_filtered.empty:
                        # Get the SWE value for this date
                        swe_value = df_filtered['snotel_swe'].iloc[0]
                        
                        # Create a record with station info and SWE value
                        snotel_data_list.append({
                            'station_id': station['station_id'],
                            'latitude': station['latitude'],
                            'longitude': station['longitude'],
                            'swe': swe_value
                        })
                    else:
                        print(f"No data found for station {station['station_id']} on {date}")
            except Exception as e:
                print(f"Error loading SNOTEL data for station {station['station_id']}: {e}")
        
        # Convert list to DataFrame
        snotel_df = pd.DataFrame(snotel_data_list)       
        return snotel_df

class SnotelCalculator:
    @staticmethod
    def find_stations_in_basin(stations_gdf, basin_geometry):
        """
        Find SNOTEL stations that fall within the basin geometry.
        
        Parameters
        ----------
        stations_gdf : geopandas.GeoDataFrame
            GeoDataFrame containing SNOTEL station information
        basin_geometry : shapely.geometry
            Basin geometry to use for filtering stations
            
        Returns
        -------
        geopandas.GeoDataFrame
            Filtered GeoDataFrame containing only stations within the basin
        """
        # Ensure CRS match between stations and basin geometry
        if hasattr(basin_geometry, 'crs') and basin_geometry.crs != stations_gdf.crs:
            stations_gdf = stations_gdf.to_crs(basin_geometry.crs)
        
        # Filter stations within the basin
        stations_in_basin = stations_gdf[stations_gdf.intersects(basin_geometry)]

        return stations_in_basin

class SnotelPlotter:
    @staticmethod
    def add_snotel_overlay(ax, snotel_data, proj):
        """
        Add SNOTEL SWE data as text overlays on a map.
        
        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Axes object to add overlay to
        snotel_data : pandas.DataFrame
            DataFrame with station information and SWE values
        proj : cartopy.crs
            Projection to use
            
        Returns
        -------
        matplotlib.axes.Axes
            Updated axes with SNOTEL overlay
        """
        if snotel_data.empty:
            return ax
        
        # Plot each SNOTEL station
        for _, station in snotel_data.iterrows():
            swe_value = f"{station['swe']:.2f}"
            color = '#990000'
            
            # Add text of swe_values at location
            ax.text(
                station['longitude'] + 0.0005, 
                station['latitude'] - 0.0005, 
                swe_value,
                fontsize=11,
                ha='left',
                va='top',
                transform=proj,
                fontweight='bold',
                color= color
            )
            
            # Add a marker for the station location
            ax.plot(
                station['longitude'], 
                station['latitude'], 
                'o',
                markersize=3,
                transform=proj,
                color=color,
                label='SNOTEL Stations (SWE)'
            )
            
            ax.legend(loc='upper right', 
                      fontsize=10, 
                      framealpha=0.5,
                      bbox_to_anchor=(1.25, 1.05)
                      )
        
        return ax
