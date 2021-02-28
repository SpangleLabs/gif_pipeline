import json

from gif_pipeline.pipeline import setup_loop, setup_logging, PipelineConfig

if __name__ == "__main__":
    setup_loop()
    setup_logging()
    with open("config.json", "r") as c:
        CONF = json.load(c)
    pipeline_conf = PipelineConfig(CONF)
    pipeline = pipeline_conf.initialise_pipeline()
    pipeline.initialise_helpers()
    pipeline.watch_workshop()
