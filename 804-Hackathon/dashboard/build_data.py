# Bundles ../outputs/*.json into data.js so the dashboard opens with a double-click
# (no server needed). Run again after re-running the Kaggle script:  python3 build_data.py
import json
import os

here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(here, "..", "outputs")
data = {key: json.load(open(os.path.join(out, name))) for key, name in
        [("results", "results.json"), ("profile", "wetbulb_profile.json"), ("replay", "replay_days.json")]}
with open(os.path.join(here, "data.js"), "w") as f:
    f.write("window.WETBULB_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
print("wrote data.js")
