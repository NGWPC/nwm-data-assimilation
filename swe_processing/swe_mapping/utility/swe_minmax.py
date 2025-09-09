"""Utility functions for tracking global min/max values across multiple data arrays."""

import logging

import numpy as np

# Initialize global variables
_global_min = float("inf")
_global_max = float("-inf")


logger = logging.getLogger(__name__)


def get_minmax(current_data: np.ndarray, vmin, vmax) -> tuple:
    """Update the global min/max with current data.

    Returns:
        The current global values

    """
    # global _global_min, _global_max

    if np.isnan(current_data).all():
        logger.warning("current_data contains only NaNs, skipping min/max calculation.")
        current_min = np.nan  # or some default value
        current_max = np.nan
    else:
        current_min = np.nanmin(current_data)
        current_max = np.nanmax(current_data)

    _global_min = min(vmin, current_min)
    _global_max = max(vmax, current_max)

    return _global_min, _global_max


def reset_minmax() -> None:
    """Reset the global min/max values."""
    global _global_min, _global_max
    _global_min = float("inf")
    _global_max = float("-inf")
