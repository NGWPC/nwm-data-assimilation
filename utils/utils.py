import logging
from contextlib import contextmanager
from time import time

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@contextmanager
def timing_block(step_str: str):
    """Context manager for timing code execution.

    Args:
        step_str: Description of the step being timed.

    """
    start = time()
    yield
    end = time()
    logger.info(f"  Execution time for {step_str}: {end - start} seconds")
