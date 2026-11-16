"""ICAO airline designator -> radiotelephony designator (the callsign word, ICAO Doc 8585). "DLH4AB" is said as
"Lufthansa four Alfa Bravo", "BAW12" as "Speedbird one two". Only entries we are sure of; an airline that is not
here is spelled ("Mike Lima Tango one two").

LiveTraffic (2026-11-15) brings the real ADS-B callsigns, so the list covers the airlines seen at European airports
plus the big ones elsewhere and the cargo and business operators. Written down from general knowledge of the
published designators, not copied from a database. A telephony word must not be one ATC or the pilot also says in
other senses (tests/test_airlines.py checks that against the phraseology words).
"""

TELEPHONY = {
    # --- Europe ------------------------------------------------------------------------------------------------
    "AEA": "Europa",  # Air Europa
    "AEE": "Aegean",
    "AFL": "Aeroflot",
    "AFR": "Airfrans",  # Air France
    "AHY": "Azal",  # Azerbaijan Airlines
    "AMC": "Air Malta",
    "ASL": "Air Serbia",
    "AUA": "Austrian",
    "AUI": "Ukraine International",
    "BAW": "Speedbird",  # British Airways
    "BEL": "Beeline",  # Brussels Airlines
    "BTI": "Air Baltic",
    "CFG": "Condor",
    "CLH": "Hansaline",  # Lufthansa CityLine
    "CTN": "Croatia",
    "DLA": "Dolomiti",  # Air Dolomiti
    "DLH": "Lufthansa",
    "EDW": "Edelweiss",
    "EIN": "Shamrock",  # Aer Lingus
    "EJU": "Alpine",  # easyJet Europe
    "EWG": "Eurowings",
    "EXS": "Channex",  # Jet2
    "EZS": "Topswiss",  # easyJet Switzerland
    "EZY": "Easy",  # easyJet UK
    "FIN": "Finnair",
    "GWI": "Germanwings",
    "IBE": "Iberia",
    "ICE": "Iceair",  # Icelandair
    "ITY": "Itarrow",  # ITA Airways
    "JAF": "Beauty",  # TUI fly Belgium
    "KLM": "KLM",
    "LGL": "Luxair",
    "LOT": "Pollot",  # LOT Polish Airlines
    "NAX": "Nor Shuttle",  # Norwegian
    "NSZ": "Rednose",  # Norwegian Air Sweden
    "OAL": "Olympic",
    "PGT": "Sunturk",  # Pegasus
    "ROT": "Tarom",
    "RUK": "Bluemax",  # Ryanair UK
    "RYR": "Ryanair",
    "SAS": "Scandinavian",
    "SWR": "Swiss",
    "SXS": "Sunexpress",
    "TAP": "Air Portugal",
    "THY": "Turkish",
    "TOM": "Tomson",  # TUI Airways
    "TRA": "Transavia",
    "TUI": "Tuijet",  # TUI fly Deutschland
    "TVF": "France Soleil",  # Transavia France
    "TVS": "Skytravel",  # Smartwings
    "VLG": "Vueling",
    "VOE": "Volotea",
    "WUK": "Wizz Go",  # Wizz Air UK
    "WZZ": "Wizz Air",
    # --- Middle East and Africa --------------------------------------------------------------------------------
    "ABY": "Arabia",  # Air Arabia
    "DAH": "Air Algerie",
    "ELY": "El Al",
    "ETD": "Etihad",
    "ETH": "Ethiopian",
    "FDB": "Sky Dubai",  # flydubai
    "GFA": "Gulf Air",
    "KAC": "Kuwaiti",
    "KQA": "Kenya",
    "MEA": "Cedar Jet",  # Middle East Airlines
    "MSR": "Egyptair",
    "OMA": "Oman Air",
    "QTR": "Qatari",
    "RAM": "Royalair Maroc",
    "RJA": "Jordanian",
    "SAA": "Springbok",  # South African
    "SVA": "Saudia",
    "TAR": "Tunair",  # Tunisair
    "UAE": "Emirates",
    # --- Asia and Pacific --------------------------------------------------------------------------------------
    "AAR": "Asiana",
    "AIC": "Airindia",
    "ANA": "All Nippon",
    "ANZ": "New Zealand",
    "CAL": "Dynasty",  # China Airlines
    "CCA": "Air China",
    "CES": "China Eastern",
    "CPA": "Cathay",
    "CSN": "China Southern",
    "EVA": "Eva",
    "GIA": "Indonesia",
    "HVN": "Viet Nam Airlines",
    "IGO": "Ifly",  # IndiGo
    "JAL": "Japanair",
    "KAL": "Koreanair",
    "MAS": "Malaysian",
    "PAL": "Philippine",
    "PIA": "Pakistan",
    "QFA": "Qantas",
    "SIA": "Singapore",
    "THA": "Thai",
    "VOZ": "Velocity",  # Virgin Australia
    # --- Americas ----------------------------------------------------------------------------------------------
    "AAL": "American",
    "AAY": "Allegiant",
    "ACA": "Air Canada",
    "AMX": "Aeromexico",
    "ASA": "Alaska",
    "ASH": "Air Shuttle",  # Mesa
    "AVA": "Avianca",
    "CMP": "Copa",
    "DAL": "Delta",
    "EDV": "Endeavor",
    "ENY": "Envoy",
    "FFT": "Frontier Flight",
    "JBU": "Jetblue",
    "JIA": "Blue Streak",  # PSA Airlines
    "NKS": "Spirit Wings",
    "ROU": "Rouge",  # Air Canada Rouge
    "RPA": "Brickyard",  # Republic
    "SKW": "Skywest",
    "SWA": "Southwest",
    "TSC": "Air Transat",
    "UAL": "United",
    "VIR": "Virgin",
    "WJA": "Westjet",
    # --- Cargo and business ------------------------------------------------------------------------------------
    "ABR": "Contract",  # ASL Airlines Ireland
    "BCS": "Eurotrans",  # European Air Transport (DHL)
    "BOX": "German Cargo",  # AeroLogic
    "CKS": "Connie",  # Kalitta
    "CLX": "Cargolux",
    "DHK": "World Express",  # DHL Air UK
    "EJA": "Execjet",  # NetJets
    "FDX": "FedEx",
    "GEC": "Lufthansa Cargo",
    "GTI": "Giant",  # Atlas Air
    "NJE": "Fraction",  # NetJets Europe
    "UPS": "UPS",
}
