from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Config:
    lcia_gwp100: tuple = (
        "IPCC 2021",
        "climate change",
        "global warming potential (GWP100)",
    )
    REED_PATH = Path.home()/"OneDrive - 2.-0 LCA Consultants ApS"/"Intranet - HorizonEurope"/"EU_REED_1277"

    BONSAI_PATH = REED_PATH/"data"/"dkea_exiobase_version"/"0.1.1"

    PROJECT_NAME = 'reed'
    BONSAI_NAME = 'bonsai_231231'