"""Utility functions for timing and min/max calculations."""

import logging
from contextlib import contextmanager
from time import time

import numpy as np

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def time_function(func):
    """Measure the execution time of a function."""

    def wrapper(*args, **kwargs):
        with timing_block(f"Executing {func.__name__}"):
            result = func(*args, **kwargs)
            return result

    return wrapper


@contextmanager
def timing_block(step_str: str):
    """Context manager for timing code execution.

    Args:
        step_str: Description of the step being timed.

    """
    start = time()
    yield
    end = time()
    logger.info(f"  Execution time for {step_str}: {round(end - start, 2)} seconds")


def get_minmax(current_data: np.ndarray, vmin, vmax) -> tuple:
    """Update the global min/max with current data.

    Returns:
        The current global values

    """
    if np.isnan(current_data).all():
        logger.warning("current_data contains only NaNs, skipping min/max calculation.")
        current_min = np.nan  # or some default value
        current_max = np.nan
    else:
        current_min = np.nanmin(current_data)
        current_max = np.nanmax(current_data)

    vmin = min(vmin, current_min)
    vmax = max(vmax, current_max)

    return vmin, vmax
