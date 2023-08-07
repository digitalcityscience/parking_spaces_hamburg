import geopandas
from typing import List
from shapely.geometry import MultiPolygon
import math
from geopy.geocoders import Nominatim

import json


"""
CLIPPING

hamburg_boundary = geopandas.read_file("HH_WFS_Verwaltungsgrenzen.gml")
hamburg_boundary = hamburg_boundary.set_crs("EPSG:25832", allow_override=True)
print(hamburg_boundary.head())
print(hamburg_boundary.crs)

bounds = geopandas.read_file("test_area_bounds.geojson")
bounds = bounds.set_crs("EPSG:4326", allow_override=True)
bounds = bounds.to_crs("EPSG:25832")  # reproject to metric coordinates

osm_parking = geopandas.read_file("all_parking_spaces_osm.geojson")
osm_parking = osm_parking.set_crs("EPSG:4326", allow_override=True)
osm_parking = osm_parking.to_crs("EPSG:25832")  # reproject to metric coordinates

osm_parking = geopandas.clip(osm_parking, hamburg_boundary)  # clip to hamburg boundaries
osm_parking = geopandas.clip(osm_parking, bounds) # clip to test boundaries for faster processing
osm_parking.to_file("test_osm_parking.geojson", driver="GeoJSON")
"""


def load_data() -> List[geopandas.GeoDataFrame]:
    """
    reads the data and sets the crs
    """
    osm_parking = geopandas.read_file("final_OSM_EXPORT.geojson")
    # fix the strings like "ca 7" or "650+" to a number in the geojson file, if script fails here.
    osm_parking["capacity"] = osm_parking["capacity"].astype(float)
    osm_parking = osm_parking.drop(columns=["FIXME", "fixme"])  # drop irrelevant semi-duplicate columns complicating export

    osm_parking = osm_parking.set_crs("EPSG:4326", allow_override=True)
    osm_parking = osm_parking.to_crs("EPSG:25832")  # reproject to metric coordinates

    geoportal_parking = geopandas.read_file("all_parking.gpkg")
    geoportal_parking = geoportal_parking.set_crs("EPSG:25832", allow_override=True)

    hamburg_boundary = geopandas.read_file("HH_WFS_Verwaltungsgrenzen.gml")
    hamburg_boundary = hamburg_boundary.set_crs("EPSG:25832", allow_override=True)

    return geopandas.clip(osm_parking, hamburg_boundary), geopandas.clip(
        geoportal_parking, hamburg_boundary
    )


def filter_on_public_parking_spaces(
    osm_parking: geopandas.GeoDataFrame, geoportal_parking: geopandas.GeoDataFrame
):
    """
    Delete all parking surfaces that have an intersection with public parking > 75% of their area
    """
    union_multi_poly: MultiPolygon = geoportal_parking.geometry.unary_union

    osm_parking["intersection_area"] = osm_parking.geometry.apply(
        lambda geom: geom.intersection(union_multi_poly).area
    )
    osm_parking["intersection_area_percent"] = (
        osm_parking["intersection_area"] / osm_parking.geometry.area
    )

    return osm_parking[osm_parking["intersection_area_percent"] <= 0.75]


def export_to_excel(gdf: geopandas.GeoDataFrame):
    # export as Excel
    print("export to Excel")
    import pandas as pd

    gdf["geometry"] = gdf["geometry"].apply(lambda p: p.wkt)
    pd.DataFrame(gdf).to_excel("result.xlsx")


def get_capacity(row):
    if row["capacity"] > 0:
        return row["capacity"]

    if row["geometry"].area == 0:
        return None

    # https://www.wuestenrot-stiftung.de/wp-content/uploads/2016/05/Raumpilot-Grundlagen.pdf
    return int(math.floor(row["geometry"].area / 25))


def add_address(osm_parking: geopandas.GeoDataFrame):
    # Add addresses
    geolocator = Nominatim(user_agent="my_app")

    def reverse_geocode(row):
        try:
            print(f"{row.geometry.centroid.y}, {row.geometry.centroid.x}")
            location = geolocator.reverse(
                f"{row.geometry.centroid.y}, {row.geometry.centroid.x}"
            )

            print(location.raw["address"])

            return json.dumps(location.raw["address"])

        except Exception as e:
            print(e)
            return '{}'

    # get address data as dict
    osm_parking = osm_parking.to_crs(
        "EPSG:4326"
    )  # project back to LAT/LON coords for reverse geocoding
    osm_parking["address_reverse_geocoded"] = osm_parking.apply(
        lambda x: reverse_geocode(x), axis=1
    )

    # extract address data to separate columns
    osm_parking["plz_reverse_geocoded"] = osm_parking["address_reverse_geocoded"].apply(
        lambda x: json.loads(x).get("postcode")
    )
    osm_parking["addresse_reverse_geocoded"] = osm_parking[
        "address_reverse_geocoded"
    ].apply(
        lambda x: f'{json.loads(x).get("road")} {json.loads(x).get("house_number")}'
    )
    osm_parking["bezirk_reverse_geocoded"] = osm_parking[
        "address_reverse_geocoded"
    ].apply(lambda x: json.loads(x).get("city_district"))
    osm_parking["stadtteil_reverse_geocoded"] = osm_parking[
        "address_reverse_geocoded"
    ].apply(lambda x: json.loads(x).get("suburb"))
    osm_parking["stadt_reverse_geocoded"] = osm_parking[
        "address_reverse_geocoded"
    ].apply(lambda x: json.loads(x).get("city"))
    osm_parking["Einrichtung_reverse_geocoded"] = osm_parking[
        "address_reverse_geocoded"
    ].apply(lambda x: json.loads(x).get("amenity"))

    osm_parking = osm_parking.drop(columns=["address_reverse_geocoded"])

    return osm_parking


# load data
osm_parking, geoportal_parking = load_data()

# filter out public parking
osm_parking = filter_on_public_parking_spaces(osm_parking, geoportal_parking)

# add capacity
osm_parking["capacity"] = osm_parking["capacity"].astype(float)
osm_parking["capacity"] = osm_parking.apply(lambda row: get_capacity(row), axis=1)

# add geom_type
osm_parking["geometry_type"] = osm_parking.geometry.apply(
    lambda geom: "Polygon" if geom.area > 0 else "Punkt"
)

# add address
osm_parking = add_address(osm_parking)

osm_parking.to_file("result.gpkg", driver="GPKG")

export_to_excel(osm_parking)


print("finish")
