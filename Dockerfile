FROM ros:jazzy-ros-base

# Revisioni Crazyswarm2 e firmware (release 2025.02).
ARG CRAZYSWARM2_COMMIT=f1e09954f56cd08e7d9aff5e13dc9a68795914a3
ARG FIRMWARE_COMMIT=16c5630707e92830dcd16455a57b5560e5838735

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git swig python3-dev python3-venv python3-setuptools \
    python3-colcon-common-extensions python3-numpy python3-yaml python3-transforms3d \
    ros-jazzy-ament-cmake-python ros-jazzy-tf2-ros ros-jazzy-rosgraph-msgs \
    && rm -rf /var/lib/apt/lists/*

# system-site-packages rende disponibili i moduli ROS installati da apt.
RUN python3 -m venv --system-site-packages /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --no-deps rowan==1.3.2
ENV PATH="/opt/venv/bin:${PATH}"

RUN git init /opt/crazyflie-firmware \
    && cd /opt/crazyflie-firmware \
    && git remote add origin https://github.com/bitcraze/crazyflie-firmware.git \
    && git fetch --depth 1 origin ${FIRMWARE_COMMIT} \
    && git checkout --detach FETCH_HEAD \
    && git submodule update --init --recursive --depth 1 \
    && make cf2_defconfig \
    && make bindings_python PYTHON=/opt/venv/bin/python3

RUN git init /opt/ros_ws/src/crazyswarm2 \
    && cd /opt/ros_ws/src/crazyswarm2 \
    && git remote add origin https://github.com/IMRCLab/crazyswarm2.git \
    && git fetch --depth 1 origin ${CRAZYSWARM2_COMMIT} \
    && git checkout --detach FETCH_HEAD
COPY docker/crazyswarm2.patch /tmp/crazyswarm2.patch
RUN cd /opt/ros_ws/src/crazyswarm2 && git apply /tmp/crazyswarm2.patch \
    && source /opt/ros/jazzy/setup.bash \
    && cd /opt/ros_ws \
    && colcon build --packages-select crazyflie_interfaces crazyflie_sim \
        --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

ENV PYTHONPATH="/app/backend:/opt/crazyflie-firmware/build" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CFP_DATA_DIR=/data \
    ROS_DOMAIN_ID=88 \
    ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
    ROS_LOG_DIR=/tmp/ros-logs
WORKDIR /app
COPY . /app
RUN chmod +x /app/docker/entrypoint.sh && mkdir -p /data && chown 1000:1000 /data
USER 1000:1000
EXPOSE 8870
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python3", "-m", "swarm_platform.main"]
