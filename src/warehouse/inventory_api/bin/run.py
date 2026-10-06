import argparse
import logging

from aiohttp import web

from warehouse.core.db.migrate import migrate_up
from warehouse.inventory_api.keys import SETTINGS
from warehouse.inventory_api.main import create_app


def main() -> None:
    """Запуск http-сервера/миграции."""
    parser = argparse.ArgumentParser(prog="inventory-api")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["migrate"],
        help="без migrate запускается HTTP-сервер, иначе миграции",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if args.command == "migrate":
        migrate_up()
        return
    app = create_app()
    settings = app[SETTINGS]
    web.run_app(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
