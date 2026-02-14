`default_nettype none

// Genesys 2 system clock helper:
// - SYSCLK_P/N is a 200MHz differential oscillator on the board.
// - This module converts it to single-ended and divides to 100MHz using an MMCM.
//
// We keep the rest of the design at 100MHz to preserve UART baud assumptions and
// existing clock-wizard IP configuration.

module clkwiz_100mhz (
  input  wire sysclk_p,
  input  wire sysclk_n,
  output wire clk_100mhz,
  output wire locked
);
  wire clk_200mhz;

  IBUFGDS #(
    .DIFF_TERM("FALSE"),
    .IBUF_LOW_PWR("FALSE")
  ) ibufgds_sysclk (
    .I (sysclk_p),
    .IB(sysclk_n),
    .O (clk_200mhz)
  );

  wire clk_100mhz_mmcm;
  wire mmcm_clkfb;
  wire mmcm_clkfb_buf;
  wire mmcm_clkfb_b_unused;
  wire clkout0b_unused;
  wire clkout1_unused;
  wire clkout1b_unused;
  wire clkout2_unused;
  wire clkout2b_unused;
  wire clkout3_unused;
  wire clkout3b_unused;
  wire clkout4_unused;
  wire clkout5_unused;
  wire clkout6_unused;

  // 200MHz in, 100MHz out:
  // Fvco = 200 * 5 / 1 = 1000 MHz (within 7-series MMCM VCO range)
  // Fout = 1000 / 10 = 100 MHz
  MMCME2_BASE #(
    .BANDWIDTH("OPTIMIZED"),
    .CLKIN1_PERIOD(5.000),
    .DIVCLK_DIVIDE(1),
    .CLKFBOUT_MULT_F(5.000),
    .CLKFBOUT_PHASE(0.0),
    .CLKOUT0_DIVIDE_F(10.000),
    .CLKOUT0_PHASE(0.0),
    .CLKOUT0_DUTY_CYCLE(0.5),
    .STARTUP_WAIT("FALSE")
  ) mmcm_sysclk_div2 (
    .CLKIN1 (clk_200mhz),
    .CLKFBIN(mmcm_clkfb_buf),
    .RST    (1'b0),
    .PWRDWN (1'b0),
    .CLKFBOUT(mmcm_clkfb),
    .CLKFBOUTB(mmcm_clkfb_b_unused),
    .CLKOUT0 (clk_100mhz_mmcm),
    .CLKOUT0B(clkout0b_unused),
    .CLKOUT1 (clkout1_unused),
    .CLKOUT1B(clkout1b_unused),
    .CLKOUT2 (clkout2_unused),
    .CLKOUT2B(clkout2b_unused),
    .CLKOUT3 (clkout3_unused),
    .CLKOUT3B(clkout3b_unused),
    .CLKOUT4 (clkout4_unused),
    .CLKOUT5 (clkout5_unused),
    .CLKOUT6 (clkout6_unused),
    .LOCKED  (locked)
  );

  BUFG bufg_sysclk_fb (
    .I(mmcm_clkfb),
    .O(mmcm_clkfb_buf)
  );

  BUFG bufg_clk_100 (
    .I(clk_100mhz_mmcm),
    .O(clk_100mhz)
  );

endmodule

`default_nettype wire
