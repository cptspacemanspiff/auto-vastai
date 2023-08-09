from pathlib import Path
import yaml

from dataclasses import asdict
from dacite import from_dict

from remote_ml_devtools.vastai_client.models import Machine
from remote_ml_devtools.vastai_client.vast_client import VastClient

from loguru import logger

def parseConfig(config_path: Path):
    with open(Path(config_path).expanduser(), "r") as cfg_file:
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
    


def getInstancesAvail(config_path, query_type = None):
    cfg = parseConfig(config_path)
    key_path = Path(cfg["API_KEY"]).expanduser()
    client = VastClient(api_key=None, api_key_file=key_path)
    query_str = " ".join(cfg["query"])
    if query_type is None:
        query_type = cfg["type"]
    offer_list = client.search_offers(
        query_type, query_str, disable_bundling=True, storage=1.0
    )
    params = cfg['estimation_params']
    # we now have a list of instances, see what is cheapest:
    cost_list = [estimateCost(x,
                              params['up_usage'],params['down_usage'],
                              params['storage_usage'],params['duration']) 
                              for x in offer_list]

    sorted_list = sorted(zip(offer_list,cost_list), key=lambda pair: (pair[1],pair[0].dlperf))

    # return a ordered list, starting with lowest cost.
    return sorted_list


def plotActiveOffersByCost():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--type", help="type of offer to plot (bid or on-demand)",default='on-demand')
    parser.add_argument("-c", "--config", help="location of config file",default='~/remote_ml_config.yaml')    
    args = parser.parse_args()

    cfg = parseConfig(args.config)

    offer_list = getInstancesAvail(args.config, query_type=args.type)

    logger.info(f"Recieved {len(offer_list)} {args.type} offers.")

    from matplotlib import pyplot as plt
    import seaborn as sns
    # create the plot:
    gpu_types = [offer[0].gpu_name for offer in offer_list]
    
    fig = plt.figure(figsize=(10, 6), dpi=120)
    fig.tight_layout()
    ax = plt.subplot(111)

    numGPUTypes = len(set(gpu_types))
    cm = sns.color_palette("husl",numGPUTypes)
    for index, gpu_type in enumerate(set(gpu_types)):

        gpu_offer_list = list(filter(lambda offer: (offer[0].gpu_name == gpu_type), offer_list))

        cost_vals = [offer[1] for offer in gpu_offer_list]
        perf_vals = [offer[0].dlperf for offer in gpu_offer_list]
    

        ax.scatter(cost_vals,perf_vals, label = gpu_type, color=cm[index])
        

    ax.set_title(f'Perf vs Dollar of {args.type} Offers \nfor a {cfg["estimation_params"]["duration"] } hr rental.')
    ax.set_xlabel('Cost $')
    ax.set_ylabel('Perf (vast.ai)')

    box = ax.get_position()
    ax.set_position([box.x0, box.y0 + box.height * 0.1,
                    box.width, box.height * 0.9])

    ax.legend(bbox_to_anchor=(.5, -.05), loc='upper center', fancybox=True, shadow=True, ncol=6)
    plt.show()

    print("dine")


if __name__ == "__main__":
     plotActiveOffersByCost()
