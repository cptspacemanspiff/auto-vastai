from pathlib import Path
import yaml

from dataclasses import asdict
from dacite import from_dict

from .vastai_client.models import Machine

from .vastai_client.vast_client import VastClient

from loguru import logger

def parseConfig(config_path: Path):
    with open(config_path, "r") as cfg_file:
        cfg = None
        try:
            cfg = yaml.safe_load(cfg_file)
            return cfg
        except yaml.YAMLError as exc:
            print(exc)
        if cfg is None:
            raise Exception("Unable to find or parse: " + str(config_path))


def estimateCost(
    offer : Machine, up_usage: float, 
    down_usage: float, storage_usage: float, duration: float
):
    if isinstance(offer, dict):
        offer = from_dict(data_class=Machine,data=offer)
    inet_cost = offer.inet_up_cost * up_usage + offer.inet_down_cost * down_usage
    # storage rate is quoted as monthly
    hrs_per_mth = 24*30
    storage_cost = (storage_usage * offer.storage_cost * duration) / hrs_per_mth
    usage_cost = offer.dph_base * duration

    total_cost = inet_cost + storage_cost + usage_cost

    return total_cost
    


def getInstancesAvail(config_path):
    cfg = parseConfig(config_path)
    key_path = Path(cfg["API_KEY"]).expanduser()
    client = VastClient(api_key=None, api_key_file=key_path)
    query_str = " ".join(cfg["query"])
    instances_avail = client.search_offers(
        cfg["type"], query_str, disable_bundling=True, storage=1.0
    )
    # we now have a list of instances, see what is cheapest:
    instances_avail_dict = [asdict(x) for x in instances_avail]
    print("dskdsjhf")
