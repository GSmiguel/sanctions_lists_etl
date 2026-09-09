"""ETL pipeline for public sanctions lists.

Stage 1 ingests the OFAC SDN "advanced" XML export and flattens the sanctioned
parties (individuals, entities, vessels, aircraft) into a single tabular sheet.
"""

__version__ = "0.1.0"
