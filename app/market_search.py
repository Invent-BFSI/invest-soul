import os
from typing import List, Dict
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")   # e.g., https://<service>.search.windows.net
SEARCH_API_KEY  = os.getenv("AZURE_SEARCH_API_KEY")
SEARCH_INDEX    = os.getenv("AZURE_SEARCH_INDEX", "market-index")

CURATED_2026 = {
    "tech":        ["TCS", "Infosys", "HCL Tech", "LTIMindtree"],
    "finance":     ["HDFC Bank", "ICICI Bank", "Axis Bank", "SBI"],
    "energy":      ["Reliance Industries", "NTPC", "Tata Power", "Adani Green"],
    "healthcare":  ["Apollo Hospitals", "Sun Pharma", "Dr. Reddy's", "Zydus Life"],
    "consumer goods": ["Hindustan Unilever", "ITC", "Nestle India", "Britannia"]
}

def search_top5(sector: str) -> List[Dict]:
    """Query Azure AI Search for recent leaders by sector, order by a score like performanceScore desc."""
    if not (SEARCH_ENDPOINT and SEARCH_API_KEY and SEARCH_INDEX):
        return []
    client = SearchClient(SEARCH_ENDPOINT, SEARCH_INDEX, AzureKeyCredential(SEARCH_API_KEY))  # Client to an existing index [6](https://learn.microsoft.com/en-us/python/api/azure-search-documents/azure.search.documents.searchclient?view=azure-python)
    # Order by a numeric field (e.g., performanceScore) using OData $orderby; top=5. [7](https://learn.microsoft.com/en-us/azure/search/search-query-odata-orderby)
    results = client.search(
        search_text=sector,
        top=5,
        order_by=["performanceScore desc"],
        select=["symbol", "name", "performanceScore", "sector"]
    )  # SearchClient usage & options per SDK docs/samples. [8](https://learn.microsoft.com/en-us/python/api/overview/azure/search-documents-readme?view=azure-python)[9](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/search/azure-search-documents/samples/README.md)
    out = []
    for r in results:
        sym = getattr(r, "symbol", None) or getattr(r, "name", None)
        out.append({"symbol": sym, "score": getattr(r, "performanceScore", None)})
    return out

def curated_four(sector: str) -> List[str]:
    key = sector.lower().strip()
    return CURATED_2026.get(key, CURATED_2026.get({
        "technology": "tech", "it": "tech", "health": "healthcare", "fmcg": "consumer goods"
    }.get(key, key), []))
