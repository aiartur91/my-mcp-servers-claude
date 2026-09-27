from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

BASE_URL = "https://www.groomershop.pl"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class ProductData(BaseModel):
    url: str
    name: str = ""
    price: str = ""
    price_old: str = ""
    currency: str = "PLN"
    ean: str = ""
    sku: str = ""
    brand: str = ""
    category: str = ""
    description: str = ""
    short_description: str = ""
    images: list[str] = []
    attributes: dict[str, str] = {}
    availability: str = ""
    variants: list[dict[str, str]] = []


class CategoryInfo(BaseModel):
    url: str
    name: str = ""
    product_count: int = 0
    subcategories: list[dict[str, str]] = []


class GroomershopScraper:
    def __init__(self, user_agent: str | None = None, delay: float = 1.0):
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._delay = delay
        self._last_request_time: float = 0
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
                timeout=30.0,
            )
        return self._client

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._delay:
            await asyncio.sleep(self._delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _fetch(self, url: str) -> str:
        await self._throttle()
        client = await self._get_client()
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # --- JSON-LD extraction (structured data many shops embed) ---

    def _extract_jsonld(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return results

    def _product_from_jsonld(self, ld: dict[str, Any], product: ProductData) -> None:
        if ld.get("@type") not in ("Product", "IndividualProduct"):
            return
        product.name = product.name or str(ld.get("name", ""))
        product.brand = product.brand or str(
            ld.get("brand", {}).get("name", "") if isinstance(ld.get("brand"), dict) else ld.get("brand", "")
        )
        product.sku = product.sku or str(ld.get("sku", ""))
        product.ean = product.ean or str(ld.get("gtin13", ld.get("gtin", ld.get("gtin14", ld.get("gtin12", "")))))
        product.description = product.description or str(ld.get("description", ""))
        if "image" in ld:
            img = ld["image"]
            if isinstance(img, str):
                product.images = product.images or [img]
            elif isinstance(img, list):
                product.images = product.images or [str(i) for i in img]
        offers = ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            product.price = product.price or str(offers.get("price", ""))
            product.currency = str(offers.get("priceCurrency", "PLN"))
            avail = str(offers.get("availability", ""))
            if "InStock" in avail:
                product.availability = "in_stock"
            elif "OutOfStock" in avail:
                product.availability = "out_of_stock"

    # --- HTML parsing helpers ---

    @staticmethod
    def _text(el: Tag | None) -> str:
        return el.get_text(strip=True) if el else ""

    @staticmethod
    def _abs_url(url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return BASE_URL + url
        if not url.startswith("http"):
            return BASE_URL + "/" + url
        return url

    # --- Product page scraping ---

    async def scrape_product(self, url: str) -> ProductData:
        html = await self._fetch(url)
        soup = BeautifulSoup(html, "lxml")
        product = ProductData(url=url)

        # 1. Try JSON-LD first (most reliable)
        for ld in self._extract_jsonld(soup):
            self._product_from_jsonld(ld, product)

        # 2. Fallback / supplement with HTML selectors
        self._parse_product_html(soup, product)

        return product

    def _parse_product_html(self, soup: BeautifulSoup, product: ProductData) -> None:
        # Name
        if not product.name:
            for sel in ["h1.product-name", "h1.product__name", "h1[itemprop='name']", ".product-title h1", "h1"]:
                el = soup.select_one(sel)
                if el:
                    product.name = self._text(el)
                    break

        # Price
        if not product.price:
            for sel in [
                ".product-price .price", "[itemprop='price']", ".price--current",
                ".product__price", ".price-normal", ".main-price",
            ]:
                el = soup.select_one(sel)
                if el:
                    val = el.get("content") or self._text(el)
                    product.price = str(val).strip()
                    break

        # Old price
        if not product.price_old:
            for sel in [".price--old", ".old-price", ".price-old", ".price--regular", "del .price"]:
                el = soup.select_one(sel)
                if el:
                    product.price_old = self._text(el)
                    break

        # EAN
        if not product.ean:
            for sel in ["[itemprop='gtin13']", "[itemprop='gtin']", ".product-ean", ".ean"]:
                el = soup.select_one(sel)
                if el:
                    val = el.get("content") or self._text(el)
                    product.ean = str(val).strip()
                    break
            if not product.ean:
                ean_match = re.search(r'EAN[:\s]*(\d{8,13})', soup.get_text())
                if ean_match:
                    product.ean = ean_match.group(1)

        # SKU / product code
        if not product.sku:
            for sel in ["[itemprop='sku']", ".product-sku", ".product-code", ".sku"]:
                el = soup.select_one(sel)
                if el:
                    val = el.get("content") or self._text(el)
                    product.sku = str(val).strip()
                    break

        # Brand
        if not product.brand:
            for sel in ["[itemprop='brand']", ".product-brand", ".brand", ".manufacturer"]:
                el = soup.select_one(sel)
                if el:
                    val = el.get("content") or self._text(el)
                    product.brand = str(val).strip()
                    break

        # Category (breadcrumb)
        if not product.category:
            breadcrumb = soup.select(".breadcrumb a, .breadcrumbs a, [itemprop='itemListElement'] a")
            if breadcrumb:
                product.category = " > ".join(self._text(a) for a in breadcrumb if self._text(a))

        # Description
        if not product.description:
            for sel in [
                "[itemprop='description']", ".product-description", ".product__description",
                ".description", "#product-description", ".tab-content .description",
            ]:
                el = soup.select_one(sel)
                if el:
                    product.description = self._text(el)
                    break

        # Short description
        if not product.short_description:
            for sel in [".short-description", ".product__short-description", ".product-intro"]:
                el = soup.select_one(sel)
                if el:
                    product.short_description = self._text(el)
                    break

        # Images
        if not product.images:
            imgs: list[str] = []
            for sel in [
                ".product-gallery img", ".product-images img", ".gallery img",
                "[itemprop='image']", ".product__gallery img", ".product-photo img",
            ]:
                for img in soup.select(sel):
                    src = img.get("data-src") or img.get("data-zoom-image") or img.get("src") or ""
                    src = str(src).strip()
                    if src and "placeholder" not in src.lower() and "lazy" not in src.lower():
                        imgs.append(self._abs_url(src))
            if not imgs:
                og_image = soup.find("meta", property="og:image")
                if og_image and og_image.get("content"):
                    imgs.append(str(og_image["content"]))
            product.images = imgs

        # Availability
        if not product.availability:
            for sel in [".availability", ".product-availability", ".stock-status", "[itemprop='availability']"]:
                el = soup.select_one(sel)
                if el:
                    text = self._text(el).lower()
                    if "dostępny" in text or "w magazynie" in text or "in stock" in text:
                        product.availability = "in_stock"
                    elif "niedostępny" in text or "brak" in text:
                        product.availability = "out_of_stock"
                    else:
                        product.availability = text
                    break

        # Attributes (spec table)
        for table in soup.select(".product-attributes, .product-params, .attributes, .specifications, .product-features"):
            for row in table.select("tr, li, .attribute, .param"):
                cells = row.select("td, th, .name, .value, dt, dd, span")
                if len(cells) >= 2:
                    key = self._text(cells[0])
                    val = self._text(cells[1])
                    if key and val:
                        product.attributes[key] = val

        # Variants
        variant_selects = soup.select("select.product-variant, select[name*='variant'], select[name*='option']")
        for sel_el in variant_selects:
            for opt in sel_el.select("option"):
                val = opt.get("value", "")
                text = self._text(opt)
                if val and text and text != "---":
                    product.variants.append({"value": str(val), "label": text})

    # --- Category page scraping ---

    async def scrape_category(self, url: str, page: int = 1) -> dict[str, Any]:
        if page > 1:
            separator = "&" if "?" in url else "?"
            fetch_url = f"{url}{separator}page={page}"
        else:
            fetch_url = url

        html = await self._fetch(fetch_url)
        soup = BeautifulSoup(html, "lxml")

        category_name = ""
        h1 = soup.select_one("h1")
        if h1:
            category_name = self._text(h1)

        products: list[dict[str, str]] = []
        for sel in [
            ".product-item", ".product-card", ".product", ".product-miniature",
            ".product-tile", "[data-product-id]", ".products-list .item",
        ]:
            for item in soup.select(sel):
                p: dict[str, str] = {}
                link = item.select_one("a[href]")
                if link:
                    p["url"] = self._abs_url(str(link["href"]))
                name_el = item.select_one(".product-name, .product-title, h2, h3, a[title]")
                if name_el:
                    p["name"] = str(name_el.get("title", "") or self._text(name_el)).strip()
                price_el = item.select_one(".price, .product-price, [itemprop='price']")
                if price_el:
                    p["price"] = str(price_el.get("content", "") or self._text(price_el)).strip()
                img_el = item.select_one("img")
                if img_el:
                    src = img_el.get("data-src") or img_el.get("src") or ""
                    if src:
                        p["image"] = self._abs_url(str(src).strip())
                if p.get("url") or p.get("name"):
                    products.append(p)

        # Pagination
        total_pages = 1
        for pag in soup.select(".pagination a, .pager a, .pages a"):
            text = self._text(pag)
            if text.isdigit():
                total_pages = max(total_pages, int(text))

        # Subcategories
        subcategories: list[dict[str, str]] = []
        for sel in [".subcategories a", ".category-list a", ".subcategory a"]:
            for a in soup.select(sel):
                href = a.get("href", "")
                name = self._text(a)
                if href and name:
                    subcategories.append({"url": self._abs_url(str(href)), "name": name})

        return {
            "url": fetch_url,
            "category_name": category_name,
            "page": page,
            "total_pages": total_pages,
            "product_count": len(products),
            "products": products,
            "subcategories": subcategories,
        }

    # --- Search ---

    async def search_products(self, query: str, page: int = 1) -> dict[str, Any]:
        search_url = f"{BASE_URL}/search?q={query}"
        if page > 1:
            search_url += f"&page={page}"
        return await self.scrape_category(search_url, page=1)

    # --- Sitemap ---

    async def get_sitemap_urls(self, sitemap_url: str | None = None) -> list[str]:
        url = sitemap_url or f"{BASE_URL}/sitemap.xml"
        html = await self._fetch(url)
        soup = BeautifulSoup(html, "lxml-xml")
        urls: list[str] = []
        for loc in soup.find_all("loc"):
            text = self._text(loc)
            if text:
                urls.append(text)
        return urls

    # --- Bulk scraping ---

    async def scrape_products_from_urls(self, urls: list[str]) -> list[ProductData]:
        results: list[ProductData] = []
        for url in urls:
            try:
                product = await self.scrape_product(url)
                results.append(product)
            except (httpx.HTTPError, ValueError, KeyError) as e:
                results.append(ProductData(url=url, name=f"ERROR: {e}"))
        return results
