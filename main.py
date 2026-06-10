import asyncio
import logging
import signal
import sys

from config import Config
from notifier import TelegramNotifier
from scanner import LZTScanner
from storage import ItemStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = Config.from_env()
    storage = ItemStorage(config.db_path)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    scanner = LZTScanner(config, storage, notifier)

    logger.info("Starting LZT scanner (poll interval: %.1fs)", config.poll_interval)
    logger.info("Database: %s (%d known items)", config.db_path, storage.count())

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals.
            pass

    scan_task = asyncio.create_task(scanner.run())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        {scan_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    storage.close()
    logger.info("Scanner stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
