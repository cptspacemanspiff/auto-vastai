import json
import yaml
from remote_ml_devtools.RemoteMLManager import parseConfig, getInstancesAvail,estimateCost
import pathlib

test_path = pathlib.Path(__file__).parent.resolve()

def test_configparser():
    cfg = parseConfig(test_path/"example.yaml")
    assert "API_KEY" in cfg
    assert "estimation_params" in cfg
    assert "query" in cfg
    # print("done")

def test_price_calc():
    # load up the exemplar json:
    cfg = parseConfig(test_path/"example.yaml")
    with open(test_path / 'offer_list.json') as json_file:
        offer_list = json.load(json_file)
        cost_list = [estimateCost(x,10,10,10,8) for x in offer_list]

        # this was value measured before:
        assert cost_list[0] == 1.0011111111111113

def test_instance_search():
    getInstancesAvail(test_path/"example.yaml")



if __name__ == "__main__":
    # test_configparser()
    # test_instance_search()
    test_price_calc()