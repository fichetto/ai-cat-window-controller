#!/bin/bash
cd /home/pi/hailo-rpi5-examples
source venv_hailo_rpi5_examples/bin/activate
source setup_env.sh
python basic_pipelines/cat_reclassify.py
