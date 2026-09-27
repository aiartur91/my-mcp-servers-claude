from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    ErrorData,
    TextContent,
    Tool,
)

from .scraper import GroomershopScraper


async def serve(user_agent: str | None = None, delay: float = 1.0) -> None:
    server = Server("groomershop-scraper")
    scraper = GroomershopScraper(user_agent=user_agent, delay=delay)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="scrape-product",
                description=(
                    "Scrape full product data from a groomershop.pl product page. "
                    "Returns: name, price, old price, EAN, SKU, brand, category, "
                    "description, images, attributes, availability, variants."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Full URL of the product page on groomershop.pl",
                        },
                    },
                    "required": ["url"],
                },
            ),
            Tool(
                name="scrape-category",
                description=(
                    "Scrape a category or listing page from groomershop.pl. "
                    "Returns product links, names, prices, and images from the listing. "
                    "Supports pagination."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Full URL of the category page on groomershop.pl",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number (default: 1)",
                            "default": 1,
                        },
                    },
                    "required": ["url"],
                },
            ),
            Tool(
                name="search-products",
                description=(
                    "Search for products on groomershop.pl by keyword. "
                    "Returns a list of matching products with links, names, and prices."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (product name, brand, etc.)",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number (default: 1)",
                            "default": 1,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="scrape-products-bulk",
                description=(
                    "Scrape full product data from multiple groomershop.pl product pages. "
                    "Provide a list of product URLs. Results include all product fields. "
                    "Requests are throttled to respect the server."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of product page URLs to scrape",
                            "maxItems": 50,
                        },
                    },
                    "required": ["urls"],
                },
            ),
            Tool(
                name="get-sitemap",
                description=(
                    "Fetch and parse the groomershop.pl sitemap. "
                    "Returns a list of URLs from the sitemap (products, categories, etc.). "
                    "Useful for discovering all available product pages."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "sitemap_url": {
                            "type": "string",
                            "description": (
                                "URL of the sitemap (default: https://www.groomershop.pl/sitemap.xml). "
                                "Can also point to a sub-sitemap."
                            ),
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        args = arguments or {}

        try:
            if name == "scrape-product":
                url = args.get("url")
                if not url or not isinstance(url, str):
                    raise McpError(ErrorData(code=INVALID_PARAMS, message="'url' is required"))
                if "groomershop.pl" not in url:
                    raise McpError(ErrorData(
                        code=INVALID_PARAMS,
                        message="URL must be from groomershop.pl",
                    ))
                product = await scraper.scrape_product(url)
                return [TextContent(type="text", text=product.model_dump_json(indent=2))]

            elif name == "scrape-category":
                url = args.get("url")
                if not url or not isinstance(url, str):
                    raise McpError(ErrorData(code=INVALID_PARAMS, message="'url' is required"))
                page = int(args.get("page", 1))
                result = await scraper.scrape_category(url, page=page)
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "search-products":
                query = args.get("query")
                if not query or not isinstance(query, str):
                    raise McpError(ErrorData(code=INVALID_PARAMS, message="'query' is required"))
                page = int(args.get("page", 1))
                result = await scraper.search_products(query, page=page)
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "scrape-products-bulk":
                urls = args.get("urls")
                if not urls or not isinstance(urls, list):
                    raise McpError(ErrorData(code=INVALID_PARAMS, message="'urls' is required (list of strings)"))
                products = await scraper.scrape_products_from_urls(urls)
                data = [p.model_dump() for p in products]
                return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]

            elif name == "get-sitemap":
                sitemap_url = args.get("sitemap_url")
                urls = await scraper.get_sitemap_urls(sitemap_url)
                return [TextContent(type="text", text=json.dumps({"urls": urls, "count": len(urls)}, indent=2))]

            else:
                raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown tool: {name}"))

        except McpError:
            raise
        except Exception as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=str(e))) from e

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

    await scraper.close()
