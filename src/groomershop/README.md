# Groomershop.pl MCP Server

An MCP server for scraping product data from [groomershop.pl](https://www.groomershop.pl).

## Features

- **scrape-product** — Full product data: name, price, EAN, SKU, brand, description, images, attributes, variants, availability
- **scrape-category** — List products from a category page with pagination
- **search-products** — Search products by keyword
- **scrape-products-bulk** — Scrape multiple product pages (throttled)
- **get-sitemap** — Parse sitemap.xml to discover all product URLs

## Installation

```bash
cd src/groomershop
uv sync --frozen --all-extras --dev
```

## Usage

### As MCP server (stdio)

```bash
mcp-server-groomershop
```

### With Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "groomershop": {
      "command": "uv",
      "args": ["--directory", "/path/to/src/groomershop", "run", "mcp-server-groomershop"]
    }
  }
}
```

### Options

- `--user-agent` — Custom User-Agent string
- `--delay` — Delay between requests in seconds (default: 1.0)

## Extracted Data

Each product scrape returns:

| Field | Description |
|---|---|
| `name` | Product name |
| `price` | Current price |
| `price_old` | Original price (if discounted) |
| `ean` | EAN/barcode |
| `sku` | Product code / SKU |
| `brand` | Manufacturer / brand |
| `category` | Breadcrumb category path |
| `description` | Full description |
| `short_description` | Short intro text |
| `images` | List of image URLs |
| `attributes` | Key-value specification table |
| `availability` | Stock status |
| `variants` | Product variants (size, color, etc.) |
