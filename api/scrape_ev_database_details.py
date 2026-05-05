import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_URL = (
    "https://ev-database.org/#group=vehicle-group&rs-pr=10000_100000&"
    "rs-er=0_1000&rs-ld=0_1000&rs-ac=2_23&rs-dcfc=0_400&rs-ub=10_200&"
    "rs-tw=0_3000&rs-ef=100_350&rs-sa=-1_5&rs-w=1000_3500&rs-c=0_5000&"
    "rs-y=2010_2030&s=1&p=0-50"
)


@dataclass
class VehicleLink:
    name: str
    href: str
    listing_page_url: str


@dataclass
class VehicleDetail:
    name: str
    href: str
    page_title: str
    heading: str
    availability: Optional[str]
    useable_battery_kwh: Optional[float]
    real_range_km: Optional[float]
    efficiency_wh_per_km: Optional[float]
    long_distance_suitability: Optional[float]
    prices_eur: str
    prices_gbp: str
    key_values_json: str
    raw_text_excerpt: str


def replace_hash_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    pairs = dict(parse_qsl(parsed.fragment, keep_blank_values=True))
    pairs[key] = value
    return urlunparse(parsed._replace(fragment=urlencode(pairs)))


def parse_hash_fragment(url: str) -> str:
    return urlparse(url).fragment


def get_hash_params(url: str) -> Dict[str, str]:
    parsed = urlparse(url)
    return dict(parse_qsl(parsed.fragment, keep_blank_values=True))


def parse_p_param(url: str) -> Optional[Tuple[int, int]]:
    raw = get_hash_params(url).get("p", "")
    match = re.fullmatch(r"(\d+)-(\d+)", raw)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_float(text: str, pattern: str) -> Optional[float]:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


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
        "\nCAPTCHA/anti-bot page detected.\n"
        "Please solve it in the browser, then press Enter here to continue..."
    )


def get_listing_cards(page) -> List[Dict[str, str]]:
    return page.evaluate(
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
            const label = (link.textContent || '').replace(/\\s+/g, ' ').trim();
            rows.push({ name: label, href: absHref });
          }
          return rows;
        }
        """
    )


def wait_for_listing_cards(page, expected_first_href: Optional[str], timeout_sec: float = 30.0) -> List[Dict[str, str]]:
    deadline = time.time() + timeout_sec
    latest: List[Dict[str, str]] = []
    while time.time() < deadline:
        body_text = page.inner_text("body")
        is_loading = "loading vehicles" in body_text.lower()
        cards = get_listing_cards(page)
        latest = cards
        if not is_loading and cards:
            if expected_first_href is None or cards[0]["href"] != expected_first_href:
                return cards
        time.sleep(0.4)
    return latest


def navigate_listing_page(page, target_url: str, expected_first_href: Optional[str]) -> List[Dict[str, str]]:
    target_fragment = parse_hash_fragment(target_url)
    page.goto(target_url, wait_until="domcontentloaded", timeout=120_000)
    page.evaluate(
        "(fragment) => { if (window.location.hash !== '#' + fragment) window.location.hash = fragment; }",
        target_fragment,
    )

    cards = wait_for_listing_cards(page, expected_first_href=expected_first_href)
    if not cards:
        return cards
    if expected_first_href is not None and cards[0]["href"] == expected_first_href:
        page.reload(wait_until="domcontentloaded", timeout=120_000)
        page.evaluate(
            "(fragment) => { if (window.location.hash !== '#' + fragment) window.location.hash = fragment; }",
            target_fragment,
        )
        cards = wait_for_listing_cards(page, expected_first_href=expected_first_href)
    return cards


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_detail_payload(page) -> Dict[str, object]:
    return page.evaluate(
        """
        () => {
          const clean = (v) => (v || '').replace(/\\s+/g, ' ').trim();
          const keyValues = [];
          const seen = new Set();
          const push = (label, value, section='') => {
            const l = clean(label);
            const v = clean(value);
            if (!l || !v) return;
            const s = clean(section);
            const key = `${s}|||${l}|||${v}`;
            if (seen.has(key)) return;
            seen.add(key);
            keyValues.push({ section: s, label: l, value: v });
          };

          for (const dl of Array.from(document.querySelectorAll('dl'))) {
            const dts = Array.from(dl.querySelectorAll('dt'));
            const dds = Array.from(dl.querySelectorAll('dd'));
            const len = Math.min(dts.length, dds.length);
            const section = dl.closest('section, article, div')?.querySelector('h2, h3')?.textContent || '';
            for (let i = 0; i < len; i++) {
              push(dts[i].textContent, dds[i].textContent, section);
            }
          }

          for (const tr of Array.from(document.querySelectorAll('table tr'))) {
            const cells = Array.from(tr.querySelectorAll('th, td'));
            if (cells.length < 2) continue;
            const section = tr.closest('section, article, div')?.querySelector('h2, h3')?.textContent || '';
            push(cells[0].textContent, cells[1].textContent, section);
          }

          for (const block of Array.from(document.querySelectorAll('[class*="data"], [class*="spec"], [class*="info"]'))) {
            const labels = Array.from(block.querySelectorAll('[class*="label"], [class*="name"]'));
            const values = Array.from(block.querySelectorAll('[class*="value"]'));
            const len = Math.min(labels.length, values.length);
            if (!len) continue;
            const section = block.closest('section, article, div')?.querySelector('h2, h3')?.textContent || '';
            for (let i = 0; i < len; i++) {
              push(labels[i].textContent, values[i].textContent, section);
            }
          }

          return {
            page_title: document.title || '',
            heading: clean(document.querySelector('h1')?.textContent || ''),
            body_text: clean(document.body?.innerText || ''),
            key_values: keyValues
          };
        }
        """
    )


def extract_availability(text: str) -> Optional[str]:
    patterns = [
        r"(Available to order[^.]*\d{4}\*?)",
        r"(Available to order[^.]*\d{4})",
        r"(Discontinued\s*\([^)]*\))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return None


def extract_currency_values(text: str, symbol: str) -> str:
    escaped = re.escape(symbol)
    values = re.findall(rf"{escaped}\s?[\d][\d.,]*", text)
    deduped: List[str] = []
    seen: Set[str] = set()
    for value in values:
        normalized = value.replace(" ", "")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return "; ".join(deduped[:12])


def write_json(items: List[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(rows: List[VehicleDetail], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(asdict(rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def run(
    url: str,
    start_page_index: int,
    results_per_page: int,
    max_pages: int,
    max_cars: Optional[int],
    delay_page: float,
    delay_car: float,
    links_json_path: Path,
    details_json_path: Path,
    details_csv_path: Optional[Path],
):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Missing dependency: playwright")
        print("Install with: pip install playwright")
        print("Then run once: python -m playwright install chromium")
        sys.exit(1)

    collected_links: List[VehicleLink] = []
    seen_links: Set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("Collecting car links from listing pages...")
        previous_first_href: Optional[str] = None
        for idx in range(max_pages):
            page_index = start_page_index + idx
            page_url = replace_hash_param(url, "p", f"{page_index}-{results_per_page}")
            print(f"[LIST {idx + 1}/{max_pages}] {page_url}")

            cards = navigate_listing_page(page, page_url, previous_first_href)
            if not cards:
                print("  No cards found; stopping listing crawl.")
                break

            page_text = page.inner_text("body")
            if looks_blocked(page_text):
                prompt_if_captcha()
                cards = navigate_listing_page(page, page_url, previous_first_href)
                if not cards:
                    break

            previous_first_href = cards[0]["href"]
            added = 0
            for card in cards:
                href = card["href"].strip()
                if not href or href in seen_links:
                    continue
                seen_links.add(href)
                collected_links.append(
                    VehicleLink(
                        name=clean_text(card.get("name", "")),
                        href=href,
                        listing_page_url=page_url,
                    )
                )
                added += 1

            print(f"  Found {len(cards)} cards, added {added} new links.")
            time.sleep(delay_page)

        if max_cars is not None:
            collected_links = collected_links[:max_cars]
            print(f"Limiting detail crawl to first {len(collected_links)} cars (--max-cars).")

        write_json([asdict(item) for item in collected_links], links_json_path)
        print(f"Wrote {len(collected_links)} links to {links_json_path}")

        print("\nScraping detail pages...")
        detail_rows: List[VehicleDetail] = []
        for i, item in enumerate(collected_links, start=1):
            print(f"[CAR {i}/{len(collected_links)}] {item.href}")
            page.goto(item.href, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(1200)
            page_text = page.inner_text("body")

            if looks_blocked(page_text):
                prompt_if_captcha()
                page.goto(item.href, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_timeout(1200)

            payload = extract_detail_payload(page)
            body_text = clean_text(str(payload.get("body_text", "")))
            key_values = payload.get("key_values", [])
            key_values_json = json.dumps(key_values, ensure_ascii=False)

            row = VehicleDetail(
                name=item.name,
                href=item.href,
                page_title=clean_text(str(payload.get("page_title", ""))),
                heading=clean_text(str(payload.get("heading", ""))),
                availability=extract_availability(body_text),
                useable_battery_kwh=parse_float(body_text, r"([\d.,]+)\s*kWh\s*\*?\s*Useable Battery"),
                real_range_km=parse_float(body_text, r"([\d.,]+)\s*km\s*\*?\s*Real Range"),
                efficiency_wh_per_km=parse_float(body_text, r"([\d.,]+)\s*Wh/km\s*\*?\s*Efficiency"),
                long_distance_suitability=parse_float(body_text, r"Long Distance Suitability\s*([\d.]+)\s*/\s*5"),
                prices_eur=extract_currency_values(body_text, "€"),
                prices_gbp=extract_currency_values(body_text, "£"),
                key_values_json=key_values_json,
                raw_text_excerpt=body_text[:5000],
            )
            detail_rows.append(row)
            time.sleep(delay_car)

        write_json([asdict(row) for row in detail_rows], details_json_path)
        print(f"\nWrote {len(detail_rows)} detailed rows to {details_json_path}")
        if details_csv_path is not None:
            write_csv(detail_rows, details_csv_path)
            print(f"Wrote detailed CSV to {details_csv_path}")

        browser.close()


def main():
    parser = argparse.ArgumentParser(
        description="Fresh crawl EV Database listings and detailed car pages into separate output files."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="EV Database listing URL with filters.")
    parser.add_argument(
        "--start-page-index",
        type=int,
        default=None,
        help="Starting page index. Defaults to index parsed from URL p=pageIndex-pageSize.",
    )
    parser.add_argument(
        "--results-per-page",
        type=int,
        default=None,
        help="Results per page. Defaults to value parsed from URL p=pageIndex-pageSize.",
    )
    parser.add_argument("--max-pages", type=int, default=27, help="How many listing pages to traverse.")
    parser.add_argument("--max-cars", type=int, default=None, help="Optional cap for detail pages.")
    parser.add_argument("--delay-page", type=float, default=1.0, help="Delay between listing pages (seconds).")
    parser.add_argument("--delay-car", type=float, default=0.8, help="Delay between car detail pages (seconds).")
    parser.add_argument(
        "--links-output-json",
        default=str(REPO_ROOT / "data" / "ev_database_car_links.json"),
        help="Output JSON path for collected car links.",
    )
    parser.add_argument(
        "--details-output-json",
        default=str(REPO_ROOT / "data" / "ev_database_car_details.json"),
        help="Output JSON path for detailed car data.",
    )
    parser.add_argument(
        "--details-output-csv",
        default=str(REPO_ROOT / "data" / "ev_database_car_details.csv"),
        help="Output CSV path for detailed car data. Use empty string to disable.",
    )
    args = parser.parse_args()

    parsed = parse_p_param(args.url)
    parsed_start = parsed[0] if parsed else 0
    parsed_page_size = parsed[1] if parsed else 50
    start_page_index = args.start_page_index if args.start_page_index is not None else parsed_start
    results_per_page = args.results_per_page if args.results_per_page is not None else parsed_page_size
    if results_per_page <= 0:
        print("--results-per-page must be positive.")
        sys.exit(1)
    if args.max_pages <= 0:
        print("--max-pages must be positive.")
        sys.exit(1)

    links_json_path = Path(args.links_output_json).expanduser().resolve()
    details_json_path = Path(args.details_output_json).expanduser().resolve()
    details_csv_path = Path(args.details_output_csv).expanduser().resolve() if args.details_output_csv else None

    run(
        url=args.url,
        start_page_index=start_page_index,
        results_per_page=results_per_page,
        max_pages=args.max_pages,
        max_cars=args.max_cars,
        delay_page=args.delay_page,
        delay_car=args.delay_car,
        links_json_path=links_json_path,
        details_json_path=details_json_path,
        details_csv_path=details_csv_path,
    )


if __name__ == "__main__":
    main()
