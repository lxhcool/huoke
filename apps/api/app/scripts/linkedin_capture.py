from __future__ import annotations

import argparse
import asyncio

from app.scrapers.linkedin.service import LinkedinScraperService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LinkedIn 页面抓取脚本")
    parser.add_argument("command", choices=["login", "company", "contact"])
    parser.add_argument("--keyword", default="laser cutting")
    parser.add_argument("--country", default=None)
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    service = LinkedinScraperService()

    if args.command == "login":
        path = await service.ensure_login_session()
        print(f"登录态已保存：{path}")
        return

    if args.command == "company":
        path = await service.scrape_company_data(args.keyword, args.country)
        print(f"公司数据原始结果已保存：{path}")
        return

    path = await service.scrape_contact_data(args.keyword, args.country)
    print(f"联系人数据原始结果已保存：{path}")


if __name__ == "__main__":
    asyncio.run(main())

