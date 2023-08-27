import datetime
import enum
from typing import Optional

from prometheus_client import Enum, Gauge

startup_time = Gauge(
    "gif_pipeline_startup_unixtime",
    "Time the gif pipeline was last started"
)


class StartupState(enum.Enum):
    LOADING_CONFIG = "01_loading_config"
    CREATING_DATABASE = "02_creating_database"
    CONNECTING_TELEGRAM = "03_connecting_telegram"
    INITIALISING_CHAT_DATA = "10_initialise_chat_data"
    LISTING_WORKSHOP_MESSAGES = "11_list_workshop_messages"
    LISTING_CHANNEL_MESSAGES = "12_list_channel_messages"
    DOWNLOADING_MESSAGES = "13_downloading_messages"
    CREATING_WORKSHOPS = "14_creating_workshops"
    CREATING_CHANNELS = "15_creating_channels"
    CLEANING_UP_CHAT_FILES = "16_cleanup_chat_files"
    CREATING_PIPELINE = "20_creating_pipeline"
    INITIALISING_DUPLICATE_DETECTOR = "21_initialising_duplicate_detector"
    INITIALISING_HELPERS = "22_initialising_helpers"
    INSTALLING_YT_DL = "23_install_yt_dl"
    LOADING_MENUS = "24_load_menus"
    INITIALISING_PUBLIC_HELPERS = "27_initialise_public_helpers"
    RUNNING = "30_running"


startup_state = Enum(
    "gif_pipeline_startup_state",
    "Current startup state of gif pipeline",
    states=[state.value for state in StartupState]
)
startup_state_latest_state_change = Gauge(
    "gif_pipeline_startup_state_change_unixtime",
    "Time that the startup state last changed"
)
startup_state_duration = Gauge(
    "gif_pipeline_startup_state_duration_seconds",
    "Time that the gif pipeline spent in the given startup state",
    labelnames=["state"]
)
for state in StartupState:
    startup_state_duration.labels(state=state.value)


class StartupMonitor:
    def __init__(self):
        self.current_state: Optional[StartupState] = None
        self.current_state_start: Optional[datetime.datetime] = None

    def set_state(self, state: StartupState) -> None:
        if self.current_state is not None:
            last_state = self.current_state
            last_duration = self.current_duration()
            if last_duration is not None:
                startup_state_duration.labels(state=last_state.value).set_function(lambda: last_duration)
        startup_state.state(state.value)
        startup_state_latest_state_change.set_to_current_time()
        startup_state_duration.labels(state=state.value).set_function(self.current_duration)
        self.current_state = state
        self.current_state_start = datetime.datetime.now()

    def current_duration(self) -> Optional[float]:
        if self.current_state_start is None:
            return None
        return (datetime.datetime.now() - self.current_state_start).total_seconds()

    def set_running(self) -> None:
        self.set_state(StartupState.RUNNING)
        startup_time.set_to_current_time()
