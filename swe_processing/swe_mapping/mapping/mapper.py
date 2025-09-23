"""SWE Mapper module to handle SWE mapping operations."""

import logging

from dotenv import load_dotenv

from utils.mappers import Mapper

from ..mapping.observed_data import SWEObsProcessor
from .simulated_data import SWEConverter, SWESimProcessor

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
load_dotenv()


class SWEMapper(Mapper):
    """SWE Mapper class to handle SWE mapping operations."""

    def __init__(self, args):
        """Initialize the SWEMapper with command line arguments."""
        super().__init__(args)
        self.converter = SWEConverter(*self.conversion_args)
        self.sim_processor = SWESimProcessor(*self.sim_mapper_args)
        self.obs_processor = SWEObsProcessor(*self.obs_args)
