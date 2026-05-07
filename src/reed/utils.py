from dataclasses import dataclass
from pathlib import Path
from pydantic_settings import BaseSettings,SettingsConfigDict

class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", validate_assignment=True
    )

    lcia_gwp100: tuple = (
        "IPCC 2021",
        "climate change",
        "global warming potential (GWP100)",
    )
    # default path. It would work for windows machines with access to the 
    # 2-0 LCA sharepoint.
    REED_PATH : Path = Path.home()/"OneDrive - 2.-0 LCA Consultants ApS"/"HorizonEurope"/"EU_REED_1277"

    BONSAI_PATH :Path = REED_PATH/"data"/"BONSAI_V2.1.6"

    PROJECT_NAME :str = 'reed'
    BONSAI_NAME : str = 'BONSAI_V2.1.6'


CONFIG = Config()