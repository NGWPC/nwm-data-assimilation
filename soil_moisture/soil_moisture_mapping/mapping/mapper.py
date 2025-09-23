import logging

from dotenv import load_dotenv

from utils.mappers import Mapper

from ..mapping.observed_data import SoilMoistureObsProcessor
from .simulated_data import SoilMoistureConverter, SoilMoistureSimProcessor

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
load_dotenv()


class SoilMoistureMapper(Mapper):
    """Soil Moisture Mapper class to handle soil moisture mapping operations."""

    def __init__(self, args):
        """Initialize the SoilMoistureMapper with command line arguments."""
        super().__init__(args)
        self.converter = SoilMoistureConverter(*self.conversion_args)
        self.sim_processor = SoilMoistureSimProcessor(*self.sim_mapper_args)
        self.obs_processor = SoilMoistureObsProcessor(*self.obs_args)
