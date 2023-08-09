from remote_ml_devtools.vastai_client import VastClient
from loguru import logger

# These require an internet connection in order to work.


def test_vastai_connection():
    client = VastClient()
    instance_list = client.get_instances()

    logger.info("Successfully connected to vastai")


def test_vastai_instance_search():
    client = VastClient()
    offer_list = client.search_offers(
        search_query="verified = false, rentable = true", no_default=True
    )

    logger.info(f"Successfully connected to vastai, recieved {len(offer_list)} items.")


# load config:
def test_json_writing():
    pass


if __name__ == "__main__":
    test_vastai_instance_search()
