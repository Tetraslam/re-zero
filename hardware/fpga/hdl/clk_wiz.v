// NOTE: ESP runs at 240 MHz

// TODO: make clock to match ESP + multiple phased clocks
// NOTE: Kintex-7 MMCM allows you to change the phase of a clock while the chip is running by increments of about 18 ps
module clk_wiz (
    input    sysclk_p,                  
    input    sysclk_n,                  
    output   sysclk_200mhz_passthrough
);

  wire sysclk_200mhz_inst;

  // ** make clocks
  IBUFDS #(
      .DIFF_TERM   ("FALSE"), 
      .IBUF_LOW_PWR("TRUE"),     
      .IOSTANDARD  ("LVDS")
  ) IBUFDS_inst (
      .O           (sysclk_200mhz_inst),
      .I           (sysclk_p),
      .IB          (sysclk_n)
  );

  // mccm 1 dynamically change phase between target and sensor (FPGA)
  

  // ** add to global routing network
  BUFG clkf_buf (
      .O           (sysclk_200mhz_passthrough),
      .I           (sysclk_200mhz_inst)
  );
endmodule