from __future__ import annotations

import argparse
import asyncio

from app.scrapers.joinf.service import JoinfScraperService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Joinf 页面抓取脚本")
    parser.add_argument("command", choices=["login", "business", "customs"])
    parser.add_argument("--keyword", default="laser cutting")
    parser.add_argument("--country", default=None)
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    service = JoinfScraperService()

    if args.command == "login":
        path = await service.ensure_login_session()
        print(f"登录态已保存：{path}")
        return

    if args.command == "business":
        path = await service.scrape_business_data(args.keyword, args.country)
        print(f"商业数据原始结果已保存：{path}")
        return

    path = await service.scrape_customs_data(args.keyword, args.country)
    print(f"海关数据原始结果已保存：{path}")


if __name__ == "__main__":
    asyncio.run(main())
