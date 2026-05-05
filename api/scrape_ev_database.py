import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_URL = (
    "https://ev-database.org/#group=vehicle-group&rs-pr=10000_100000&"
    "rs-er=0_1000&rs-ld=0_1000&rs-ac=2_23&rs-dcfc=0_400&rs-ub=10_200&"
    "rs-tw=0_3000&rs-ef=100_350&rs-sa=-1_5&rs-w=1000_3500&rs-c=0_5000&"
    "rs-y=2010_2030&s=1&p=0-10"
)


@dataclass
class VehicleRow:
    name: str
    href: str
    range_km: Optional[float]
    one_stop_range_km: Optional[float]
    efficiency_wh_per_km: Optional[float]
    battery_kwh: Optional[float]
    fastcharge_kw: Optional[float]
    acceleration_0_100_sec: Optional[float]
    towing_kg: Optional[float]
    cargo_l: Optional[float]
    weight_kg: Optional[float]
    raw_text: str
    page_url: str


def parse_float(text: str, pattern: str) -> Optional[float]:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).replace(",", "").strip()
    try:
        return float(value)
    except ValueError:
        return None


def parse_vehicle_metrics(text: str) -> Dict[str, Optional[float]]:
    return {
        "range_km": parse_float(text, r"\bRange\*?\s+([\d.,]+)\s*km\b"),
        "one_stop_range_km": parse_float(text, r"\b1-Stop Range\s+([\d.,]+)\s*km\b"),
        "efficiency_wh_per_km": parse_float(text, r"\bEfficiency\*?\s+([\d.,]+)\s*Wh/km\b"),
        "battery_kwh": parse_float(text, r"\bBattery\*?\s+([\d.,]+)\s*kWh\b"),
        "fastcharge_kw": parse_float(text, r"\bFastcharge\s+([\d.,]+)\s*kW\b"),
        "acceleration_0_100_sec": parse_float(text, r"\b0-100\s+([\d.,]+)\s*sec\b"),
        "towing_kg": parse_float(text, r"\bTowing\s+([\d.,]+)\s*kg\b"),
        "cargo_l": parse_float(text, r"\bCargo\s*Vol\.?\s+([\d.,]+)\s*L\b"),
        "weight_kg": parse_float(text, r"\bWeight\s+([\d.,]+)\s*kg\b"),
    }


def replace_hash_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    hash_part = parsed.fragment
    pairs = dict(parse_qsl(hash_part, keep_blank_values=True))
    pairs[key] = value
    new_fragment = urlencode(pairs)
    return urlunparse(parsed._replace(fragment=new_fragment))


def get_hash_params(url: str) -> Dict[str, str]:
    parsed = urlparse(url)
    return dict(parse_qsl(parsed.fragment, keep_blank_values=True))


def parse_p_param(url: str) -> Optional[tuple[int, int]]:
    params = get_hash_params(url)
    raw = params.get("p", "")
    match = re.fullmatch(r"(\d+)-(\d+)", raw)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_hash_fragment(url: str) -> str:
    return urlparse(url).fragment


def get_card_hrefs(page) -> List[str]:
    return page.evaluate(
        """
        () => {
          const links = Array.from(document.querySelectorAll('a[href*="/car/"]'));
          const hrefs = [];
          const seen = new Set();
          for (const link of links) {
            const href = link.getAttribute('href') || '';
            if (!/\\/car\\/\\d+/.test(href)) continue;
            const absHref = new URL(href, window.location.origin).toString();
            if (seen.has(absHref)) continue;
            seen.add(absHref);
            hrefs.push(absHref);
          }
          return hrefs;
        }
        """
    )


def wait_for_page_cards(page, expected_first_href: Optional[str], timeout_sec: float = 25.0) -> List[str]:
    deadline = time.time() + timeout_sec
    latest_hrefs: List[str] = []
    while time.time() < deadline:
        body_text = page.inner_text("body")
        is_loading = "loading vehicles" in body_text.lower()
        hrefs = get_card_hrefs(page)
        latest_hrefs = hrefs

        if not is_loading and hrefs:
            if expected_first_href is None or hrefs[0] != expected_first_href:
                return hrefs
        time.sleep(0.4)
    return latest_hrefs


def navigate_to_hash_page(
    page,
    target_url: str,
    expected_first_href: Optional[str],
) -> List[str]:
    target_fragment = parse_hash_fragment(target_url)
    page.goto(target_url, wait_until="domcontentloaded", timeout=120_000)

    # Ensure hash-based filtering/pagination is applied by explicitly setting hash in-page.
    page.evaluate(
        "(fragment) => { if (window.location.hash !== '#' + fragment) window.location.hash = fragment; }",
        target_fragment,
    )

    hrefs = wait_for_page_cards(page, expected_first_href=expected_first_href)
    if not hrefs:
        return hrefs

    # Retry once with a full reload if the list did not change as expected.
    if expected_first_href is not None and hrefs[0] != expected_first_href:
        return hrefs

    page.reload(wait_until="domcontentloaded", timeout=120_000)
    page.evaluate(
        "(fragment) => { if (window.location.hash !== '#' + fragment) window.location.hash = fragment; }",
        target_fragment,
    )
    return wait_for_page_cards(page, expected_first_href=expected_first_href)


def looks_blocked(page_text: str) -> bool:
    lowered = page_text.lower()
    markers = [
        "captcha",
        "verify you are human",
        "attention required",
        "checking your browser",
        "cloudflare",
    ]
    return any(marker in lowered for marker in markers)


def prompt_if_captcha():
    input(
        "\nCAPTCHA or anti-bot page may be shown.\n"
        "Please solve it in the browser, then press Enter here to continue..."
    )


def scrape_page(page, page_url: str) -> List[VehicleRow]:
    page.wait_for_timeout(2000)
    page_text = page.inner_text("body")
    if looks_blocked(page_text):
        prompt_if_captcha()
        page.wait_for_timeout(2000)

    car_cards = page.evaluate(
        """
        () => {
          const links = Array.from(document.querySelectorAll('a[href*="/car/"]'));
          const rows = [];
          const seen = new Set();

          for (const link of links) {
            const href = link.getAttribute('href') || '';
            if (!/\\/car\\/\\d+/.test(href)) continue;

            const absHref = new URL(href, window.location.origin).toString();
            if (seen.has(absHref)) continue;
            seen.add(absHref);

            const card = link.closest('article, li, .card, .list-item, [class*="vehicle"], [class*="model"]') || link.parentElement;
            const cardText = (card?.innerText || '').replace(/\\s+/g, ' ').trim();
            const name = (link.textContent || '').replace(/\\s+/g, ' ').trim() || cardText.split(' ').slice(0, 6).join(' ');

            rows.push({
              name,
              href: absHref,
              raw_text: cardText
            });
          }

          return rows;
        }
        """
    )

    vehicles: List[VehicleRow] = []
    for card in car_cards:
        raw_text = card.get("raw_text", "")
        metrics = parse_vehicle_metrics(raw_text)
        vehicles.append(
            VehicleRow(
                name=card.get("name", "").strip(),
                href=card.get("href", "").strip(),
                raw_text=raw_text,
                page_url=page_url,
                **metrics,
            )
        )
    return vehicles


def write_json(rows: List[VehicleRow], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(row) for row in rows]
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(rows: List[VehicleRow], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return

    fieldnames = list(asdict(rows[0]).keys())
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def load_existing_rows(path: Path) -> List[VehicleRow]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows: List[VehicleRow] = []
    if not isinstance(payload, list):
        return rows
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append(
            VehicleRow(
                name=str(item.get("name", "")),
                href=str(item.get("href", "")),
                range_km=item.get("range_km"),
                one_stop_range_km=item.get("one_stop_range_km"),
                efficiency_wh_per_km=item.get("efficiency_wh_per_km"),
                battery_kwh=item.get("battery_kwh"),
                fastcharge_kw=item.get("fastcharge_kw"),
                acceleration_0_100_sec=item.get("acceleration_0_100_sec"),
                towing_kg=item.get("towing_kg"),
                cargo_l=item.get("cargo_l"),
                weight_kg=item.get("weight_kg"),
                raw_text=str(item.get("raw_text", "")),
                page_url=str(item.get("page_url", "")),
            )
        )
    return rows


def run_scraper(
    start_url: str,
    output_json: Path,
    output_csv: Optional[Path],
    start_page_index: int,
    results_per_page: int,
    max_pages: int,
    delay_sec: float,
    resume_existing: bool,
):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Missing dependency: playwright")
        print("Install with: pip install playwright")
        print("Then run once: python -m playwright install chromium")
        sys.exit(1)

    all_rows: List[VehicleRow] = []
    seen_hrefs: Set[str] = set()

    if resume_existing:
        existing_rows = load_existing_rows(output_json)
        if existing_rows:
            all_rows.extend(existing_rows)
            seen_hrefs.update(row.href for row in existing_rows if row.href)
            print(f"Loaded {len(existing_rows)} existing rows from {output_json}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        consecutive_empty_pages = 0
        previous_first_href: Optional[str] = None
        for idx in range(max_pages):
            page_index = start_page_index + idx
            page_url = replace_hash_param(start_url, "p", f"{page_index}-{results_per_page}")
            print(f"[{idx + 1}/{max_pages}] Visiting: {page_url}")

            page_hrefs = navigate_to_hash_page(
                page=page,
                target_url=page_url,
                expected_first_href=previous_first_href,
            )
            if not page_hrefs:
                print("  No vehicle cards detected after waiting; stopping.")
                break

            rows = scrape_page(page, page_url)
            if rows:
                previous_first_href = rows[0].href

            newly_added = 0
            for row in rows:
                if not row.href or row.href in seen_hrefs:
                    continue
                seen_hrefs.add(row.href)
                all_rows.append(row)
                newly_added += 1

            print(f"  Found {len(rows)} cards, added {newly_added} new vehicles.")
            if newly_added == 0:
                consecutive_empty_pages += 1
            else:
                consecutive_empty_pages = 0

            if consecutive_empty_pages >= 2:
                print("No new vehicles across two pages; stopping early.")
                break

            time.sleep(delay_sec)

        browser.close()

    write_json(all_rows, output_json)
    print(f"Wrote {len(all_rows)} vehicles to {output_json}")
    if output_csv is not None:
        write_csv(all_rows, output_csv)
        print(f"Wrote CSV to {output_csv}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape EV data from ev-database.org listing pages with manual CAPTCHA support."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="EV Database listing URL with filters/hash params.")
    parser.add_argument(
        "--output-json",
        default=str(REPO_ROOT / "data" / "ev_database_vehicles.json"),
        help="Path to output JSON file.",
    )
    parser.add_argument(
        "--output-csv",
        default=str(REPO_ROOT / "data" / "ev_database_vehicles.csv"),
        help="Path to output CSV file. Use empty string to disable.",
    )
    parser.add_argument(
        "--start-page-index",
        type=int,
        default=None,
        help="Starting page index (first part of p=pageIndex-pageSize). Defaults to URL value.",
    )
    parser.add_argument(
        "--results-per-page",
        type=int,
        default=None,
        help="Number of results per page (second part of p=pageIndex-pageSize). Defaults to URL value.",
    )
    parser.add_argument("--max-pages", type=int, default=50, help="Maximum pages to visit.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between page navigations in seconds.")
    parser.add_argument(
        "--no-resume-existing",
        action="store_true",
        help="Do not load existing JSON output before scraping.",
    )
    args = parser.parse_args()

    output_json = Path(args.output_json).expanduser().resolve()
    output_csv = Path(args.output_csv).expanduser().resolve() if args.output_csv else None
    parsed_p = parse_p_param(args.url)
    parsed_start_index = parsed_p[0] if parsed_p else 0
    parsed_results_per_page = parsed_p[1] if parsed_p else 50

    start_page_index = args.start_page_index if args.start_page_index is not None else parsed_start_index
    results_per_page = args.results_per_page if args.results_per_page is not None else parsed_results_per_page

    if results_per_page <= 0:
        print("--results-per-page must be a positive integer.")
        sys.exit(1)

    run_scraper(
        start_url=args.url,
        output_json=output_json,
        output_csv=output_csv,
        start_page_index=start_page_index,
        results_per_page=results_per_page,
        max_pages=args.max_pages,
        delay_sec=args.delay,
        resume_existing=not args.no_resume_existing,
    )


if __name__ == "__main__":
    main()
