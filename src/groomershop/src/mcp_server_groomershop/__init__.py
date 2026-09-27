from .server import serve


def main():
    """MCP Groomershop Server - scrape product data from groomershop.pl"""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="Scrape product data from groomershop.pl via MCP"
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        help="Custom User-Agent string",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1.0)",
    )

    args = parser.parse_args()
    asyncio.run(serve(args.user_agent, args.delay))


if __name__ == "__main__":
    main()
