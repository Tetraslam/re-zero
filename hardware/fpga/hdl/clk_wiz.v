`default_nettype none

module clk_wiz (
    input wire sysclk_p,
    input wire sysclk_n,

    output logic sysclk_200mhz
);

// IN PROGRESS
  logic ilk_200mhz;
  IBUFDS #(
      .DIFF_TERM ("TRUE"),
      .IOSTANDARD("LVDS")
  ) u_ibufds (
      .O (clk_200mhz),
      .I (sysclk_p),
      .IB(sysclk_n)
  );

  BUFG u_bufg (
      .I(clk_ibufg),
      .O(sysclk_200mhz)
  );



endmodule

`default_nettype wire
