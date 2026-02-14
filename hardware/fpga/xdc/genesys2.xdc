# Genesys 2 constraints.

# Differential clocking system
set_property -dict { PACKAGE_PIN AD12 IOSTANDARD LVDS } [get_ports { sysclk_p }]
set_property -dict { PACKAGE_PIN AD11 IOSTANDARD LVDS } [get_ports { sysclk_n }]
create_clock -add -name sysclk_200mhz -period 5.000 -waveform {0 2.5} [get_ports { sysclk_p }]

# Set Bank 0 voltage
# set_property CFGBVS VCCO [current_design]
# set_property CONFIG_VOLTAGE 3.3 [current_design]

# Genesys2 DDR3 is a 32-bit interface, while this project currently uses only a
# 16-bit subset. The "unused" FPGA pins that still connect to the DDR3 chip(s)
# must not be weakly pulled up/down by default, or they can interfere with DDR3
# training. Set all unused pins to high-impedance.
set_property BITSTREAM.CONFIG.UNUSEDPIN PULLNONE [current_design]

# Optional cross-domain constraints
# The HDMI pixel clock (74.25MHz) and DDR controller clock (83.33MHz) are produced
# by different MMCMs and are not phase-related. All crossings between these domains
# are via async FIFOs, so treat the clocks as asynchronous for timing analysis.
set_clock_groups -asynchronous \
  -group [get_clocks clk_pixel_cw_hdmi] \
  -group [get_clocks clk_controller_clk_wiz_0]

# (Older/alternative approach kept for reference)
# set_max_delay -datapath_only 6 -from [get_clocks clk_controller_clk_wiz_0] -to [get_clocks clk_pixel_cw_hdmi]
# set_max_delay -datapath_only 6 -from [get_clocks clk_pixel_cw_hdmi] -to [get_clocks clk_controller_clk_wiz_0]
# set_max_delay -datapath_only 6 -from [get_clocks clk_controller_clk_wiz_0] -to [get_clocks clk_passthrough_clk_wiz_0]
# set_max_delay -datapath_only 6 -from [get_clocks clk_passthrough_clk_wiz_0] -to [get_clocks clk_controller_clk_wiz_0]

# USER GREEN LEDS
set_property -dict { PACKAGE_PIN T28   IOSTANDARD LVCMOS33 } [get_ports { led[0] }]; #IO_L15P_T2_DQS_13 Sch=led[0]
set_property -dict { PACKAGE_PIN V19   IOSTANDARD LVCMOS33 } [get_ports { led[1] }]; #IO_L15N_T2_DQS_13 Sch=led[1]
set_property -dict { PACKAGE_PIN U30   IOSTANDARD LVCMOS33 } [get_ports { led[2] }]; #IO_L17P_T2_13 Sch=led[2]
set_property -dict { PACKAGE_PIN U29   IOSTANDARD LVCMOS33 } [get_ports { led[3] }]; #IO_L17N_T2_13 Sch=led[3]
set_property -dict { PACKAGE_PIN V20   IOSTANDARD LVCMOS33 } [get_ports { led[4] }]; #IO_L14N_T2_SRCC_13 Sch=led[4]
set_property -dict { PACKAGE_PIN V26   IOSTANDARD LVCMOS33 } [get_ports { led[5] }]; #IO_L16N_T2_13 Sch=led[5]
set_property -dict { PACKAGE_PIN W24   IOSTANDARD LVCMOS33 } [get_ports { led[6] }]; #IO_L16P_T2_13 Sch=led[6]
set_property -dict { PACKAGE_PIN W23   IOSTANDARD LVCMOS33 } [get_ports { led[7] }]; #IO_L5P_T0_13 Sch=led[7]

## USER PUSH BUTTON
set_property -dict { PACKAGE_PIN E18 IOSTANDARD LVCMOS12 } [get_ports { "btn[0]" }]; #IO_L20N_T3_16 Sch=btnc
set_property -dict { PACKAGE_PIN M19 IOSTANDARD LVCMOS12 } [get_ports { "btn[1]" }]; #IO_L22N_T3_16 Sch=btnd
set_property -dict { PACKAGE_PIN M20 IOSTANDARD LVCMOS12 } [get_ports { "btn[2]" }]; #IO_L20P_T3_16 Sch=btnl
set_property -dict { PACKAGE_PIN C19 IOSTANDARD LVCMOS12 } [get_ports { "btn[3]" }]; #IO_L6P_T0_16 Sch=btnr
set_property -dict { PACKAGE_PIN B19 IOSTANDARD LVCMOS12 } [get_ports { "btn[4]" }]; #IO_0_16 Sch=btnu
set_property -dict { PACKAGE_PIN R19 IOSTANDARD LVCMOS33 } [get_ports { cpu_resetn }]

## USER SLIDE SWITCH
set_property -dict { PACKAGE_PIN G19  IOSTANDARD LVCMOS12 } [get_ports { sw[0] }]; #IO_L22P_T3_16 Sch=sw[0]
set_property -dict { PACKAGE_PIN G25  IOSTANDARD LVCMOS12 } [get_ports { sw[1] }]; #IO_25_16 Sch=sw[1]
set_property -dict { PACKAGE_PIN H24  IOSTANDARD LVCMOS12 } [get_ports { sw[2] }]; #IO_L24P_T3_16 Sch=sw[2]
set_property -dict { PACKAGE_PIN K19  IOSTANDARD LVCMOS12 } [get_ports { sw[3] }]; #IO_L24N_T3_16 Sch=sw[3]
set_property -dict { PACKAGE_PIN N19  IOSTANDARD LVCMOS12 } [get_ports { sw[4] }]; #IO_L6P_T0_15 Sch=sw[4]
set_property -dict { PACKAGE_PIN P19  IOSTANDARD LVCMOS12 } [get_ports { sw[5] }]; #IO_0_15 Sch=sw[5]
# sw[6]/sw[7] sit in a 3.3V bank on Genesys2; keeping these at LVCMOS12
# causes the Bank VCCO conflict seen during `place_design`.
set_property -dict { PACKAGE_PIN P26  IOSTANDARD LVCMOS33 } [get_ports { sw[6] }]; #IO_L19P_T3_A22_15 Sch=sw[6]
set_property -dict { PACKAGE_PIN P27  IOSTANDARD LVCMOS33 } [get_ports { sw[7] }]; #IO_25_15 Sch=sw[7]


# PMOD A Signals (this project top-level currently has no `pmoda[]` ports)
# set_property -dict {PACKAGE_PIN F14 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[0]} ]
# set_property -dict {PACKAGE_PIN F15 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[1]} ]
# set_property -dict {PACKAGE_PIN H13 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[2]} ]
# set_property -dict {PACKAGE_PIN H14 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[3]} ]
# set_property -dict {PACKAGE_PIN J13 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[4]} ]
# set_property -dict {PACKAGE_PIN J14 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[5]} ]
# set_property -dict {PACKAGE_PIN E14 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[6]} ]
# set_property -dict {PACKAGE_PIN E15 IOSTANDARD LVCMOS33}  [ get_ports {pmoda[7]} ]

# PMOD B Signals
##fixed K14 and J15 which were a copy-paste and wrong.
#set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[0]" ]
#set_property -dict {PACKAGE_PIN G18 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[1]" ]
#set_property -dict {PACKAGE_PIN K14 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[2]" ]
#set_property -dict {PACKAGE_PIN J15 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[3]" ]
#set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[4]" ]
#set_property -dict {PACKAGE_PIN H17 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[5]" ]
#set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[6]" ]
#set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33}  [ get_ports "pmodb[7]" ]

# PMOD AB Signals
#set_property -dict {PACKAGE_PIN D11 IOSTANDARD LVCMOS33} [get_ports {jab[0]}]
#set_property -dict {PACKAGE_PIN C12 IOSTANDARD LVCMOS33} [get_ports {jab[1]}]
#set_property -dict {PACKAGE_PIN E16 IOSTANDARD LVCMOS33} [get_ports {jab[2]}]
#set_property -dict {PACKAGE_PIN G16 IOSTANDARD LVCMOS33} [get_ports {jab[3]}]
#set_property -dict {PACKAGE_PIN C11 IOSTANDARD LVCMOS33} [get_ports {jab[4]}]
#set_property -dict {PACKAGE_PIN D10 IOSTANDARD LVCMOS33} [get_ports {jab[5]}]


#HDMI Signals
set_property -dict { PACKAGE_PIN AB20 IOSTANDARD TMDS_33 } [get_ports {hdmi_clk_n}]
set_property -dict { PACKAGE_PIN AA20 IOSTANDARD TMDS_33 } [get_ports {hdmi_clk_p}]
set_property -dict { PACKAGE_PIN AC21 IOSTANDARD TMDS_33 } [get_ports {hdmi_tx_n[0]}]
set_property -dict { PACKAGE_PIN AA23 IOSTANDARD TMDS_33 } [get_ports {hdmi_tx_n[1]}]
set_property -dict { PACKAGE_PIN AC25 IOSTANDARD TMDS_33 } [get_ports {hdmi_tx_n[2]}]
set_property -dict { PACKAGE_PIN AC20 IOSTANDARD TMDS_33 } [get_ports {hdmi_tx_p[0]}]
set_property -dict { PACKAGE_PIN AA22 IOSTANDARD TMDS_33 } [get_ports {hdmi_tx_p[1]}]
set_property -dict { PACKAGE_PIN AB24 IOSTANDARD TMDS_33 } [get_ports {hdmi_tx_p[2]}]

# PWM audio out signals
# set_property PACKAGE_PIN B13 [ get_ports "spkl"]
# set_property PACKAGE_PIN B14 [ get_ports "spkr"]
# set_property IOSTANDARD LVCMOS33 [ get_ports "spk*"]

# PWM Microphone signals
# set_property -dict {PACKAGE_PIN E12 IOSTANDARD LVCMOS33} [get_ports {mic_clk}]
# set_property -dict {PACKAGE_PIN D12 IOSTANDARD LVCMOS33} [get_ports {mic_data}]

# UART over micro-USB signals
# labeled from the perspective of the FPGA!
# note the inversion from RealDigital official documentation.
## USB-UART (per Digilent Genesys2 board part):
## - FPGA RXD: Y20
## - FPGA TXD: Y23
set_property -dict { PACKAGE_PIN Y20 IOSTANDARD LVCMOS33 } [get_ports {uart_rxd}]
set_property -dict { PACKAGE_PIN Y23 IOSTANDARD LVCMOS33 } [get_ports { uart_txd }]

# MICRO SD SPI signals
# set_property -dict {PACKAGE_PIN M16 IOSTANDARD LVCMOS33} [get_ports {sd_cipo}]
# set_property -dict {PACKAGE_PIN N18 IOSTANDARD LVCMOS33} [get_ports {sd_cs}]
# set_property -dict {PACKAGE_PIN P17 IOSTANDARD LVCMOS33} [get_ports {sd_copi}]
# set_property -dict {PACKAGE_PIN P18 IOSTANDARD LVCMOS33} [get_ports {sd_dclk}]

############## NET - IOSTANDARD ##################
### Pins below are for the DDR3
### Remove the first column of comments in one block to activate all appropriate pins

### Genesys2 DDR3 pinout
### Sourced from Digilent's Genesys-2 HDMI demo MIG constraints (MT41J256M16 x2, 1.5V).
###
### NOTE: Genesys2 DDR3 is a 32-bit interface on the board. This project currently
### exposes only a 16-bit bus (`ddr3_dq[15:0]`, `ddr3_dm[1:0]`, `ddr3_dqs_[1:0]`),
### so we constrain only the lower 16 bits here.

## DQ[0:15] (SSTL15)
## TODO: figure out SSTL15_T_DCI (og) vs SSTL15 (hack?)
set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[0]}]
set_property SLEW FAST [get_ports {ddr3_dq[0]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[0]}]
set_property PACKAGE_PIN AD3 [get_ports {ddr3_dq[0]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[1]}]
set_property SLEW FAST [get_ports {ddr3_dq[1]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[1]}]
set_property PACKAGE_PIN AC2 [get_ports {ddr3_dq[1]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[2]}]
set_property SLEW FAST [get_ports {ddr3_dq[2]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[2]}]
set_property PACKAGE_PIN AC1 [get_ports {ddr3_dq[2]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[3]}]
set_property SLEW FAST [get_ports {ddr3_dq[3]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[3]}]
set_property PACKAGE_PIN AC5 [get_ports {ddr3_dq[3]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[4]}]
set_property SLEW FAST [get_ports {ddr3_dq[4]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[4]}]
set_property PACKAGE_PIN AC4 [get_ports {ddr3_dq[4]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[5]}]
set_property SLEW FAST [get_ports {ddr3_dq[5]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[5]}]
set_property PACKAGE_PIN AD6 [get_ports {ddr3_dq[5]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[6]}]
set_property SLEW FAST [get_ports {ddr3_dq[6]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[6]}]
set_property PACKAGE_PIN AE6 [get_ports {ddr3_dq[6]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[7]}]
set_property SLEW FAST [get_ports {ddr3_dq[7]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[7]}]
set_property PACKAGE_PIN AC7 [get_ports {ddr3_dq[7]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[8]}]
set_property SLEW FAST [get_ports {ddr3_dq[8]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[8]}]
set_property PACKAGE_PIN AF2 [get_ports {ddr3_dq[8]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[9]}]
set_property SLEW FAST [get_ports {ddr3_dq[9]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[9]}]
set_property PACKAGE_PIN AE1 [get_ports {ddr3_dq[9]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[10]}]
set_property SLEW FAST [get_ports {ddr3_dq[10]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[10]}]
set_property PACKAGE_PIN AF1 [get_ports {ddr3_dq[10]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[11]}]
set_property SLEW FAST [get_ports {ddr3_dq[11]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[11]}]
set_property PACKAGE_PIN AE4 [get_ports {ddr3_dq[11]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[12]}]
set_property SLEW FAST [get_ports {ddr3_dq[12]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[12]}]
set_property PACKAGE_PIN AE3 [get_ports {ddr3_dq[12]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[13]}]
set_property SLEW FAST [get_ports {ddr3_dq[13]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[13]}]
set_property PACKAGE_PIN AE5 [get_ports {ddr3_dq[13]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[14]}]
set_property SLEW FAST [get_ports {ddr3_dq[14]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[14]}]
set_property PACKAGE_PIN AF5 [get_ports {ddr3_dq[14]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dq[15]}]
set_property SLEW FAST [get_ports {ddr3_dq[15]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dq[15]}]
set_property PACKAGE_PIN AF6 [get_ports {ddr3_dq[15]}]

## DM[0:1] (SSTL15)
set_property VCCAUX_IO NORMAL [get_ports {ddr3_dm[0]}]
set_property SLEW FAST [get_ports {ddr3_dm[0]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dm[0]}]
set_property PACKAGE_PIN AD4 [get_ports {ddr3_dm[0]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dm[1]}]
set_property SLEW FAST [get_ports {ddr3_dm[1]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_dm[1]}]
set_property PACKAGE_PIN AF3 [get_ports {ddr3_dm[1]}]

## DQS[0:1] (DIFF_SSTL15)
set_property VCCAUX_IO NORMAL [get_ports {ddr3_dqs_p[0]}]
set_property SLEW FAST [get_ports {ddr3_dqs_p[0]}]
set_property IOSTANDARD DIFF_SSTL15 [get_ports {ddr3_dqs_p[0]}]
set_property PACKAGE_PIN AD2 [get_ports {ddr3_dqs_p[0]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dqs_n[0]}]
set_property SLEW FAST [get_ports {ddr3_dqs_n[0]}]
set_property IOSTANDARD DIFF_SSTL15 [get_ports {ddr3_dqs_n[0]}]
set_property PACKAGE_PIN AD1 [get_ports {ddr3_dqs_n[0]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dqs_p[1]}]
set_property SLEW FAST [get_ports {ddr3_dqs_p[1]}]
set_property IOSTANDARD DIFF_SSTL15 [get_ports {ddr3_dqs_p[1]}]
set_property PACKAGE_PIN AG4 [get_ports {ddr3_dqs_p[1]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_dqs_n[1]}]
set_property SLEW FAST [get_ports {ddr3_dqs_n[1]}]
set_property IOSTANDARD DIFF_SSTL15 [get_ports {ddr3_dqs_n[1]}]
set_property PACKAGE_PIN AG3 [get_ports {ddr3_dqs_n[1]}]

## CK (renamed here as ddr3_clk_[p/n])
set_property SLEW FAST [get_ports {ddr3_clk_p}]
set_property IOSTANDARD DIFF_SSTL15 [get_ports {ddr3_clk_p}]
set_property PACKAGE_PIN AB9 [get_ports {ddr3_clk_p}]

set_property SLEW FAST [get_ports {ddr3_clk_n}]
set_property IOSTANDARD DIFF_SSTL15 [get_ports {ddr3_clk_n}]
set_property PACKAGE_PIN AC9 [get_ports {ddr3_clk_n}]

## Address/control (SSTL15)
set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[0]}]
set_property SLEW FAST [get_ports {ddr3_addr[0]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[0]}]
set_property PACKAGE_PIN AC12 [get_ports {ddr3_addr[0]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[1]}]
set_property SLEW FAST [get_ports {ddr3_addr[1]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[1]}]
set_property PACKAGE_PIN AE8 [get_ports {ddr3_addr[1]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[2]}]
set_property SLEW FAST [get_ports {ddr3_addr[2]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[2]}]
set_property PACKAGE_PIN AD8 [get_ports {ddr3_addr[2]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[3]}]
set_property SLEW FAST [get_ports {ddr3_addr[3]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[3]}]
set_property PACKAGE_PIN AC10 [get_ports {ddr3_addr[3]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[4]}]
set_property SLEW FAST [get_ports {ddr3_addr[4]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[4]}]
set_property PACKAGE_PIN AD9 [get_ports {ddr3_addr[4]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[5]}]
set_property SLEW FAST [get_ports {ddr3_addr[5]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[5]}]
set_property PACKAGE_PIN AA13 [get_ports {ddr3_addr[5]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[6]}]
set_property SLEW FAST [get_ports {ddr3_addr[6]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[6]}]
set_property PACKAGE_PIN AA10 [get_ports {ddr3_addr[6]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[7]}]
set_property SLEW FAST [get_ports {ddr3_addr[7]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[7]}]
set_property PACKAGE_PIN AA11 [get_ports {ddr3_addr[7]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[8]}]
set_property SLEW FAST [get_ports {ddr3_addr[8]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[8]}]
set_property PACKAGE_PIN Y10 [get_ports {ddr3_addr[8]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[9]}]
set_property SLEW FAST [get_ports {ddr3_addr[9]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[9]}]
set_property PACKAGE_PIN Y11 [get_ports {ddr3_addr[9]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[10]}]
set_property SLEW FAST [get_ports {ddr3_addr[10]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[10]}]
set_property PACKAGE_PIN AB8 [get_ports {ddr3_addr[10]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[11]}]
set_property SLEW FAST [get_ports {ddr3_addr[11]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[11]}]
set_property PACKAGE_PIN AA8 [get_ports {ddr3_addr[11]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[12]}]
set_property SLEW FAST [get_ports {ddr3_addr[12]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[12]}]
set_property PACKAGE_PIN AB12 [get_ports {ddr3_addr[12]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[13]}]
set_property SLEW FAST [get_ports {ddr3_addr[13]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[13]}]
set_property PACKAGE_PIN AA12 [get_ports {ddr3_addr[13]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_addr[14]}]
set_property SLEW FAST [get_ports {ddr3_addr[14]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_addr[14]}]
set_property PACKAGE_PIN AH9 [get_ports {ddr3_addr[14]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_ba[0]}]
set_property SLEW FAST [get_ports {ddr3_ba[0]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_ba[0]}]
set_property PACKAGE_PIN AE9 [get_ports {ddr3_ba[0]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_ba[1]}]
set_property SLEW FAST [get_ports {ddr3_ba[1]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_ba[1]}]
set_property PACKAGE_PIN AB10 [get_ports {ddr3_ba[1]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_ba[2]}]
set_property SLEW FAST [get_ports {ddr3_ba[2]}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_ba[2]}]
set_property PACKAGE_PIN AC11 [get_ports {ddr3_ba[2]}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_ras_n}]
set_property SLEW FAST [get_ports {ddr3_ras_n}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_ras_n}]
set_property PACKAGE_PIN AE11 [get_ports {ddr3_ras_n}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_cas_n}]
set_property SLEW FAST [get_ports {ddr3_cas_n}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_cas_n}]
set_property PACKAGE_PIN AF11 [get_ports {ddr3_cas_n}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_we_n}]
set_property SLEW FAST [get_ports {ddr3_we_n}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_we_n}]
set_property PACKAGE_PIN AG13 [get_ports {ddr3_we_n}]

## Reset (MIG uses LVCMOS15 on Genesys2)
set_property VCCAUX_IO NORMAL [get_ports {ddr3_reset_n}]
set_property SLEW FAST [get_ports {ddr3_reset_n}]
set_property IOSTANDARD LVCMOS15 [get_ports {ddr3_reset_n}]
set_property PACKAGE_PIN AG5 [get_ports {ddr3_reset_n}]

## CKE/ODT
set_property VCCAUX_IO NORMAL [get_ports {ddr3_clke}]
set_property SLEW FAST [get_ports {ddr3_clke}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_clke}]
set_property PACKAGE_PIN AJ9 [get_ports {ddr3_clke}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_cs_n}]
set_property SLEW FAST [get_ports {ddr3_cs_n}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_cs_n}]
set_property PACKAGE_PIN AH12 [get_ports {ddr3_cs_n}]

set_property VCCAUX_IO NORMAL [get_ports {ddr3_odt}]
set_property SLEW FAST [get_ports {ddr3_odt}]
set_property IOSTANDARD SSTL15 [get_ports {ddr3_odt}]
set_property PACKAGE_PIN AK9 [get_ports {ddr3_odt}]


# GLOBAL CONFIGURATIONS

# IMPORTANT: keep unused pins high-Z.
# (Genesys2 DDR3 is x32; this design currently uses a x16 subset.)
set_property BITSTREAM.CONFIG.UNUSEDPIN PULLNONE [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]

# Genesys2 DDR3 uses external VREF0V75 (do not set INTERNAL_VREF unless you
# intentionally switch to internal VREF in your memory interface configuration).
# set_property INTERNAL_VREF 0.75 [get_iobanks 34]
# set_property CFGBVS VCCO [current_design]
# set_property CONFIG_VOLTAGE 3.3 [current_design]
