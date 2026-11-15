# BurnWindow
A burning-activity calendar for NASA Space Apps 2026's MODIS and VIIRS hotspot harmonization challenge.
Search a place, compare satellite records, and explore seasonal patterns with visible model errors and observation limits.
Python 3.12+: `pip install -r requirements.txt`, `python prepare_data.py`, then `python server.py --port 8766`; open http://localhost:8766.
Data: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/), [NOAA](https://registry.opendata.aws/noaa-jpss/), [MTBS](https://www.mtbs.gov/), [GeoNames (CC BY 4.0)](https://www.geonames.org/), [Natural Earth](https://www.naturalearthdata.com/). Counts represent reports, not distinct fires.
