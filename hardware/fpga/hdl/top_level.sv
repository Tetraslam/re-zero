`default_nettype none

module top_level (
    input wire sysclk_p,
    input wire sysclk_n,

    input wire [4:0] btn,
    input wire [7:0] sw,
    output logic [7:0] led,

    input wire esp_sig_p,
    input wire esp_sig_n
);
    logic sysclk_200mhz_passthrough;
    clk_wiz clk_inst(
        .sysclk_p(sysclk_p),
        .sysclk_n(sysclk_n),
        .sysclk_200mhz_passthrough(sysclk_200mhz_passthrough)
    );


endmodule
`default_nettype wire
