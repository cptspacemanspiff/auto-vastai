from pathlib import Path
import signal
import sys
from time import sleep
import yaml

from dataclasses import asdict
from dacite import from_dict

from remote_ml_devtools.vastai_client.models import Machine
from remote_ml_devtools.vastai_client.vast_client import VastClient

from loguru import logger

from datetime import datetime, timezone, timedelta
import asyncio


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


class InstanceManager:
    client: VastClient
    cfg: dict

    exit_flag = False

    def __init__(self, cfg: dict) -> None:
        self.client = VastClient
        key_path = Path(cfg["API_KEY"]).expanduser()
        self.client = VastClient(api_key=None, api_key_file=key_path)
        self.cfg = cfg

    def estimateCost(
        self,
        offer: Machine,
        up_usage: float,
        down_usage: float,
        storage_usage: float,
        duration: float,
    ):
        if isinstance(offer, dict):
            offer = from_dict(data_class=Machine, data=offer)
        inet_cost = offer.inet_up_cost * up_usage + offer.inet_down_cost * down_usage
        # storage rate is quoted as monthly
        hrs_per_mth = 24 * 30
        storage_cost = (storage_usage * offer.storage_cost * duration) / hrs_per_mth
        usage_cost = offer.dph_base * duration

        total_cost = inet_cost + storage_cost + usage_cost

        return total_cost

    def getOffersAvail(self, request_type: str):
        query_str = " ".join(self.cfg["query"])
        offer_list = self.client.search_offers(
            request_type, query_str, disable_bundling=True, storage=1.0
        )
        params = self.cfg["estimation_params"]
        # we now have a list of instances, see what is cheapest:
        cost_list = [
            self.estimateCost(
                x,
                params["up_usage"],
                params["down_usage"],
                params["storage_usage"],
                params["duration"],
            )
            for x in offer_list
        ]

        sorted_list = sorted(
            zip(offer_list, cost_list), key=lambda pair: (pair[1], pair[0].dlperf)
        )
        # return a ordered list, starting with lowest cost.
        return sorted_list

    def createNewInstance(self, request_type):
        offer_list = self.getOffersAvail(request_type)
        logger.info(f"Recieved {len(offer_list)} {request_type} offers.")

        indexToCreate = 0
        if request_type == "bid":
            indexToCreate = self.cfg["creation_params"]["bid_buffer"]

        if offer_list[indexToCreate][1] > self.cfg["creation_params"]["tot_max_price"]:
            logger.error(
                offer_list[indexToCreate] + "was the instance closest to request"
            )
            raise (Exception("Could not satisfy creation request."))

        offer_to_create = offer_list[indexToCreate]

        instance_id = self.client.create_instance(
            offer_to_create[0].id,
            image=self.cfg["creation_params"]["image"],
            price=offer_to_create[0].min_bid + 0.005,
            ssh=True,
            disk=1.0,
        )

        return dict(instance_id)

    def monitorInstances(self):
        instances = self.client.get_instances()

        logger.info(f"Currently there are {len(instances)} active instances.")

        for idx, instance in enumerate(instances):
            tzinfo = timezone(timedelta(hours=-8.0))
            instance_create_date = datetime.utcfromtimestamp(instance.start_date)
            duration = datetime.utcnow() - instance_create_date
            BilledDown = 0
            BilledUp = 0
            BilledStorage = (
                instance.storage_total_cost * duration.total_seconds() / 3600
            )
            BilledCompute = instance.dph_base * duration.total_seconds() / 3600
            if instance.inet_down_billed is not None:
                BilledDown = instance.inet_down_billed * instance.inet_down_cost * 10e-6
                BilledUp = instance.inet_up_billed * instance.inet_up_cost * 10e-6
            logger.info(
                f"""
    Instance {idx} is a {instance.gpu_name} w/ {instance.gpu_ram} of GPURAM.
        Usage:
            inet_down (KB): {instance.inet_down_billed} 
            inet_up (KB): {instance.inet_up_billed}
            storage: {instance.storage_cost}
            active for: {duration}
            created on: {instance_create_date}
        Costs:
            Download Cost Total: {BilledDown}
            Upload Cost Total: {BilledUp}
            Storage Cost Total: {BilledStorage}
            Compute Cost Total: {BilledCompute}
            Total Cost: {BilledDown+BilledUp+BilledStorage+BilledCompute}
                    """
            )

        return instances

    def getCurrentSessions(self):
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-t",
            "--type",
            help="type of offer to plot (bid or on-demand)",
            default="on-demand",
        )
        parser.add_argument(
            "-c",
            "--config",
            help="location of config file",
            default="~/remote_ml_config.yaml",
        )
        args = parser.parse_args()

        cfg = self.parseConfig(args.config)

        self.monitorInstances(cfg)

    def WaitForInstanceRunning(self, instance_id: str):
        while True:
            logger.info(f"Confirming instances are ready.")
            instances = self.monitorInstances()
            if instances[0].actual_status == "running":
                logger.info(
                    f"Instance {instance_id} is ready, actual status is {instances[0].actual_status}, status is {instances[0].cur_state}"
                )
                break
            logger.info(
                f"""Waiting for instance {instance_id} to start, actual status is {instances[0].actual_status}, status is {instances[0].cur_state}"""
            )
            sleep(60)

    def signal_handler(self, sig, frame):
        logger.info("Manual shutdown requested, exiting.")
        self.exit_flag = True


def startAndMonitorInstance():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--directory",
        help="Location of directory to sync",
        default="/home/nlong/vastai_sync",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="location of config file",
        default="~/remote_ml_config.yaml",
    )
    args = parser.parse_args()

    cfg = parseConfig(args.config)
    manager = InstanceManager(cfg)

    signal.signal(signal.SIGINT, manager.signal_handler)

    # create a bid instance, if the list of current instances is empty:
    instance_list = manager.monitorInstances()
    if not instance_list:
        instance_id = manager.createNewInstance("bid")["new_contract"]
        logger.info(f"Created instance {instance_id}")
        logger.info(f"Waiting for instance {instance_id} to start.")
        manager.WaitForInstanceRunning(instance_id)
    else:
        instance_id = instance_list[0].id
        logger.info(f"Using instance {instance_id}")
        if not instance_list[0].actual_status == "running":
            manager.WaitForInstanceRunning(instance_id)

    logger.info(f"Instance {instance_id} is ready.")

    # copy to remote from local:
    logger.info(f"Syncing {args.directory} to instance {instance_id}")
    manager.client.copy(
        str(Path(args.directory).absolute()), str(instance_id) + ":/workspace"
    )

    # monitor the connection:
    logger.info(f"Monitoring instance {instance_id} for exit.")

    monitorIdx = 0
    while not manager.exit_flag:
        sleep(1)
        monitorIdx += 1
        if monitorIdx % 60 == 0:
            manager.monitorInstances()

    # copy from remote to local:
    logger.info(f"Syncing {args.directory} from instance {instance_id}")
    manager.client.copy(
        str(instance_id) + ":/workspace", str(Path(args.directory).absolute())
    )


def plotActiveOffersByCost():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-t",
        "--type",
        help="type of offer to plot (bid or on-demand)",
        default="on-demand",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="location of config file",
        default="~/remote_ml_config.yaml",
    )
    args = parser.parse_args()

    cfg = parseConfig(args.config)
    manager = InstanceManager(cfg)

    # cfg =
    offer_list = manager.getOffersAvail(args.type)

    logger.info(f"Recieved {len(offer_list)} {args.type} offers.")

    from matplotlib import pyplot as plt
    import seaborn as sns

    # create the plot:
    gpu_types = [offer[0].gpu_name for offer in offer_list]

    fig = plt.figure(figsize=(10, 8), dpi=120)
    fig.tight_layout()
    ax = plt.subplot(111)

    # Plot the rented instances as grey:
    gpu_offer_list = list(filter(lambda offer: (offer[0].rented), offer_list))
    cost_vals = [offer[1] for offer in gpu_offer_list]
    perf_vals = [offer[0].dlperf for offer in gpu_offer_list]
    ax.scatter(cost_vals, perf_vals, label="rented bids")

    numGPUTypes = len(set(gpu_types))
    cm = sns.color_palette("husl", numGPUTypes)
    for index, gpu_type in enumerate(sorted(set(gpu_types))):
        gpu_offer_list = list(
            filter(
                lambda offer: (offer[0].gpu_name == gpu_type and not offer[0].rented),
                offer_list,
            )
        )

        cost_vals = [offer[1] for offer in gpu_offer_list]
        perf_vals = [offer[0].dlperf for offer in gpu_offer_list]
        ax.scatter(cost_vals, perf_vals, label=gpu_type, color=cm[index])

    ax.set_title(
        f'Perf vs Dollar of {args.type} Offers \nfor a {cfg["estimation_params"]["duration"] } hr rental.'
    )
    ax.set_xlabel("Cost $")
    ax.set_ylabel("Perf (vast.ai)")

    box = ax.get_position()
    ax.set_position([box.x0, box.y0 + box.height * 0.1, box.width, box.height * 0.9])

    ax.legend(
        bbox_to_anchor=(0.5, -0.05),
        loc="upper center",
        fancybox=True,
        shadow=True,
        ncol=6,
    )
    plt.show()

    print("dine")


if __name__ == "__main__":
    # plotActiveOffersByCost()
    startAndMonitorInstance()
    # createNewInstance()
    # getCurrentSessions()
    pass
