"""Write examples/kickoff_parameters.xlsx, the parameters file used in the demo."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kdemo.xlsx import HEAD, TEXT, OutCell, OutSheet, write_workbook  # noqa: E402

HEADER = ["Name", "URL", "Access", "Years", "Documents", "Force learning"]
SITES = [
    ["Société Générale", "https://investors.societegenerale.com/fr/base-documentaire?theme=finance&category[resultats-financiers]&fiscal[2025]",
     "Public", "2024-2025", "annual reports, half-year reports, quarterly results", "No"],
    ["Crédit Agricole", "https://www.credit-agricole.com/finance/publications-financieres",
     "Public", "2024-2025", "annual reports, universal registration documents, quarterly results", "Yes"],
    ["Deutsche Bank", "https://investor-relations.db.com/reports-and-events/quarterly-results",
     "Public", "2024-2025", "quarterly results, annual report", "No"],
    ["AllianceBernstein", "https://www.alliancebernstein.com/",
     "Private", "2025", "fund statements and reports", "No"],
    ["UBS", "https://www.ubs.com/global/en/investor-relations/financial-information/quarterly-reporting/qr-archive/qr-archive21-25.html",
     "Public", "2024-2025", "quarterly reports, annual report", "No"],
    ["Airbus", "https://www.airbus.com/en/investors/annual-reports",
     "Public", "2024-2025", "annual reports, half-year reports, financial statements", "No"],
    ["HSBC", "https://www.hsbc.com/investors/results-and-announcements",
     "Public", "2024-2025", "annual report, interim report, results", "No"],
    ["TotalEnergies", "https://totalenergies.com/investors/publications-and-regulated-information/regulated-information/annual-financial-reports",
     "Public", "2024-2025", "universal registration document, half-year report", "No"],
]


def main() -> None:
    rows = [[OutCell(h, HEAD) for h in HEADER]] + [[OutCell(v, TEXT) for v in r] for r in SITES]
    sheet = OutSheet("Sites", rows, widths=[22, 70, 10, 12, 60, 15])
    out = ROOT / "examples" / "kickoff_parameters.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(write_workbook([sheet]))
    print(out)


if __name__ == "__main__":
    main()
