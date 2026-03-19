from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Config:
    lcia_gwp100: tuple = (
        "IPCC 2021",
        "climate change",
        "global warming potential (GWP100)",
    )
    REED_PATH = Path.home()/"OneDrive - 2.-0 LCA Consultants ApS"/"HorizonEurope"/"EU_REED_1277"

    BONSAI_PATH = REED_PATH/"data"/"BONSAI_V2.1.3"

    PROJECT_NAME = 'reed'
    BONSAI_NAME = 'BONSAI_V2.1.3'