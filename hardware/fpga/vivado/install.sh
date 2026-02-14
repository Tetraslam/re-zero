#!/usr/bin/env bash
set -euo pipefail

# ~/code/vivado/vivado_2025.1/install.sh
cd ~/code/vivado/vivado_2025.1

mkdir -p ${HOME}/vivado_2025.1
time (tar -xf FPGAs_AdaptiveSoCs_Unified_SDI_2025.1_0530_0145.tar -C ${HOME}/vivado_2025.1)
cd ${HOME}/vivado_2025.1/FPGAs_AdaptiveSoCs_Unified_SDI_2025.1_0530_0145

# Install and select Vivado -> Vivado ML Enterprise
printf "2\n2\n" | ./xsetup -b ConfigGen

# Select boards
sed -i 's/Kintex-7 FPGAs:0/Kintex-7 FPGAs:1/' ${HOME}/.Xilinx/install_config.txt

# Set locale
apt-get install -y locales
locale-gen en_US.UTF-8

# Install Vivado
time (./xsetup -a XilinxEULA,3rdPartyEULA -b Install -c ${HOME}/.Xilinx/install_config.txt)

# Install packages
time (source /tools/Xilinx/2025.1/Vivado/scripts/installLibs.sh)

# Add Vivado to bin
echo 'export PATH="$PATH:/tools/Xilinx/2025.1/Vivado/bin"' >> ~/.bashrc

# This command needs to be run or else Vivado will run into an error
echo 'export LD_PRELOAD=/lib/x86_64-linux-gnu/libudev.so.1' >> ~/.bashrc

# Add license
cp ~/Downloads/Xilinx.lic ~/.Xilinx/Xilinx.lic
