module clk_wiz (
    input    sysclk_p,                  
    input    sysclk_n,                  
    output   sysclk_200mhz_passthrough
);

  wire sysclk_200mhz_inst;

  // make clocks
  IBUFDS #(
      .DIFF_TERM   ("FALSE"), 
      .IBUF_LOW_PWR("TRUE"),     
      .IOSTANDARD  ("LVDS")
  ) IBUFDS_inst (
      .O           (sysclk_200mhz_inst),
      .I           (sysclk_p),
      .IB          (sysclk_n)
  );

  // add to global routing network
  BUFG clkf_buf (
      .O           (sysclk_200mhz_passthrough),
      .I           (sysclk_200mhz_inst)
  );

endmodule