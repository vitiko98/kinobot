import requests
import os
import json

TOKEN = os.environ.get("RANDOMORG")


# return a random integer
def getRandom(minN, maxN):
    randomHost = "https://api.random.org/json-rpc/2/invoke"
    params = {
        "jsonrpc": "2.0",
        "method": "generateIntegers",
        "params": {
            "apiKey": TOKEN,
            "n": 1,
            "min": minN,
            "max": maxN,
            "replacement": True,
            "base": 10,
        },
        "id": 6206,
    }
    headers = {"content-type": "application/json; charset=utf-8"}

    r = requests.post(randomHost, data=json.dumps(params), headers=headers)
    return json.loads(r.content)["result"]["random"]["data"][0]
