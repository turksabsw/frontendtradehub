# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Turkey Address Data Setup Module

This module provides functions to import and setup Turkish geographic data including:
- Districts (Ilce) - 970+ districts linked to their parent cities
- Neighborhoods (Mahalle) - thousands of neighborhoods linked to their parent districts

Usage:
    # Import all Turkey data
    from tr_tradehub.setup.setup_turkey_data import setup_turkey_data
    setup_turkey_data()

    # Import only districts
    from tr_tradehub.setup.setup_turkey_data import setup_districts
    setup_districts()

    # Import only neighborhoods
    from tr_tradehub.setup.setup_turkey_data import setup_neighborhoods
    setup_neighborhoods()

This module is designed to be called:
1. During app installation via hooks.py after_install
2. Manually via bench console
3. Via custom bench commands
"""

import json
import os
from typing import Dict, List, Optional

import frappe
from frappe import _


# =============================================================================
# MAIN SETUP FUNCTION
# =============================================================================


def setup_turkey_data(verbose: bool = True) -> Dict[str, int]:
    """
    Import all Turkey geographic data.

    This is the main entry point for setting up Turkey address data.
    It imports cities, districts, and neighborhoods in the correct order
    to maintain referential integrity.

    Args:
        verbose: If True, print progress messages

    Returns:
        dict: Statistics of imported records
            {
                "cities": <count>,
                "districts": <count>,
                "neighborhoods": <count>
            }
    """
    stats = {
        "cities": 0,
        "districts": 0,
        "neighborhoods": 0
    }

    if verbose:
        frappe.publish_realtime(
            "setup_progress",
            {"message": "Starting Turkey data setup..."}
        )

    # Cities are typically imported via fixtures (03_city.json)
    # Here we verify they exist before proceeding
    city_count = frappe.db.count("City")
    if city_count == 0:
        if verbose:
            frappe.publish_realtime(
                "setup_progress",
                {"message": "Warning: No cities found. Please import cities first via fixtures."}
            )
        frappe.msgprint(
            _("No cities found. Please run 'bench --site [site] import-fixtures' first to import cities."),
            alert=True
        )
        return stats

    stats["cities"] = city_count

    # Import districts
    if verbose:
        frappe.publish_realtime(
            "setup_progress",
            {"message": "Importing districts..."}
        )

    district_count = setup_districts(verbose=verbose)
    stats["districts"] = district_count

    # Import neighborhoods
    if verbose:
        frappe.publish_realtime(
            "setup_progress",
            {"message": "Importing neighborhoods..."}
        )

    neighborhood_count = setup_neighborhoods(verbose=verbose)
    stats["neighborhoods"] = neighborhood_count

    if verbose:
        frappe.publish_realtime(
            "setup_progress",
            {"message": f"Turkey data setup complete. Cities: {city_count}, Districts: {district_count}, Neighborhoods: {neighborhood_count}"}
        )
        frappe.msgprint(
            _("Turkey data setup complete.<br>Cities: {0}<br>Districts: {1}<br>Neighborhoods: {2}").format(
                city_count, district_count, neighborhood_count
            )
        )

    return stats


# =============================================================================
# DISTRICT SETUP FUNCTIONS
# =============================================================================


def setup_districts(
    data: Optional[List[Dict]] = None,
    verbose: bool = True
) -> int:
    """
    Import district (Ilce) data into the District DocType.

    Districts are the middle level of Turkey's address hierarchy:
    City (Il) -> District (Ilce) -> Neighborhood (Mahalle)

    Args:
        data: Optional list of district dictionaries. If not provided,
              uses built-in sample data for major cities.
        verbose: If True, print progress messages

    Returns:
        int: Number of districts imported
    """
    if data is None:
        data = get_sample_districts()

    imported = 0
    skipped = 0
    errors = 0

    for district_data in data:
        try:
            result = create_or_update_district(district_data)
            if result == "created":
                imported += 1
            elif result == "exists":
                skipped += 1
        except Exception as e:
            errors += 1
            if verbose:
                frappe.log_error(
                    f"Error importing district {district_data.get('district_name')}: {str(e)}",
                    "District Import Error"
                )

    if verbose and errors > 0:
        frappe.msgprint(
            _("{0} districts imported, {1} skipped (already exist), {2} errors").format(
                imported, skipped, errors
            )
        )

    # Commit the transaction
    frappe.db.commit()

    return imported + skipped


def create_or_update_district(district_data: Dict) -> str:
    """
    Create a new district or skip if it already exists.

    Args:
        district_data: Dictionary containing district information
            Required keys:
                - district_name: Name of the district
                - city: City code (e.g., "34" for Istanbul)
            Optional keys:
                - district_code: Official district code
                - postal_code_prefix: Common postal code prefix
                - is_active: Whether district is active (default: 1)

    Returns:
        str: "created" if new district was created, "exists" if already exists
    """
    # Validate required fields
    if not district_data.get("district_name"):
        raise ValueError("district_name is required")
    if not district_data.get("city"):
        raise ValueError("city is required")

    # Check if city exists
    if not frappe.db.exists("City", district_data["city"]):
        raise ValueError(f"City '{district_data['city']}' does not exist")

    # Check if district already exists in this city
    existing = frappe.db.exists(
        "District",
        {
            "district_name": district_data["district_name"],
            "city": district_data["city"]
        }
    )

    if existing:
        return "exists"

    # Create new district
    district = frappe.new_doc("District")
    district.district_name = district_data["district_name"]
    district.city = district_data["city"]
    district.district_code = district_data.get("district_code", "")
    district.postal_code_prefix = district_data.get("postal_code_prefix", "")
    district.is_active = district_data.get("is_active", 1)

    district.insert(ignore_permissions=True)

    return "created"


def get_sample_districts() -> List[Dict]:
    """
    Get sample district data for major Turkish cities.

    This provides a starting set of districts for the most populous cities.
    For a complete dataset, import from an external source or fixture file.

    Returns:
        list: List of district dictionaries
    """
    # Sample districts for major cities
    # City codes reference the city_code field in City DocType
    return [
        # Istanbul (34) - Some major districts
        {"district_name": "Kadikoy", "city": "34", "district_code": "34-KAD"},
        {"district_name": "Besiktas", "city": "34", "district_code": "34-BES"},
        {"district_name": "Uskudar", "city": "34", "district_code": "34-USK"},
        {"district_name": "Fatih", "city": "34", "district_code": "34-FAT"},
        {"district_name": "Beyoglu", "city": "34", "district_code": "34-BEY"},
        {"district_name": "Sisli", "city": "34", "district_code": "34-SIS"},
        {"district_name": "Bakirkoy", "city": "34", "district_code": "34-BAK"},
        {"district_name": "Maltepe", "city": "34", "district_code": "34-MAL"},
        {"district_name": "Kartal", "city": "34", "district_code": "34-KAR"},
        {"district_name": "Pendik", "city": "34", "district_code": "34-PEN"},
        {"district_name": "Tuzla", "city": "34", "district_code": "34-TUZ"},
        {"district_name": "Atasehir", "city": "34", "district_code": "34-ATA"},
        {"district_name": "Umraniye", "city": "34", "district_code": "34-UMR"},
        {"district_name": "Sancaktepe", "city": "34", "district_code": "34-SAN"},
        {"district_name": "Cekmekoy", "city": "34", "district_code": "34-CEK"},
        {"district_name": "Sultanbeyli", "city": "34", "district_code": "34-SUL"},
        {"district_name": "Beykoz", "city": "34", "district_code": "34-BKZ"},
        {"district_name": "Sile", "city": "34", "district_code": "34-SIL"},
        {"district_name": "Adalar", "city": "34", "district_code": "34-ADA"},
        {"district_name": "Avcilar", "city": "34", "district_code": "34-AVC"},
        {"district_name": "Bagcilar", "city": "34", "district_code": "34-BAG"},
        {"district_name": "Bahcelievler", "city": "34", "district_code": "34-BAH"},
        {"district_name": "Basaksehir", "city": "34", "district_code": "34-BAS"},
        {"district_name": "Bayrampasa", "city": "34", "district_code": "34-BAY"},
        {"district_name": "Buyukcekmece", "city": "34", "district_code": "34-BUY"},
        {"district_name": "Catalca", "city": "34", "district_code": "34-CAT"},
        {"district_name": "Esenler", "city": "34", "district_code": "34-ESN"},
        {"district_name": "Esenyurt", "city": "34", "district_code": "34-ESY"},
        {"district_name": "Eyupsultan", "city": "34", "district_code": "34-EYP"},
        {"district_name": "Gaziosmanpasa", "city": "34", "district_code": "34-GOP"},
        {"district_name": "Gungoren", "city": "34", "district_code": "34-GUN"},
        {"district_name": "Kagithane", "city": "34", "district_code": "34-KAG"},
        {"district_name": "Kucukcekmece", "city": "34", "district_code": "34-KCK"},
        {"district_name": "Sariyer", "city": "34", "district_code": "34-SAR"},
        {"district_name": "Silivri", "city": "34", "district_code": "34-SLV"},
        {"district_name": "Sultangazi", "city": "34", "district_code": "34-SGZ"},
        {"district_name": "Zeytinburnu", "city": "34", "district_code": "34-ZYT"},
        {"district_name": "Arnavutkoy", "city": "34", "district_code": "34-ARN"},

        # Ankara (06) - Some major districts
        {"district_name": "Cankaya", "city": "06", "district_code": "06-CAN"},
        {"district_name": "Kecioren", "city": "06", "district_code": "06-KEC"},
        {"district_name": "Yenimahalle", "city": "06", "district_code": "06-YEN"},
        {"district_name": "Mamak", "city": "06", "district_code": "06-MAM"},
        {"district_name": "Etimesgut", "city": "06", "district_code": "06-ETI"},
        {"district_name": "Sincan", "city": "06", "district_code": "06-SIN"},
        {"district_name": "Altindag", "city": "06", "district_code": "06-ALT"},
        {"district_name": "Pursaklar", "city": "06", "district_code": "06-PUR"},
        {"district_name": "Golbasi", "city": "06", "district_code": "06-GOL"},
        {"district_name": "Polatli", "city": "06", "district_code": "06-POL"},

        # Izmir (35) - Some major districts
        {"district_name": "Konak", "city": "35", "district_code": "35-KON"},
        {"district_name": "Karsiyaka", "city": "35", "district_code": "35-KAR"},
        {"district_name": "Bornova", "city": "35", "district_code": "35-BOR"},
        {"district_name": "Buca", "city": "35", "district_code": "35-BUC"},
        {"district_name": "Cigli", "city": "35", "district_code": "35-CIG"},
        {"district_name": "Bayrakli", "city": "35", "district_code": "35-BAY"},
        {"district_name": "Karabaglar", "city": "35", "district_code": "35-KAB"},
        {"district_name": "Gaziemir", "city": "35", "district_code": "35-GAZ"},
        {"district_name": "Narlidere", "city": "35", "district_code": "35-NAR"},
        {"district_name": "Balcova", "city": "35", "district_code": "35-BAL"},

        # Bursa (16) - Some major districts
        {"district_name": "Osmangazi", "city": "16", "district_code": "16-OSM"},
        {"district_name": "Yildirim", "city": "16", "district_code": "16-YIL"},
        {"district_name": "Nilufer", "city": "16", "district_code": "16-NIL"},
        {"district_name": "Gemlik", "city": "16", "district_code": "16-GEM"},
        {"district_name": "Mudanya", "city": "16", "district_code": "16-MUD"},
        {"district_name": "Inegol", "city": "16", "district_code": "16-INE"},

        # Antalya (07) - Some major districts
        {"district_name": "Muratpasa", "city": "07", "district_code": "07-MUR"},
        {"district_name": "Kepez", "city": "07", "district_code": "07-KEP"},
        {"district_name": "Konyaalti", "city": "07", "district_code": "07-KON"},
        {"district_name": "Aksu", "city": "07", "district_code": "07-AKS"},
        {"district_name": "Dosemealti", "city": "07", "district_code": "07-DOS"},
        {"district_name": "Alanya", "city": "07", "district_code": "07-ALA"},
        {"district_name": "Manavgat", "city": "07", "district_code": "07-MAN"},

        # Adana (01) - Some major districts
        {"district_name": "Seyhan", "city": "01", "district_code": "01-SEY"},
        {"district_name": "Cukurova", "city": "01", "district_code": "01-CUK"},
        {"district_name": "Yuregir", "city": "01", "district_code": "01-YUR"},
        {"district_name": "Saricam", "city": "01", "district_code": "01-SAR"},

        # Konya (42) - Some major districts
        {"district_name": "Selcuklu", "city": "42", "district_code": "42-SEL"},
        {"district_name": "Meram", "city": "42", "district_code": "42-MER"},
        {"district_name": "Karatay", "city": "42", "district_code": "42-KAR"},

        # Gaziantep (27) - Some major districts
        {"district_name": "Sahinbey", "city": "27", "district_code": "27-SAH"},
        {"district_name": "Sehitkamil", "city": "27", "district_code": "27-SEH"},

        # Kocaeli (41) - Some major districts
        {"district_name": "Izmit", "city": "41", "district_code": "41-IZM"},
        {"district_name": "Gebze", "city": "41", "district_code": "41-GEB"},
        {"district_name": "Darica", "city": "41", "district_code": "41-DAR"},
        {"district_name": "Korfez", "city": "41", "district_code": "41-KOR"},

        # Mersin (33) - Some major districts
        {"district_name": "Yenisehir", "city": "33", "district_code": "33-YEN"},
        {"district_name": "Toroslar", "city": "33", "district_code": "33-TOR"},
        {"district_name": "Akdeniz", "city": "33", "district_code": "33-AKD"},
        {"district_name": "Mezitli", "city": "33", "district_code": "33-MEZ"},

        # Kayseri (38) - Some major districts
        {"district_name": "Melikgazi", "city": "38", "district_code": "38-MEL"},
        {"district_name": "Kocasinan", "city": "38", "district_code": "38-KOC"},
        {"district_name": "Talas", "city": "38", "district_code": "38-TAL"},

        # Eskisehir (26) - Some major districts
        {"district_name": "Odunpazari", "city": "26", "district_code": "26-ODU"},
        {"district_name": "Tepebasi", "city": "26", "district_code": "26-TEP"},

        # Diyarbakir (21) - Some major districts
        {"district_name": "Baglar", "city": "21", "district_code": "21-BAG"},
        {"district_name": "Kayapinar", "city": "21", "district_code": "21-KAY"},
        {"district_name": "Sur", "city": "21", "district_code": "21-SUR"},
        {"district_name": "Yenisehir", "city": "21", "district_code": "21-YEN"},

        # Samsun (55) - Some major districts
        {"district_name": "Ilkadim", "city": "55", "district_code": "55-ILK"},
        {"district_name": "Atakum", "city": "55", "district_code": "55-ATA"},
        {"district_name": "Canik", "city": "55", "district_code": "55-CAN"},
        {"district_name": "Tekkeköy", "city": "55", "district_code": "55-TEK"},
    ]


# =============================================================================
# NEIGHBORHOOD SETUP FUNCTIONS
# =============================================================================


def setup_neighborhoods(
    data: Optional[List[Dict]] = None,
    verbose: bool = True
) -> int:
    """
    Import neighborhood (Mahalle) data into the Neighborhood DocType.

    Neighborhoods are the lowest level of Turkey's address hierarchy:
    City (Il) -> District (Ilce) -> Neighborhood (Mahalle)

    Args:
        data: Optional list of neighborhood dictionaries. If not provided,
              uses built-in sample data for major districts.
        verbose: If True, print progress messages

    Returns:
        int: Number of neighborhoods imported
    """
    if data is None:
        data = get_sample_neighborhoods()

    imported = 0
    skipped = 0
    errors = 0

    for neighborhood_data in data:
        try:
            result = create_or_update_neighborhood(neighborhood_data)
            if result == "created":
                imported += 1
            elif result == "exists":
                skipped += 1
        except Exception as e:
            errors += 1
            if verbose:
                frappe.log_error(
                    f"Error importing neighborhood {neighborhood_data.get('neighborhood_name')}: {str(e)}",
                    "Neighborhood Import Error"
                )

    if verbose and errors > 0:
        frappe.msgprint(
            _("{0} neighborhoods imported, {1} skipped (already exist), {2} errors").format(
                imported, skipped, errors
            )
        )

    # Commit the transaction
    frappe.db.commit()

    return imported + skipped


def create_or_update_neighborhood(neighborhood_data: Dict) -> str:
    """
    Create a new neighborhood or skip if it already exists.

    Args:
        neighborhood_data: Dictionary containing neighborhood information
            Required keys:
                - neighborhood_name: Name of the neighborhood
                - district: District name/ID
            Optional keys:
                - neighborhood_code: Official neighborhood code
                - postal_code: Postal/ZIP code
                - is_active: Whether neighborhood is active (default: 1)

    Returns:
        str: "created" if new neighborhood was created, "exists" if already exists
    """
    # Validate required fields
    if not neighborhood_data.get("neighborhood_name"):
        raise ValueError("neighborhood_name is required")
    if not neighborhood_data.get("district"):
        raise ValueError("district is required")

    # Check if district exists
    if not frappe.db.exists("District", neighborhood_data["district"]):
        raise ValueError(f"District '{neighborhood_data['district']}' does not exist")

    # Check if neighborhood already exists in this district
    existing = frappe.db.exists(
        "Neighborhood",
        {
            "neighborhood_name": neighborhood_data["neighborhood_name"],
            "district": neighborhood_data["district"]
        }
    )

    if existing:
        return "exists"

    # Create new neighborhood
    neighborhood = frappe.new_doc("Neighborhood")
    neighborhood.neighborhood_name = neighborhood_data["neighborhood_name"]
    neighborhood.district = neighborhood_data["district"]
    neighborhood.neighborhood_code = neighborhood_data.get("neighborhood_code", "")
    neighborhood.postal_code = neighborhood_data.get("postal_code", "")
    neighborhood.is_active = neighborhood_data.get("is_active", 1)

    neighborhood.insert(ignore_permissions=True)

    return "created"


def get_sample_neighborhoods() -> List[Dict]:
    """
    Get sample neighborhood data for major districts.

    This provides a starting set of neighborhoods for commonly used districts.
    For a complete dataset, import from an external source or fixture file.

    Note: District references use the naming_series format (DIST-.#####).
    These will need to be updated based on actual district names created.

    Returns:
        list: List of neighborhood dictionaries
    """
    # Note: Neighborhood data requires district references
    # Districts need to be created first, and their names captured
    # This sample data uses placeholder district names that should be
    # replaced with actual district document names after district import

    # Since districts use naming_series (DIST-.#####), we need to look up
    # the actual district names by district_name + city combination

    neighborhoods = []

    # Get actual district names for sample neighborhoods
    sample_district_neighborhoods = {
        # Istanbul - Kadikoy neighborhoods
        ("Kadikoy", "34"): [
            "Caferaga", "Osmanaga", "Rasimpasa", "Moda", "Feneryolu",
            "Kozyatagi", "Bostanci", "Suadiye", "Goztepe", "Egitim",
            "Fikirtepe", "Hasanpasa", "Dumlupinar", "Merdivenköy"
        ],
        # Istanbul - Besiktas neighborhoods
        ("Besiktas", "34"): [
            "Levent", "Etiler", "Bebek", "Ortakoy", "Arnavutkoy",
            "Konaklar", "Ulus", "Akatlar", "Nisbetiye"
        ],
        # Istanbul - Sisli neighborhoods
        ("Sisli", "34"): [
            "Mecidiyekoy", "Nisantasi", "Osmanbey", "Bomonti",
            "Fulya", "Halaskargazi", "Kurtuluş", "Feriköy"
        ],
        # Ankara - Cankaya neighborhoods
        ("Cankaya", "06"): [
            "Kizilay", "Kavaklidere", "Gaziosmanpasa", "Cukurambar",
            "Bahcelievler", "Emek", "Balgat", "Orun", "Dikmen"
        ],
        # Izmir - Konak neighborhoods
        ("Konak", "35"): [
            "Alsancak", "Kemeralti", "Basmane", "Tepecik",
            "Guzelyali", "Hatay", "Kültür"
        ],
    }

    for (district_name, city), neighborhood_names in sample_district_neighborhoods.items():
        # Find the district document name
        district = frappe.db.get_value(
            "District",
            {"district_name": district_name, "city": city},
            "name"
        )

        if district:
            for name in neighborhood_names:
                neighborhoods.append({
                    "neighborhood_name": name,
                    "district": district
                })

    return neighborhoods


# =============================================================================
# BULK IMPORT FUNCTIONS
# =============================================================================


def import_districts_from_json(filepath: str, verbose: bool = True) -> int:
    """
    Import districts from a JSON file.

    The JSON file should contain an array of district objects with the same
    structure as the create_or_update_district function expects.

    Args:
        filepath: Path to the JSON file
        verbose: If True, print progress messages

    Returns:
        int: Number of districts imported
    """
    if not os.path.exists(filepath):
        frappe.throw(_("File not found: {0}").format(filepath))

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    return setup_districts(data=data, verbose=verbose)


def import_neighborhoods_from_json(filepath: str, verbose: bool = True) -> int:
    """
    Import neighborhoods from a JSON file.

    The JSON file should contain an array of neighborhood objects with the same
    structure as the create_or_update_neighborhood function expects.

    Args:
        filepath: Path to the JSON file
        verbose: If True, print progress messages

    Returns:
        int: Number of neighborhoods imported
    """
    if not os.path.exists(filepath):
        frappe.throw(_("File not found: {0}").format(filepath))

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    return setup_neighborhoods(data=data, verbose=verbose)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def get_district_count_by_city() -> Dict[str, int]:
    """
    Get the count of districts for each city.

    Returns:
        dict: Dictionary mapping city codes to district counts
    """
    result = frappe.db.sql("""
        SELECT city, COUNT(*) as count
        FROM `tabDistrict`
        GROUP BY city
        ORDER BY city
    """, as_dict=True)

    return {row["city"]: row["count"] for row in result}


def get_neighborhood_count_by_district() -> Dict[str, int]:
    """
    Get the count of neighborhoods for each district.

    Returns:
        dict: Dictionary mapping district names to neighborhood counts
    """
    result = frappe.db.sql("""
        SELECT district, COUNT(*) as count
        FROM `tabNeighborhood`
        GROUP BY district
        ORDER BY district
    """, as_dict=True)

    return {row["district"]: row["count"] for row in result}


def validate_address_hierarchy() -> Dict[str, List[str]]:
    """
    Validate the address hierarchy data integrity.

    Checks for:
    - Districts with invalid city references
    - Neighborhoods with invalid district references

    Returns:
        dict: Dictionary containing lists of validation errors
            {
                "invalid_district_cities": [...],
                "invalid_neighborhood_districts": [...]
            }
    """
    errors = {
        "invalid_district_cities": [],
        "invalid_neighborhood_districts": []
    }

    # Check districts with invalid city references
    invalid_districts = frappe.db.sql("""
        SELECT d.name, d.district_name, d.city
        FROM `tabDistrict` d
        LEFT JOIN `tabCity` c ON d.city = c.name
        WHERE c.name IS NULL
    """, as_dict=True)

    for d in invalid_districts:
        errors["invalid_district_cities"].append(
            f"District '{d['district_name']}' ({d['name']}) has invalid city '{d['city']}'"
        )

    # Check neighborhoods with invalid district references
    invalid_neighborhoods = frappe.db.sql("""
        SELECT n.name, n.neighborhood_name, n.district
        FROM `tabNeighborhood` n
        LEFT JOIN `tabDistrict` d ON n.district = d.name
        WHERE d.name IS NULL
    """, as_dict=True)

    for n in invalid_neighborhoods:
        errors["invalid_neighborhood_districts"].append(
            f"Neighborhood '{n['neighborhood_name']}' ({n['name']}) has invalid district '{n['district']}'"
        )

    return errors


def clear_turkey_data(confirm: bool = False) -> Dict[str, int]:
    """
    Clear all Turkey geographic data (for testing/reset purposes).

    WARNING: This will delete all neighborhoods, districts, and cities!

    Args:
        confirm: Must be True to actually delete data

    Returns:
        dict: Counts of deleted records
    """
    if not confirm:
        frappe.throw(
            _("Set confirm=True to actually delete data. This action cannot be undone!")
        )

    deleted = {
        "neighborhoods": 0,
        "districts": 0,
        "cities": 0
    }

    # Delete in reverse order to maintain referential integrity

    # Delete neighborhoods first
    neighborhoods = frappe.get_all("Neighborhood", pluck="name")
    for name in neighborhoods:
        frappe.delete_doc("Neighborhood", name, ignore_permissions=True, force=True)
        deleted["neighborhoods"] += 1

    # Delete districts
    districts = frappe.get_all("District", pluck="name")
    for name in districts:
        frappe.delete_doc("District", name, ignore_permissions=True, force=True)
        deleted["districts"] += 1

    # Delete cities
    cities = frappe.get_all("City", pluck="name")
    for name in cities:
        frappe.delete_doc("City", name, ignore_permissions=True, force=True)
        deleted["cities"] += 1

    frappe.db.commit()

    return deleted


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def run_setup_turkey_data() -> Dict[str, int]:
    """
    Whitelisted API to run Turkey data setup.

    Can be called from client-side or via API.
    Requires System Manager role.

    Returns:
        dict: Statistics of imported records
    """
    if not frappe.has_permission("District", "create"):
        frappe.throw(_("You do not have permission to import Turkey data"))

    return setup_turkey_data(verbose=True)


@frappe.whitelist()
def get_setup_statistics() -> Dict[str, int]:
    """
    Get current statistics of Turkey geographic data.

    Returns:
        dict: Counts of cities, districts, and neighborhoods
    """
    return {
        "cities": frappe.db.count("City"),
        "districts": frappe.db.count("District"),
        "neighborhoods": frappe.db.count("Neighborhood")
    }
