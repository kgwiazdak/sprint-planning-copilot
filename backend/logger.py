import logging, sys

logging.basicConfig(
    level=logging.INFO,  # poziom dla roota
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],  # do stdout -> docker logs
)

logger = logging.getLogger(__name__)